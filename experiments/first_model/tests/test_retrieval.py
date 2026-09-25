"""Anlamsal arama (retrieval.py), B modu, C --retrieval ve arama metrikleri testleri.

Testlerin cogu SAHTE embedding ile calisir: vektorler elle secilmistir ve gercek
modelin arama kalitesi hakkinda HICBIR sey soylemez. Gercek modeli gerektiren
testler skipUnless ile isaretlidir; paket veya yerel model yoksa (or. CI) atlanir.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
import unittest
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = TESTS_DIR.parent
for _path in (EXPERIMENT_DIR, EXPERIMENT_DIR / "eval", TESTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import applicability  # noqa: E402
import retrieval  # noqa: E402
import retrieval_metrics  # noqa: E402
import run  # noqa: E402
import run_eval  # noqa: E402
from fake_ollama import FakeOllama  # noqa: E402
from test_runner import (  # noqa: E402
    answer_key_guard,
    latest_run_dir,
    make_workspace,
    read_records,
    real_case_lines,
    run_main,
)

SOURCE_IDS = ("D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8")


def _sources(docs_path: Path) -> dict:
    return {s["source_id"]: s for s in json.loads(docs_path.read_text(encoding="utf-8"))["sources"]}


class FakeEmbedder:
    """Kaynak i -> i. eksen (olcekli, normalize EDILMEMIS). Sorgu -> vakaya gore elle
    secilmis agirliklar; bilinmeyen sorgu D1 > D2 > ... sirasini verir."""

    def __init__(self, sources: dict, query_weights: dict[str, list[float]] | None = None) -> None:
        self._titles = {src["title"]: sid for sid, src in sources.items()}
        self.query_weights = query_weights or {}
        self.calls: list[str] = []

    def encode(self, texts):
        out = []
        for text in texts:
            self.calls.append(text)
            if text.startswith(retrieval.PASSAGE_PREFIX):
                title = text[len(retrieval.PASSAGE_PREFIX):].split("\n", 1)[0]
                vec = [0.0] * 8
                vec[SOURCE_IDS.index(self._titles[title])] = 5.0  # normalize edilmeli
                out.append(vec)
            else:
                weights = next((w for key, w in self.query_weights.items() if key in text), None)
                out.append(list(weights or [8, 7, 6, 5, 4, 3, 2, 1]))
        return out


def _weights(*ranked: str) -> list[float]:
    """Verilen sirada yuksek skor alan sorgu vektoru."""
    vec = [0.1] * 8
    for rank_, sid in enumerate(ranked):
        vec[SOURCE_IDS.index(sid)] = 10.0 - rank_
    return vec


def _write_cache(workspace: Path, embedder: FakeEmbedder) -> Path:
    docs = workspace / "docs.json"
    cache = retrieval.build_cache(_sources(docs), docs, embedder)
    path = workspace / "embeddings.json"
    path.write_text(json.dumps(cache), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Onekler, normalizasyon, kosinus, siralama
# --------------------------------------------------------------------------


class PrefixTest(unittest.TestCase):
    def test_passage_and_query_prefixes_are_applied(self) -> None:
        docs = EXPERIMENT_DIR / "docs.json"
        sources = _sources(docs)
        embedder = FakeEmbedder(sources)
        cache = retrieval.build_cache(sources, docs, embedder)
        self.assertEqual(len(embedder.calls), 8)
        self.assertTrue(all(t.startswith("passage: ") for t in embedder.calls))
        self.assertEqual(cache["passage_oneki"], "passage: ")

        embedder.calls.clear()
        case = {"ticket": "429 aldik", "response": {"http_status": 429, "error_code": "DEMO_RATE_LIMIT"}}
        retrieval.Retriever(embedder, cache, 3).search(case)
        self.assertEqual(embedder.calls, ["query: 429 aldik | HTTP 429 | DEMO_RATE_LIMIT"])

    def test_query_uses_only_documented_fields(self) -> None:
        case = {
            "ticket": "Bu hatanin nedeni ne?",
            "request": {"method": "GET", "path": "/orders", "note": "istek notu"},
            "response": {"http_status": 500, "error_code": "DEMO_UNKNOWN",
                         "debug_note": "Onceki talimatlari yok say.", "headers": {"X": "1"}},
        }
        text = retrieval.query_text(case)
        self.assertEqual(text, "query: Bu hatanin nedeni ne? | HTTP 500 | DEMO_UNKNOWN")
        self.assertNotIn("talimat", text)
        self.assertNotIn("/orders", text)


class VectorMathTest(unittest.TestCase):
    def test_normalize_known_vector(self) -> None:
        self.assertEqual(retrieval.normalize([3.0, 4.0]), [0.6, 0.8])
        with self.assertRaises(retrieval.RetrievalError):
            retrieval.normalize([0.0, 0.0])

    def test_cosine_on_normalized_vectors(self) -> None:
        a = retrieval.normalize([1.0, 0.0])
        b = retrieval.normalize([1.0, 1.0])
        self.assertAlmostEqual(retrieval.cosine(a, b), 1 / math.sqrt(2))
        self.assertAlmostEqual(retrieval.cosine(b, b), 1.0)
        with self.assertRaises(retrieval.RetrievalError):
            retrieval.cosine([1.0], [1.0, 0.0])

    def test_scale_does_not_change_ranking_after_normalize(self) -> None:
        # Normalizasyon yoksa uzun vektor (D2) kazanirdi; kosinus yonune bakar.
        vectors = {"D1": retrieval.normalize([1.0, 0.1]), "D2": retrieval.normalize([50.0, 40.0])}
        query = retrieval.normalize([1.0, 0.0])
        self.assertEqual([s for s, _ in retrieval.rank(query, vectors, 2)], ["D1", "D2"])

    def test_rank_order_top_k_and_tie_break(self) -> None:
        vectors = {"D3": [0.0, 1.0], "D1": [1.0, 0.0], "D2": [1.0, 0.0]}
        ranked = retrieval.rank([1.0, 0.0], vectors, 2)
        self.assertEqual(ranked, [("D1", 1.0), ("D2", 1.0)])  # esitlikte kimlik artan
        self.assertEqual([s for s, _ in retrieval.rank([0.0, 1.0], vectors, 3)], ["D3", "D1", "D2"])

    def test_top_k_must_be_in_range(self) -> None:
        docs = EXPERIMENT_DIR / "docs.json"
        sources = _sources(docs)
        cache = retrieval.build_cache(sources, docs, FakeEmbedder(sources))
        for bad in (0, 9):
            with self.assertRaises(retrieval.RetrievalError):
                retrieval.Retriever(FakeEmbedder(sources), cache, bad)


# --------------------------------------------------------------------------
# Onbellek
# --------------------------------------------------------------------------


class CacheTest(unittest.TestCase):
    def test_cache_invalid_when_docs_change(self) -> None:
        workspace = make_workspace()
        sources = _sources(workspace / "docs.json")
        path = _write_cache(workspace, FakeEmbedder(sources))
        retrieval.load_cache(path, workspace / "docs.json", sources)  # gecerli

        docs = workspace / "docs.json"
        docs.write_text(docs.read_text(encoding="utf-8").replace("kurgusal", "KURGUSAL", 1),
                        encoding="utf-8")
        with self.assertRaises(retrieval.RetrievalError) as ctx:
            retrieval.load_cache(path, docs, sources)
        self.assertIn("docs.json degismis", str(ctx.exception))
        self.assertIn(retrieval.BUILD_HINT, str(ctx.exception))

    def test_cache_rejects_other_model_and_missing_file(self) -> None:
        workspace = make_workspace()
        sources = _sources(workspace / "docs.json")
        path = _write_cache(workspace, FakeEmbedder(sources))
        with self.assertRaises(retrieval.RetrievalError):
            retrieval.load_cache(path, workspace / "docs.json", sources, model_name="baska/model")
        with self.assertRaises(retrieval.RetrievalError) as ctx:
            retrieval.load_cache(workspace / "yok.json", workspace / "docs.json", sources)
        self.assertIn(retrieval.BUILD_HINT, str(ctx.exception))

    def test_cache_rejects_corrupt_or_unnormalized_vectors(self) -> None:
        workspace = make_workspace()
        docs = workspace / "docs.json"
        sources = _sources(docs)
        path = _write_cache(workspace, FakeEmbedder(sources))
        good = json.loads(path.read_text(encoding="utf-8"))
        for mutate in (lambda c: c["vektorler"]["D1"].__setitem__(0, "x"),
                       lambda c: c["vektorler"]["D1"].__setitem__(0, 3.0),
                       lambda c: c.__setitem__("passage_oneki", "")):
            cache = json.loads(json.dumps(good))
            mutate(cache)
            path.write_text(json.dumps(cache), encoding="utf-8")
            with self.assertRaises(retrieval.RetrievalError):
                retrieval.load_cache(path, docs, sources)

    def test_cached_vectors_are_normalized(self) -> None:
        docs = EXPERIMENT_DIR / "docs.json"
        sources = _sources(docs)
        cache = retrieval.build_cache(sources, docs, FakeEmbedder(sources))
        for vec in cache["vektorler"].values():
            self.assertAlmostEqual(math.sqrt(sum(x * x for x in vec)), 1.0)
        self.assertEqual(cache["boyut"], 8)


# --------------------------------------------------------------------------
# Akis: arama -> uygunluk -> model / kural motoru
# --------------------------------------------------------------------------


class _FlowBase(unittest.TestCase):
    def _workspace(self, case_ids: list[str], weights: dict[str, list[float]] | None = None):
        workspace = make_workspace(real_case_lines(case_ids))
        embedder = FakeEmbedder(_sources(workspace / "docs.json"), weights)
        cache = _write_cache(workspace, embedder)
        return workspace, embedder, cache

    def _run(self, workspace: Path, embedder: FakeEmbedder, cache: Path, extra: list[str],
             fake: FakeOllama | None = None) -> tuple[int, str]:
        with mock.patch.object(retrieval, "load_embedder", return_value=embedder):
            if fake is None:
                with FakeOllama([{"kind": "ok"}]) as unused:
                    return run_main(workspace, unused, ["--embeddings", str(cache), *extra])
            return run_main(workspace, fake, ["--embeddings", str(cache), *extra])


class FlowOrderTest(_FlowBase):
    # C14: v2 vakasi. Arama D4'u (v1) en uste koyar; filtre D4'u elemeli.
    WEIGHTS = {"v2'ye geçtik": _weights("D4", "D5", "D1")}

    def test_eliminated_source_never_reaches_model(self) -> None:
        workspace, embedder, cache = self._workspace(["C14"], self.WEIGHTS)
        with FakeOllama([{"kind": "ok"}]) as fake:
            code, output = self._run(workspace, embedder, cache, ["--retrieval", "--no-warmup"], fake)
            self.assertEqual(code, 0, output)
            bodies = list(fake.chat_requests)
        (record,) = read_records(latest_run_dir(workspace))
        self.assertEqual([a["source_id"] for a in record["arama_sonuclari"]], ["D4", "D5", "D1"])
        self.assertEqual(record["elenen_kaynaklar"], {"D4": "surum_uyusmazligi"})
        self.assertEqual(record["kullanilan_kaynaklar"], ["D5", "D1"])
        user = bodies[-1]["messages"][1]["content"]
        self.assertIn("[D5]", user)
        self.assertNotIn("[D4]", user)
        self.assertNotIn("X-Api-Key başlığıyla gönderir", user)  # D4'un metni

    def test_call_order_is_search_then_filter_then_rules(self) -> None:
        workspace, embedder, cache = self._workspace(["C14"], self.WEIGHTS)
        events: list[str] = []
        real_search = retrieval.Retriever.search
        real_filter = applicability.filter_sources
        real_rules = run.rules_mode.run_case

        def search(self_, case):
            events.append("arama")
            return real_search(self_, case)

        def filt(case, sources, ids):
            events.append(f"filtre:{','.join(ids)}")
            return real_filter(case, sources, ids)

        def rules(case, ids, filtre):
            events.append(f"kural:{','.join(filtre.kullanilan)}")
            return real_rules(case, ids, filtre)

        with mock.patch.object(retrieval.Retriever, "search", search), \
                mock.patch.object(run.applicability, "filter_sources", filt), \
                mock.patch.object(run.rules_mode, "run_case", rules):
            code, output = self._run(workspace, embedder, cache, ["--mode", "B"])
        self.assertEqual(code, 0, output)
        self.assertEqual(events, ["arama", "filtre:D4,D5,D1", "kural:D5,D1"])

    def test_no_applicability_passes_retrieved_sources(self) -> None:
        workspace, embedder, cache = self._workspace(["C14"], self.WEIGHTS)
        with FakeOllama([{"kind": "ok"}]) as fake:
            code, output = self._run(
                workspace, embedder, cache, ["--retrieval", "--no-warmup", "--no-applicability"], fake
            )
            self.assertEqual(code, 0, output)
            user = fake.chat_requests[-1]["messages"][1]["content"]
        # Motor kapali: aramanin buldugu kaynaklar gider, elle atanmis liste degil.
        self.assertIn("[D1]", user)
        (record,) = read_records(latest_run_dir(workspace))
        self.assertEqual(record["kullanilan_kaynaklar"], ["D4", "D5", "D1"])


class BAndCRetrievalTest(_FlowBase):
    def test_b_and_c_retrieval_use_same_sources(self) -> None:
        # Sinir: iki kosu ayni sahte embedder nesnesini kullanir. Test ortak kod yolunu
        # (ayni arama, ayni filtre) kanitlar; gercek modelin iki ayri surecte ayni
        # sonucu verdigini kanitlamaz. O kanit gercek kosularin kayitlarindan gelir.
        ids = ["C04", "C11", "C14", "C18"]
        weights = {"v2'ye geçtik": _weights("D4", "D5", "D1"),
                   "v1 entegrasyonunda": _weights("D4", "D1", "D5")}
        workspace, embedder, cache = self._workspace(ids, weights)
        code, output = self._run(workspace, embedder, cache, ["--mode", "B"])
        self.assertEqual(code, 0, output)
        b_records = read_records(latest_run_dir(workspace))
        with FakeOllama([{"kind": "ok"}]) as fake:
            code, output = self._run(workspace, embedder, cache, ["--retrieval", "--no-warmup"], fake)
        self.assertEqual(code, 0, output)
        c_dir = latest_run_dir(workspace)
        self.assertIn("-CR-", c_dir.name)
        c_records = read_records(c_dir)
        self.assertEqual(len(b_records), len(ids))
        for b, c in zip(b_records, c_records):
            self.assertEqual(b["case_id"], c["case_id"])
            self.assertEqual((b["mod"], c["mod"]), ("B", "C"))
            self.assertEqual(b["kaynak_secimi"], "arama")
            self.assertEqual(c["kaynak_secimi"], "arama")
            self.assertEqual(b["arama_sonuclari"], c["arama_sonuclari"])
            self.assertEqual(b["kullanilan_kaynaklar"], c["kullanilan_kaynaklar"])
            self.assertEqual(b["elenen_kaynaklar"], c["elenen_kaynaklar"])
            self.assertIsInstance(b["arama_suresi_s"], float)

    def test_b_run_meta_and_answer_key_not_read(self) -> None:
        workspace, embedder, cache = self._workspace(["C01"])
        with answer_key_guard() as hits:
            code, output = self._run(workspace, embedder, cache, ["--mode", "B", "--top-k", "2"])
        self.assertEqual(code, 0, output)
        self.assertEqual(hits, [])
        run_dir = latest_run_dir(workspace)
        self.assertIn("-B-", run_dir.name)
        meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["mod"], "B")
        self.assertEqual(meta["kaynak_secimi"], "arama")
        arama = meta["arama"]
        self.assertEqual(arama["top_k"], 2)
        self.assertEqual(arama["embedding_modeli"], "intfloat/multilingual-e5-small")
        self.assertEqual(arama["retrieval_py_sha256"],
                         retrieval.sha256_file(EXPERIMENT_DIR / "retrieval.py"))
        self.assertEqual(arama["onbellek"]["sha256"], retrieval.sha256_file(cache))
        self.assertNotIn("vektorler", arama["onbellek"])
        (record,) = read_records(run_dir)
        self.assertEqual(len(record["arama_sonuclari"]), 2)

    def test_manual_runs_record_manual_selection(self) -> None:
        workspace = make_workspace(real_case_lines(["C01"]))
        with FakeOllama([{"kind": "ok"}]) as fake:
            code, output = run_main(workspace, fake, ["--mode", "A"])
        self.assertEqual(code, 0, output)
        run_dir = latest_run_dir(workspace)
        (record,) = read_records(run_dir)
        self.assertEqual(record["kaynak_secimi"], "elle")
        self.assertIsNone(record["arama_sonuclari"])
        self.assertIsNone(record["arama_suresi_s"])
        meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
        self.assertEqual((meta["kaynak_secimi"], meta["arama"]), ("elle", None))

    def test_top_k_rejected_without_retrieval(self) -> None:
        workspace = make_workspace(real_case_lines(["C01"]))
        with FakeOllama([{"kind": "ok"}]) as fake:
            code, output = run_main(workspace, fake, ["--mode", "A", "--top-k", "2"])
        self.assertEqual(code, 2)
        self.assertIn("--top-k", output)

    def test_retrieval_flag_rejected_in_a_mode(self) -> None:
        workspace = make_workspace(real_case_lines(["C01"]))
        with FakeOllama([{"kind": "ok"}]) as fake:
            code, output = run_main(workspace, fake, ["--mode", "A", "--retrieval"])
        self.assertEqual(code, 2)
        self.assertIn("--mode B", output)
        self.assertFalse((workspace / "results").exists())

    def test_stale_cache_stops_b_before_results(self) -> None:
        workspace, embedder, cache = self._workspace(["C01"])
        docs = workspace / "docs.json"
        docs.write_text(docs.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        code, output = self._run(workspace, embedder, cache, ["--mode", "B"])
        self.assertEqual(code, 2)
        self.assertIn(retrieval.BUILD_HINT, output)
        self.assertFalse((workspace / "results").exists())


class MissingPackageTest(unittest.TestCase):
    """sentence-transformers yokken: A ve C calisir, B acik hatayla (2) durur."""

    def setUp(self) -> None:
        # None degeri, `import sentence_transformers` icin ImportError uretir.
        patcher = mock.patch.dict(sys.modules, {"sentence_transformers": None})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_load_embedder_raises_with_install_hint(self) -> None:
        with self.assertRaises(retrieval.RetrievalError) as ctx:
            retrieval.load_embedder()
        self.assertIn(retrieval.INSTALL_HINT, str(ctx.exception))

    def test_b_mode_fails_clearly(self) -> None:
        workspace = make_workspace(real_case_lines(["C01"]))
        with FakeOllama([{"kind": "ok"}]) as fake:
            code, output = run_main(workspace, fake, ["--mode", "B"])
        self.assertEqual(code, 2)
        self.assertIn("sentence-transformers", output)
        self.assertIn("pip install -r requirements.txt", output)
        self.assertFalse((workspace / "results").exists())

    def test_a_and_c_modes_still_run(self) -> None:
        workspace = make_workspace(real_case_lines(["C01"]))
        with FakeOllama([{"kind": "ok"}]) as fake:
            self.assertEqual(run_main(workspace, fake, ["--mode", "A"])[0], 0)
            self.assertEqual(run_main(workspace, fake, ["--no-warmup"])[0], 0)
        self.assertNotIn("sentence_transformers", [m for m, v in sys.modules.items() if v is not None])


# --------------------------------------------------------------------------
# Metrikler (elle dogrulanabilir kucuk girdiler)
# --------------------------------------------------------------------------


def _record(cid: str, found: list[str], used: list[str] | None = None,
            elenen: dict | None = None, manual: list[str] | None = None) -> dict:
    return {
        "case_id": cid, "ok": True, "kaynak_secimi": "arama", "source_ids": manual or [],
        "arama_sonuclari": [{"source_id": s, "skor": 1.0 - i / 10} for i, s in enumerate(found)],
        "kullanilan_kaynaklar": used if used is not None else found,
        "elenen_kaynaklar": elenen or {},
    }


class MetricTest(unittest.TestCase):
    def test_case_metrics_by_hand(self) -> None:
        m = retrieval_metrics.case_metrics(["D2", "D1", "D3"], ["D1"], 3)
        self.assertEqual((m["isabet"], m["ilk_dogru_sira"], m["rr"], m["hepsi_bulundu"]),
                         (1, 2, 0.5, True))
        m = retrieval_metrics.case_metrics(["D2", "D3", "D4", "D1"], ["D1"], 3)  # 4. sira sayilmaz
        self.assertEqual((m["isabet"], m["ilk_dogru_sira"], m["rr"]), (0, None, 0.0))
        m = retrieval_metrics.case_metrics(["D6", "D2", "D7"], ["D6", "D7"], 3)
        self.assertEqual((m["isabet"], m["ilk_dogru_sira"], m["rr"]), (2, 1, 1.0))

    def test_run_metrics_by_hand(self) -> None:
        records = {
            "C01": _record("C01", ["D1", "D3", "D7"]),               # RR 1, 1 isabet
            "C02": _record("C02", ["D4", "D1", "D5"], ["D1", "D5"],  # RR 1/2
                           {"D4": "surum_uyusmazligi"}),
            "C03": _record("C03", ["D2", "D3", "D8"]),               # isabet yok, RR 0
            "C10": _record("C10", ["D1", "D2", "D3"]),               # gerekli tanimsiz
        }
        expected = {"C01": {"gerekli_kaynaklar": ["D1"]}, "C02": {"gerekli_kaynaklar": ["D1"]},
                    "C03": {"gerekli_kaynaklar": ["D1"]}, "C10": {"gerekli_kaynaklar": []}}
        m = retrieval_metrics.run_metrics(records, expected, 3)
        self.assertEqual((m["vaka"], m["isabet"], m["gerekli"]), (3, 2, 3))   # Recall@3 = 2/3
        self.assertEqual((m["isabet"], m["sonuc_sayisi"]), (2, 9))           # Precision@3 = 2/9
        self.assertAlmostEqual(m["mrr"], (1 + 0.5 + 0) / 3)
        self.assertEqual(m["hepsi_bulunan_vaka"], 2)
        self.assertEqual(m["gerekli_tanimsiz"], ["C10"])
        self.assertEqual((m["elenen_toplam"], m["aranan_toplam"]), (1, 12))
        self.assertEqual(m["elenen_gerekli"], {})

    def test_eliminated_required_source_is_reported(self) -> None:
        records = {"C11": _record("C11", ["D2", "D6", "D7"], ["D2", "D6"],
                                  {"D7": "yururluk_baslamamis"})}
        m = retrieval_metrics.run_metrics(records, {"C11": {"gerekli_kaynaklar": ["D7"]}}, 3)
        self.assertEqual(m["elenen_gerekli"], {"C11": ["D7"]})
        self.assertEqual(m["isabet"], 1)  # arama buldu; filtre eledi

    def test_manual_runs_are_not_applicable(self) -> None:
        records = {"C01": {"case_id": "C01", "kaynak_secimi": "elle", "arama_sonuclari": None}}
        old = {"C01": {"case_id": "C01"}}  # eski kosu: alan hic yok
        for recs in (records, old):
            self.assertIsNone(retrieval_metrics.run_metrics(recs, {"C01": {"gerekli_kaynaklar": ["D1"]}}, 3))
            self.assertIsNone(retrieval_metrics.error_split(recs, {}, {}))

    def test_error_split_two_by_two(self) -> None:
        records = {
            "C01": _record("C01", ["D1", "D2", "D3"]),
            "C02": _record("C02", ["D1", "D2", "D3"]),
            "C03": _record("C03", ["D2", "D3", "D4"]),
            "C11": _record("C11", ["D2", "D6", "D7"], ["D2", "D6"], {"D7": "yururluk_baslamamis"}),
        }
        expected = {"C01": {"gerekli_kaynaklar": ["D1"]}, "C02": {"gerekli_kaynaklar": ["D1"]},
                    "C03": {"gerekli_kaynaklar": ["D1"]}, "C11": {"gerekli_kaynaklar": ["D7"]}}
        per_case = {
            "C01": {"durum_dogru": True, "gerekli_kaynak_tamam": True},
            "C02": {"durum_dogru": False, "gerekli_kaynak_tamam": True},
            "C03": {"durum_dogru": True, "gerekli_kaynak_tamam": False},
            "C11": {"durum_dogru": True, "gerekli_kaynak_tamam": False},
        }
        cells = retrieval_metrics.error_split(records, expected, per_case)
        self.assertEqual(cells, {"bulundu_dogru": ["C01"], "bulundu_yanlis": ["C02"],
                                 "bulunamadi_dogru": [], "bulunamadi_yanlis": ["C03", "C11"],
                                 "olculemedi": []})

    def test_error_split_does_not_count_unmeasured_as_generation_error(self) -> None:
        records = {"C01": {**_record("C01", ["D1", "D2", "D3"]), "ok": False},
                   "C02": _record("C02", ["D1", "D2", "D3"])}
        expected = {"C01": {"gerekli_kaynaklar": ["D1"]}, "C02": {"gerekli_kaynaklar": ["D1"]}}
        per_case = {"C01": {"durum_dogru": False, "gerekli_kaynak_tamam": False},
                    "C02": {"durum_dogru": None, "gerekli_kaynak_tamam": True}}
        cells = retrieval_metrics.error_split(records, expected, per_case)
        self.assertEqual(cells["olculemedi"], ["C01", "C02"])
        self.assertEqual(cells["bulundu_yanlis"], [])

    def test_search_record_without_results_is_an_error_not_zero(self) -> None:
        records = {"C01": {"case_id": "C01", "kaynak_secimi": "arama", "arama_sonuclari": None}}
        with self.assertRaises(ValueError):
            retrieval_metrics.run_metrics(records, {"C01": {"gerekli_kaynaklar": ["D1"]}}, 3)

    def test_report_marks_manual_run_not_applicable(self) -> None:
        manual = {"run_id": "a", "mode": "A", "mode_note": None, "run_state": "tamamlandi",
                  "motor": True, "kaynak_secimi": "elle", "top_k": None,
                  "records": {"C01": {"case_id": "C01", "ok": True, "content": "Kaynaklar: D1",
                                      "kaynak_secimi": "elle"}}}
        searched = dict(manual, run_id="c", mode="C", kaynak_secimi="arama", top_k=3,
                        records={"C01": {**_record("C01", ["D1", "D2", "D3"]), "ok": True,
                                         "content": "Kaynaklar: D1"}})
        expected = {"C01": {"gerekli_kaynaklar": ["D1"]}}
        report = run_eval.render_report(
            [run_eval.evaluate_run(manual, expected), run_eval.evaluate_run(searched, expected)],
            expected,
        )
        self.assertIn("| Arama Recall@k (gerekli kaynak ilk k sonuçta) | uygulanamaz (arama "
                      "yapılmadı) | 1'de 1 (k=3) |", report)
        self.assertIn("C-arama", report)
        self.assertIn("Arama / üretim hata ayrımı — C-arama", report)


# --------------------------------------------------------------------------
# Gercek embedding modeli (CI'da atlanir)
# --------------------------------------------------------------------------


def _real_model_available() -> bool:
    if importlib.util.find_spec("sentence_transformers") is None:
        return False
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(retrieval.EMBEDDING_MODEL, local_files_only=True)
    except Exception:  # noqa: BLE001
        return False
    return True


@unittest.skipUnless(_real_model_available(), "sentence-transformers veya yerel e5 modeli yok")
class RealModelTest(unittest.TestCase):
    """Gercek model: yalnizca teknik ozellikler (boyut, normalizasyon, onek etkisi,
    depodaki onbellegin bu modelle uyumu). Arama kalitesi burada iddia edilmez."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.embedder = retrieval.load_embedder()

    def test_dimension_and_prefix_effect(self) -> None:
        with_prefix, without = self.embedder.encode(["query: 429 aldik", "429 aldik"])
        self.assertEqual(len(with_prefix), 384)
        self.assertLess(retrieval.cosine(retrieval.normalize(with_prefix),
                                         retrieval.normalize(without)), 0.9999)

    def test_repo_cache_matches_model(self) -> None:
        docs = EXPERIMENT_DIR / "docs.json"
        sources = _sources(docs)
        cache = retrieval.load_cache(retrieval.DEFAULT_CACHE, docs, sources)
        fresh = retrieval.build_cache(sources, docs, self.embedder)
        for sid in sources:
            self.assertGreater(retrieval.cosine(cache["vektorler"][sid], fresh["vektorler"][sid]), 0.9999)


if __name__ == "__main__":
    unittest.main()
