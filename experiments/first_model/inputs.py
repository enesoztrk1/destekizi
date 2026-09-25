"""Destekizi - girdi dosyalarinin okunmasi ve dogrulanmasi.

Cevap anahtari (expected.jsonl) uretim yoluna girmez; `read_text` ve `sha256_file`
bunu engeller. Yalnizca Python 3.12 standart kutuphanesi kullanilir.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import applicability  # kaynak surum/yururluk dogrulamasi (ayni dizindeki modul)

HERE = Path(__file__).resolve().parent

# Cevap anahtari uretim yoluna hicbir kosulda girmez.
FORBIDDEN_INPUT_FILENAMES = {"expected.jsonl"}
# Yalnizca yol/dosya kimligi karsilastirmasi icin; icerigi okunmaz veya ozetlenmez.
ANSWER_KEY_PATH = HERE / "expected.jsonl"


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
            applicability.validate_version(case.get("api_version"), f"{case_id}.api_version")
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
