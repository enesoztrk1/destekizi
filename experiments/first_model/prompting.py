"""Destekizi - modele giden mesajlarin kurulmasi.

Sistem promptu prompt.txt dosyasindan `inputs.read_text` ile okunur (run.py ve
api.py); bu modul her vaka icin sifirdan mesaj dizisi kurar.
"""

from __future__ import annotations

import json
from typing import Any

import applicability  # uygunluk karari tipleri ve gerekce aciklamalari

def build_user_message(
    case: dict[str, Any],
    sources: dict[str, dict[str, Any]],
    filtre: applicability.Filtre | None = None,
    candidates: list[str] | None = None,
) -> str:
    """Yalnizca bu vakanin verisini ve secilmis kaynaklarini iceren kullanici mesaji.

    filtre verilirse (uygunluk motoru acik) yalnizca elenmemis kaynaklarin metni
    gonderilir; elenen kaynaklarin METNI modele hic gitmez. Motor kapaliyken ve
    vakada olay_tarihi yokken mesaj, motordan onceki bicimle birebir aynidir.
    candidates: aramanin buldugu kaynaklar; None ise vakanin elle atanmis source_ids'i.
    """
    lines: list[str] = []

    if filtre is not None:
        source_ids = list(filtre.kullanilan)
    else:
        source_ids = list(candidates if candidates is not None else case["source_ids"])
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
    candidates: list[str] | None = None,
) -> list[dict[str, str]]:
    """Her vaka icin sifirdan mesaj dizisi. Onceki vaka/cevap tasinmaz."""
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": build_user_message(case, sources, filtre, candidates)},
    ]
