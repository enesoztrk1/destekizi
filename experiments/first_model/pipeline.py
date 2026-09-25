"""Destekizi - tek vakanin analiz yolu (`analyze_case`).

SIRA SABITTIR: maskeleme -> arama -> uygunluk filtresi -> kural motoru veya model.
Calistirici (run.py) ve servis (api.py) ayni fonksiyonu kullanir.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import applicability  # kaynak surum/yururluk filtresi
import masking  # hassas deger maskeleme
import retrieval  # anlamsal arama; ucuncu taraf paketi yalnizca aramada, tembel yuklenir
import rules_mode  # A/B modu: kural tabanli sablon
from model_client import chat_once
from prompting import build_messages

KNOWN_SOURCE_PATTERNS = ("D1", "D2", "D3")

REQUIRED_HEADINGS = (
    "Bulgular",
    "Belirsizlik",
    "Sonraki adım",
    "Kaynaklar",
)


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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def analyze_case(
    case: dict[str, Any],
    *,
    mode: str,
    sources: dict[str, dict[str, Any]],
    system_prompt: str,
    retriever: retrieval.Retriever | None,
    applicability_on: bool,
    host: str,
    model: str,
    options: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    """Tek vakanin analiz kaydi. Calistirici ve servis (api.py) ayni yolu kullanir.

    SIRA SABITTIR: maskeleme -> arama -> uygunluk filtresi -> kural motoru veya model.
    Maskeleme ilk adimdir: arama sorgusu, kurallar, modele giden mesaj ve kayit
    yalnizca maskelenmis vakayi gorur. Uygunluk filtresi aramadan SONRA, modelden ve
    kural motorundan ONCE calisir; eledigi kaynak kurala/modele hic ulasmaz.
    """
    case, maskelenen = masking.mask_case(case)
    arama = retriever.search(case) if retriever is not None else None
    candidates = list(arama.kaynaklar) if arama is not None else list(case["source_ids"])
    filtre = (
        applicability.filter_sources(case, sources, candidates)
        if applicability_on
        else None
    )
    started_at_utc = _utc_now()  # istekten ONCE alinir
    if mode in ("A", "B"):
        messages = None  # modele mesaj gonderilmez
        result = rules_mode.run_case(case, candidates, filtre)
    else:
        messages = build_messages(system_prompt, case, sources, filtre, candidates)
        result = chat_once(host, model, messages, options, timeout)
    uygunluk = (
        filtre.kayit()
        if filtre is not None
        else {
            # Motor kapali: karar verilmedi; tum aday kaynaklar kullanildi.
            "degerlendirilen_kaynaklar": None,
            "kullanilan_kaynaklar": candidates,
            "elenen_kaynaklar": None,
            "belirsiz_kaynaklar": None,
        }
    )
    return {
        "case_id": case["case_id"],
        "mod": mode,
        "api_version": case.get("api_version"),
        "olay_tarihi": case.get("olay_tarihi"),
        # Vakanin elle atanmis listesi; aramali kosuda karsilastirma icin korunur.
        "source_ids": list(case.get("source_ids") or []),
        # Maskelenen alanlarin yolu (degerleri degil); bos liste: maskelenecek deger yok.
        "maskelenen_alanlar": maskelenen,
        "kaynak_secimi": "arama" if arama is not None else "elle",
        "arama_sonuclari": arama.kayit() if arama is not None else None,
        "arama_suresi_s": arama.sure_s if arama is not None else None,
        "uygunluk_motoru_acik": applicability_on,
        **uygunluk,
        "model": model if mode == "C" else None,
        "started_at_utc": started_at_utc,
        "request_options": options if mode == "C" else None,
        "messages": messages,
        "kural_karari": None,
        **result,
        "mekanik_gozlem": mechanical_observations(result.get("content")),
    }
