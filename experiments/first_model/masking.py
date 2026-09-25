"""Destekizi - vaka verisinde hassas deger maskeleme.

Vaka okunduktan hemen sonra, aramaya, uygunluk filtresine, kural motoruna, modele
ve kayda gitmeden ONCE uygulanir (run.analyze_case'in ilk adimi).

Maskelenenler:
    - Hassas HTTP basliklari (buyuk/kucuk harf duyarsiz sozluk anahtari olarak):
      Authorization, Proxy-Authorization, X-Api-Key, Cookie, Set-Cookie.
    - Hassas JSON alan adlari (ic ice nesnelerde ve listelerde de): password,
      api_key, apikey, secret, token, access_token, refresh_token.
    - Serbest metin desenleri (tum metin degerlerinde): e-posta, Turkiye cep
      telefonu, JWT (eyJ ile baslayan uc parcali dizi), "Bearer/Basic <deger>".

Korunanlar (teshis bilgisi): Basligin VARLIGI ve TURU korunur, yalnizca degeri
gizlenir. "Bearer abc.def" -> "Bearer ***", "Basic dXNlcg==" -> "Basic ***",
"k-999" -> "***". Cookie'de cerez ADLARI ve Set-Cookie oznitelikleri korunur.
Boylece maskelemeden sonra da "Authorization basligi var mi, Bearer mi Basic mi?"
sorusu cevaplanabilir; 401 teshisi bu bilgiye dayanir. Anahtarlar ve yapi
(alan adlari, null degerler, sayilar, tarihler) degismez.

SINIR: Bu modul sabit alan adlari ve duzenli ifadelerle calisir. Listede olmayan
alan adlarindaki sirlari, farkli bicimde yazilmis telefon veya anahtarlari ve
serbest metindeki kisi adlari, adresler gibi kisisel verileri BULMAZ. Hassas
verinin temizlendigine dair bir guvence vermez; yalnizca bilinen kaliplari gizler.

Yalnizca Python 3.12 standart kutuphanesi kullanilir.
"""

from __future__ import annotations

import re
from typing import Any

MASK = "***"

SENSITIVE_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "x-api-key", "cookie", "set-cookie"}
)
SENSITIVE_FIELDS = frozenset(
    {"password", "api_key", "apikey", "secret", "token", "access_token", "refresh_token"}
)
# Degerinde "<sema> <kimlik bilgisi>" bicimi tasiyan basliklar: sema korunur.
_SCHEMED_HEADERS = frozenset({"authorization", "proxy-authorization"})

_SCHEME_RE = re.compile(r"^(\s*[A-Za-z][A-Za-z0-9._~+-]*)\s+\S.*$", re.S)

# Serbest metin desenleri: (ad, desen, yerine konan). Yer tutucu verinin TURUNU
# gosterir ki okuyan kisi orada ne oldugunu bilsin.
_TEXT_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"), "<jwt>"),
    ("kimlik_bilgisi",
     re.compile(r"\b(Bearer|Basic)\s+(?!\*\*\*)[A-Za-z0-9._~+/=-]{8,}", re.I), r"\1 ***"),
    ("e_posta", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "<e-posta>"),
    # +90 5xx xxx xx xx, 0 5xx xxx xx xx, 5xxxxxxxxx; bosluk veya tire ayiraci.
    ("telefon",
     re.compile(r"(?<![\d+])(?:\+90[\s-]?|0090[\s-]?|0)?5\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}(?!\d)"),
     "<telefon>"),
)


def mask_header_value(name: str, value: Any) -> Any:
    """Tek bir hassas basligin degeri. Metin olmayan veya bos deger oldugu gibi kalir
    (gizlenecek bir sey yoktur; varlik bilgisi korunur)."""
    if not isinstance(value, str) or not value.strip():
        return value
    lowered = name.lower()
    if lowered in _SCHEMED_HEADERS:
        # Tur (Bearer, Basic, ...) korunur: teshis icin gereklidir.
        match = _SCHEME_RE.match(value)
        return f"{match.group(1)} {MASK}" if match else MASK
    if lowered == "cookie":
        return ";".join(_mask_pair(part) for part in value.split(";"))
    if lowered == "set-cookie":
        first, _, attrs = value.partition(";")
        return _mask_pair(first) + (";" + attrs if attrs else "")
    return MASK


def _mask_pair(part: str) -> str:
    name, sep, _ = part.partition("=")
    return f"{name}={MASK}" if sep else MASK


def mask_text(text: str) -> tuple[str, list[str]]:
    """Serbest metindeki bilinen desenler. (yeni metin, eslesen desen adlari)."""
    hits: list[str] = []
    for name, pattern, repl in _TEXT_PATTERNS:
        text, count = pattern.subn(repl, text)
        if count:
            hits.append(name)
    return text, hits


def mask_value(value: Any, path: str = "", changed: list[str] | None = None) -> Any:
    """Ozyinelemeli maskeleme; yeni nesne dondurur, girdiyi degistirmez.
    changed verilirse degisen alanlarin yolu (degeri degil) eklenir."""
    changed = changed if changed is not None else []
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            sub = f"{path}.{key}" if path else str(key)
            lowered = str(key).lower()
            if lowered in SENSITIVE_HEADERS:
                masked = mask_header_value(lowered, item)
                if masked != item:
                    changed.append(sub)
                out[key] = masked
            elif lowered in SENSITIVE_FIELDS:
                # null (bilgi yok) korunur; diger her deger (ic ice nesne dahil) gizlenir.
                masked = item if item is None else MASK
                if masked != item:
                    changed.append(sub)
                out[key] = masked
            else:
                out[key] = mask_value(item, sub, changed)
        return out
    if isinstance(value, list):
        return [mask_value(item, f"{path}[{i}]", changed) for i, item in enumerate(value)]
    if isinstance(value, str):
        masked, hits = mask_text(value)
        if hits:
            changed.append(f"{path} ({', '.join(hits)})")
        return masked
    return value


def mask_case(case: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Bir vakanin maskelenmis kopyasi ve degisen alan yollari (degerler yazilmaz)."""
    changed: list[str] = []
    return mask_value(case, "", changed), changed
