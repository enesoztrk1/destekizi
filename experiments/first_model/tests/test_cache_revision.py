"""Embedding onbelleginin model revizyonu kontrolu (sahte embedding; gercek model gerekmez)."""

from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
for _path in (TESTS_DIR.parent, TESTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import retrieval  # noqa: E402
from test_retrieval import FakeEmbedder, _sources  # noqa: E402
from test_runner import latest_run_dir, make_workspace, real_case_lines, run_main  # noqa: E402
from fake_ollama import FakeOllama  # noqa: E402

REV_A = "a" * 40
REV_B = "b" * 40


class CheckRevisionTest(unittest.TestCase):
    def test_same_revision_passes(self) -> None:
        self.assertEqual(retrieval.check_revision(REV_A, REV_A), "eslesti")

    def test_different_revision_raises_with_build_hint(self) -> None:
        with self.assertRaises(retrieval.RetrievalError) as ctx:
            retrieval.check_revision(REV_A, REV_B)
        self.assertIn("revizyon", str(ctx.exception))
        self.assertIn(retrieval.BUILD_HINT, str(ctx.exception))

    def test_unknown_revision_warns_and_continues(self) -> None:
        for cached, loaded, side in ((None, REV_A, "onbellek"), (REV_A, None, "yuklenen model"),
                                     (None, None, "onbellek")):
            err = io.StringIO()
            with redirect_stderr(err):
                state = retrieval.check_revision(cached, loaded)
            self.assertEqual(state, f"dogrulanamadi: {side} revizyonu bilinmiyor")
            self.assertIn("UYARI", err.getvalue())


class RevisionFlowTest(unittest.TestCase):
    """Calistirici uzerinden: uyusmazlikta sonuc dizini acilmadan cikis 2."""

    def _setup(self, cache_revision: str | None):
        workspace = make_workspace(real_case_lines(["C01"]))
        docs = workspace / "docs.json"
        embedder = FakeEmbedder(_sources(docs))
        with mock.patch.object(retrieval, "_model_revision", return_value=cache_revision):
            cache = retrieval.build_cache(_sources(docs), docs, embedder)
        path = workspace / "embeddings.json"
        path.write_text(json.dumps(cache), encoding="utf-8")
        return workspace, embedder, path

    def _run(self, workspace: Path, embedder, cache: Path, loaded_revision: str | None):
        with mock.patch.object(retrieval, "load_embedder", return_value=embedder), \
                mock.patch.object(retrieval, "_model_revision", return_value=loaded_revision), \
                FakeOllama([{"kind": "ok"}]) as fake:
            return run_main(workspace, fake, ["--mode", "B", "--embeddings", str(cache)])

    def test_mismatched_revision_stops_before_results(self) -> None:
        workspace, embedder, cache = self._setup(REV_A)
        code, output = self._run(workspace, embedder, cache, REV_B)
        self.assertEqual(code, 2)
        self.assertIn(retrieval.BUILD_HINT, output)
        self.assertFalse((workspace / "results").exists())

    def test_matching_revision_recorded(self) -> None:
        workspace, embedder, cache = self._setup(REV_A)
        code, output = self._run(workspace, embedder, cache, REV_A)
        self.assertEqual(code, 0, output)
        meta = json.loads((latest_run_dir(workspace) / "run_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["arama"]["revizyon_kontrolu"], "eslesti")

    def test_missing_revision_warns_and_runs(self) -> None:
        workspace, embedder, cache = self._setup(None)
        code, output = self._run(workspace, embedder, cache, REV_A)
        self.assertEqual(code, 0, output)
        self.assertIn("UYARI", output)
        meta = json.loads((latest_run_dir(workspace) / "run_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["arama"]["revizyon_kontrolu"], "dogrulanamadi: onbellek revizyonu bilinmiyor")


if __name__ == "__main__":
    unittest.main()
