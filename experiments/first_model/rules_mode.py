"""Destekizi - A modu: kural tabanli, deterministik temel yontem.

Modelden bagimsizdir; ag cagrisi yapmaz. Kurallar YALNIZCA docs.json'daki D1-D3
metinlerinden elle turetilmistir; her kuralin yaninda dayandigi kaynak cumlesi
yorum olarak durur. Disaridan HTTP bilgisi veya varsayim eklenmez.

Girdi: bir vaka kaydi ve o vakanin secilmis kaynak kimlikleri.
Okunan alanlar yalnizca yapisaldir: response.http_status, response.error_code,
response.required_scope, response.headers, response.has_more / next_cursor /
item_count, request.path / query, request.authorization_present, api_version.
Serbest metin alanlari (ticket,
note, debug_note) OKUNMAZ; bu yuzden kayit icindeki talimat benzeri ifadeler
cikti uretimini etkileyemez.

Cikti, C modundaki model yanitiyla ayni dort basliklidir.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

# Durum ve aile adlari expected.jsonl -> makine_kontrolleri ile ayni sozlukten.
TASLAK_HAZIR = "taslak_hazir"
BILGI_GEREKLI = "bilgi_gerekli"
UZMAN_INCELEMESI = "uzman_incelemesi"

YETKILENDIRME = "yetkilendirme"
ISTEK_SINIRI = "istek_siniri"
SAYFALAMA = "sayfalama"


@dataclass(frozen=True)
class Decision:
    """Kural motorunun karari. Metin render() ile uretilir."""

    kural: str
    aile: str | None
    durum: str
    bulgular: tuple[str, ...]
    belirsizlik: tuple[str, ...]
    sonraki_adim: tuple[str, ...]
    kaynaklar: tuple[str, ...] = field(default_factory=tuple)


def _response(case: dict[str, Any]) -> dict[str, Any]:
    response = case.get("response")
    return response if isinstance(response, dict) else {}


def _request(case: dict[str, Any]) -> dict[str, Any]:
    request = case.get("request")
    return request if isinstance(request, dict) else {}


def _header(response: dict[str, Any], name: str) -> str | None:
    headers = response.get("headers")
    if not isinstance(headers, dict):
        return None
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == name.lower():
            return value if isinstance(value, str) else None
    return None


# --------------------------------------------------------------------------
# D1 - Kimlik dogrulama ve yetkilendirme
# --------------------------------------------------------------------------


def _rule_auth(case: dict[str, Any]) -> Decision | None:
    response = _response(case)
    status = response.get("http_status")
    code = response.get("error_code")
    if status not in (401, 403):
        return None

    # D1: "401 / DEMO_TOKEN_EXPIRED: Erisim belirtecinin suresi dolmustur. Sonraki adim
    #      yeni bir erisim belirteci edinmektir. Bu kaynak, belirtecin hangi endpoint
    #      veya yontemle edinilecegini aciklamaz."
    if status == 401 and code == "DEMO_TOKEN_EXPIRED":
        return Decision(
            kural="D1/401/DEMO_TOKEN_EXPIRED",
            aile=YETKILENDIRME,
            durum=TASLAK_HAZIR,
            bulgular=(
                "Yanıt kaydı: HTTP 401, DEMO_TOKEN_EXPIRED.",
                "D1'e göre bu kod, erişim belirtecinin süresinin dolmuş olduğunu belirtir.",
            ),
            belirsizlik=(
                "D1, yeni belirtecin hangi endpoint veya yöntemle edinileceğini açıklamaz.",
            ),
            sonraki_adim=("Yeni bir erişim belirteci edinin.",),
            kaynaklar=("D1",),
        )

    # D1: "401 / DEMO_AUTH_MISSING: Istekte Authorization basligi yoktur. Sonraki adim,
    #      basligin istemci tarafindan gonderildigini kontrol etmektir. Bu hata, baska
    #      yerde bulunan bir belirtecin gecerli veya gecersiz oldugunu kanitlamaz."
    if status == 401 and code == "DEMO_AUTH_MISSING":
        bulgular = [
            "Yanıt kaydı: HTTP 401, DEMO_AUTH_MISSING.",
            "D1'e göre bu kod, istekte Authorization başlığının bulunmadığını belirtir.",
        ]
        if _request(case).get("authorization_present") is False:
            bulgular.append("İstek kaydında da authorization_present=false görünüyor.")
        return Decision(
            kural="D1/401/DEMO_AUTH_MISSING",
            aile=YETKILENDIRME,
            durum=TASLAK_HAZIR,
            bulgular=tuple(bulgular),
            belirsizlik=(
                "D1'e göre bu hata, başka yerde bulunan bir belirtecin geçerli veya "
                "geçersiz olduğunu kanıtlamaz.",
            ),
            sonraki_adim=(
                "Authorization başlığının istemci tarafından gönderildiğini kontrol edin.",
            ),
            kaynaklar=("D1",),
        )

    # D1: "403 / DEMO_SCOPE_MISSING: Istekte kullanilan kimligin gerekli yetkisi yoktur.
    #      GET /orders icin gereken yetki orders:read olarak adlandirilir. Yetki atamasi
    #      kontrol edilmelidir. Bu hata tek basina belirtecin suresinin doldugunu
    #      gostermez."
    if status == 403 and code == "DEMO_SCOPE_MISSING":
        scope = response.get("required_scope")
        # Kayitta yetki adi yoksa D1'in GET /orders icin verdigi ad kullanilir.
        if not isinstance(scope, str) and _request(case).get("path") == "/orders":
            scope = "orders:read"
        bulgular = [
            "Yanıt kaydı: HTTP 403, DEMO_SCOPE_MISSING.",
            "D1'e göre bu kod, istekte kullanılan kimliğin gerekli yetkisinin "
            "olmadığını belirtir.",
        ]
        if isinstance(scope, str):
            bulgular.append(f"Gerekli yetki: {scope}.")
        sonraki = (
            f"{scope} yetkisinin atanıp atanmadığını kontrol edin."
            if isinstance(scope, str)
            else "Gerekli yetki atamasını kontrol edin."
        )
        return Decision(
            kural="D1/403/DEMO_SCOPE_MISSING",
            aile=YETKILENDIRME,
            durum=TASLAK_HAZIR,
            bulgular=tuple(bulgular),
            belirsizlik=(
                "D1'e göre bu hata tek başına belirtecin süresinin dolduğunu göstermez.",
            ),
            sonraki_adim=(sonraki,),
            kaynaklar=("D1",),
        )

    # D1: "Yalnizca HTTP 401 veya 403 goruluyor ve bu acik hata kodlarindan biri
    #      bulunmuyorsa kesin kok neden cikarilamaz; hata govdesi ve ilgili istek
    #      bilgileri gerekir. Gercek belirtec degeri istenmemelidir."
    return Decision(
        kural=f"D1/{status}/acik-kod-yok",
        aile=YETKILENDIRME,
        durum=BILGI_GEREKLI,
        bulgular=(f"Yanıt kaydı: HTTP {status}; D1'deki açık hata kodlarından biri yok.",),
        belirsizlik=("D1'e göre bu durumda kesin kök neden çıkarılamaz.",),
        sonraki_adim=(
            "Hata gövdesini ve ilgili istek bilgilerini paylaşın; gerçek belirteç "
            "değerini paylaşmayın.",
        ),
        kaynaklar=("D1",),
    )


# --------------------------------------------------------------------------
# D2 - Istek siniri
# --------------------------------------------------------------------------


def _rule_rate_limit(case: dict[str, Any]) -> Decision | None:
    response = _response(case)
    if response.get("http_status") != 429 or response.get("error_code") != "DEMO_RATE_LIMIT":
        return None

    retry_after = _header(response, "Retry-After")
    # D2: "Retry-After basligi varsa degeri negatif olmayan tam sayi olarak saniye
    #      cinsindendir. Ayni istegi yeniden denemeden once en az bu sure
    #      beklenmelidir. ... sinirsiz veya araliksiz yeniden deneme onerilmez."
    if retry_after is not None and re.fullmatch(r"\d+", retry_after.strip()):
        seconds = int(retry_after.strip())
        return Decision(
            kural="D2/429/retry-after-var",
            aile=ISTEK_SINIRI,
            durum=TASLAK_HAZIR,
            bulgular=(
                "Yanıt kaydı: HTTP 429, DEMO_RATE_LIMIT; istek hız sınırına takılmış.",
                f"Retry-After: {seconds} (D2'ye göre birim saniyedir).",
            ),
            belirsizlik=("D2 sayısal bir istek kotası vermez.",),
            sonraki_adim=(
                f"Aynı isteği yeniden denemeden önce en az {seconds} saniye bekleyin.",
                "Sınırsız veya aralıksız yeniden deneme yapmayın.",
            ),
            kaynaklar=("D2",),
        )

    # D2: "Baslik yoksa ya da gecerli bir tam sayi degilse bu kaynaktan kesin bekleme
    #      suresi belirlenemez; yanit basliklari ve gecerli limit bilgisi istenir. Bu
    #      kaynak, sayisal bir istek kotasi veya eksik baslik icin varsayilan bir
    #      bekleme suresi vermez."
    durum_metni = "yok" if retry_after is None else "geçerli bir tam sayı değil"
    return Decision(
        kural="D2/429/retry-after-yok-veya-gecersiz",
        aile=ISTEK_SINIRI,
        durum=BILGI_GEREKLI,
        bulgular=(
            "Yanıt kaydı: HTTP 429, DEMO_RATE_LIMIT; istek hız sınırına takılmış.",
            f"Retry-After başlığı {durum_metni}.",
        ),
        belirsizlik=(
            "D2'ye göre bu durumda kesin bekleme süresi belirlenemez; D2 eksik başlık "
            "için varsayılan bir bekleme süresi vermez.",
        ),
        sonraki_adim=("Yanıt başlıklarını ve geçerli limit bilgisini paylaşın.",),
        kaynaklar=("D2",),
    )


# --------------------------------------------------------------------------
# D3 - Siparis sayfalamasi (GET /orders)
# --------------------------------------------------------------------------


def _rule_pagination(case: dict[str, Any]) -> Decision | None:
    response = _response(case)
    request = _request(case)
    if response.get("http_status") != 200 or request.get("path") != "/orders":
        return None
    query = request.get("query") if isinstance(request.get("query"), dict) else {}
    version = case.get("api_version")

    # D3: "Bir sayfada 100 kayit bulunmasi tek basina tum kayitlarin alindigini
    #      gostermez."
    count_note = (
        ("D3'e göre bir sayfada 100 kayıt bulunması tek başına tüm kayıtların "
         "alındığını göstermez.",)
        if response.get("item_count") == 100
        else ()
    )

    # D3: "v1, 1'den baslayan page parametresini kullanir. page_size en cok 100 olabilir.
    #      has_more=true ise ayni filtrelerle page bir artirilarak sonraki sayfa istenir;
    #      has_more=false ise devam edilmez."
    if version == "v1":
        has_more = response.get("has_more")
        if has_more is True:
            page = query.get("page")
            page_size = query.get("page_size")
            if isinstance(page, int) and not isinstance(page, bool):
                target = f"page={page + 1}"
            else:
                target = "page bir artırılarak"
            size = (
                f" ve page_size={page_size}"
                if isinstance(page_size, int) and not isinstance(page_size, bool)
                else ""
            )
            return Decision(
                kural="D3/v1/has_more-true",
                aile=SAYFALAMA,
                durum=TASLAK_HAZIR,
                bulgular=(
                    "API sürümü v1; D3'e göre v1 page parametresini kullanır.",
                    "Yanıtta has_more=true: sonraki sayfa var.",
                ),
                belirsizlik=count_note or ("Toplam kayıt sayısı kayıtta yok.",),
                sonraki_adim=(f"Aynı filtrelerle {target}{size} ile sonraki sayfayı alın.",),
                kaynaklar=("D3",),
            )
        if has_more is False:
            return Decision(
                kural="D3/v1/has_more-false",
                aile=SAYFALAMA,
                durum=TASLAK_HAZIR,
                bulgular=("API sürümü v1; yanıtta has_more=false.",),
                belirsizlik=("Kayıtta ek belirsizlik yok.",),
                sonraki_adim=("D3'e göre devam edilmez; sonraki sayfa istenmez.",),
                kaynaklar=("D3",),
            )
        return _pagination_needs_info(
            "D3/v1/has_more-yok", "API sürümü v1 ancak yanıtta has_more alanı yok.", count_note
        )

    # D3: "v2, cursor kullanir. limit en cok 100 olabilir. Yanitta bos olmayan next_cursor
    #      varsa ayni filtrelerle bu deger degistirilmeden sonraki istegin cursor
    #      parametresine aktarilir. next_cursor=null ise devam edilmez. v2'de page
    #      yontemi kullanilmaz."
    if version == "v2":
        if "next_cursor" in response:
            cursor = response.get("next_cursor")
            if isinstance(cursor, str) and cursor:
                limit = query.get("limit")
                limit_text = (
                    f" ve limit={limit}" if isinstance(limit, int) and not isinstance(limit, bool)
                    else ""
                )
                return Decision(
                    kural="D3/v2/next_cursor-var",
                    aile=SAYFALAMA,
                    durum=TASLAK_HAZIR,
                    bulgular=(
                        "API sürümü v2; D3'e göre v2 cursor kullanır, page yöntemi kullanılmaz.",
                        f"Yanıtta next_cursor={cursor}.",
                    ),
                    belirsizlik=count_note or ("Toplam kayıt sayısı kayıtta yok.",),
                    sonraki_adim=(
                        f"Aynı filtrelerle cursor={cursor}{limit_text} ile sonraki isteği yapın; "
                        "cursor değerini değiştirmeyin.",
                    ),
                    kaynaklar=("D3",),
                )
            if cursor is None:
                return Decision(
                    kural="D3/v2/next_cursor-null",
                    aile=SAYFALAMA,
                    durum=TASLAK_HAZIR,
                    bulgular=("API sürümü v2; yanıtta next_cursor=null.",),
                    belirsizlik=("Kayıtta ek belirsizlik yok.",),
                    sonraki_adim=("D3'e göre devam edilmez; sonraki istek yapılmaz.",),
                    kaynaklar=("D3",),
                )
        return _pagination_needs_info(
            "D3/v2/next_cursor-yok", "API sürümü v2 ancak yanıtta next_cursor alanı yok.",
            count_note,
        )

    # D3: "API surumu bilinmiyorsa hangi devam yonteminin gecerli oldugu varsayilmaz;
    #      surum ve ilk istek/yanit ornegi istenir."
    return Decision(
        kural="D3/surum-bilinmiyor",
        aile=SAYFALAMA,
        durum=BILGI_GEREKLI,
        bulgular=("API sürümü bilinmiyor.",) + count_note,
        belirsizlik=(
            "D3'e göre sürüm bilinmeden devam yöntemi (v1 page / v2 cursor) varsayılmaz.",
        ),
        sonraki_adim=("API sürümünü ve ilk istek/yanıt örneğini paylaşın.",),
        kaynaklar=("D3",),
    )


def _pagination_needs_info(kural: str, finding: str, count_note: tuple[str, ...]) -> Decision:
    return Decision(
        kural=kural,
        aile=SAYFALAMA,
        durum=BILGI_GEREKLI,
        bulgular=(finding,) + count_note,
        belirsizlik=("Devam alanı olmadan sonraki sayfanın olup olmadığı bilinmez.",),
        sonraki_adim=("İlk istek/yanıt örneğini devam alanlarıyla birlikte paylaşın.",),
        kaynaklar=("D3",),
    )


# --------------------------------------------------------------------------
# Karar
# --------------------------------------------------------------------------

# (kural fonksiyonu, kuralin dayandigi kaynak). Kaynak vakada secilmemisse kural
# kullanilamaz; secilmemis bir kaynaga dayanilmaz.
_RULES = (
    (_rule_auth, "D1"),
    (_rule_rate_limit, "D2"),
    (_rule_pagination, "D3"),
)


def decide(case: dict[str, Any], source_ids: list[str] | tuple[str, ...]) -> Decision:
    """Vaka icin deterministik karar. Hicbir kural uymazsa teshis uretmez."""
    selected = set(source_ids)
    for rule, source in _RULES:
        if source not in selected:
            continue
        decision = rule(case)
        if decision is not None:
            return decision

    # Kapsam disi (or. 500 DEMO_UNKNOWN) veya ilgili kaynak secilmemis: teshis yok.
    # Istenen bilgi D1'deki genel ilkeden alinir ("hata govdesi ve ilgili istek
    # bilgileri gerekir"); kaynaklarda olmayan bir neden veya adim eklenmez.
    response = _response(case)
    status = response.get("http_status")
    code = response.get("error_code")
    kayit = f"HTTP {status}" + (f", {code}" if isinstance(code, str) else "")
    return Decision(
        kural="kapsam-disi",
        aile=None,
        durum=UZMAN_INCELEMESI,
        bulgular=(
            f"Yanıt kaydı: {kayit}.",
            "Seçilmiş kaynaklarda bu kayıt için bir kural yok; kök neden bu "
            "kaynaklardan çıkarılamaz.",
        ),
        belirsizlik=("Hatanın kök nedeni bilinmiyor.",),
        sonraki_adim=(
            "Hata gövdesini ve ilgili istek/yanıt bilgilerini paylaşın.",
            "Kaydı uzman incelemesine yönlendirin.",
        ),
        kaynaklar=(),
    )


def render(decision: Decision) -> str:
    """C modundaki yanitla ayni dort baslikli metin."""
    lines = ["Bulgular:"]
    lines += [f"- {item}" for item in decision.bulgular]
    lines += ["", "Belirsizlik / eksik bilgi:"]
    lines += [f"- {item}" for item in decision.belirsizlik]
    lines += ["", "Sonraki adım:"]
    lines += [f"- {item}" for item in decision.sonraki_adim]
    lines += ["", f"Kaynaklar: {', '.join(decision.kaynaklar) if decision.kaynaklar else 'yok'}"]
    return "\n".join(lines)


def run_case(case: dict[str, Any], source_ids: list[str]) -> dict[str, Any]:
    """C modundaki chat_once sonucu ile ayni alanlar. Model olcumleri null'dir."""
    started = time.perf_counter()
    decision = decide(case, source_ids)
    content = render(decision)
    elapsed = time.perf_counter() - started
    return {
        "ok": True,
        "failure_kind": None,
        "client_elapsed_s": round(elapsed, 6),
        "istemci_eksi_sunucu_total_s": None,
        "http_status": None,
        "error": None,
        "done": None,
        "done_reason": None,
        "content": content,
        "thinking": None,
        "metrics": None,
        "raw_response": None,
        "kural_karari": {
            "kural": decision.kural,
            "aile": decision.aile,
            "durum": decision.durum,
            "kaynaklar": list(decision.kaynaklar),
        },
    }
