"""Destekizi - yerel Ollama HTTP istemcisi.

On kontrol (`preflight`), model ust verisi, tek /api/chat cagrisi (`chat_once`) ve
hata siniflandirmasi. Otomatik yeniden deneme yok. Yalnizca standart kutuphane.
"""

from __future__ import annotations

import http.client
import json
import math
import time
import urllib.error
import urllib.request
from typing import Any

from inputs import ExperimentError

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:4b-instruct-2507-q4_K_M"
DEFAULT_NUM_CTX = 4096
DEFAULT_NUM_PREDICT = 384
DEFAULT_TIMEOUT_S = 180
PREFLIGHT_TIMEOUT_S = 20

NS_DURATION_FIELDS = (
    "total_duration",
    "load_duration",
    "prompt_eval_duration",
    "eval_duration",
)


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
