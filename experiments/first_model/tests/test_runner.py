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
import subprocess
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
# Gercek vaka setinin boyutu; veri genisledikce testler sabit sayiya bagli kalmasin.
REAL_CASE_COUNT = sum(
    1 for line in (EXPERIMENT_DIR / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
)

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
        self.assertEqual(len(fake.chat_requests), 1 + REAL_CASE_COUNT)  # isinma + her vaka

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

    def test_failure_while_writing_partial_summary_does_not_hide_original_error(self) -> None:
        workspace = make_workspace(real_case_lines(["C01", "C02"]))
        self.addCleanup(shutil.rmtree, workspace, True)

        def boom(content):
            raise RuntimeError("asil hata")

        def broken_writer(run_dir, summary):
            raise OSError("disk dolu")

        with mock.patch.object(run, "mechanical_observations", boom), \
                mock.patch.object(run, "_write_summary", broken_writer), \
                FakeOllama([{"kind": "ok"}]) as fake:
            buffer = io.StringIO()
            with redirect_stdout(buffer), redirect_stderr(buffer):
                with self.assertRaisesRegex(RuntimeError, "asil hata"):
                    run.main(["--host", fake.url, "--model", fake.model,
                              "--prompt", str(workspace / "prompt.txt"),
                              "--docs", str(workspace / "docs.json"),
                              "--cases", str(workspace / "cases.jsonl"),
                              "--results-root", str(workspace / "results"), "--no-warmup"])
        self.assertIn("kismi ozet yazilamadi", buffer.getvalue())
        self.assertIn("disk dolu", buffer.getvalue())

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


class ModeATest(unittest.TestCase):
    """A modu: kural tabanli yol; Ollama'ya hicbir istek gitmemeli."""

    def test_mode_a_sends_no_request_at_all(self) -> None:
        workspace = make_workspace(real_case_lines(["C01", "C05", "C10"]))
        self.addCleanup(shutil.rmtree, workspace, True)

        with FakeOllama([{"kind": "ok"}]) as fake:
            code, output = run_main(workspace, fake, ["--mode", "A"])  # isinma acik birakildi
        self.assertEqual(code, 0, output)
        self.assertEqual(fake.all_requests, [], "on kontrol, isinma veya model istegi gitmemeli")
        self.assertEqual(fake.chat_requests, [])

        run_dir = latest_run_dir(workspace)
        self.assertIn("-A-", run_dir.name)
        self.assertFalse((run_dir / "warmup.json").exists())
        meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["mod"], "A")
        self.assertIsNone(meta["model"])
        self.assertEqual(meta["kural_motoru_dosyasi"]["sha256"],
                         hashlib.sha256(Path(run.rules_mode.__file__).read_bytes()).hexdigest())

        records = read_records(run_dir)
        self.assertEqual([r["mod"] for r in records], ["A", "A", "A"])
        for record in records:
            self.assertTrue(record["ok"])
            self.assertIsNone(record["metrics"])
            self.assertIsNone(record["messages"])
            self.assertIsNone(record["model"])
            self.assertIsNotNone(record["kural_karari"])
            self.assertIsInstance(record["client_elapsed_s"], float)
            self.assertTrue(record["mekanik_gozlem"]["dort_baslik_var"])
        self.assertEqual(records[2]["kural_karari"]["durum"], "uzman_incelemesi")

        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["mod"], "A")
        self.assertEqual(summary["isinma"]["durum"], "uygulanamaz")
        self.assertIsNone(summary["sunucu_total_duration_s"])
        self.assertEqual(summary["istemci_gecen_sure_s"]["adet"], 3)

    def test_mode_a_full_run_never_opens_the_real_answer_key(self) -> None:
        results_root = Path(tempfile.mkdtemp(prefix="destekizi_test_"))
        self.addCleanup(shutil.rmtree, results_root, True)
        with answer_key_guard() as hits:
            buffer = io.StringIO()
            with redirect_stdout(buffer), redirect_stderr(buffer):
                code = run.main(["--mode", "A", "--results-root", str(results_root)])
        self.assertEqual(code, 0, buffer.getvalue())
        self.assertEqual(hits, [])

    def test_default_mode_is_still_c(self) -> None:
        workspace = make_workspace(real_case_lines(["C01"]))
        self.addCleanup(shutil.rmtree, workspace, True)
        with FakeOllama([{"kind": "ok"}]) as fake:
            code, _ = run_main(workspace, fake, ["--no-warmup"])
        self.assertEqual(code, 0)
        run_dir = latest_run_dir(workspace)
        self.assertNotIn("-A-", run_dir.name)
        self.assertEqual(json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))["mod"], "C")
        record = read_records(run_dir)[0]
        self.assertEqual(record["mod"], "C")
        self.assertIsNone(record["kural_karari"])
        self.assertEqual(len(fake.chat_requests), 1)


    def test_runs_from_other_cwd_without_script_dir_on_sys_path(self) -> None:
        # -I: betik dizini sys.path'e eklenmez; rules_mode yine bulunmali.
        other_cwd = Path(tempfile.mkdtemp(prefix="destekizi_cwd_"))
        self.addCleanup(shutil.rmtree, other_cwd, True)
        proc = subprocess.run(
            [sys.executable, "-I", str(EXPERIMENT_DIR / "run.py"), "--mode", "A",
             "--results-root", str(other_cwd / "results")],
            cwd=other_cwd, capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        run_dirs = list((other_cwd / "results").iterdir())
        self.assertEqual(len(run_dirs), 1)
        self.assertEqual(len(read_records(run_dirs[0])), REAL_CASE_COUNT)

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


# Yalnizca D4 / D5 metninde gecen ayirt edici ifadeler.
D4_TEXT = "v1 istekleri kimliği X-Api-Key başlığıyla gönderir"
D5_TEXT = "v2 istekleri kimliği Authorization: Bearer"
D8_TEXT = "limit en çok 50 olabilir"
SAMPLE_C_RUN = EXPERIMENT_DIR / "results_sample" / "20260923T214519Z-661fd9" / "cases.jsonl"


class ApplicabilityFlowTest(unittest.TestCase):
    """Uygunluk filtresi modelden ve kural motorundan ONCE calisir."""

    def _run(self, case_ids: list[str], extra: list[str]) -> tuple[Path, FakeOllama, str]:
        workspace = make_workspace(real_case_lines(case_ids))
        self.addCleanup(shutil.rmtree, workspace, True)
        with FakeOllama([{"kind": "ok"}]) as fake:
            code, output = run_main(workspace, fake, ["--no-warmup"] + extra)
        self.assertEqual(code, 0, output)
        return latest_run_dir(workspace), fake, output

    def test_eliminated_source_text_never_reaches_the_model(self) -> None:
        run_dir, fake, _ = self._run(["C14", "C17"], [])
        body_c14 = json.dumps(fake.chat_requests[0], ensure_ascii=False)
        self.assertNotIn(D4_TEXT, body_c14)  # v1 kaynagi, v2 vakasinda elenir
        self.assertIn(D5_TEXT, body_c14)
        self.assertIn("D4: UYGUN_DEGIL (surum_uyusmazligi)", body_c14)
        body_c17 = json.dumps(fake.chat_requests[1], ensure_ascii=False)
        self.assertNotIn(D8_TEXT, body_c17)  # olay tarihinde yururlukte degil
        self.assertIn("D3: BELIRSIZ (kaynak_tarihi_yok)", body_c17)
        self.assertIn("olay_tarihi: 2026-09-20", body_c17)

        c14, c17 = read_records(run_dir)
        self.assertEqual(c14["kullanilan_kaynaklar"], ["D5"])
        self.assertEqual(c14["elenen_kaynaklar"], {"D4": "surum_uyusmazligi"})
        self.assertEqual(c14["belirsiz_kaynaklar"], [])
        self.assertEqual(c14["degerlendirilen_kaynaklar"]["D5"],
                         {"durum": "UYGUN", "gerekce": "uygun"})
        self.assertEqual(c17["kullanilan_kaynaklar"], ["D3"])
        self.assertEqual(c17["belirsiz_kaynaklar"], ["D3"])
        self.assertEqual(c17["elenen_kaynaklar"], {"D8": "yururluk_baslamamis"})
        self.assertTrue(c14["uygunluk_motoru_acik"])

    def test_no_applicability_flag_really_disables_the_filter(self) -> None:
        run_dir, fake, output = self._run(["C14", "C17"], ["--no-applicability"])
        self.assertIn("KAPALI", output)
        body_c14 = json.dumps(fake.chat_requests[0], ensure_ascii=False)
        self.assertIn(D4_TEXT, body_c14)
        self.assertNotIn("UYGUNLUK KONTROLU", body_c14)
        self.assertIn(D8_TEXT, json.dumps(fake.chat_requests[1], ensure_ascii=False))
        for record in read_records(run_dir):
            self.assertFalse(record["uygunluk_motoru_acik"])
            self.assertIsNone(record["degerlendirilen_kaynaklar"])
            self.assertIsNone(record["elenen_kaynaklar"])
            self.assertEqual(record["kullanilan_kaynaklar"], record["source_ids"])
        meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
        self.assertFalse(meta["uygunluk_motoru"]["acik"])

    def test_disabled_filter_keeps_the_original_message_byte_for_byte(self) -> None:
        # Motor kapaliyken C01-C10 mesaji, motordan once uretilen ornek kosudakiyle ayni.
        sample = {r["case_id"]: r["messages"] for r in read_records(SAMPLE_C_RUN.parent)}
        case_ids = sorted(sample)
        self.assertEqual(len(case_ids), 10)
        _, fake, _ = self._run(case_ids, ["--no-applicability"])
        for case_id, request in zip(case_ids, fake.chat_requests):
            self.assertEqual(request["messages"], sample[case_id], case_id)

    def test_no_usable_source_means_expert_review_in_both_modes(self) -> None:
        run_dir, fake, _ = self._run(["C18"], [])
        body = json.dumps(fake.chat_requests[0], ensure_ascii=False)
        self.assertNotIn(D5_TEXT, body)
        self.assertIn("uygun kaynak kalmadi", body)
        self.assertIn("uzman", body)
        self.assertEqual(read_records(run_dir)[0]["kullanilan_kaynaklar"], [])

        run_dir, fake, _ = self._run(["C18"], ["--mode", "A"])
        self.assertEqual(fake.all_requests, [])
        record = read_records(run_dir)[0]
        self.assertEqual(record["kural_karari"]["durum"], "uzman_incelemesi")
        self.assertEqual(record["kural_karari"]["kaynaklar"], [])
        self.assertIn("surum_uyusmazligi", record["content"])
        self.assertNotIn("Bearer", record["content"])

    def test_mode_a_without_filter_uses_the_wrong_version_source(self) -> None:
        run_dir, _, _ = self._run(["C18"], ["--mode", "A", "--no-applicability"])
        record = read_records(run_dir)[0]
        self.assertEqual(record["kural_karari"]["kural"], "D5/401/DEMO_AUTH_MISSING")
        self.assertIsNone(record["degerlendirilen_kaynaklar"])

    def test_uncertain_sources_are_used_and_shown_in_mode_a(self) -> None:
        run_dir, _, _ = self._run(["C01", "C16", "C17"], ["--mode", "A"])
        c01, c16, c17 = read_records(run_dir)
        self.assertEqual(c01["kullanilan_kaynaklar"], ["D1"])
        self.assertEqual(c01["belirsiz_kaynaklar"], ["D1"])
        self.assertIn("(tarih_bilinmiyor)", c01["content"].split("Sonraki adım:")[0])
        self.assertIn("D6, D7", c16["content"])
        self.assertIn("(kaynak_tarihi_yok)", c17["content"])
        self.assertEqual(c17["kural_karari"]["kaynaklar"], ["D3"])

    def test_run_meta_records_engine_hash_and_state(self) -> None:
        run_dir, _, _ = self._run(["C01"], ["--mode", "A"])
        meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
        engine = EXPERIMENT_DIR / "applicability.py"
        self.assertTrue(meta["uygunluk_motoru"]["acik"])
        self.assertEqual(meta["uygunluk_motoru"]["sha256"],
                         hashlib.sha256(engine.read_bytes()).hexdigest())

    def test_mode_a_is_deterministic_with_filter(self) -> None:
        ids = [f"C{n:02d}" for n in range(1, 19)]
        first, _, _ = self._run(ids, ["--mode", "A"])
        second, _, _ = self._run(ids, ["--mode", "A"])
        keys = ("content", "kural_karari", "degerlendirilen_kaynaklar", "kullanilan_kaynaklar",
                "elenen_kaynaklar", "belirsiz_kaynaklar")
        strip = lambda d: [{k: r[k] for k in keys} for r in read_records(d)]  # noqa: E731
        self.assertEqual(strip(first), strip(second))

    def test_invalid_dates_stop_before_any_request(self) -> None:
        bad_case = json.loads(real_case_lines(["C14"])[0])
        bad_case["olay_tarihi"] = "15.08.2026"
        workspace = make_workspace([json.dumps(bad_case, ensure_ascii=False)])
        self.addCleanup(shutil.rmtree, workspace, True)
        with FakeOllama([{"kind": "ok"}]) as fake:
            code, output = run_main(workspace, fake)
        self.assertEqual(code, 2)
        self.assertIn("olay_tarihi", output)
        self.assertEqual(fake.all_requests, [])

        workspace = make_workspace(real_case_lines(["C01"]))
        self.addCleanup(shutil.rmtree, workspace, True)
        docs = json.loads((workspace / "docs.json").read_text(encoding="utf-8"))
        docs["sources"][0]["valid_from"] = "2026-13-01"
        (workspace / "docs.json").write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
        with FakeOllama([{"kind": "ok"}]) as fake:
            code, output = run_main(workspace, fake)
        self.assertEqual(code, 2)
        self.assertIn("D1.valid_from", output)
        self.assertEqual(fake.all_requests, [])


if __name__ == "__main__":
    unittest.main()
