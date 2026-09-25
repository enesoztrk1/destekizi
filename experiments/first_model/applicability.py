"""Destekizi - kaynak uygulanabilirlik motoru.

Tek sorumluluk: bir kaynak, bir olay tarihi ve bir API surumu verildiginde kaynagin
kullanilabilir olup olmadigina karar vermek. Uc soruyu cevaplar: surum uyuyor mu,
olay tarihinde yururlukte mi, bilinmiyor mu.

Sonuc uc durumludur (UYGUN / UYGUN_DEGIL / BELIRSIZ) ve her sonuc sabit bir gerekce
kodu tasir; serbest metin gerekce uretilmez.

Karar sirasi (deterministik):
    1. Kesin olumsuzlar once gelir: surum uyusmazligi, sonra yururluk disi tarih.
       Bir bilgi eksik olsa bile digeri kaynagi kesin olarak eliyorsa UYGUN_DEGIL.
    2. Sonra bilinmeyenler: once surum, sonra tarih; her birinde once vaka tarafi
       (surum_bilinmiyor / tarih_bilinmiyor), sonra kaynak tarafi
       (kaynak_surumu_yok / kaynak_tarihi_yok).
    3. Hicbiri yoksa UYGUN.

Tarihler yalnizca `date` duzeyindedir (YYYY-MM-DD). Saat dilimi farki gun
sinirinda belirsizlik yaratabilir (or. bir olay UTC'de 31 Mayis, yerel saatte
1 Haziran olabilir); bu motor saat bilgisi islemez. "Gelecek" daima olay tarihine
goredir; motor bugunun tarihini hic kullanmaz, bu yuzden sonuc calisma gunune
bagli degildir.

Yalnizca Python 3.12 standart kutuphanesi kullanilir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

UYGUN = "UYGUN"
UYGUN_DEGIL = "UYGUN_DEGIL"
BELIRSIZ = "BELIRSIZ"
DURUMLAR = (UYGUN, UYGUN_DEGIL, BELIRSIZ)

# Gerekce kodlari. Tek yer burasidir; degerlendirme betigi de buradan okur.
GEREKCE_UYGUN = "uygun"
SURUM_UYUSMAZLIGI = "surum_uyusmazligi"
YURURLUK_BASLAMAMIS = "yururluk_baslamamis"
YURURLUK_BITMIS = "yururluk_bitmis"
SURUM_BILINMIYOR = "surum_bilinmiyor"
KAYNAK_SURUMU_YOK = "kaynak_surumu_yok"
TARIH_BILINMIYOR = "tarih_bilinmiyor"
KAYNAK_TARIHI_YOK = "kaynak_tarihi_yok"

# Her kodun ait oldugu durum. Bir kod baska bir durumla birlikte kullanilamaz.
GEREKCE_DURUMU = {
    GEREKCE_UYGUN: UYGUN,
    SURUM_UYUSMAZLIGI: UYGUN_DEGIL,
    YURURLUK_BASLAMAMIS: UYGUN_DEGIL,
    YURURLUK_BITMIS: UYGUN_DEGIL,
    SURUM_BILINMIYOR: BELIRSIZ,
    KAYNAK_SURUMU_YOK: BELIRSIZ,
    TARIH_BILINMIYOR: BELIRSIZ,
    KAYNAK_TARIHI_YOK: BELIRSIZ,
}

# Ciktida gosterilecek sabit aciklamalar (kod basina bir cumle; uretilmez, secilir).
GEREKCE_ACIKLAMASI = {
    GEREKCE_UYGUN: "sürüm ve yürürlük tarihi uyuyor",
    SURUM_UYUSMAZLIGI: "kaynak vakanın API sürümü için geçerli değil",
    YURURLUK_BASLAMAMIS: "kaynak olay tarihinde henüz yürürlükte değil",
    YURURLUK_BITMIS: "kaynağın yürürlüğü olay tarihinden önce bitmiş",
    SURUM_BILINMIYOR: "vakanın API sürümü bilinmiyor; kaynağın sürüme uygunluğu doğrulanamadı",
    KAYNAK_SURUMU_YOK: "kaynak API sürümü belirtmiyor; sürüme uygunluğu doğrulanamadı",
    TARIH_BILINMIYOR: "olay tarihi bilinmiyor; kaynağın o tarihte yürürlükte olduğu doğrulanamadı",
    KAYNAK_TARIHI_YOK: "kaynakta yürürlük tarihi yok; olay tarihinde geçerli olduğu doğrulanamadı",
}

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_VERSION_RE = re.compile(r"v\d+")


@dataclass(frozen=True)
class Karar:
    durum: str
    gerekce: str


@dataclass(frozen=True)
class Filtre:
    """Bir vakanin kaynak listesine uygulanan filtrenin sonucu (vaka sirasi korunur)."""

    degerlendirilen: dict[str, Karar]
    kullanilan: tuple[str, ...]
    elenen: dict[str, str]
    belirsiz: tuple[str, ...]

    def kayit(self) -> dict[str, Any]:
        """Vaka kaydina yazilan alanlar."""
        return {
            "degerlendirilen_kaynaklar": {
                sid: {"durum": k.durum, "gerekce": k.gerekce}
                for sid, k in self.degerlendirilen.items()
            },
            "kullanilan_kaynaklar": list(self.kullanilan),
            "elenen_kaynaklar": dict(self.elenen),
            "belirsiz_kaynaklar": list(self.belirsiz),
        }


def parse_date(value: Any, field: str) -> date | None:
    """None -> None. Aksi halde tam olarak YYYY-MM-DD olmali; degilse ValueError.

    Hatali tarih sessizce "bilinmiyor" sayilmaz: veri hatasi, karar degildir.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise ValueError(f"{field}: YYYY-MM-DD biciminde tarih veya null olmali, {value!r} geldi")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field}: gecersiz tarih {value!r} ({exc})") from exc


def validate_version(value: Any, field: str) -> None:
    """None (bilinmiyor) veya "v<sayi>". "V2", "", " v2" gibi degerler sessizce
    surum uyusmazligina donusmesin: veri hatasidir."""
    if value is not None and (not isinstance(value, str) or not _VERSION_RE.fullmatch(value)):
        raise ValueError(f"{field}: 'v<sayi>' biciminde surum veya null olmali, {value!r} geldi")


def validate_source(source: dict[str, Any]) -> None:
    """Kaynagin uygunluk alanlarini dogrular; hatada ValueError."""
    sid = source.get("source_id")
    start = parse_date(source.get("valid_from"), f"{sid}.valid_from")
    end = parse_date(source.get("valid_to"), f"{sid}.valid_to")
    if start is not None and end is not None and not start < end:
        raise ValueError(f"{sid}: valid_from ({start}) valid_to ({end}) tarihinden once olmali")
    versions = source.get("api_versions")
    if versions is not None:
        if not isinstance(versions, list) or not versions:
            raise ValueError(f"{sid}.api_versions: bos olmayan liste veya null olmali")
        for version in versions:
            validate_version(version, f"{sid}.api_versions")


def evaluate(source: dict[str, Any], olay_tarihi: date | None, api_version: str | None) -> Karar:
    """Tek kaynak icin karar. Siralama modul aciklamasindadir."""
    sid = source.get("source_id")
    versions = source.get("api_versions") or []
    start = parse_date(source.get("valid_from"), f"{sid}.valid_from")
    end = parse_date(source.get("valid_to"), f"{sid}.valid_to")

    # Surum: None = bilinmiyor.
    if api_version is None:
        surum = SURUM_BILINMIYOR
    elif not versions:
        surum = KAYNAK_SURUMU_YOK
    elif api_version in versions:
        surum = None
    else:
        surum = SURUM_UYUSMAZLIGI

    # Tarih araligi: baslangic <= olay_tarihi < bitis
    # (baslangic gunu DAHIL, bitis gunu HARIC). valid_from null -> her zaman
    # baslamis; valid_to null -> hala yururlukte. IKISI DE null ise tarih bilgisi
    # yoktur: bu "her zaman gecerli" DEGILDIR, BELIRSIZ olur.
    if olay_tarihi is None:
        tarih = TARIH_BILINMIYOR
    elif start is None and end is None:
        tarih = KAYNAK_TARIHI_YOK
    elif start is not None and olay_tarihi < start:
        tarih = YURURLUK_BASLAMAMIS
    elif end is not None and olay_tarihi >= end:
        tarih = YURURLUK_BITMIS
    else:
        tarih = None

    for kod in (surum, tarih):
        if kod in (SURUM_UYUSMAZLIGI, YURURLUK_BASLAMAMIS, YURURLUK_BITMIS):
            return Karar(UYGUN_DEGIL, kod)
    for kod in (surum, tarih):
        if kod is not None:
            return Karar(BELIRSIZ, kod)
    return Karar(UYGUN, GEREKCE_UYGUN)


def filter_sources(
    case: dict[str, Any], sources: dict[str, dict[str, Any]], source_ids: list[str]
) -> Filtre:
    """Vakanin kendi source_ids listesini filtreler. UYGUN_DEGIL elenir; BELIRSIZ
    kullanilir ama ayrica listelenir ki ciktida gosterilebilsin."""
    olay = parse_date(case.get("olay_tarihi"), f"{case.get('case_id')}.olay_tarihi")
    version = case.get("api_version")
    degerlendirilen = {sid: evaluate(sources[sid], olay, version) for sid in source_ids}
    return Filtre(
        degerlendirilen=degerlendirilen,
        kullanilan=tuple(s for s, k in degerlendirilen.items() if k.durum != UYGUN_DEGIL),
        elenen={s: k.gerekce for s, k in degerlendirilen.items() if k.durum == UYGUN_DEGIL},
        belirsiz=tuple(s for s, k in degerlendirilen.items() if k.durum == BELIRSIZ),
    )


def grouped_by_reason(filtre: Filtre, sids: tuple[str, ...] | list[str]) -> list[tuple[str, list[str]]]:
    """Kaynaklari gerekce koduna gore gruplar; ilk gorulme sirasi korunur."""
    groups: dict[str, list[str]] = {}
    for sid in sids:
        groups.setdefault(filtre.degerlendirilen[sid].gerekce, []).append(sid)
    return list(groups.items())
