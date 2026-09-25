"""HTTP servis katmani (api.py) testleri.

fastapi ve httpx (requirements-api.txt) kurulu degilse atlanir; standart
kutuphaneyle calisan test isi bu dosyayi atlar, API isi calistirir. Gercek model
kullanilmaz: C modu sahte Ollama servisine karsi calisir.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = TESTS_DIR.parent
for _path in (EXPERIMENT_DIR, TESTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

HAS_API_DEPS = all(importlib.util.find_spec(m) for m in ("fastapi", "httpx"))

if HAS_API_DEPS:
    from fastapi.testclient import TestClient

    import api
    import run

from fake_ollama import FakeOllama  # noqa: E402
from test_masking import SECRETS, secret_case  # noqa: E402


def _dead_host() -> str:
    """Dinleyen sunucusu olmayan yerel adres (baglanti reddedilir)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"


def _case(**overrides) -> dict:
    case = json.loads((EXPERIMENT_DIR / "cases.jsonl").read_text(encoding="utf-8").splitlines()[0])
    case.update(overrides)
    return case


@unittest.skipUnless(HAS_API_DEPS, "fastapi/httpx kurulu degil (requirements-api.txt)")
class ApiTestBase(unittest.TestCase):
    def client(self, host: str | None = None, timeout: int = 5, workdir: Path | None = None) -> "TestClient":
        kwargs = {}
        if workdir is not None:
            kwargs.update(docs_path=workdir / "docs.json", prompt_path=workdir / "prompt.txt",
                          cases_path=workdir / "cases.jsonl")
        settings = api.Settings(ollama_host=host or _dead_host(), model="sahte-model:test",
                                model_timeout_s=timeout, **kwargs)
        return TestClient(api.create_app(settings), raise_server_exceptions=False)


class HealthTest(ApiTestBase):
    def test_health_probes_ollama_and_sources(self) -> None:
        with FakeOllama([{"kind": "ok"}]) as fake:
            resp = self.client(fake.url).get("/health")
            probed = list(fake.all_requests)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["bilesenler"]["ollama"]["durum"], "ok")
        self.assertEqual(body["bilesenler"]["ollama"]["surum"], "0.0.0-test")
        self.assertEqual(body["bilesenler"]["kaynak_verisi"]["kaynak_sayisi"], 8)
        self.assertIn(("GET", "/api/version"), probed)
        self.assertIn(("GET", "/api/tags"), probed)
        self.assertIn(body["bilesenler"]["arama"]["durum"], ("ok", "paket_yok", "onbellek_gecersiz"))

    def test_health_reports_unreachable_ollama_as_partial(self) -> None:
        body = self.client(_dead_host()).get("/health").json()
        self.assertEqual(body["bilesenler"]["ollama"]["durum"], "erisilemez")
        self.assertEqual(body["durum"], "kismi")

    def test_health_detects_changed_source_data(self) -> None:
        work = Path(tempfile.mkdtemp(prefix="destekizi_api_"))
        self.addCleanup(shutil.rmtree, work, True)
        for name in ("docs.json", "prompt.txt", "cases.jsonl"):
            shutil.copy2(EXPERIMENT_DIR / name, work / name)
        client = self.client(workdir=work)
        docs = work / "docs.json"
        docs.write_text(docs.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        resp = client.get("/health")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["bilesenler"]["kaynak_verisi"]["durum"], "degisti")


class ValidationTest(ApiTestBase):
    def test_invalid_inputs_get_422(self) -> None:
        client = self.client()
        bad = [
            {"mod": "X", "case_id": "C01"},
            {"mod": "A"},  # ne vaka ne case_id
            {"mod": "A", "case_id": "C01", "vaka": _case()},  # ikisi birden
            {"mod": "A", "vaka": _case(ticket="")},
            {"mod": "A", "vaka": _case(ticket="x" * (api.MAX_TICKET_CHARS + 1))},
            {"mod": "A", "vaka": _case(request={"blob": "x" * (api.MAX_RECORD_BYTES + 1)})},
            {"mod": "A", "vaka": _case(source_ids=[])},  # A elle kaynak ister
            {"mod": "A", "vaka": _case(api_version="V2")},
            {"mod": "A", "vaka": _case(olay_tarihi="2026-02-30")},
            {"mod": "A", "vaka": _case(beklenmeyen_alan=1)},
            {"mod": "B", "case_id": "C01", "top_k": 0},
        ]
        for body in bad:
            with self.subTest(body=str(body)[:80]):
                self.assertEqual(client.post("/v1/analyses", json=body).status_code, 422)

    def test_unknown_source_and_case_get_404(self) -> None:
        client = self.client()
        self.assertEqual(client.get("/v1/sources/D99").status_code, 404)
        self.assertEqual(client.post("/v1/analyses", json={"mod": "A", "case_id": "C99"}).status_code, 404)
        resp = client.post("/v1/analyses", json={"mod": "A", "vaka": _case(source_ids=["D1", "D99"])})
        self.assertEqual(resp.status_code, 404)
        self.assertIn("D99", resp.json()["detail"])

    def test_get_source(self) -> None:
        body = self.client().get("/v1/sources/D4").json()
        self.assertEqual(body["source_id"], "D4")
        self.assertEqual(body["api_versions"], ["v1"])
        self.assertIn("X-Api-Key", body["text"])


class ModelErrorTest(ApiTestBase):
    def test_unreachable_model_gets_503(self) -> None:
        resp = self.client(_dead_host()).post("/v1/analyses", json={"mod": "C", "case_id": "C01"})
        self.assertEqual(resp.status_code, 503)
        self.assertIn("Yerel model kullanilamiyor", resp.json()["detail"])

    def test_model_timeout_gets_504(self) -> None:
        with FakeOllama([{"kind": "hang", "seconds": 3}]) as fake:
            resp = self.client(fake.url, timeout=1).post("/v1/analyses", json={"mod": "C", "case_id": "C01"})
        self.assertEqual(resp.status_code, 504)

    def test_truncated_answer_is_not_success(self) -> None:
        with FakeOllama([{"kind": "length"}]) as fake:
            resp = self.client(fake.url).post("/v1/analyses", json={"mod": "C", "case_id": "C01"})
        self.assertEqual(resp.status_code, 502)
        self.assertIn("truncated_length", resp.json()["detail"])

    def test_unexpected_error_hides_internals(self) -> None:
        client = self.client()
        with mock.patch.object(run, "analyze_case", side_effect=RuntimeError("IC_AYRINTI C:/gizli/yol")), \
                self.assertLogs("destekizi.api", level="ERROR") as logs:
            resp = client.post("/v1/analyses", json={"mod": "A", "case_id": "C01"})
        self.assertEqual(resp.status_code, 500)
        self.assertNotIn("IC_AYRINTI", resp.text)
        self.assertNotIn("Traceback", resp.text)
        self.assertIn("hata_kimligi", resp.json())
        self.assertIn("IC_AYRINTI", "\n".join(logs.output))  # loglandi


class AnalysisTest(ApiTestBase):
    def test_c_mode_end_to_end_with_fake_model(self) -> None:
        with FakeOllama([{"kind": "ok", "content": "Bulgular: x\nKaynaklar: D1"}]) as fake:
            resp = self.client(fake.url).post("/v1/analyses", json={"mod": "C", "case_id": "C01"})
            sent = fake.chat_requests[-1]
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual((body["case_id"], body["mod"], body["ok"]), ("C01", "C", True))
        self.assertEqual(body["content"], "Bulgular: x\nKaynaklar: D1")
        self.assertEqual(body["messages"], sent["messages"])
        self.assertEqual(body["kaynak_secimi"], "elle")
        self.assertEqual(body["maskelenen_alanlar"], [])

    def test_response_matches_case_record(self) -> None:
        # Cikti sozlesmesi: kayittaki analiz sonucunun aynisi (zaman alanlari haric).
        resp = self.client().post("/v1/analyses", json={"mod": "A", "case_id": "C14"})
        self.assertEqual(resp.status_code, 200, resp.text)
        case = run.load_cases(EXPERIMENT_DIR / "cases.jsonl")[13]
        expected = run.analyze_case(
            case, mode="A", sources=run.load_sources(EXPERIMENT_DIR / "docs.json"), system_prompt="",
            retriever=None, applicability_on=True, host="", model="", options={}, timeout=1,
        )
        got = resp.json()
        for key in ("started_at_utc", "client_elapsed_s"):
            got.pop(key), expected.pop(key)
        self.assertEqual(got, json.loads(json.dumps(expected, ensure_ascii=False)))

    def test_body_case_without_event_date_keeps_runner_semantics(self) -> None:
        resp = self.client().post("/v1/analyses", json={"mod": "A", "vaka": _case()})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIsNone(resp.json()["olay_tarihi"])

    def test_secret_not_in_response(self) -> None:
        with FakeOllama([{"kind": "ok"}]) as fake:
            resp = self.client(fake.url).post("/v1/analyses", json={"mod": "C", "vaka": secret_case()})
            sent = json.dumps(fake.chat_requests, ensure_ascii=False)
        self.assertEqual(resp.status_code, 200, resp.text)
        for secret in SECRETS:
            self.assertNotIn(secret, resp.text)
            self.assertNotIn(secret, sent)
        self.assertIn("request.headers.Authorization", resp.json()["maskelenen_alanlar"])

    def test_b_mode_without_search_dependency_gets_503(self) -> None:
        with mock.patch.object(api.retrieval, "load_embedder",
                               side_effect=api.retrieval.RetrievalError("paket yok")):
            resp = self.client().post("/v1/analyses", json={"mod": "B", "case_id": "C01"})
        self.assertEqual(resp.status_code, 503)
        self.assertIn("Arama kullanilamiyor", resp.json()["detail"])


if __name__ == "__main__":
    unittest.main()
