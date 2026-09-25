"""Destekizi - arama (retrieval) metrikleri. Model CAGIRMAZ; run_eval.py kullanir.

Gerekli kaynaklar yeni bir alandan degil, mevcut
expected.jsonl -> makine_kontrolleri.gerekli_kaynaklar alanindan okunur.

Tanimlar (vaka bazinda; gerekli kaynagi tanimsiz vakalar paydaya girmez):
    Recall@k    = |gerekli ∩ ilk k| / |gerekli|
    Precision@k = |gerekli ∩ ilk k| / k
    RR          = 1 / (ilk gerekli kaynagin sirasi); ilk k'da yoksa 0
    MRR         = RR ortalamasi
Raporda mutlak sayilar kullanilir (ör. "20 gerekli kaynagin 18'i ilk 3'te").

Arama yapilmamis kosuda (elle atama) bu metrikler None doner; rapor "uygulanamaz"
yazar, sifir saymaz.
"""

from __future__ import annotations

from typing import Any, Callable


def retrieved_ids(record: dict[str, Any] | None) -> list[str] | None:
    """Aramanin sirali sonuc kimlikleri; arama yapilmamissa None."""
    if not record or record.get("kaynak_secimi") != "arama":
        return None
    results = record.get("arama_sonuclari")
    if not isinstance(results, list) or not results:
        # Bozuk kayit "hicbir sey bulunamadi" (sifir) sayilmaz; veri hatasidir.
        raise ValueError(f"{record.get('case_id')}: kaynak_secimi=arama ama arama_sonuclari "
                         f"bos olmayan liste degil: {results!r}")
    return [item["source_id"] for item in results]


def case_metrics(retrieved: list[str], required: list[str], k: int) -> dict[str, Any]:
    """Tek vaka. required bos olamaz (cagiran eler)."""
    top = retrieved[:k]
    hits = [s for s in required if s in top]
    rank = next((i for i, s in enumerate(top, start=1) if s in required), None)
    return {
        "isabet": len(hits),
        "gerekli": len(required),
        "k": k,
        "hepsi_bulundu": len(hits) == len(required),
        "ilk_dogru_sira": rank,
        "rr": 1.0 / rank if rank else 0.0,
    }


def run_metrics(
    records: dict[str, dict[str, Any]],
    expected: dict[str, dict[str, Any] | None],
    k: int | None,
) -> dict[str, Any] | None:
    """Kosu duzeyinde arama metrikleri. Arama yapilmamissa None (uygulanamaz)."""
    searched = {cid: ids for cid, r in records.items() if (ids := retrieved_ids(r)) is not None}
    if not searched:
        return None
    if k is None:
        k = max(len(ids) for ids in searched.values())
    per_case: dict[str, dict[str, Any]] = {}
    undefined: list[str] = []
    eliminated: dict[str, dict[str, str]] = {}
    eliminated_required: dict[str, list[str]] = {}
    for cid in sorted(searched):
        record = records[cid]
        required = list((expected.get(cid) or {}).get("gerekli_kaynaklar") or [])
        elenen = record.get("elenen_kaynaklar") or {}
        if elenen:
            eliminated[cid] = dict(elenen)
            lost = [s for s in required if s in elenen]
            if lost:
                eliminated_required[cid] = lost
        if not required:
            undefined.append(cid)
            continue
        per_case[cid] = case_metrics(searched[cid], required, k)
    n = len(per_case)
    return {
        "k": k,
        "vaka": n,
        "gerekli_tanimsiz": undefined,
        "isabet": sum(c["isabet"] for c in per_case.values()),
        "gerekli": sum(c["gerekli"] for c in per_case.values()),
        "hepsi_bulunan_vaka": sum(1 for c in per_case.values() if c["hepsi_bulundu"]),
        "sonuc_sayisi": n * k,  # Precision@k paydasi
        "rr_toplam": sum(c["rr"] for c in per_case.values()),
        "mrr": (sum(c["rr"] for c in per_case.values()) / n) if n else None,
        "vaka_bazli": per_case,
        "elenen": eliminated,
        "elenen_toplam": sum(len(v) for v in eliminated.values()),
        "aranan_toplam": sum(len(ids) for ids in searched.values()),
        "elenen_gerekli": eliminated_required,
    }


def error_split(
    records: dict[str, dict[str, Any]],
    expected: dict[str, dict[str, Any] | None],
    per_case_eval: dict[str, dict[str, Any]],
) -> dict[str, list[str]] | None:
    """Arama hatasi ile uretim hatasini ayiran 2x2 tablo.

    Satir - dogru kaynak bulundu mu: gerekli kaynaklarin HEPSI arama + uygunluk
    filtresinden sonra kurala/modele ulasti mi (kayittaki kullanilan_kaynaklar).
    Sutun - sonuc dogru mu (makine vekili): metinden turetilen durum dogru VE
    gerekli kaynaklarin hepsi Kaynaklar bolumunde listelenmis.
    Gerekli kaynagi tanimsiz vakalar tabloya girmez. Teknik basarisiz kayit (ok=false)
    veya durum/kaynak kontrolu olmayan vaka uretim hatasi SAYILMAZ; "olculemedi"
    listesine girer. Arama yoksa None.
    """
    if not any(retrieved_ids(r) is not None for r in records.values()):
        return None
    cells: dict[str, list[str]] = {"bulundu_dogru": [], "bulundu_yanlis": [],
                                   "bulunamadi_dogru": [], "bulunamadi_yanlis": [],
                                   "olculemedi": []}
    for cid in sorted(records):
        record = records[cid]
        required = (expected.get(cid) or {}).get("gerekli_kaynaklar") or []
        if retrieved_ids(record) is None or not required:
            continue
        ev = per_case_eval.get(cid) or {}
        if (not record.get("ok") or ev.get("durum_dogru") is None
                or ev.get("gerekli_kaynak_tamam") is None):
            cells["olculemedi"].append(cid)
            continue
        reached = set(required) <= set(record.get("kullanilan_kaynaklar") or [])
        correct = ev["durum_dogru"] is True and ev["gerekli_kaynak_tamam"] is True
        key = ("bulundu" if reached else "bulunamadi") + ("_dogru" if correct else "_yanlis")
        cells[key].append(cid)
    return cells


def _ids(items: list[str] | dict[str, str]) -> str:
    if isinstance(items, dict):
        return ", ".join(f"{s} ({code})" for s, code in items.items()) or "—"
    return ", ".join(items) or "—"


def render(evaluations: list[dict[str, Any]], label: Callable[[dict], str],
           of: Callable[[int, int], str]) -> list[str]:
    """Rapor bolumleri: elle/arama farki ve arama/uretim hata ayrimi."""
    searched = [ev for ev in evaluations if ev.get("arama") is not None]
    out = ["## Arama (retrieval)", ""]
    for ev in evaluations:
        if ev.get("arama") is None:
            out.append(f"- {label(ev)}: uygulanamaz (kaynaklar elle atandı; arama yapılmadı).")
    for ev in searched:
        m = ev["arama"]
        out.append(f"- {label(ev)}: k={m['k']}; gerekli kaynağı tanımsız olduğu için arama "
                   f"metriklerine girmeyen vakalar: {', '.join(m['gerekli_tanimsiz']) or 'yok'}. "
                   f"{of(m['vaka'], m['hepsi_bulunan_vaka'])} vakada gerekli kaynakların hepsi "
                   f"ilk {m['k']} sonuçta.")
    out.append("")
    if not searched:
        return out

    for ev in searched:
        out += [f"### Elle atama ile arama farkı — {label(ev)}", "",
                "Eksik: elle atanmış ama aramanın ilk k sonucunda olmayan. Fazla: aramanın "
                "bulduğu ama elle atanmamış. Kullanılan: uygunluk filtresinden sonra kalan.", "",
                "| Vaka | Elle | Arama (skor) | Eksik | Fazla | Filtre eledi | Kullanılan |",
                "| --- | --- | --- | --- | --- | --- | --- |"]
        for row in ev["elle_arama"]:
            found = ", ".join(f"{a['source_id']} ({a['skor']:.3f})" for a in row["arama"]) or "—"
            out.append(f"| {row['case_id']} | {_ids(row['elle'])} | {found} | {_ids(row['eksik'])} "
                       f"| {_ids(row['fazla'])} | {_ids(row['elenen'])} | {_ids(row['kullanilan'])} |")
        out.append("")

        cells = ev["hata_ayrimi"]
        out += [f"### Arama / üretim hata ayrımı — {label(ev)}", "",
                "Satır: gerekli kaynakların hepsi arama ve uygunluk filtresinden sonra "
                "kurala/modele ulaştı mı. Sütun: sonuç doğru mu (makine vekili: türetilen durum "
                "doğru ve gerekli kaynakların hepsi listelenmiş). Gerekli kaynağı tanımsız "
                "vakalar tabloya girmez.", "",
                "| | Sonuç doğru | Sonuç yanlış |", "| --- | --- | --- |"]
        for row_key, row_name in (("bulundu", "Doğru kaynak ulaştı"),
                                  ("bulunamadi", "Doğru kaynak ulaşmadı")):
            vals = [cells[f"{row_key}_{c}"] for c in ("dogru", "yanlis")]
            out.append(f"| {row_name} | " + " | ".join(
                f"{len(v)}" + (f": {', '.join(v)}" if v else "") for v in vals) + " |")
        if cells["olculemedi"]:
            out += ["", f"Ölçülemedi (teknik başarısız veya kontrol yok; üretim hatası "
                    f"sayılmadı): {', '.join(cells['olculemedi'])}."]
        out += ["", "Okuma: *ulaştı + yanlış* üretim hatasıdır; *ulaşmadı + yanlış* arama "
                "(veya filtre) hatasıdır; *ulaşmadı + doğru* kaynak eksikken doğru durumu "
                "tahmin etmektir.", ""]
    return out


def manual_vs_search(records: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Elle atanmis source_ids ile arama sonuclarinin vaka bazli farki."""
    rows = []
    for cid in sorted(records):
        record = records[cid]
        ids = retrieved_ids(record)
        if ids is None:
            continue
        manual = list(record.get("source_ids") or [])
        rows.append({
            "case_id": cid,
            "elle": manual,
            "arama": record.get("arama_sonuclari") or [],
            "eksik": [s for s in manual if s not in ids],
            "fazla": [s for s in ids if s not in manual],
            "elenen": record.get("elenen_kaynaklar") or {},
            "kullanilan": list(record.get("kullanilan_kaynaklar") or []),
        })
    return rows
