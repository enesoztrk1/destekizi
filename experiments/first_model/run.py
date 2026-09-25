#!/usr/bin/env python3
"""Destekizi - ilk yerel model deneyi calistiricisi (komut satiri giris noktasi).

Veri akisi:
    vaka + kaynaklar (elle secilmis veya --retrieval/B ile aranmis)
    -> uygunluk filtresi -> gorev yonergesi (prompt.txt)
    -> yerel Ollama /api/chat -> ham yanit + olcumler -> insan degerlendirmesi

Bu dosya arguman ayristirma, kosu dizini, vaka dongusu ve ozet yazimini tasir.
Girdi okuma inputs.py, tek vaka analizi pipeline.py, mesaj kurma prompting.py,
Ollama istemcisi model_client.py icindedir.

Cevap anahtari (expected.jsonl) OKUNMAZ; `inputs.read_text` bunu engeller.
Yalnizca Python 3.12 standart kutuphanesi kullanilir.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
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
import masking  # noqa: E402  hassas deger maskeleme; standart kutuphane
import retrieval  # noqa: E402  anlamsal arama; ucuncu taraf paketi yalnizca aramada, tembel yuklenir
import rules_mode  # noqa: E402  A modu: kural tabanli temel yontem (ayni dizindeki modul)

from inputs import (  # noqa: E402  girdi okuma ve dogrulama
    ExperimentError,
    load_cases,
    load_sources,
    read_text,
    sha256_file,
    validate_case_sources,
)
from model_client import (  # noqa: E402  Ollama istemcisi
    DEFAULT_HOST,
    DEFAULT_MODEL,
    DEFAULT_NUM_CTX,
    DEFAULT_NUM_PREDICT,
    DEFAULT_TIMEOUT_S,
    chat_once,
    fetch_model_metadata,
    preflight,
)
from pipeline import _utc_now, analyze_case  # noqa: E402  tek vaka analizi

RULES_PATH = Path(rules_mode.__file__).resolve()
APPLICABILITY_PATH = Path(applicability.__file__).resolve()
MASKING_PATH = Path(masking.__file__).resolve()

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

B_MODE_NOTES = [
    "B modu: anlamsal arama + A modunun kural tabanli sablonu (rules_mode.py).",
    "Kaynaklar elle atanmaz; retrieval.py ile en yakin top-k kaynak bulunur.",
    "Sira: arama -> uygunluk filtresi -> kural motoru.",
] + A_MODE_NOTES[1:]

WARMUP_MESSAGES = [
    {"role": "system", "content": "Kisa ve Turkce yanit ver."},
    {"role": "user", "content": "Bu bir isinma istegidir. Yalnizca 'hazir' yaz."},
]


# --------------------------------------------------------------------------
# Calisma
# --------------------------------------------------------------------------


def make_run_id(mode: str = "C", use_retrieval: bool = False) -> str:
    """C modunun adi degismez; A ve B modu dizin adinda '-A-' / '-B-', aramali C
    modu '-CR-' ile ayirt edilir."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    marker = {"A": "-A", "B": "-B"}.get(mode, "-CR" if use_retrieval else "")
    return f"{stamp}{marker}-{uuid.uuid4().hex[:6]}"


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
    if mode in ("A", "B"):
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
    if mode == "A" and args.retrieval:
        raise ExperimentError("A modu elle atanmis kaynaklari kullanir; arama icin --mode B kullanin.")
    # B modu her zaman aramayla calisir; C modu yalnizca --retrieval ile.
    use_retrieval = mode == "B" or args.retrieval
    if not use_retrieval and args.top_k != retrieval.DEFAULT_TOP_K:
        raise ExperimentError("--top-k yalnizca aramayla (--mode B veya --retrieval) kullanilir.")
    retriever: retrieval.Retriever | None = None
    retrieval_meta: dict[str, Any] | None = None
    if use_retrieval:
        # Paket, model ve onbellek sonuc dizini acilmadan ONCE dogrulanir.
        retriever, retrieval_meta = retrieval.open_retriever(
            Path(args.embeddings).resolve(), docs_path, sources, args.top_k
        )
        print(
            f"Arama: {retrieval_meta['embedding_modeli']} ({retrieval_meta['cihaz']}) "
            f"| top-k {args.top_k} | kaynaklar elle atanmaz."
        )
    if mode == "C":
        preflight_info = preflight(args.host, args.model)
        metadata = fetch_model_metadata(args.host, args.model)
        print(
            f"Ollama {preflight_info['ollama_version']} | model {args.model} "
            f"| kisa kimlik {preflight_info['model_short_id']}"
        )
    elif mode == "B":
        print("B modu: arama + kural tabanli sablon. Ollama'ya istek gonderilmez.")
    else:
        print("A modu: kural tabanli temel yontem. Ollama'ya istek gonderilmez.")
    print(
        "Uygunluk motoru: "
        + ("KAPALI (--no-applicability); kaynaklar filtrelenmez." if args.no_applicability
           else "acik; kaynaklar surum ve olay tarihine gore filtrelenir.")
    )

    run_id = make_run_id(mode, use_retrieval)
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
    source_selection = {
        "kaynak_secimi": "arama" if use_retrieval else "elle",
        # null: arama yapilmadi (elle atama).
        "arama": retrieval_meta,
        "maskeleme": {
            "path": str(MASKING_PATH),
            "sha256": sha256_file(MASKING_PATH),
            "not": "Her vaka analizden once masking.mask_case ile maskelenir.",
        },
    }

    if mode in ("A", "B"):
        run_meta = {
            "run_id": run_id,
            "mod": mode,
            "started_at_utc": _utc_now(),
            "model": None,
            "host": None,
            "options": None,
            "auto_retry": 0,
            "concurrency": 1,
            "ayar_notlari": B_MODE_NOTES if mode == "B" else A_MODE_NOTES,
            "girdi_dosyalari": input_files,
            "calistirici_dosyasi": runner_file,
            "kural_motoru_dosyasi": {
                "path": str(RULES_PATH),
                "sha256": sha256_file(RULES_PATH),
                "not": "Calisma basinda diskteki rules_mode.py dosyasinin ozeti.",
            },
            "uygunluk_motoru": applicability_meta,
            **source_selection,
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
            **source_selection,
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
    if mode in ("A", "B"):
        pass  # A ve B modunda model yok; isinma uygulanamaz.
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

                record = analyze_case(
                    case,
                    mode=mode,
                    sources=sources,
                    system_prompt=system_prompt,
                    retriever=retriever,
                    applicability_on=applicability_on,
                    host=args.host,
                    model=args.model,
                    options=options,
                    timeout=args.timeout,
                )
                result = record
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
        choices=("A", "B", "C"),
        default="C",
        help="C: yerel model (varsayilan). A: kural tabanli temel yontem; modele istek gitmez. "
        "B: anlamsal arama + A'nin kural sablonu; modele istek gitmez.",
    )
    parser.add_argument(
        "--retrieval",
        action="store_true",
        help="C modunda kaynaklari elle atama yerine anlamsal aramayla secer (B modu zaten arar).",
    )
    parser.add_argument(
        "--top-k", type=int, default=retrieval.DEFAULT_TOP_K, help="Aramada donen kaynak sayisi."
    )
    parser.add_argument(
        "--embeddings", default=str(retrieval.DEFAULT_CACHE), help="Kaynak embedding onbellegi."
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
    except (ExperimentError, retrieval.RetrievalError) as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
