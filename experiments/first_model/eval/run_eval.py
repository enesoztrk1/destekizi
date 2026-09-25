#!/usr/bin/env python3
"""Destekizi - deterministik degerlendirme betigi. Model CAGIRMAZ.

Bir veya iki sonuc dizinini (results/<run_id>/) okur, expected.jsonl icindeki
makine_kontrolleri ile karsilastirir ve markdown rapor uretir. Iki dizin
verilirse (ornegin A ve C modu) yan yana karsilastirir.

SINIR: Buradaki metrikler bicimsel ve kaynak duzeyindedir. Aciklamanin teknik
dogrulugunu, kaynak desteginin gercekligini ve belirsizlik yonetimini OLCMEZ.
Ifade kontrolleri buyuk/kucuk harf duyarsiz alt dize eslesmesidir; anlami
olcmez (olumsuz cumle, alinti veya esanlamli ifade yanlis sonuc verebilir).

Kullanim:
    py -3.12 eval/run_eval.py <sonuc_dizini> [<ikinci_sonuc_dizini>] [--out rapor.md]
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_EXPECTED = HERE.parent / "expected.jsonl"

# Uygunluk durum ve gerekce kodlarinin tek kaynagi applicability.py'dir. Yalnizca
# sabitler okunur; beklenen degerler motorla HESAPLANMAZ.
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))
import applicability  # noqa: E402

STATUSES = ("taslak_hazir", "bilgi_gerekli", "uzman_incelemesi")
UNDETERMINED = "belirlenemedi"
MULTIPLE_FAMILIES = "coklu"

SOURCE_FAMILY = {
    "D1": "yetkilendirme", "D2": "istek_siniri", "D3": "sayfalama",
    "D4": "yetkilendirme", "D5": "yetkilendirme",
    "D6": "istek_siniri", "D7": "istek_siniri", "D8": "sayfalama",
}
SOURCE_ID_RE = re.compile(r"\b(" + "|".join(SOURCE_FAMILY) + r")\b")

# Belirsizlik gosterimi sezgiseli: beklenen BELIRSIZ kaynagin gerekce koduna gore
# "Belirsizlik / eksik bilgi" bolumunde aranan isaret. A modunun belirsizlik
# satirlari ayni kisi tarafindan yazildi; bu metrik de A lehine yanli olabilir.
UNCERTAINTY_MARKERS = {
    applicability.TARIH_BILINMIYOR: "olay tarihi",
    applicability.KAYNAK_TARIHI_YOK: "yürürlük",
    applicability.SURUM_BILINMIYOR: "sürüm",
    applicability.KAYNAK_SURUMU_YOK: "sürüm",
}

# Durum sezgiseli: YALNIZCA "Sonraki adim" bolumune bakilir, sirayla:
#   "uzman" geciyorsa -> uzman_incelemesi
#   bilgi isteme isaretlerinden biri geciyorsa -> bilgi_gerekli
#   aksi halde -> taslak_hazir
# Bu bir yaklasikliktir: esanlamli ifadeleri kacirir. Liste A modu metinleriyle
# ayni kisi tarafindan yazildigi icin karsilastirma A lehine yanli olabilir.
EXPERT_MARKERS = ("uzman",)
INFO_REQUEST_MARKERS = ("paylaş", "belirtin", "iletin")

HEADINGS = {
    # Baslik sozcugunden sonra \b sart: "- Kaynakların ..." gibi bir madde yeni bolum
    # baslatmasin (Turkce ek almis sozcuk baslik degildir).
    "bulgular": re.compile(r"^\W*bulgular\b\W*:?", re.I),
    "belirsizlik": re.compile(r"^\W*belirsizlik\b[^:\n]*:?", re.I),
    "sonraki_adim": re.compile(r"^\W*sonraki\s+ad[ıi]m\b\W*:?", re.I),
    "kaynaklar": re.compile(r"^\W*kaynaklar\b\W*:?", re.I),
}

LIMITATION = (
    "> **Sınır:** Bu metrikler biçimsel ve kaynak düzeyindedir. Açıklamanın teknik "
    "doğruluğunu, kaynak desteğinin gerçekliğini ve belirsizlik yönetimini "
    "**ölçmezler**. Bunlar `review_template.md` ile insan tarafından puanlanır ve bu "
    "puanlama **henüz yapılmamıştır**."
)
APPLICABILITY_LIMITATION = (
    "> **Uygunluk metriklerinin sınırı:** Uygunluk metrikleri kaynak uygunluk "
    "kararının (sürüm ve yürürlük) doğruluğunu ölçer; açıklamanın teknik doğruluğunu "
    "ve kaynak desteğinin gerçekliğini **ölçmez**. Bunlar `review_template.md` ile "
    "insan tarafından puanlanır ve bu puanlama **henüz yapılmamıştır**."
)


# --------------------------------------------------------------------------
# Okuma
# --------------------------------------------------------------------------


FAMILIES = ("yetkilendirme", "istek_siniri", "sayfalama")
LIST_KEYS = ("gerekli_kaynaklar", "yasak_kaynaklar", "yasak_ifadeler", "gerekli_ifadeler")
MAP_KEYS = ("beklenen_uygunluk", "beklenen_gerekce")
CHECK_KEYS = ("beklenen_durum", "beklenen_aile") + LIST_KEYS + MAP_KEYS


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Bozuk satiri dosya ve satir numarasiyla bildirir; sessizce atlamaz."""
    rows = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name} satir {lineno}: bozuk JSON ({exc})") from exc
        if not isinstance(row, dict) or not isinstance(row.get("case_id"), str):
            raise ValueError(f"{path.name} satir {lineno}: case_id iceren bir nesne degil")
        rows.append(row)
    return rows


def _validate_checks(case_id: str, block: dict[str, Any]) -> None:
    """Yazim hatali anahtar veya gecersiz deger sessizce 'kontrol yok' olmasin."""
    unknown = sorted(set(block) - set(CHECK_KEYS))
    if unknown:
        raise ValueError(f"{case_id}: makine_kontrolleri bilinmeyen alan: {', '.join(unknown)}")
    if "beklenen_durum" in block and block["beklenen_durum"] not in STATUSES:
        raise ValueError(f"{case_id}: gecersiz beklenen_durum: {block['beklenen_durum']!r}")
    if "beklenen_aile" in block and block["beklenen_aile"] not in FAMILIES + (None,):
        raise ValueError(f"{case_id}: gecersiz beklenen_aile: {block['beklenen_aile']!r}")
    for key in LIST_KEYS:
        value = block.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError(f"{case_id}: {key} metin listesi olmali")
    for key in MAP_KEYS:
        value = block.get(key, {})
        if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
            raise ValueError(f"{case_id}: {key} kaynak kimligi -> deger nesnesi olmali")
    states = block.get("beklenen_uygunluk", {})
    for sid, state in states.items():
        if state not in applicability.DURUMLAR:
            raise ValueError(f"{case_id}: gecersiz beklenen_uygunluk {sid}: {state!r}")
    for sid, code in block.get("beklenen_gerekce", {}).items():
        if code not in applicability.GEREKCE_DURUMU:
            raise ValueError(f"{case_id}: gecersiz beklenen_gerekce {sid}: {code!r}")
        if sid in states and applicability.GEREKCE_DURUMU[code] != states[sid]:
            raise ValueError(
                f"{case_id}: {sid} gerekcesi {code!r}, {states[sid]} durumuyla celisiyor"
            )


def load_expected(path: Path) -> dict[str, dict[str, Any] | None]:
    """case_id -> makine_kontrolleri (alan yoksa None)."""
    checks: dict[str, dict[str, Any] | None] = {}
    for row in _read_jsonl(path):
        case_id = row["case_id"]
        if case_id in checks:
            raise ValueError(f"{path.name}: yinelenen case_id: {case_id}")
        block = row.get("makine_kontrolleri")
        if block is not None and not isinstance(block, dict):
            raise ValueError(f"{case_id}: makine_kontrolleri bir nesne olmali")
        if block is not None:
            _validate_checks(case_id, block)
        checks[case_id] = block
    return checks


def load_run(run_dir: Path) -> dict[str, Any]:
    records = _read_jsonl(run_dir / "cases.jsonl")
    seen: set[str] = set()
    for record in records:
        if record["case_id"] in seen:
            raise ValueError(f"{run_dir.name}/cases.jsonl: yinelenen case_id: {record['case_id']}")
        seen.add(record["case_id"])
    meta_path = run_dir / "run_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    summary_path = run_dir / "summary.json"
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        run_state = summary.get("calisma_durumu") or "belirtilmemiş (eski özet)"
    else:
        run_state = "özet yok"
    mode = meta.get("mod") or next((r.get("mod") for r in records if r.get("mod")), None)
    mode_note = None
    if mode is None:
        mode, mode_note = "C", "kayıtta mod alanı yok; C varsayıldı"
    motor_meta = meta.get("uygunluk_motoru")
    motor = motor_meta.get("acik") if isinstance(motor_meta, dict) else None
    return {
        "run_id": meta.get("run_id") or run_dir.name,
        "mode": mode,
        "mode_note": mode_note,
        "run_state": run_state,
        "motor": motor,  # True / False / None (motordan onceki kosu)
        "records": {r["case_id"]: r for r in records},
    }


# --------------------------------------------------------------------------
# Metinden turetilen ozellikler (her iki mod icin AYNI kurallar)
# --------------------------------------------------------------------------


def fold(text: str) -> str:
    """Buyuk/kucuk harf duyarsiz karsilastirma icin. 'İ' -> 'i' (Python 'i̇' uretmesin)."""
    return text.replace("İ", "i").lower()


def parse_sections(content: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in content.splitlines():
        matched = next((name for name, rx in HEADINGS.items() if rx.match(line.strip())), None)
        if matched:
            current = matched
            rest = HEADINGS[matched].sub("", line.strip(), count=1)
            sections[current] = [rest] if rest.strip() else []
        elif current:
            sections[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def cited_sources(sections: dict[str, str]) -> list[str] | None:
    """Yalnizca 'Kaynaklar' bolumundeki bilinen kaynak kimlikleri. Bolum yoksa None."""
    if "kaynaklar" not in sections:
        return None
    return sorted(set(SOURCE_ID_RE.findall(sections["kaynaklar"])))


def derive_status(sections: dict[str, str]) -> str:
    text = sections.get("sonraki_adim")
    if not text:
        return UNDETERMINED
    folded = fold(text)
    if any(marker in folded for marker in EXPERT_MARKERS):
        return "uzman_incelemesi"
    if any(marker in folded for marker in INFO_REQUEST_MARKERS):
        return "bilgi_gerekli"
    return "taslak_hazir"


def derive_family(cited: list[str] | None) -> str | None:
    if cited is None:
        return UNDETERMINED
    families = {SOURCE_FAMILY[s] for s in cited}
    if not families:
        return None
    return families.pop() if len(families) == 1 else MULTIPLE_FAMILIES


# --------------------------------------------------------------------------
# Degerlendirme
# --------------------------------------------------------------------------


def evaluate_case(record: dict[str, Any] | None, checks: dict[str, Any] | None) -> dict[str, Any]:
    """Tek vaka. Kontrol alani yoksa ilgili metrik None (kontrol edilmedi) olur."""
    ok = bool(record and record.get("ok"))
    content = (record or {}).get("content") or ""
    has_answer = ok and bool(content.strip())
    sections = parse_sections(content) if has_answer else {}
    cited = cited_sources(sections) if has_answer else None
    status = derive_status(sections) if has_answer else UNDETERMINED
    family = derive_family(cited) if has_answer else UNDETERMINED
    checks = checks or {}
    # Basarisiz kaydin (or. truncated_length) kismi metni ifade kontrolunu gecirmemeli.
    folded = fold(content) if has_answer else ""

    result: dict[str, Any] = {
        "kayit_var": record is not None,
        "cevap_var": has_answer,
        "ok": ok,
        "failure_kind": (record or {}).get("failure_kind") if record else "kayit_yok",
        "durum": status,
        "aile": family,
        "kaynaklar": cited,
        "durum_dogru": None,
        "aile_dogru": None,
        "gerekli_kaynak_tamam": None,
        "yasak_kaynak_ihlali": None,
        "yasak_ifadeler_bulunan": None,
        "gerekli_ifadeler_eksik": None,
        "uygunluk_dogru": None,
        "gerekce_dogru": None,
        "uygunluk_hatalari": None,
        "yururluk_disi_kaynak": None,
        "belirsizlik_gosterildi": None,
    }
    if "beklenen_durum" in checks:
        result["durum_dogru"] = status == checks["beklenen_durum"]
    if "beklenen_aile" in checks:
        result["aile_dogru"] = family == checks["beklenen_aile"]
    required = checks.get("gerekli_kaynaklar") or []
    if required:
        result["gerekli_kaynak_tamam"] = cited is not None and set(required) <= set(cited)
    # Yasak kontrolleri yalnizca incelenecek bir cevap varsa anlamlidir. Cevap yoksa
    # (veya Kaynaklar bolumu yoksa) "temiz" sayilmaz; None = kontrol edilemedi.
    forbidden = checks.get("yasak_kaynaklar") or []
    if forbidden and cited is not None:
        result["yasak_kaynak_ihlali"] = bool(set(forbidden) & set(cited))
    phrases = checks.get("yasak_ifadeler") or []
    if phrases and has_answer:
        result["yasak_ifadeler_bulunan"] = [p for p in phrases if fold(p) in folded]
    phrases = checks.get("gerekli_ifadeler") or []
    if phrases:
        result["gerekli_ifadeler_eksik"] = [p for p in phrases if fold(p) not in folded]
    _evaluate_applicability(result, record, checks, sections, cited, has_answer)
    return result


def _evaluate_applicability(
    result: dict[str, Any],
    record: dict[str, Any] | None,
    checks: dict[str, Any],
    sections: dict[str, str],
    cited: list[str] | None,
    has_answer: bool,
) -> None:
    """Uygunluk metrikleri. None = olculmedi (beklenti yok, motor kapali veya cevap yok)."""
    states = checks.get("beklenen_uygunluk") or {}
    reasons = checks.get("beklenen_gerekce") or {}
    decided = (record or {}).get("degerlendirilen_kaynaklar")
    if isinstance(decided, dict):
        errors = []
        if states:
            hits = 0
            for sid, want in states.items():
                got = (decided.get(sid) or {}).get("durum")
                hits += got == want
                if got != want:
                    errors.append(f"{sid}: {got or 'yok'} (beklenen {want})")
            result["uygunluk_dogru"] = (hits, len(states))
        if reasons:
            hits = 0
            for sid, want in reasons.items():
                got = (decided.get(sid) or {}).get("gerekce")
                hits += got == want
                if got != want:
                    errors.append(f"{sid}: {got or 'yok'} (beklenen {want})")
            result["gerekce_dogru"] = (hits, len(reasons))
        result["uygunluk_hatalari"] = errors
    # Kararin dogrulugundan bagimsiz olarak yanitin kendisine bakilir: yanit,
    # cevap anahtarina gore olay tarihinde/surumde gecersiz bir kaynaga dayaniyor mu?
    invalid = sorted(sid for sid, st in states.items() if st == applicability.UYGUN_DEGIL)
    if invalid and cited is not None:
        result["yururluk_disi_kaynak"] = [sid for sid in cited if sid in invalid]
    wanted_markers = sorted({
        UNCERTAINTY_MARKERS[reasons[sid]]
        for sid, st in states.items()
        if st == applicability.BELIRSIZ and reasons.get(sid) in UNCERTAINTY_MARKERS
    })
    if wanted_markers and has_answer:
        text = fold(sections.get("belirsizlik", ""))
        result["belirsizlik_gosterildi"] = all(fold(m) in text for m in wanted_markers)


def _range(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {"adet": len(values), "medyan": statistics.median(values),
            "min": min(values), "max": max(values)}


def evaluate_run(run: dict[str, Any], expected: dict[str, dict | None]) -> dict[str, Any]:
    case_ids = sorted(set(expected) | set(run["records"]))
    per_case = {cid: evaluate_case(run["records"].get(cid), expected.get(cid)) for cid in case_ids}
    records = [r for r in run["records"].values()]
    ok_records = [r for r in records if r.get("ok")]

    def metric_values(key: str) -> list[Any]:
        return [c[key] for c in per_case.values() if c[key] is not None]

    failure_kinds: dict[str, int] = {}
    for cid, case in per_case.items():
        if not case["ok"]:
            kind = case["failure_kind"] or "bilinmiyor"
            failure_kinds[kind] = failure_kinds.get(kind, 0) + 1

    confusion: dict[str, dict[str, int]] = {}
    for cid, case in per_case.items():
        wanted = (expected.get(cid) or {}).get("beklenen_durum")
        if wanted is None:
            continue
        row = confusion.setdefault(wanted, {})
        row[case["durum"]] = row.get(case["durum"], 0) + 1

    def pair_sum(key: str) -> tuple[int, int]:
        pairs = metric_values(key)
        return (sum(h for h, _ in pairs), sum(t for _, t in pairs))

    def metric_list(key: str) -> list[float]:
        return [
            r["metrics"][key] for r in ok_records
            if isinstance(r.get("metrics"), dict) and isinstance(r["metrics"].get(key), (int, float))
        ]

    return {
        "run": run,
        "per_case": per_case,
        "vaka_sayisi": len(case_ids),
        "teknik_tamamlanan": sum(1 for c in per_case.values() if c["ok"]),
        "cevap_yok": sorted(cid for cid, c in per_case.items() if not c["cevap_var"]),
        "basarisizlik_turleri": failure_kinds,
        "durum": (sum(metric_values("durum_dogru")), len(metric_values("durum_dogru"))),
        "aile": (sum(metric_values("aile_dogru")), len(metric_values("aile_dogru"))),
        "gerekli_kaynak": (sum(metric_values("gerekli_kaynak_tamam")),
                           len(metric_values("gerekli_kaynak_tamam"))),
        "yasak_kaynak": (sum(metric_values("yasak_kaynak_ihlali")),
                         len(metric_values("yasak_kaynak_ihlali"))),
        "yasak_ifade": (sum(1 for v in metric_values("yasak_ifadeler_bulunan") if v),
                        len(metric_values("yasak_ifadeler_bulunan"))),
        "gerekli_ifade": (sum(1 for v in metric_values("gerekli_ifadeler_eksik") if v),
                          len(metric_values("gerekli_ifadeler_eksik"))),
        "uygunluk": pair_sum("uygunluk_dogru"),
        "gerekce": pair_sum("gerekce_dogru"),
        "yururluk_disi": (sum(1 for v in metric_values("yururluk_disi_kaynak") if v),
                          len(metric_values("yururluk_disi_kaynak"))),
        "yururluk_disi_atif": sum(len(v) for v in metric_values("yururluk_disi_kaynak")),
        "belirsizlik_gosterim": (sum(metric_values("belirsizlik_gosterildi")),
                                 len(metric_values("belirsizlik_gosterildi"))),
        "karisiklik": confusion,
        "istemci_sure_s": _range([r["client_elapsed_s"] for r in ok_records
                                  if isinstance(r.get("client_elapsed_s"), (int, float))]),
        "sunucu_sure_s": _range(metric_list("total_duration_s")),
        "eval_count": _range(metric_list("eval_count")),
        "prompt_eval_count": _range(metric_list("prompt_eval_count")),
    }


# --------------------------------------------------------------------------
# Rapor
# --------------------------------------------------------------------------


def _locative(n: int) -> str:
    """Turkce bulunma eki: 10'da, 5'te, 6'da, 20'de, 100'de."""
    units = {1: "de", 2: "de", 3: "te", 4: "te", 5: "te", 6: "da", 7: "de", 8: "de", 9: "da"}
    tens = {1: "da", 2: "de", 3: "da", 4: "ta", 5: "de", 6: "ta", 7: "te", 8: "de", 9: "da"}
    if n % 10:
        return units[n % 10]
    if n % 100:
        return tens[(n // 10) % 10]
    return "de"  # yuz, bin


def _of(total: int, hit: int) -> str:
    return f"{total}'{_locative(total)} {hit}"


def _frac(pair: tuple[int, int]) -> str:
    hit, total = pair
    return "kontrol yok" if total == 0 else _of(total, hit)


def _num(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)


def _range_text(stats: dict[str, float] | None) -> str:
    if not stats:
        return "yok (ölçülmedi)"
    return (f"medyan {_num(stats['medyan'])}, min {_num(stats['min'])}, "
            f"max {_num(stats['max'])} ({stats['adet']} vaka)")


def assign_labels(evaluations: list[dict[str, Any]]) -> None:
    """Etiket mod adidir. Iki kosu ayni moddaysa ve uygunluk motoru biri acik biri
    kapaliysa etikete bu eklenir (ablation); aksi halde sira numarasi eklenir."""
    modes = [ev["run"]["mode"] for ev in evaluations]
    motors = [ev["run"].get("motor") for ev in evaluations]
    ablation = len(evaluations) == 2 and modes[0] == modes[1] and set(motors) == {True, False}
    for index, ev in enumerate(evaluations, start=1):
        mode = ev["run"]["mode"]
        if ablation:
            ev["label"] = f"{mode}-{'açık' if ev['run']['motor'] else 'kapalı'}"
        elif modes.count(mode) > 1:
            ev["label"] = f"{mode}{index}"
        else:
            ev["label"] = mode


def _motor_text(motor: bool | None) -> str:
    return {True: "açık", False: "kapalı"}.get(motor, "kayıtta yok (motordan önceki koşu)")


def _measured(pair: tuple[int, int], ev: dict[str, Any]) -> str:
    if pair[1]:
        return _of(pair[1], pair[0])
    if ev["run"].get("motor") is not True:
        return "ölçülmedi (motor kapalı veya kayıtta yok)"
    return "kontrol yok"


def _label(ev: dict[str, Any]) -> str:
    return ev["label"]


METRIC_ROWS = (
    ("Teknik tamamlanma", lambda ev: _of(ev["vaka_sayisi"], ev["teknik_tamamlanan"])),
    ("Başarısızlık türleri", lambda ev: ", ".join(f"{k}: {v}" for k, v in
                                                  sorted(ev["basarisizlik_turleri"].items())) or "yok"),
    ("Cevabı olmayan vaka (yasak kontrolleri yapılamaz)",
     lambda ev: f"{len(ev['cevap_yok'])}" + (f": {', '.join(ev['cevap_yok'])}" if ev["cevap_yok"] else "")),
    ("Durum doğru", lambda ev: _frac(ev["durum"])),
    ("Aile doğru", lambda ev: _frac(ev["aile"])),
    ("Gerekli kaynakların hepsi listelenmiş", lambda ev: _frac(ev["gerekli_kaynak"])),
    ("Yasak kaynak listelenmiş", lambda ev: _frac(ev["yasak_kaynak"])),
    ("Yasak ifade bulunan vaka", lambda ev: _frac(ev["yasak_ifade"])),
    ("Gerekli ifadesi eksik vaka", lambda ev: _frac(ev["gerekli_ifade"])),
    ("Uygunluk kararı doğru (kaynak bazında)", lambda ev: _measured(ev["uygunluk"], ev)),
    ("Gerekçe kodu doğru (kaynak bazında)", lambda ev: _measured(ev["gerekce"], ev)),
    ("Yürürlükte/sürümde olmayan kaynağa dayanan vaka",
     lambda ev: _frac(ev["yururluk_disi"]) + f" (toplam atıf: {ev['yururluk_disi_atif']})"),
    ("Belirsizliği çıktıda gösteren vaka", lambda ev: _frac(ev["belirsizlik_gosterim"])),
    ("İstemci süresi (s)", lambda ev: _range_text(ev["istemci_sure_s"])),
    ("Sunucu total_duration (s)", lambda ev: _range_text(ev["sunucu_sure_s"])),
    ("Çıktı token (eval_count)", lambda ev: _range_text(ev["eval_count"])),
    ("Girdi token (prompt_eval_count)", lambda ev: _range_text(ev["prompt_eval_count"])),
)

PAIRED = (
    ("Durum", "durum_dogru", False),
    ("Aile", "aile_dogru", False),
    ("Gerekli kaynaklar", "gerekli_kaynak_tamam", False),
    ("Yasak ifade yok", "yasak_ifadeler_bulunan", True),
    ("Gerekli ifadeler tam", "gerekli_ifadeler_eksik", True),
    ("Yürürlük/sürüm dışı kaynağa dayanmıyor", "yururluk_disi_kaynak", True),
    ("Belirsizlik gösterildi", "belirsizlik_gosterildi", False),
)


def _passed(case: dict[str, Any], key: str, is_list: bool) -> bool | None:
    value = case[key]
    if value is None:
        return None
    return (not value) if is_list else bool(value)


def _cell(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "evet" if value else "hayır"
    if isinstance(value, list):
        return ", ".join(value) if value else "yok"
    return str(value)


def render_report(evaluations: list[dict[str, Any]], expected: dict[str, dict | None]) -> str:
    assign_labels(evaluations)
    out: list[str] = ["# Destekİzi — makine kontrolleri raporu", "", LIMITATION, "",
                      APPLICABILITY_LIMITATION, ""]

    out += ["## Değerlendirilen koşular", "",
            "| Etiket | run_id | Mod | Uygunluk motoru | Çalışma durumu | Not |",
            "| --- | --- | --- | --- | --- | --- |"]
    for ev in evaluations:
        run = ev["run"]
        out.append(f"| {_label(ev)} | `{run['run_id']}` | {run['mode']} "
                   f"| {_motor_text(run.get('motor'))} | {run['run_state']} "
                   f"| {run['mode_note'] or ''} |")
    missing = sorted(cid for cid, block in expected.items() if block is None)
    out += ["", f"makine_kontrolleri alanı olmayan vakalar: {', '.join(missing) if missing else 'yok'}.", ""]

    out += ["## Metrikler", "", "Mutlak sayılar; yüzde kullanılmaz. \"kontrol yok\": o metrik için "
            "hiçbir vakada kontrol tanımlı değil.", ""]
    out.append("| Metrik | " + " | ".join(_label(ev) for ev in evaluations) + " |")
    out.append("| --- | " + " | ".join("---" for _ in evaluations) + " |")
    for name, fn in METRIC_ROWS:
        out.append(f"| {name} | " + " | ".join(fn(ev) for ev in evaluations) + " |")
    out.append("")

    for ev in evaluations:
        out += [f"### Durum karışıklık matrisi — {_label(ev)}", "",
                "Satır: beklenen durum. Sütun: metinden türetilen durum.", ""]
        cols = list(STATUSES) + [UNDETERMINED]
        out.append("| beklenen \\ türetilen | " + " | ".join(cols) + " |")
        out.append("| --- | " + " | ".join("---" for _ in cols) + " |")
        for wanted in STATUSES:
            row = ev["karisiklik"].get(wanted, {})
            out.append(f"| {wanted} | " + " | ".join(str(row.get(c, 0)) for c in cols) + " |")
        out.append("")

    if len(evaluations) == 2:
        first, second = evaluations
        a_lab, b_lab = _label(first), _label(second)
        out += [f"## Eşleştirilmiş fark ({a_lab} ve {b_lab})", ""]
        out.append(f"| Metrik | {a_lab} geçti, {b_lab} kaldı | {b_lab} geçti, {a_lab} kaldı | "
                   "İkisi de geçti | İkisi de kaldı |")
        out.append("| --- | --- | --- | --- | --- |")
        for name, key, is_list in PAIRED:
            buckets: dict[str, list[str]] = {"a": [], "b": [], "both": [], "none": []}
            for cid in sorted(set(first["per_case"]) | set(second["per_case"])):
                pa = _passed(first["per_case"].get(cid, {key: None}), key, is_list)
                pb = _passed(second["per_case"].get(cid, {key: None}), key, is_list)
                if pa is None or pb is None:
                    continue
                buckets["both" if pa and pb else "a" if pa else "b" if pb else "none"].append(cid)
            out.append(f"| {name} | " + " | ".join(
                f"{len(buckets[k])}: {', '.join(buckets[k])}" if buckets[k] else "0"
                for k in ("a", "b", "both", "none")) + " |")
        out.append("")

    out += ["## Vaka bazlı ayrıntı", ""]
    header = ["Vaka", "Beklenen durum", "Beklenen aile"]
    for ev in evaluations:
        lab = _label(ev)
        header += [f"{lab} durum", f"{lab} aile", f"{lab} kaynaklar",
                   f"{lab} yasak ifade", f"{lab} eksik ifade",
                   f"{lab} yürürlük dışı atıf", f"{lab} belirsizlik gösterildi"]
    out.append("| " + " | ".join(header) + " |")
    out.append("| " + " | ".join("---" for _ in header) + " |")
    for cid in sorted(set().union(*(ev["per_case"] for ev in evaluations))):
        block = expected.get(cid) or {}
        row = [cid, _cell(block.get("beklenen_durum")), _cell(block.get("beklenen_aile"))]
        for ev in evaluations:
            case = ev["per_case"].get(cid)
            if case is None:
                row += ["—"] * 7
                continue
            mark = lambda ok, v: f"{v} ({'✓' if ok else '✗'})" if ok is not None else str(v)
            row += [
                mark(case["durum_dogru"], case["durum"] or "null"),
                mark(case["aile_dogru"], case["aile"] or "null"),
                _cell(case["kaynaklar"]) if case["kaynaklar"] is not None else "bölüm yok",
                _cell(case["yasak_ifadeler_bulunan"]),
                _cell(case["gerekli_ifadeler_eksik"]),
                _cell(case["yururluk_disi_kaynak"]),
                _cell(case["belirsizlik_gosterildi"]),
            ]
        out.append("| " + " | ".join(row) + " |")
    out.append("")

    out += ["## Uygunluk kararları", "",
            "Beklenen: `expected.jsonl → beklenen_uygunluk / beklenen_gerekce`. Kayıt: "
            "vaka kaydındaki `degerlendirilen_kaynaklar`. Motor kapalı koşuda karar yoktur.", ""]
    for ev in evaluations:
        if ev["run"].get("motor") is not True:
            out += [f"- {_label(ev)}: ölçülmedi (uygunluk motoru {_motor_text(ev['run'].get('motor'))}).", ""]
            continue
        wrong = {cid: c["uygunluk_hatalari"] for cid, c in ev["per_case"].items()
                 if c["uygunluk_hatalari"]}
        if not wrong:
            out += [f"- {_label(ev)}: beklenen her karar ve gerekçe kayıtla aynı.", ""]
            continue
        out.append(f"- {_label(ev)}: beklenenden farklı kararlar:")
        out += [f"  - {cid}: {'; '.join(errs)}" for cid, errs in sorted(wrong.items())]
        out.append("")

    out += [
        "## Yöntem ve yaklaşıklıklar",
        "",
        "- **Aynı kurallar:** Durum ve aile her iki mod için de yanıt **metninden** aynı "
        "kurallarla türetilir. A modunun iç kararı (`kural_karari`) kullanılmaz.",
        "- **Aile:** Yalnızca `Kaynaklar` bölümündeki D1–D3 kimliklerinden türetilir "
        "(D1 → yetkilendirme, D2 → istek_siniri, D3 → sayfalama). Hiç kaynak yoksa `null`, "
        "birden fazla aile varsa `coklu`.",
        "- **Durum:** Yalnızca `Sonraki adım` bölümüne bakılır. Bölümde "
        f"{', '.join(repr(m) for m in EXPERT_MARKERS)} geçiyorsa `uzman_incelemesi`; "
        f"{', '.join(repr(m) for m in INFO_REQUEST_MARKERS)} işaretlerinden biri geçiyorsa "
        "`bilgi_gerekli`; hiçbiri yoksa `taslak_hazir` sayılır.",
        "- **İfade kontrolleri:** Büyük/küçük harf duyarsız alt dize eşleşmesidir. Anlamı "
        "ölçmez; olumsuz cümle, alıntı veya eşanlamlı ifade yanlış sonuç verebilir.",
        "- **Yanlılık uyarısı:** A modunun metinleri, durum işaret listesi ve "
        "`makine_kontrolleri` aynı kişi tarafından yazıldı. A metinleri bu işaretleri "
        "kullandığı için karşılaştırma A lehine yanlı olabilir.",
        "- **Uygunluk kararı ve gerekçe:** Vaka kaydındaki `degerlendirilen_kaynaklar` ile "
        "cevap anahtarındaki beklenen değerler kaynak bazında karşılaştırılır. Motor kapalı "
        "koşuda kayıt yoktur; metrik ölçülmez.",
        "- **Yürürlük/sürüm dışı kaynak:** Yanıtın `Kaynaklar` bölümünde, cevap anahtarında "
        "`UYGUN_DEGIL` olan bir kaynağın bulunmasıdır. Yalnızca atıfa bakar; metnin o "
        "kaynağın kuralını uygulayıp uygulamadığını ölçmez.",
        "- **Belirsizlik gösterimi:** Beklenen `BELIRSIZ` kaynağın gerekçe koduna göre "
        "`Belirsizlik / eksik bilgi` bölümünde bir işaret aranır: "
        + ", ".join(f"{code} → {marker!r}" for code, marker in UNCERTAINTY_MARKERS.items())
        + ". A modunun belirsizlik satırları ve bu işaretler aynı kişi tarafından yazıldı.",
        f"- **Örneklem:** {len(expected)} vaka ve her koşu tek; C modu deterministik değildir "
        "(`temperature` 0.7).",
        "",
        APPLICABILITY_LIMITATION,
        "",
        LIMITATION,
        "",
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Destekizi makine kontrolleri raporu (model cagirmaz).")
    parser.add_argument("run_dirs", nargs="+", help="Bir veya iki sonuc dizini.")
    parser.add_argument("--expected", default=str(DEFAULT_EXPECTED))
    parser.add_argument("--out", help="Rapor dosyasi. Verilmezse standart ciktiya yazilir.")
    args = parser.parse_args(argv)
    if len(args.run_dirs) > 2:
        parser.error("en fazla iki sonuc dizini verilebilir")

    try:
        expected = load_expected(Path(args.expected))
        evaluations = [evaluate_run(load_run(Path(d)), expected) for d in args.run_dirs]
    except (OSError, ValueError) as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 2
    report = render_report(evaluations, expected)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"Rapor yazildi: {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
