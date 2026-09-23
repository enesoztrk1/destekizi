"""Calistirici davranis testleri.

Kapsam: istek govdesine ne girdigi, cevap anahtarinin okunmamasi, normal/kesik
yanit ayrimi, bozuk JSON ve zaman asiminin acik hata kaydina donmesi.

ONEMLI: Bu testler sahte bir HTTP servisine karsi calisir. Gectiklerinde
gercek modelin cevap kalitesi hakkinda HICBIR sey kanitlamazlar.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

EXPERIMENT_DIR = Path(__file__).resolve().parents[1]
if str(EXPERIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_DIR))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import run  # noqa: E402
from fake_ollama import FakeOllama  # noqa: E402

# Cevap anahtarinin sizip sizmadigini anlamak icin kullanilan benzersiz isaret.
SENTINEL = "SENTINEL_CEVAP_ANAHTARI_7F3A9C"

# Kaynak metinlerinde yalnizca o kaynakta gecen ayirt edici ifadeler.
SOURCE_MARKERS = {
    "D1": "DEMO_TOKEN_EXPIRED",
    "D2": "DEMO_RATE_LIMIT",
    "D3": "next_cursor",
}

# --------------------------------------------------------------------------
# Gercek cevap anahtari yoluna acma girisimini yakalayan denetim (audit hook).
# Etkinken hedef dosyanin acilmasini ENGELLER (PermissionError) ve kaydeder;
# boylece test sirasinda anahtarin icerigi okunmaz. Yalnizca bu yolu izler;
# yeniden adlandirilmis kopyalari yakalamaz.
# --------------------------------------------------------------------------

REAL_ANSWER_KEY = os.path.normcase(str((EXPERIMENT_DIR / "expected.jsonl").resolve()))
_GUARD: dict = {"active": False, "hits": []}


def _answer_key_audit(event: str, args: tuple) -> None:
    if event != "open" or not _GUARD["active"] or not args:
        return
    target = args[0]
    if target is None or isinstance(target, int):
        return
    try:
        opened = os.path.normcase(os.path.abspath(os.fsdecode(os.fspath(target))))
    except (TypeError, ValueError):
        return
    if opened == REAL_ANSWER_KEY:
        _GUARD["hits"].append(opened)
        raise PermissionError(f"test denetimi: cevap anahtari acma girisimi engellendi: {opened}")


sys.addaudithook(_answer_key_audit)


@contextmanager
def answer_key_guard():
    hits: list[str] = []
    _GUARD["hits"] = hits
    _GUARD["active"] = True
    try:
        yield hits
    finally:
        _GUARD["active"] = False


def make_workspace(case_lines: list[str] | None = None, write_expected: bool = True) -> Path:
    """Gercek prompt/docs dosyalarini gecici bir calisma alanina kopyalar."""
    tmp = Path(tempfile.mkdtemp(prefix="destekizi_test_"))
    shutil.copy2(EXPERIMENT_DIR / "prompt.txt", tmp / "prompt.txt")
    shutil.copy2(EXPERIMENT_DIR / "docs.json", tmp / "docs.json")

    if case_lines is None:
        shutil.copy2(EXPERIMENT_DIR / "cases.jsonl", tmp / "cases.jsonl")
    else:
        (tmp / "cases.jsonl").write_text("\n".join(case_lines) + "\n", encoding="utf-8")

    if write_expected:
        # Gercek anahtarin yerine izlenebilir bir isaret koyuyoruz.
        (tmp / "expected.jsonl").write_text(
            json.dumps({"case_id": "C01", "beklenen": SENTINEL}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return tmp


def real_case_lines(case_ids: list[str]) -> list[str]:
    lines = []
    for line in (EXPERIMENT_DIR / "cases.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip() and json.loads(line)["case_id"] in case_ids:
            lines.append(line)
    return lines


def run_main(workspace: Path, fake: FakeOllama, extra: list[str] | None = None) -> tuple[int, str]:
    argv = [
        "--host", fake.url,
        "--model", fake.model,
        "--prompt", str(workspace / "prompt.txt"),
        "--docs", str(workspace / "docs.json"),
        "--cases", str(workspace / "cases.jsonl"),
        "--results-root", str(workspace / "results"),
        "--timeout", "2",
    ]
    argv.extend(extra or [])
    buffer = io.StringIO()
    with redirect_stdout(buffer), redirect_stderr(buffer):
        code = run.main(argv)
    return code, buffer.getvalue()


def latest_run_dir(workspace: Path) -> Path:
    dirs = sorted((workspace / "results").iterdir())
    assert dirs, "sonuc dizini olusmadi"
    return dirs[-1]


def _reject_constant(name: str):
    raise ValueError(f"standart disi JSON sayisi: {name}")


def _finite_float(text: str) -> float:
    value = float(text)
    if value in (float("inf"), float("-inf")):
        raise ValueError(f"sonsuza tasan JSON sayisi: {text}")
    return value


def strict_json_loads(text: str):
    """Testlerin bagimsiz katı okuyucusu: NaN/Infinity/-Infinity ve tasmayi reddeder."""
    return json.loads(text, parse_constant=_reject_constant, parse_float=_finite_float)


def read_records(run_dir: Path) -> list[dict]:
    text = (run_dir / "cases.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


class RequestContentTest(unittest.TestCase):
    """Istek govdesine yalnizca ilgili vaka ve secilen kaynaklar girmeli."""

    def test_only_selected_sources_reach_the_model(self) -> None:
        workspace = make_workspace(real_case_lines(["C03", "C04"]))
        self.addCleanup(shutil.rmtree, workspace, True)

        with FakeOllama([{"kind": "ok"}]) as fake:
            code, _ = run_main(workspace, fake, ["--no-warmup"])
        self.assertEqual(code, 0)
        self.assertEqual(len(fake.chat_requests), 2)

        # C03 yalnizca D1 kullanir.
        body_c03 = json.dumps(fake.chat_requests[0], ensure_ascii=False)
        self.assertIn(SOURCE_MARKERS["D1"], body_c03)
        self.assertNotIn(SOURCE_MARKERS["D2"], body_c03)
        self.assertNotIn(SOURCE_MARKERS["D3"], body_c03)
        self.assertIn("DEMO_SCOPE_MISSING", body_c03)

        # C04 yalnizca D2 kullanir.
        body_c04 = json.dumps(fake.chat_requests[1], ensure_ascii=False)
        self.assertIn(SOURCE_MARKERS["D2"], body_c04)
        self.assertNotIn(SOURCE_MARKERS["D1"], body_c04)
        self.assertNotIn(SOURCE_MARKERS["D3"], body_c04)

        # Onceki vakanin verisi sonraki isteğe tasinmamali.
        self.assertNotIn("C03", body_c04)

    def test_each_case_starts_with_a_fresh_message_list(self) -> None:
        workspace = make_workspace(real_case_lines(["C01", "C02"]))
        self.addCleanup(shutil.rmtree, workspace, True)

        with FakeOllama([{"kind": "ok", "content": "ONCEKI_CEVAP_IZI"}]) as fake:
            code, _ = run_main(workspace, fake, ["--no-warmup"])
        self.assertEqual(code, 0)

        for request_body in fake.chat_requests:
            messages = request_body["messages"]
            self.assertEqual(len(messages), 2)
            self.assertEqual([m["role"] for m in messages], ["system", "user"])
            self.assertNotIn("ONCEKI_CEVAP_IZI", json.dumps(request_body, ensure_ascii=False))

    def test_unknown_source_id_stops_before_any_request(self) -> None:
        bad_case = json.dumps(
            {
                "case_id": "CXX",
                "ticket": "test",
                "platform": "DemoCommerce",
                "environment": "test",
                "api_version": "v2",
                "request": {},
                "response": {},
                "source_ids": ["D9"],
            },
            ensure_ascii=False,
        )
        workspace = make_workspace([bad_case])
        self.addCleanup(shutil.rmtree, workspace, True)

        with FakeOllama([{"kind": "ok"}]) as fake:
            code, output = run_main(workspace, fake)

        self.assertEqual(code, 2)
        self.assertIn("D9", output)
        self.assertEqual(fake.chat_requests, [], "hatali kaynakla modele istek gonderilmemeli")


class AnswerKeyIsolationTest(unittest.TestCase):
    """expected.jsonl uretim yoluna hicbir sekilde girmemeli."""

    def test_answer_key_never_reaches_request_or_results(self) -> None:
        workspace = make_workspace(real_case_lines(["C01", "C05"]))
        self.addCleanup(shutil.rmtree, workspace, True)
        self.assertIn(SENTINEL, (workspace / "expected.jsonl").read_text(encoding="utf-8"))

        with FakeOllama([{"kind": "ok"}]) as fake:
            code, output = run_main(workspace, fake, ["--no-warmup"])
        self.assertEqual(code, 0)

        self.assertNotIn(SENTINEL, json.dumps(fake.chat_requests, ensure_ascii=False))
        self.assertNotIn(SENTINEL, output)

        run_dir = latest_run_dir(workspace)
        for path in run_dir.iterdir():
            self.assertNotIn(SENTINEL, path.read_text(encoding="utf-8"), f"{path.name} sizdirdi")

    def test_run_succeeds_even_if_answer_key_is_absent(self) -> None:
        workspace = make_workspace(real_case_lines(["C01"]), write_expected=False)
        self.addCleanup(shutil.rmtree, workspace, True)
        self.assertFalse((workspace / "expected.jsonl").exists())

        with FakeOllama([{"kind": "ok"}]) as fake:
            code, _ = run_main(workspace, fake, ["--no-warmup"])
        self.assertEqual(code, 0)

    def test_read_text_refuses_the_answer_key(self) -> None:
        with self.assertRaises(run.ExperimentError):
            run.read_text(EXPERIMENT_DIR / "expected.jsonl")

    def test_audit_guard_catches_a_deliberate_open_attempt(self) -> None:
        # Denetimin kendisi calisiyor mu? Kasitli girisim engellenmeli ve kaydedilmeli.
        with answer_key_guard() as hits:
            with self.assertRaises(PermissionError):
                with open(EXPERIMENT_DIR / "expected.jsonl", "rb"):
                    pass
            with self.assertRaises(PermissionError):
                (EXPERIMENT_DIR / "expected.jsonl").read_bytes()
        self.assertEqual(len(hits), 2)

    def test_full_run_with_default_paths_never_opens_the_real_answer_key(self) -> None:
        results_root = Path(tempfile.mkdtemp(prefix="destekizi_test_"))
        self.addCleanup(shutil.rmtree, results_root, True)

        with answer_key_guard() as hits, FakeOllama([{"kind": "ok"}]) as fake:
            buffer = io.StringIO()
            with redirect_stdout(buffer), redirect_stderr(buffer):
                code = run.main(
                    ["--host", fake.url, "--model", fake.model,
                     "--results-root", str(results_root), "--timeout", "2"]
                )
        self.assertEqual(code, 0, buffer.getvalue())
        self.assertEqual(hits, [], "calistirici gercek cevap anahtarini acmaya calisti")
        self.assertEqual(len(fake.chat_requests), 11)  # isinma + 10 vaka

    def test_answer_key_passed_as_input_stops_before_any_request(self) -> None:
        workspace = make_workspace(real_case_lines(["C01"]))
        self.addCleanup(shutil.rmtree, workspace, True)

        with FakeOllama([{"kind": "ok"}]) as fake:
            code, output = run_main(
                workspace, fake, ["--cases", str(workspace / "expected.jsonl")]
            )
        self.assertEqual(code, 2)
        self.assertIn("Cevap anahtari", output)
        self.assertEqual(fake.chat_requests, [])
        self.assertFalse((workspace / "results").exists())

    def test_hard_link_to_answer_key_is_refused(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="destekizi_test_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        fake_key = tmp / "anahtar_kaynagi.jsonl"
        fake_key.write_text("{}\n", encoding="utf-8")

        link = tmp / "baska_ad.jsonl"
        try:
            os.link(fake_key, link)
        except OSError as exc:
            self.skipTest(f"hard link olusturulamadi: {exc}")
        with mock.patch.object(run, "ANSWER_KEY_PATH", fake_key):
            with self.assertRaisesRegex(run.ExperimentError, "Cevap anahtari"):
                run.read_text(link)
            with self.assertRaisesRegex(run.ExperimentError, "Cevap anahtari"):
                run.sha256_file(link)

    def test_case_variant_name_is_refused(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="destekizi_test_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        variant = tmp / "Expected.JSONL"
        variant.write_text("{}\n", encoding="utf-8")  # var olan dosya: ret sebebi ad olmali

        with self.assertRaisesRegex(run.ExperimentError, "Cevap anahtari"):
            run.read_text(variant)

    def test_identity_check_error_fails_closed(self) -> None:
        with mock.patch.object(run.os.path, "samefile", side_effect=OSError("erisim yok")):
            with self.assertRaises(run.ExperimentError):
                run.read_text(EXPERIMENT_DIR / "prompt.txt")


class FailureClassificationTest(unittest.TestCase):
    """Normal yanit, kesik yanit ve hata durumlari birbirine karismamali."""

    def test_normal_and_length_truncated_answers_are_separated(self) -> None:
        workspace = make_workspace(real_case_lines(["C01", "C02"]))
        self.addCleanup(shutil.rmtree, workspace, True)

        behaviors = [{"kind": "ok", "content": "Bulgular: ...\nKaynaklar: D1"}, {"kind": "length"}]
        with FakeOllama(behaviors) as fake:
            code, _ = run_main(workspace, fake, ["--no-warmup"])
        self.assertEqual(code, 0)

        run_dir = latest_run_dir(workspace)
        records = read_records(run_dir)

        self.assertTrue(records[0]["ok"])
        self.assertIsNone(records[0]["failure_kind"])
        self.assertEqual(records[0]["done_reason"], "stop")
        # Nanosaniye -> saniye donusumu
        self.assertEqual(records[0]["metrics"]["total_duration_s"], 2.5)
        self.assertEqual(records[0]["metrics"]["load_duration_s"], 1.0)

        self.assertFalse(records[1]["ok"])
        self.assertEqual(records[1]["failure_kind"], "truncated_length")
        self.assertEqual(records[1]["done_reason"], "length")

        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["teknik_tamamlanan"], 1)
        self.assertEqual(summary["basarisizlik_turleri"], {"truncated_length": 1})
        self.assertEqual(summary["sure_ozetine_dahil_vakalar"], ["C01"])

    def test_bad_json_and_timeout_are_recorded_as_errors_and_run_continues(self) -> None:
        workspace = make_workspace(real_case_lines(["C01", "C02", "C03"]))
        self.addCleanup(shutil.rmtree, workspace, True)

        behaviors = [
            {"kind": "bad_json"},
            {"kind": "hang", "seconds": 4},
            {"kind": "ok", "content": "son vaka calisti"},
        ]
        with FakeOllama(behaviors) as fake:
            code, _ = run_main(workspace, fake, ["--no-warmup"])
        self.assertEqual(code, 0, "bir vakanin hatasi calismayi durdurmamali")

        records = read_records(latest_run_dir(workspace))
        self.assertEqual(len(records), 3)

        self.assertEqual(records[0]["failure_kind"], "invalid_json")
        self.assertEqual(records[0]["error"]["type"], "JSONDecodeError")
        self.assertIsNone(records[0]["metrics"], "hatali vakaya sahte olcum yazilmamali")

        self.assertEqual(records[1]["failure_kind"], "timeout")

        self.assertTrue(records[2]["ok"])
        self.assertEqual(records[2]["content"], "son vaka calisti")

    def test_empty_answer_is_a_failure(self) -> None:
        workspace = make_workspace(real_case_lines(["C01"]))
        self.addCleanup(shutil.rmtree, workspace, True)

        with FakeOllama([{"kind": "empty"}]) as fake:
            code, _ = run_main(workspace, fake, ["--no-warmup"])
        self.assertEqual(code, 0)

        records = read_records(latest_run_dir(workspace))
        self.assertEqual(records[0]["failure_kind"], "empty_response")
        self.assertFalse(records[0]["ok"])


class ResultDirectoryTest(unittest.TestCase):
    def test_second_run_does_not_overwrite_the_first(self) -> None:
        workspace = make_workspace(real_case_lines(["C01"]))
        self.addCleanup(shutil.rmtree, workspace, True)

        with FakeOllama([{"kind": "ok", "content": "birinci"}]) as fake:
            run_main(workspace, fake, ["--no-warmup"])
        with FakeOllama([{"kind": "ok", "content": "ikinci"}]) as fake:
            run_main(workspace, fake, ["--no-warmup"])

        run_dirs = sorted((workspace / "results").iterdir())
        self.assertEqual(len(run_dirs), 2)
        contents = {read_records(d)[0]["content"] for d in run_dirs}
        self.assertEqual(contents, {"birinci", "ikinci"})

    def test_existing_run_directory_is_a_clear_error_not_a_traceback(self) -> None:
        workspace = make_workspace(real_case_lines(["C01"]))
        self.addCleanup(shutil.rmtree, workspace, True)

        with mock.patch.object(run, "make_run_id", lambda *a, **k: "SABIT"), \
                FakeOllama([{"kind": "ok", "content": "birinci"}]) as fake:
            first_code, _ = run_main(workspace, fake, ["--no-warmup"])
            first_bytes = (workspace / "results" / "SABIT" / "cases.jsonl").read_bytes()
            second_code, output = run_main(workspace, fake, ["--no-warmup"])

        self.assertEqual(first_code, 0)
        self.assertEqual(second_code, 2)
        self.assertIn("Sonuc dizini zaten var", output)
        self.assertEqual(len(fake.chat_requests), 1, "ikinci calisma modele istek gondermemeli")
        self.assertEqual(
            (workspace / "results" / "SABIT" / "cases.jsonl").read_bytes(), first_bytes,
            "ilk calismanin sonucu ezilmemeli",
        )

    def test_unexpected_exception_still_writes_partial_summary_and_is_reraised(self) -> None:
        workspace = make_workspace(real_case_lines(["C01", "C02", "C03"]))
        self.addCleanup(shutil.rmtree, workspace, True)

        real_observe = run.mechanical_observations
        calls: list[int] = []

        def fail_on_second_case(content):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("beklenmeyen hata")
            return real_observe(content)

        with mock.patch.object(run, "mechanical_observations", fail_on_second_case), \
                FakeOllama([{"kind": "ok"}]) as fake:
            with self.assertRaisesRegex(RuntimeError, "beklenmeyen hata"):  # yutulmamali
                run_main(workspace, fake, ["--no-warmup"])

        run_dir = latest_run_dir(workspace)
        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["calisma_durumu"], "yarida_kesildi")
        self.assertEqual(summary["planlanan_vaka_sayisi"], 3)
        self.assertEqual(summary["vaka_sayisi"], 1)
        self.assertEqual(summary["kesinti"]["istisna_turu"], "RuntimeError")
        self.assertEqual(summary["kesinti"]["kesildigi_vaka"], "C02")
        self.assertEqual(summary["sure_ozetine_dahil_vakalar"], ["C01"])
        self.assertEqual(len(read_records(run_dir)), 1)

    def test_completed_run_is_marked_complete(self) -> None:
        workspace = make_workspace(real_case_lines(["C01", "C02"]))
        self.addCleanup(shutil.rmtree, workspace, True)
        with FakeOllama([{"kind": "ok"}]) as fake:
            run_main(workspace, fake, ["--no-warmup"])
        summary = json.loads((latest_run_dir(workspace) / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["calisma_durumu"], "tamamlandi")
        self.assertIsNone(summary["kesinti"])
        self.assertEqual(summary["planlanan_vaka_sayisi"], 2)

    def test_warmup_is_stored_separately_from_case_results(self) -> None:
        workspace = make_workspace(real_case_lines(["C01"]))
        self.addCleanup(shutil.rmtree, workspace, True)

        behaviors = [{"kind": "ok", "content": "hazir"}, {"kind": "ok", "content": "vaka cevabi"}]
        with FakeOllama(behaviors) as fake:
            code, _ = run_main(workspace, fake)
        self.assertEqual(code, 0)

        run_dir = latest_run_dir(workspace)
        warmup = json.loads((run_dir / "warmup.json").read_text(encoding="utf-8"))
        self.assertEqual(warmup["content"], "hazir")
        self.assertFalse(warmup["sure_ozetine_dahil_mi"])

        records = read_records(run_dir)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["content"], "vaka cevabi")

        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["isinma"]["durum"], "basarili")


class ResponseContractTest(unittest.TestCase):
    """Basari: bos olmayan metin + done=true + done_reason='stop'. Digerleri basarisizlik."""

    def _run(self, case_ids: list[str], behaviors: list[dict]) -> tuple[list[dict], dict]:
        workspace = make_workspace(real_case_lines(case_ids))
        self.addCleanup(shutil.rmtree, workspace, True)
        with FakeOllama(behaviors) as fake:
            code, output = run_main(workspace, fake, ["--no-warmup"])
        self.assertEqual(code, 0, output)
        run_dir = latest_run_dir(workspace)
        self.last_run_dir = run_dir
        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        return read_records(run_dir), summary

    def test_bad_shapes_and_protocol_errors_are_failures_and_run_continues(self) -> None:
        behaviors = [
            {"kind": "raw_json", "payload": []},
            {"kind": "raw_json", "payload": {"message": "metin", "done": True}},
            {"kind": "raw_json", "payload": {"message": {"content": None}, "done": True,
                                              "done_reason": "stop"}},
            {"kind": "incomplete"},
            {"kind": "http_error", "status": 500},
            {"kind": "ok", "content": "son vaka"},
        ]
        records, summary = self._run(["C01", "C02", "C03", "C04", "C05", "C06"], behaviors)

        self.assertEqual(
            [r["failure_kind"] for r in records],
            ["invalid_shape", "invalid_shape", "invalid_shape", "protocol_error",
             "http_error", None],
        )
        for record in records[:5]:
            self.assertFalse(record["ok"])
            self.assertIsNone(record["metrics"], "hatali vakaya sahte olcum yazilmamali")
            self.assertIsNone(record["istemci_eksi_sunucu_total_s"])
        self.assertEqual(records[4]["http_status"], 500)
        self.assertTrue(records[5]["ok"])

        self.assertEqual(summary["teknik_tamamlanan"], 1)
        self.assertEqual(
            summary["basarisizlik_turleri"],
            {"invalid_shape": 3, "protocol_error": 1, "http_error": 1},
        )
        self.assertEqual(summary["sure_ozetine_dahil_vakalar"], ["C06"])
        self.assertEqual(summary["istemci_gecen_sure_s"]["adet"], 1)
        self.assertEqual(summary["sunucu_total_duration_s"]["adet"], 1)
        self.assertEqual(summary["sunucu_total_duration_s"]["medyan"], 2.5)

    def test_missing_or_unexpected_completion_fields_are_not_success(self) -> None:
        behaviors = [
            {"kind": "ok", "drop": ["done"]},
            {"kind": "ok", "override": {"done": False}},
            {"kind": "ok", "drop": ["done_reason"]},
            {"kind": "ok", "override": {"done_reason": "load"}},
            {"kind": "length"},
            {"kind": "ok", "override": {"done": "true"}},  # metin "true" bool degildir
            {"kind": "ok", "content": "  \n"},  # yalnizca bosluk
            {"kind": "ok"},
        ]
        records, summary = self._run(
            ["C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08"], behaviors
        )

        self.assertEqual(
            [r["failure_kind"] for r in records],
            ["not_done", "not_done", "unexpected_done_reason", "unexpected_done_reason",
             "truncated_length", "not_done", "empty_response", None],
        )
        self.assertEqual([r["ok"] for r in records], [False] * 7 + [True])
        self.assertEqual(summary["sure_ozetine_dahil_vakalar"], ["C08"])
        self.assertEqual(summary["sunucu_total_duration_s"]["adet"], 1)
        self.assertEqual(
            summary["basarisizlik_turleri"],
            {"not_done": 3, "unexpected_done_reason": 2, "truncated_length": 1,
             "empty_response": 1},
        )

    def test_client_minus_server_difference_is_recorded_or_null(self) -> None:
        behaviors = [
            {"kind": "ok"},
            {"kind": "ok", "drop": ["total_duration"]},
            {"kind": "ok", "override": {"total_duration": -1}},
            {"kind": "ok", "override": {"total_duration": True}},
        ]
        records, summary = self._run(["C01", "C02", "C03", "C04"], behaviors)
        for record in records[2:]:  # negatif ve bool gecerli sure degil
            self.assertIsNone(record["istemci_eksi_sunucu_total_s"])
            self.assertIsNone(record["metrics"]["total_duration_s"])
        # Gecersiz olcum sunucu istatistigine girmez; ozet standart JSON kalir.
        self.assertEqual(summary["sunucu_total_duration_s"]["adet"], 1)
        strict_json_loads((self.last_run_dir / "summary.json").read_text(encoding="utf-8"))

        first = records[0]
        self.assertAlmostEqual(
            first["istemci_eksi_sunucu_total_s"], first["client_elapsed_s"] - 2.5, delta=0.002
        )
        self.assertEqual(first["metrics"]["total_duration_s"], 2.5)  # ham olcum korunur

        self.assertTrue(records[1]["ok"])
        self.assertIsNone(records[1]["metrics"]["total_duration_s"])
        self.assertIsNone(records[1]["istemci_eksi_sunucu_total_s"], "eksik olcume sahte deger yok")
        self.assertIsNone(summary["vaka_bazli"][1]["istemci_eksi_sunucu_total_s"])


class NonStandardNumberTest(unittest.TestCase):
    """NaN / Infinity / -Infinity / tasma: invalid_json; sonuc dosyalarina sizmaz."""

    def test_non_standard_numbers_fail_and_never_reach_result_files(self) -> None:
        workspace = make_workspace(real_case_lines(["C01", "C02", "C03", "C04", "C05"]))
        self.addCleanup(shutil.rmtree, workspace, True)

        overflow_body = json.dumps(
            {"message": {"role": "assistant", "content": "tasma"}, "done": True,
             "done_reason": "stop", "total_duration": 1}
        ).replace('"total_duration": 1', '"total_duration": 1e999')
        behaviors = [
            {"kind": "ok", "override": {"total_duration": float("nan")}},   # isinma
            {"kind": "ok", "override": {"total_duration": float("inf")}},   # C01
            {"kind": "ok", "override": {"eval_duration": float("-inf")}},   # C02
            {"kind": "ok", "override": {"eval_count": float("nan")}},       # C03
            {"kind": "raw_text", "body": overflow_body},                    # C04
            {"kind": "ok", "content": "gecerli vaka"},                      # C05
        ]
        with FakeOllama(behaviors) as fake:
            code, output = run_main(workspace, fake)
        self.assertEqual(code, 0, output)
        self.assertIn("1e999", overflow_body)

        run_dir = latest_run_dir(workspace)

        # Uretilen butun dosyalar (her JSONL satiri dahil) katı okuyucudan gecmeli.
        meta = strict_json_loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
        warmup = strict_json_loads((run_dir / "warmup.json").read_text(encoding="utf-8"))
        summary = strict_json_loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        lines = [l for l in (run_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines() if l]
        records = [strict_json_loads(line) for line in lines]
        self.assertEqual(meta["run_id"], run_dir.name)

        self.assertFalse(warmup["ok"])
        self.assertEqual(warmup["failure_kind"], "invalid_json")
        self.assertEqual(warmup["error"]["type"], "NonStandardJSONNumber")
        self.assertIsNone(warmup["raw_response"])
        self.assertEqual(summary["isinma"]["durum"], "basarisiz")
        self.assertEqual(summary["isinma"]["failure_kind"], "invalid_json")

        self.assertEqual(
            [r["failure_kind"] for r in records],
            ["invalid_json"] * 4 + [None],
        )
        for record in records[:4]:
            self.assertFalse(record["ok"])
            self.assertEqual(record["error"]["type"], "NonStandardJSONNumber")
            self.assertIsNone(record["raw_response"])
            self.assertIsNone(record["metrics"])
            self.assertIn("raw_text_prefix", record["error"])  # sinirli ham metin korunur
        self.assertTrue(records[4]["ok"])
        self.assertEqual(records[4]["content"], "gecerli vaka")

        self.assertEqual(summary["teknik_tamamlanan"], 1)
        self.assertEqual(summary["basarisizlik_turleri"], {"invalid_json": 4})
        self.assertEqual(summary["sure_ozetine_dahil_vakalar"], ["C05"])
        self.assertEqual(summary["vaka_bazli"][2]["eval_count"], None)

    def test_strict_reader_rejects_each_non_standard_form(self) -> None:
        for text in ('{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}', '{"a": 1e999}',
                     '{"a": -1e999}'):
            with self.subTest(text=text), self.assertRaises(run.NonStandardJSONNumber):
                run.loads_strict(text)
        self.assertEqual(run.loads_strict('{"a": 1.5, "b": 2}'), {"a": 1.5, "b": 2})


class WarmupStatusTest(unittest.TestCase):
    def test_failed_warmup_is_reported_and_kept_out_of_case_stats(self) -> None:
        workspace = make_workspace(real_case_lines(["C01", "C02"]))
        self.addCleanup(shutil.rmtree, workspace, True)

        with FakeOllama([{"kind": "http_error", "status": 500}, {"kind": "ok"}]) as fake:
            code, output = run_main(workspace, fake)
        self.assertEqual(code, 0, output)
        self.assertEqual(len(fake.chat_requests), 3)

        run_dir = latest_run_dir(workspace)
        warmup = json.loads((run_dir / "warmup.json").read_text(encoding="utf-8"))
        self.assertFalse(warmup["ok"])

        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["isinma"]["durum"], "basarisiz")
        self.assertEqual(summary["isinma"]["failure_kind"], "http_error")
        self.assertIn("model yukleme", summary["isinma"]["not"])
        self.assertEqual(summary["sure_ozetine_dahil_vakalar"], ["C01", "C02"])
        self.assertEqual(summary["istemci_gecen_sure_s"]["adet"], 2)
        self.assertEqual(summary["vaka_sayisi"], 2)

    def test_skipped_warmup_is_reported(self) -> None:
        workspace = make_workspace(real_case_lines(["C01"]))
        self.addCleanup(shutil.rmtree, workspace, True)

        with FakeOllama([{"kind": "ok"}]) as fake:
            code, _ = run_main(workspace, fake, ["--no-warmup"])
        self.assertEqual(code, 0)

        run_dir = latest_run_dir(workspace)
        self.assertFalse((run_dir / "warmup.json").exists())
        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["isinma"]["durum"], "atlandi")


class TimestampAndMetadataTest(unittest.TestCase):
    def test_started_at_is_taken_before_the_request_on_success_and_failure(self) -> None:
        workspace = make_workspace(real_case_lines(["C01", "C02"]))
        self.addCleanup(shutil.rmtree, workspace, True)

        events: list[str] = []
        real_chat_once = run.chat_once

        def fake_clock() -> str:
            events.append("clock")
            return f"clock-{len(events)}"

        def spy_chat_once(*args, **kwargs):
            events.append("chat")
            return real_chat_once(*args, **kwargs)

        behaviors = [{"kind": "ok"}, {"kind": "http_error", "status": 500}]
        with mock.patch.object(run, "_utc_now", fake_clock), \
                mock.patch.object(run, "chat_once", spy_chat_once), \
                FakeOllama(behaviors) as fake:
            code, output = run_main(workspace, fake, ["--no-warmup"])
        self.assertEqual(code, 0, output)

        # run_meta, (vaka1 saat, istek), (vaka2 saat, istek)
        self.assertEqual(events, ["clock", "clock", "chat", "clock", "chat"])
        records = read_records(latest_run_dir(workspace))
        self.assertTrue(records[0]["ok"])
        self.assertFalse(records[1]["ok"])
        self.assertEqual(records[0]["started_at_utc"], "clock-2")
        self.assertEqual(records[1]["started_at_utc"], "clock-4")

    def test_run_meta_records_runner_hash_and_renamed_version_timing(self) -> None:
        workspace = make_workspace(real_case_lines(["C01"]))
        self.addCleanup(shutil.rmtree, workspace, True)

        with FakeOllama([{"kind": "ok"}]) as fake:
            code, _ = run_main(workspace, fake, ["--no-warmup"])
        self.assertEqual(code, 0)

        meta = json.loads((latest_run_dir(workspace) / "run_meta.json").read_text(encoding="utf-8"))
        runner_file = Path(run.__file__).resolve()
        self.assertEqual(meta["calistirici_dosyasi"]["path"], str(runner_file))
        self.assertEqual(
            meta["calistirici_dosyasi"]["sha256"],
            hashlib.sha256(runner_file.read_bytes()).hexdigest(),
        )
        self.assertIsInstance(meta["api_version_istek_suresi_s"], float)
        self.assertNotIn("baglanti_ek_yuku_s", meta)


if __name__ == "__main__":
    unittest.main()
