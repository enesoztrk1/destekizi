#!/usr/bin/env python3
"""Destekizi - ilk yerel model deneyi calistiricisi.

Veri akisi:
    vaka + elle secilmis kaynaklar -> gorev yonergesi (prompt.txt)
    -> yerel Ollama /api/chat -> ham yanit + olcumler -> insan degerlendirmesi

Bu dosya cevap anahtarini (expected.jsonl) OKUMAZ; `read_text` bunu engeller.
Yalnizca Python 3.12 standart kutuphanesi kullanilir.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import math
import os
import platform
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUNNER_PATH = Path(__file__).resolve()
HERE = RUNNER_PATH.parent

# `py -P` / `-I`, PYTHONSAFEPATH veya dosya yoluyla yukleme durumunda betik dizini
# sys.path'e eklenmez; kural motoru yine bu dosyanin yanindaki modulden alinir.
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import applicability  # noqa: E402  kaynak surum/yururluk filtresi (ayni dizindeki modul)
import rules_mode  # noqa: E402  A modu: kural tabanli temel yontem (ayni dizindeki modul)

RULES_PATH = Path(rules_mode.__file__).resolve()
APPLICABILITY_PATH = Path(applicability.__file__).resolve()

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:4b-instruct-2507-q4_K_M"
DEFAULT_NUM_CTX = 4096
DEFAULT_NUM_PREDICT = 384
DEFAULT_TIMEOUT_S = 180
PREFLIGHT_TIMEOUT_S = 20

# Cevap anahtari uretim yoluna hicbir kosulda girmez.
FORBIDDEN_INPUT_FILENAMES = {"expected.jsonl"}
# Yalnizca yol/dosya kimligi karsilastirmasi icin; icerigi okunmaz veya ozetlenmez.
ANSWER_KEY_PATH = HERE / "expected.jsonl"

SETTINGS_NOTES = [
    "num_predict ilk kontrolde 256 idi; dort baslikli cevap icin 384'e cikarildi.",
    "think alani, /no_think ve ozel model sablonu kullanilmaz (bkz. docs/PROJECT.md).",
    "Otomatik yeniden deneme yok; her vaka bir kez calisir.",
    "Eszamanli istek 1; vakalar sirayla calisir.",
]

RESULT_NOTES = [
    "Isinma istegi sonuclardan ve sure ozetinden ayri tutulur.",
    "Basarisiz/kesilmis cikitilar sure ozetine dahil edilmez.",
    "10 ornekten p95, SLA veya genel basari yuzdesi cikarilamaz.",
    "prompt_eval_count tek basina baglamin kesilmedigine kesin kanit degildir; "
    "bu pakette baglama sigma dogrulamasi yapilmamistir.",
    "Mekanik gozlemler (baslik/kaynak kimligi varligi) teknik dogruluk puani degildir.",
    "Bildirilen model boyutu olculmus tepe VRAM tuketimi degildir.",
    "istemci_eksi_sunucu_total_s = istemci gecen suresi - sunucu total_duration. "
    "Sunucunun total_duration disinda kalan tum isleri (baglanti, aktarim, "
    "serilestirme vb.) karisik olarak icerir; nedeni bu kayittan ayristirilamaz. "
    "Model suresi icin sunucu olcumlerine bakin.",
    "run_meta.json icindeki api_version_istek_suresi_s tek bir /api/version isteginin "
    "suresidir; istemci surelerinden cikarilacak sabit bir deger degildir.",
]

A_MODE_NOTES = [
    "A modu: kural tabanli, deterministik temel yontem (rules_mode.py).",
    "Ollama'ya istek gonderilmez; on kontrol, isinma ve model cagrisi atlanir.",
    "Model olcumleri (token, sunucu sureleri) null'dir; client_elapsed_s kural suresidir.",
    "Kurallar yalnizca docs.json kaynak metinlerinden turetilmistir.",
]

WARMUP_MESSAGES = [
    {"role": "system", "content": "Kisa ve Turkce yanit ver."},
    {"role": "user", "content": "Bu bir isinma istegidir. Yalnizca 'hazir' yaz."},
]

NS_DURATION_FIELDS = (
    "total_duration",
    "load_duration",
    "prompt_eval_duration",
    "eval_duration",
)

KNOWN_SOURCE_PATTERNS = ("D1", "D2", "D3")

REQUIRED_HEADINGS = (
    "Bulgular",
    "Belirsizlik",
    "Sonraki adım",
    "Kaynaklar",
)


class ExperimentError(RuntimeError):
    """Calismayi tek, anlasilir bir hatayla durduran durum."""


# --------------------------------------------------------------------------
# Dosya okuma ve dogrulama
# --------------------------------------------------------------------------


def _is_answer_key(path: Path) -> bool:
    """Ad (buyuk/kucuk harf duyarsiz) veya dosya kimligi (samefile) ile eslesme.

    Icerik okunmaz. Yeniden adlandirilmis bir KOPYAYI yakalamaz; genel bir
    sizinti garantisi degildir.
    """
    if path.name.casefold() in FORBIDDEN_INPUT_FILENAMES:
        return True
    try:
        return path.exists() and ANSWER_KEY_PATH.exists() and os.path.samefile(
            path, ANSWER_KEY_PATH
        )
    except OSError as exc:
        # Kimlik kontrolu yapilamiyorsa okumaya devam etme (fail-closed).
        raise ExperimentError(
            f"Cevap anahtari kimlik kontrolu yapilamadi: {path} ({exc})"
        ) from exc


def _reject_answer_key(path: Path) -> None:
    if _is_answer_key(path):
        raise ExperimentError(
            f"Cevap anahtari uretim yolunda okunamaz: {path.name}. "
            "Bu dosya yalnizca insan degerlendirmesi icindir."
        )


def read_text(path: Path) -> str:
    """Girdi dosyasini UTF-8 okur. Cevap anahtarinin okunmasini engeller."""
    _reject_answer_key(path)
    if not path.is_file():
        raise ExperimentError(f"Girdi dosyasi bulunamadi: {path}")
    return path.read_text(encoding="utf-8")


def sha256_file(path: Path) -> str:
    _reject_answer_key(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_sources(path: Path) -> dict[str, dict[str, Any]]:
    raw = json.loads(read_text(path))
    items = raw["sources"] if isinstance(raw, dict) else raw
    by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        source_id = item.get("source_id")
        if not source_id:
            raise ExperimentError(f"{path}: source_id alani olmayan kaynak var.")
        if source_id in by_id:
            raise ExperimentError(f"{path}: kaynak kimligi benzersiz degil: {source_id}")
        if not (item.get("text") or "").strip():
            raise ExperimentError(f"{path}: {source_id} kaynaginin metni bos.")
        try:
            applicability.validate_source(item)
        except ValueError as exc:
            raise ExperimentError(f"{path}: {exc}") from exc
        by_id[source_id] = item
    if not by_id:
        raise ExperimentError(f"{path}: hic kaynak bulunamadi.")
    return by_id


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for lineno, line in enumerate(read_text(path).splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            case = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ExperimentError(f"{path} satir {lineno}: bozuk JSON ({exc})") from exc
        case_id = case.get("case_id")
        if not case_id:
            raise ExperimentError(f"{path} satir {lineno}: case_id alani yok.")
        if case_id in seen:
            raise ExperimentError(f"{path} satir {lineno}: vaka kimligi benzersiz degil: {case_id}")
        try:
            applicability.parse_date(case.get("olay_tarihi"), f"{case_id}.olay_tarihi")
        except ValueError as exc:
            raise ExperimentError(f"{path} satir {lineno}: {exc}") from exc
        seen.add(case_id)
        cases.append(case)
    if not cases:
        raise ExperimentError(f"{path}: hic vaka bulunamadi.")
    return cases


def validate_case_sources(cases: list[dict[str, Any]], sources: dict[str, Any]) -> None:
    """Olmayan kaynak kimligi varsa istek gondermeden durur."""
    for case in cases:
        source_ids = case.get("source_ids") or []
        if not source_ids:
            raise ExperimentError(f"{case['case_id']}: source_ids bos; istek gonderilmedi.")
        missing = [sid for sid in source_ids if sid not in sources]
        if missing:
            raise ExperimentError(
                f"{case['case_id']}: kaynak kimligi cozulemedi: {', '.join(missing)}. "
                f"Mevcut kaynaklar: {', '.join(sorted(sources))}. Modele istek gonderilmedi."
            )


# --------------------------------------------------------------------------
# Prompt kurma
# --------------------------------------------------------------------------


def build_user_message(
    case: dict[str, Any],
    sources: dict[str, dict[str, Any]],
    filtre: applicability.Filtre | None = None,
) -> str:
    """Yalnizca bu vakanin verisini ve secilmis kaynaklarini iceren kullanici mesaji.

    filtre verilirse (uygunluk motoru acik) yalnizca elenmemis kaynaklarin metni
    gonderilir; elenen kaynaklarin METNI modele hic gitmez. Motor kapaliyken ve
    vakada olay_tarihi yokken mesaj, motordan onceki bicimle birebir aynidir.
    """
    lines: list[str] = []

    source_ids = list(filtre.kullanilan) if filtre is not None else list(case["source_ids"])
    lines.append("### KAYNAKLAR (veri)")
    if not source_ids:
        lines.append("")
        lines.append("(Olay tarihi ve API surumu icin uygun kaynak kalmadi.)")
    for source_id in source_ids:
        doc = sources[source_id]
        versions = ", ".join(doc.get("api_versions") or [])
        lines.append("")
        lines.append(f"[{doc['source_id']}] {doc.get('title', '')}")
        lines.append(
            f"platform={doc.get('platform')} | ortam={doc.get('environment')} | "
            f"api_surumleri={versions} | anlik_goruntu_tarihi={doc.get('snapshot_date')}"
        )
        lines.append(doc["text"].strip())

    lines.append("")
    lines.append("### VAKA (veri)")
    api_version = case.get("api_version")
    lines.append(f"vaka_kimligi: {case['case_id']}")
    lines.append(f"platform: {case.get('platform')} | ortam: {case.get('environment')}")
    lines.append(f"api_surumu: {api_version if api_version is not None else 'bilinmiyor'}")
    if "olay_tarihi" in case:
        olay = case["olay_tarihi"]
        lines.append(f"olay_tarihi: {olay if olay is not None else 'bilinmiyor'}")
    lines.append(f"destek_talebi: {case.get('ticket', '')}")
    lines.append("istek_kaydi: " + json.dumps(case.get("request"), ensure_ascii=False))
    lines.append("yanit_kaydi: " + json.dumps(case.get("response"), ensure_ascii=False))

    if filtre is not None:
        lines.append("")
        lines.append("### UYGUNLUK KONTROLU (kurallarla tespit edilen bulgular; veri)")
        for source_id, karar in filtre.degerlendirilen.items():
            note = {
                applicability.UYGUN_DEGIL: " Bu kaynak gonderilmedi.",
                applicability.BELIRSIZ: " Kaynak gonderildi; uygunlugu dogrulanamadi.",
            }.get(karar.durum, "")
            lines.append(
                f"- {source_id}: {karar.durum} ({karar.gerekce}) - "
                f"{applicability.GEREKCE_ACIKLAMASI[karar.gerekce]}.{note}"
            )

    lines.append("")
    lines.append("### GOREV")
    lines.append(
        "Yukaridaki kayda ve yalnizca verilen kaynaklara dayanarak dort baslikli "
        "Turkce yanit taslagini yaz."
    )
    if filtre is not None and filtre.belirsiz:
        lines.append(
            "UYGUNLUK KONTROLU bolumundeki belirsizlikleri 'Belirsizlik / eksik bilgi' "
            "basliginda belirt."
        )
    if filtre is not None and not filtre.kullanilan:
        lines.append(
            "Uygun kaynak kalmadigi icin teshis yazma; gerekceyi belirt ve kaydi uzman "
            "incelemesine yonlendir."
        )
    return "\n".join(lines)


def build_messages(
    system_prompt: str,
    case: dict[str, Any],
    sources: dict[str, dict[str, Any]],
    filtre: applicability.Filtre | None = None,
) -> list[dict[str, str]]:
    """Her vaka icin sifirdan mesaj dizisi. Onceki vaka/cevap tasinmaz."""
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": build_user_message(case, sources, filtre)},
    ]


# --------------------------------------------------------------------------
# Ollama istemcisi
# --------------------------------------------------------------------------


def _http_json(url: str, payload: dict | None = None, timeout: int = PREFLIGHT_TIMEOUT_S) -> Any:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url, data=data, headers=headers, method="POST" if data is not None else "GET"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
    return loads_strict(body)


class NonStandardJSONNumber(ValueError):
    """NaN / Infinity / -Infinity veya sonsuza tasan sayi: standart JSON degildir."""


def _reject_constant(name: str) -> Any:
    raise NonStandardJSONNumber(f"standart disi JSON sayisi: {name}")


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):  # ör. 1e999 -> inf
        raise NonStandardJSONNumber(f"sonsuza tasan JSON sayisi: {text[:50]}")
    return value


def loads_strict(text: str) -> Any:
    """Ollama yanitlari icin JSON okuyucu; standart disi sayilari reddeder."""
    return json.loads(text, parse_constant=_reject_constant, parse_float=_finite_float)


def _is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError)


def preflight(host: str, model: str) -> dict[str, Any]:
    """Sunucu ve model yoksa tek acik hatayla durur."""
    started = time.perf_counter()
    try:
        version_info = _http_json(f"{host}/api/version")
    except Exception as exc:  # noqa: BLE001 - tek anlasilir hataya ceviriyoruz
        raise ExperimentError(
            f"Ollama sunucusuna ulasilamadi: {host} ({type(exc).__name__}: {exc}). "
            "Sunucunun calistigini dogrulayin."
        ) from exc
    # Tek, soguk bir istek turunun tamami: ad cozumleme, baglanti, HTTP turu, sunucu
    # isleme ve JSON ayristirma birlikte. Saf baglanti maliyeti degildir.
    version_request_s = round(time.perf_counter() - started, 4)

    try:
        tags = _http_json(f"{host}/api/tags")
    except Exception as exc:  # noqa: BLE001
        raise ExperimentError(
            f"Model listesi alinamadi: {host}/api/tags ({type(exc).__name__}: {exc})"
        ) from exc

    entries = tags.get("models") or []
    entry = next(
        (item for item in entries if model in {item.get("model"), item.get("name")}), None
    )
    if entry is None:
        installed = ", ".join(sorted(str(i.get("model") or i.get("name")) for i in entries))
        raise ExperimentError(
            f"Model bulunamadi: {model}. Yuklu modeller: {installed or '(bos)'}. "
            "Otomatik indirme yapilmaz ve baska modele gecilmez."
        )

    digest = entry.get("digest") or ""
    return {
        "ollama_version": version_info.get("version"),
        "api_version_istek_suresi_s": version_request_s,
        "api_version_istek_suresi_notu": (
            "Tek GET /api/version isteginin istemcide olculen toplam suresi (tek ornek). "
            "Saf baglanti maliyeti degildir ve istemci surelerinden cikarilacak sabit bir "
            "deger olarak kullanilmamalidir. Vaka bazli fark icin "
            "istemci_eksi_sunucu_total_s alanina bakin; nedeni bu olcumle belirlenmez."
        ),
        "model_tag_entry": entry,
        "model_digest": digest or None,
        "model_short_id": digest[:12] if digest else None,
        "model_short_id_note": "digest'in ilk 12 karakterinden turetildi (ollama list ID ile ayni yontem).",
    }


def fetch_model_metadata(host: str, model: str) -> dict[str, Any]:
    """Modelin varsayilan parametrelerini kaydeder; alinamazsa 'bilinmiyor' yazar."""
    try:
        data = _http_json(f"{host}/api/show", {"model": model})
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "bilinmiyor",
            "reason": f"/api/show cagrisi basarisiz: {type(exc).__name__}: {exc}",
        }

    parameters = data.get("parameters")
    model_info = data.get("model_info")
    return {
        "status": "alindi",
        "details": data.get("details"),
        "capabilities": data.get("capabilities"),
        "default_parameters_raw": parameters if parameters else None,
        "default_parameters_status": (
            "alindi" if parameters else "bilinmiyor: /api/show 'parameters' alani bos dondu"
        ),
        "model_info_keys": sorted(model_info) if isinstance(model_info, dict) else None,
    }


def extract_metrics(data: dict[str, Any]) -> dict[str, Any]:
    """Sunucu olcumleri. Nanosaniye -> saniye. Eksik alan icin None (sahte sifir yok)."""
    metrics: dict[str, Any] = {
        "prompt_eval_count": data.get("prompt_eval_count"),
        "eval_count": data.get("eval_count"),
    }
    for field in NS_DURATION_FIELDS:
        value = data.get(field)
        metrics[f"{field}_ns"] = value  # ham deger oldugu gibi saklanir
        metrics[f"{field}_s"] = (
            round(value / 1_000_000_000, 4) if _is_valid_duration(value) else None
        )
    return metrics


def _is_valid_duration(value: Any) -> bool:
    """Sonlu, negatif olmayan sayi. bool, NaN, sonsuz ve negatif deger gecersizdir."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def chat_once(
    host: str,
    model: str,
    messages: list[dict[str, str]],
    options: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    """Tek /api/chat cagrisi. Yeniden deneme yok. Hatalar kayit olarak doner."""
    payload = {"model": model, "messages": messages, "stream": False, "options": options}
    request = urllib.request.Request(
        f"{host}/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            http_status = response.status
            raw_text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            body = "(govde okunamadi)"
        return _failure(
            "http_error",
            time.perf_counter() - started,
            {"type": "HTTPError", "http_status": exc.code, "body": body[:2000]},
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        kind = "timeout" if _is_timeout(exc) else "connection_error"
        return _failure(
            kind,
            time.perf_counter() - started,
            {"type": type(exc).__name__, "message": str(exc)},
        )
    except http.client.HTTPException as exc:
        # Yarim govde (IncompleteRead), bozuk durum satiri vb. OSError degildir.
        return _failure(
            "protocol_error",
            time.perf_counter() - started,
            {"type": type(exc).__name__, "message": str(exc)},
        )

    elapsed = time.perf_counter() - started

    try:
        data = loads_strict(raw_text)
    except ValueError as exc:  # JSONDecodeError, NonStandardJSONNumber, int basamak siniri
        return _failure(
            "invalid_json",
            elapsed,
            {
                "type": type(exc).__name__,
                "message": str(exc),
                "http_status": http_status,
                "raw_text_prefix": raw_text[:2000],
            },
        )

    shape_problem = None
    if not isinstance(data, dict):
        shape_problem = f"kok govde nesne degil: {type(data).__name__}"
    elif not isinstance(data.get("message"), dict):
        shape_problem = f"message nesne degil: {type(data.get('message')).__name__}"
    elif not isinstance(data["message"].get("content"), str):
        shape_problem = f"message.content metin degil: {type(data['message'].get('content')).__name__}"
    if shape_problem:
        return _failure(
            "invalid_shape",
            elapsed,
            {
                "type": "UnexpectedShape",
                "message": shape_problem,
                "http_status": http_status,
                "raw_text_prefix": raw_text[:2000],
            },
        )

    message = data["message"]
    content = message["content"]
    done_reason = data.get("done_reason")

    # Tamamlanmis yanit sozlesmesi: bos olmayan metin, done=true, done_reason="stop".
    failure_kind = None
    if done_reason == "length":
        failure_kind = "truncated_length"
    elif not content.strip():
        failure_kind = "empty_response"
    elif data.get("done") is not True:
        failure_kind = "not_done"
    elif done_reason != "stop":
        failure_kind = "unexpected_done_reason"

    metrics = extract_metrics(data)
    return {
        "ok": failure_kind is None,
        "failure_kind": failure_kind,
        "client_elapsed_s": round(elapsed, 3),
        "istemci_eksi_sunucu_total_s": _client_minus_server(elapsed, metrics),
        "http_status": http_status,
        "error": None,
        "done": data.get("done"),
        "done_reason": done_reason,
        "content": content,
        "thinking": message.get("thinking"),
        "metrics": metrics,
        "raw_response": data,
    }


def _client_minus_server(elapsed: float, metrics: dict[str, Any]) -> float | None:
    """Istemci gecen suresi - sunucu total_duration. Olcum eksik/gecersizse None."""
    total_ns = metrics.get("total_duration_ns")
    if not _is_valid_duration(total_ns):
        return None
    return round(elapsed - total_ns / 1_000_000_000, 4)


def _failure(kind: str, elapsed: float, error: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": False,
        "failure_kind": kind,
        "client_elapsed_s": round(elapsed, 3),
        "istemci_eksi_sunucu_total_s": None,
        "http_status": error.get("http_status"),
        "error": error,
        "done": None,
        "done_reason": None,
        "content": None,
        "thinking": None,
        "metrics": None,
        "raw_response": None,
    }


# --------------------------------------------------------------------------
# Mekanik gozlem (puan degildir)
# --------------------------------------------------------------------------


def mechanical_observations(content: str | None) -> dict[str, Any]:
    """Sadece bicimsel gozlem. Teknik dogruluk veya kaynak destegi puani DEGILDIR."""
    if not content:
        return {"karakter_sayisi": 0, "dort_baslik_var": False, "gecen_kaynak_kimlikleri": []}
    return {
        "karakter_sayisi": len(content),
        "dort_baslik_var": all(heading in content for heading in REQUIRED_HEADINGS),
        "gecen_kaynak_kimlikleri": [sid for sid in KNOWN_SOURCE_PATTERNS if sid in content],
        "uyari": "Bu alanlar bicimsel kontroldur; iddianin dogrulugunu kanitlamaz.",
    }


# --------------------------------------------------------------------------
# Calisma
# --------------------------------------------------------------------------


def make_run_id(mode: str = "C") -> str:
    """C modunun adi degismez; A modu dizin adinda '-A-' ile ayirt edilir."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    marker = "-A" if mode == "A" else ""
    return f"{stamp}{marker}-{uuid.uuid4().hex[:6]}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stats(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "adet": len(values),
        # 6 basamak: A modunun mikrosaniye duzeyindeki sureleri 0.0'a yuvarlanmasin.
        "medyan": round(statistics.median(values), 6),
        "min": round(min(values), 6),
        "max": round(max(values), 6),
    }


def warmup_summary(warmup_result: dict[str, Any] | None, mode: str = "C") -> dict[str, Any]:
    """Isinmanin durumu. Isinma hicbir kosulda vaka istatistiklerine girmez."""
    if mode == "A":
        return {"durum": "uygulanamaz", "failure_kind": None, "not": None}
    if warmup_result is None:
        return {
            "durum": "atlandi",
            "failure_kind": None,
            "not": "Isinma yapilmadi; ilk vakanin sureleri model yukleme etkisi icerebilir.",
        }
    if warmup_result["ok"]:
        return {"durum": "basarili", "failure_kind": None, "not": None}
    return {
        "durum": "basarisiz",
        "failure_kind": warmup_result["failure_kind"],
        "not": (
            "Isinma basarisiz oldu; sonraki vaka surelerinin (ozellikle ilk vakanin) "
            "model yukleme etkisi icerebilir. load_duration_s alanina bakin."
        ),
    }


def build_summary(
    run_id: str,
    model: str,
    records: list[dict[str, Any]],
    warmup_result: dict[str, Any] | None = None,
    planned_cases: int | None = None,
    interruption: dict[str, Any] | None = None,
    mode: str = "C",
) -> dict[str, Any]:
    ok_records = [r for r in records if r["ok"]]
    failed = [r for r in records if not r["ok"]]

    failure_kinds: dict[str, int] = {}
    for record in failed:
        kind = record["failure_kind"] or "unknown"
        failure_kinds[kind] = failure_kinds.get(kind, 0) + 1

    client_times = [r["client_elapsed_s"] for r in ok_records if r["client_elapsed_s"] is not None]
    server_times = [
        r["metrics"]["total_duration_s"]
        for r in ok_records
        if r.get("metrics") and r["metrics"].get("total_duration_s") is not None
    ]

    per_case = []
    for record in records:
        metrics = record.get("metrics") or {}
        per_case.append(
            {
                "case_id": record["case_id"],
                "ok": record["ok"],
                "failure_kind": record["failure_kind"],
                "done_reason": record.get("done_reason"),
                "client_elapsed_s": record.get("client_elapsed_s"),
                "istemci_eksi_sunucu_total_s": record.get("istemci_eksi_sunucu_total_s"),
                "total_duration_s": metrics.get("total_duration_s"),
                "load_duration_s": metrics.get("load_duration_s"),
                "prompt_eval_duration_s": metrics.get("prompt_eval_duration_s"),
                "eval_duration_s": metrics.get("eval_duration_s"),
                "prompt_eval_count": metrics.get("prompt_eval_count"),
                "eval_count": metrics.get("eval_count"),
            }
        )

    return {
        "run_id": run_id,
        "mod": mode,
        "model": model,
        "isinma": warmup_summary(warmup_result, mode),
        "calisma_durumu": "yarida_kesildi" if interruption else "tamamlandi",
        "kesinti": interruption,
        "planlanan_vaka_sayisi": planned_cases if planned_cases is not None else len(records),
        "vaka_sayisi": len(records),
        "teknik_tamamlanan": len(ok_records),
        "teknik_basarisiz": len(failed),
        "basarisizlik_turleri": failure_kinds,
        "sure_ozetine_dahil_vakalar": [r["case_id"] for r in ok_records],
        "sure_ozeti_disinda": [
            {"case_id": r["case_id"], "failure_kind": r["failure_kind"]} for r in failed
        ],
        "istemci_gecen_sure_s": _stats(client_times),
        "sunucu_total_duration_s": _stats(server_times),
        "vaka_bazli": per_case,
        "notlar": RESULT_NOTES,
    }


def _write_summary(run_dir: Path, summary: dict[str, Any]) -> None:
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run_experiment(args: argparse.Namespace) -> int:
    prompt_path = Path(args.prompt).resolve()
    docs_path = Path(args.docs).resolve()
    cases_path = Path(args.cases).resolve()

    system_prompt = read_text(prompt_path)
    sources = load_sources(docs_path)
    cases = load_cases(cases_path)
    validate_case_sources(cases, sources)

    print(
        f"Veri dogrulandi: {len(sources)} kaynak ({', '.join(sorted(sources))}), "
        f"{len(cases)} vaka ({cases[0]['case_id']}..{cases[-1]['case_id']})."
    )

    if args.validate_only:
        print("--validate-only: model istegi gonderilmedi.")
        return 0

    mode = args.mode
    if mode == "C":
        preflight_info = preflight(args.host, args.model)
        metadata = fetch_model_metadata(args.host, args.model)
        print(
            f"Ollama {preflight_info['ollama_version']} | model {args.model} "
            f"| kisa kimlik {preflight_info['model_short_id']}"
        )
    else:
        print("A modu: kural tabanli temel yontem. Ollama'ya istek gonderilmez.")
    print(
        "Uygunluk motoru: "
        + ("KAPALI (--no-applicability); kaynaklar filtrelenmez." if args.no_applicability
           else "acik; kaynaklar surum ve olay tarihine gore filtrelenir.")
    )

    run_id = make_run_id(mode)
    run_dir = Path(args.results_root).resolve() / run_id
    try:
        run_dir.mkdir(parents=True, exist_ok=False)  # mevcut sonuclar asla ezilmez
    except FileExistsError as exc:
        raise ExperimentError(
            f"Sonuc dizini zaten var: {run_dir}. Mevcut sonuclar ezilmez; calisma durduruldu."
        ) from exc

    options = {"num_ctx": args.num_ctx, "num_predict": args.num_predict}

    input_files = {
        "prompt.txt": {"path": str(prompt_path), "sha256": sha256_file(prompt_path)},
        "docs.json": {"path": str(docs_path), "sha256": sha256_file(docs_path)},
        "cases.jsonl": {"path": str(cases_path), "sha256": sha256_file(cases_path)},
    }
    runner_file = {
        "path": str(RUNNER_PATH),
        "sha256": sha256_file(RUNNER_PATH),
        "not": "Calisma basinda diskteki run.py dosyasinin ozeti.",
    }
    applicability_on = not args.no_applicability
    applicability_meta = {
        "acik": applicability_on,
        "path": str(APPLICABILITY_PATH),
        "sha256": sha256_file(APPLICABILITY_PATH),
        "not": (
            "Calisma basinda diskteki applicability.py dosyasinin ozeti. acik=false: "
            "--no-applicability ile kapatildi; kaynaklar filtrelenmedi."
        ),
    }

    if mode == "A":
        run_meta = {
            "run_id": run_id,
            "mod": "A",
            "started_at_utc": _utc_now(),
            "model": None,
            "host": None,
            "options": None,
            "auto_retry": 0,
            "concurrency": 1,
            "ayar_notlari": A_MODE_NOTES,
            "girdi_dosyalari": input_files,
            "calistirici_dosyasi": runner_file,
            "kural_motoru_dosyasi": {
                "path": str(RULES_PATH),
                "sha256": sha256_file(RULES_PATH),
                "not": "Calisma basinda diskteki rules_mode.py dosyasinin ozeti.",
            },
            "uygunluk_motoru": applicability_meta,
            "cevap_anahtari": "expected.jsonl uretim yolunda okunmaz; ozeti bilerek alinmaz.",
            "python_version": sys.version,
            "python_implementation": platform.python_implementation(),
            "platform": platform.platform(),
        }
    else:
        run_meta = {
            "run_id": run_id,
            "mod": "C",
            "started_at_utc": _utc_now(),
            "model": args.model,
            "host": args.host,
            "options": options,
            "stream": False,
            "request_timeout_s": args.timeout,
            "auto_retry": 0,
            "concurrency": 1,
            "ayar_notlari": SETTINGS_NOTES,
            "girdi_dosyalari": input_files,
            "calistirici_dosyasi": runner_file,
            "uygunluk_motoru": applicability_meta,
            "cevap_anahtari": "expected.jsonl uretim yolunda okunmaz; ozeti bilerek alinmaz.",
            "ollama_version": preflight_info["ollama_version"],
            "api_version_istek_suresi_s": preflight_info["api_version_istek_suresi_s"],
            "api_version_istek_suresi_notu": preflight_info["api_version_istek_suresi_notu"],
            "model_digest": preflight_info["model_digest"],
            "model_short_id": preflight_info["model_short_id"],
            "model_short_id_note": preflight_info["model_short_id_note"],
            "model_tag_entry": preflight_info["model_tag_entry"],
            "model_metadata": metadata,
            "python_version": sys.version,
            "python_implementation": platform.python_implementation(),
            "platform": platform.platform(),
        }
    (run_dir / "run_meta.json").write_text(
        json.dumps(run_meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --- Isinma: sonuclardan ve sure ozetinden ayri tutulur ---
    warmup_result: dict[str, Any] | None = None
    if mode == "A":
        pass  # A modunda model yok; isinma uygulanamaz.
    elif args.no_warmup:
        print("Isinma istegi atlandi (--no-warmup).")
    else:
        print("Isinma istegi gonderiliyor...")
        warmup_result = chat_once(
            args.host, args.model, WARMUP_MESSAGES, options, args.timeout
        )
        (run_dir / "warmup.json").write_text(
            json.dumps(
                {
                    "amac": "Model yukleme maliyetini vaka olcumlerinden ayirmak.",
                    "sure_ozetine_dahil_mi": False,
                    "messages": WARMUP_MESSAGES,
                    "options": options,
                    **warmup_result,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        state = "tamam" if warmup_result["ok"] else f"HATA ({warmup_result['failure_kind']})"
        print(f"  isinma: {state} | istemci {warmup_result['client_elapsed_s']} s")

    # --- Vakalar: sirayla, her biri yeni mesaj dizisiyle ---
    records: list[dict[str, Any]] = []
    cases_out = run_dir / "cases.jsonl"
    current_case_id: str | None = None
    try:
        with cases_out.open("w", encoding="utf-8") as handle:
            for index, case in enumerate(cases, start=1):
                current_case_id = case["case_id"]
                print(f"[{index}/{len(cases)}] {case['case_id']} calisiyor...", flush=True)

                # Uygunluk filtresi aramadan ve modelden ONCE calisir.
                filtre = (
                    applicability.filter_sources(case, sources, list(case["source_ids"]))
                    if applicability_on
                    else None
                )
                started_at_utc = _utc_now()  # istekten ONCE alinir
                if mode == "A":
                    messages = None  # modele mesaj gonderilmez
                    result = rules_mode.run_case(case, list(case["source_ids"]), filtre)
                else:
                    messages = build_messages(system_prompt, case, sources, filtre)
                    result = chat_once(args.host, args.model, messages, options, args.timeout)
                uygunluk = (
                    filtre.kayit()
                    if filtre is not None
                    else {
                        # Motor kapali: karar verilmedi; tum kaynaklar kullanildi.
                        "degerlendirilen_kaynaklar": None,
                        "kullanilan_kaynaklar": list(case["source_ids"]),
                        "elenen_kaynaklar": None,
                        "belirsiz_kaynaklar": None,
                    }
                )
                record = {
                    "case_id": case["case_id"],
                    "mod": mode,
                    "api_version": case.get("api_version"),
                    "olay_tarihi": case.get("olay_tarihi"),
                    "source_ids": list(case["source_ids"]),
                    "uygunluk_motoru_acik": applicability_on,
                    **uygunluk,
                    "model": args.model if mode == "C" else None,
                    "started_at_utc": started_at_utc,
                    "request_options": options if mode == "C" else None,
                    "messages": messages,
                    "kural_karari": None,
                    **result,
                    "mekanik_gozlem": mechanical_observations(result.get("content")),
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                records.append(record)

                if result["ok"]:
                    total = (result["metrics"] or {}).get("total_duration_s")
                    print(
                        f"    tamam | istemci {result['client_elapsed_s']} s "
                        f"| sunucu total {total} s | eval_count {(result['metrics'] or {}).get('eval_count')}"
                    )
                else:
                    print(f"    BASARISIZ | tur: {result['failure_kind']} | {result['error']}")
    except BaseException as exc:
        # Beklenmeyen istisna (Ctrl+C dahil): o ana kadarki ozet yazilir, istisna yutulmaz.
        interruption = {
            "istisna_turu": type(exc).__name__,
            "mesaj": str(exc)[:500],
            "kesildigi_vaka": current_case_id,
            "calistirilan_vaka_sayisi": len(records),
        }
        try:
            _write_summary(
                run_dir,
                build_summary(
                    run_id, run_meta["model"], records, warmup_result, len(cases), interruption,
                    mode,
                ),
            )
        except Exception as summary_exc:  # noqa: BLE001 - asil istisna asagida yine firlatilir
            print(
                f"HATA: kismi ozet yazilamadi ({type(summary_exc).__name__}: {summary_exc}).",
                file=sys.stderr,
            )
        else:
            print(
                f"HATA: calisma {current_case_id} vakasinda yarida kesildi "
                f"({type(exc).__name__}); {len(records)}/{len(cases)} vakanin ozeti yazildi: "
                f"{run_dir / 'summary.json'}",
                file=sys.stderr,
            )
        raise  # asil istisna; ozet yazimindaki ikinci hata onu gizlemez

    summary = build_summary(
        run_id, run_meta["model"], records, warmup_result, len(cases), None, mode
    )
    _write_summary(run_dir, summary)

    print("")
    print(f"Sonuc dizini: {run_dir}")
    print(
        f"Teknik tamamlanan: {summary['teknik_tamamlanan']}/{summary['vaka_sayisi']} "
        f"| basarisiz: {summary['teknik_basarisiz']} {summary['basarisizlik_turleri'] or ''}"
    )
    print(f"Isinma: {summary['isinma']['durum']}")
    if summary["isinma"]["not"]:
        print(f"  UYARI: {summary['isinma']['not']}")
    print(f"Istemci gecen sure (yalniz tamamlananlar): {summary['istemci_gecen_sure_s']}")
    print("Teknik dogruluk ve kaynak destegi insan tarafindan puanlanacak (review_template.md).")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Destekizi ilk yerel model deneyi (kontrollu kaynaklar ve gelistirme vakalari)."
    )
    parser.add_argument(
        "--mode",
        choices=("A", "C"),
        default="C",
        help="C: yerel model (varsayilan). A: kural tabanli temel yontem; modele istek gitmez.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--prompt", default=str(HERE / "prompt.txt"))
    parser.add_argument("--docs", default=str(HERE / "docs.json"))
    parser.add_argument("--cases", default=str(HERE / "cases.jsonl"))
    parser.add_argument("--results-root", default=str(HERE / "results"))
    parser.add_argument("--num-ctx", type=int, default=DEFAULT_NUM_CTX)
    parser.add_argument("--num-predict", type=int, default=DEFAULT_NUM_PREDICT)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--no-warmup", action="store_true")
    parser.add_argument(
        "--no-applicability",
        action="store_true",
        help="Uygunluk motorunu kapatir (ablation): vakanin tum kaynaklari filtresiz kullanilir.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Yalnizca veri dogrulamasi yapar; modele istek gondermez.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = build_arg_parser().parse_args(argv)
    try:
        return run_experiment(args)
    except ExperimentError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
