"""Degerlendirme betigi (eval/run_eval.py) testleri. Model veya ag kullanilmaz."""

from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

EXPERIMENT_DIR = Path(__file__).resolve().parents[1]
for extra in (EXPERIMENT_DIR, EXPERIMENT_DIR / "eval"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import run  # noqa: E402
import run_eval  # noqa: E402

CHECKS = {
    "beklenen_durum": "taslak_hazir",
    "beklenen_aile": "yetkilendirme",
    "gerekli_kaynaklar": ["D1"],
    "yasak_kaynaklar": ["D3"],
    "yasak_ifadeler": ["süresi doldu"],
    "gerekli_ifadeler": ["orders:read"],
}

GOOD = """Bulgular:
- HTTP 403, DEMO_SCOPE_MISSING.

Belirsizlik / eksik bilgi:
- Bu kayıt tek başına belirtecin süresinin dolduğunu göstermez.

Sonraki adım:
- orders:read yetkisini kontrol edin.

Kaynaklar: D1"""

BAD = """**Bulgular:**
- Token süresi doldu.

**Belirsizlik / eksik bilgi:**
- Yok.

**Sonraki adım:**
- Hata gövdesini paylaşın.

**Kaynaklar:** D1, D3"""


def write_run(root: Path, name: str, mode: str | None, contents: dict[str, str | None]) -> Path:
    run_dir = root / name
    run_dir.mkdir(parents=True)
    meta = {"run_id": name}
    if mode is not None:
        meta["mod"] = mode
    (run_dir / "run_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    lines = []
    for case_id, content in contents.items():
        ok = content is not None
        lines.append(json.dumps({
            "case_id": case_id, "ok": ok, "failure_kind": None if ok else "timeout",
            "content": content, "client_elapsed_s": 1.5 if ok else 180.0,
            "metrics": {"total_duration_s": 1.0, "eval_count": 100, "prompt_eval_count": 900}
            if ok else None,
        }, ensure_ascii=False))
    (run_dir / "cases.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return run_dir


def write_expected(root: Path, rows: dict[str, dict | None]) -> Path:
    path = root / "expected.jsonl"
    lines = []
    for case_id, block in rows.items():
        row = {"case_id": case_id, "beklenen": "x"}
        if block is not None:
            row["makine_kontrolleri"] = block
        lines.append(json.dumps(row, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class ParsingTest(unittest.TestCase):
    def test_sections_are_found_in_plain_and_bold_formats(self) -> None:
        for text in (GOOD, BAD):
            sections = run_eval.parse_sections(text)
            self.assertEqual(set(sections), {"bulgular", "belirsizlik", "sonraki_adim", "kaynaklar"})
        self.assertEqual(run_eval.cited_sources(run_eval.parse_sections(BAD)), ["D1", "D3"])

    def test_only_the_kaynaklar_section_counts_as_cited(self) -> None:
        text = "Bulgular:\n- D2 ve D3 bu hatayı kapsamaz.\n\nSonraki adım:\n- Bekleyin.\n\nKaynaklar: D1"
        self.assertEqual(run_eval.cited_sources(run_eval.parse_sections(text)), ["D1"])

    def test_missing_kaynaklar_section_is_not_an_empty_citation(self) -> None:
        self.assertIsNone(run_eval.cited_sources(run_eval.parse_sections("Bulgular:\n- x")))

    def test_status_heuristic(self) -> None:
        derive = lambda body: run_eval.derive_status(run_eval.parse_sections(f"Sonraki adım:\n- {body}"))
        self.assertEqual(derive("Kaydı uzman incelemesine yönlendirin; bilgileri paylaşın."),
                         "uzman_incelemesi")
        self.assertEqual(derive("Yanıt başlıklarını paylaşın."), "bilgi_gerekli")
        self.assertEqual(derive("En az 12 saniye bekleyin."), "taslak_hazir")
        self.assertEqual(run_eval.derive_status({}), run_eval.UNDETERMINED)

    def test_family_from_sources(self) -> None:
        self.assertEqual(run_eval.derive_family(["D2"]), "istek_siniri")
        self.assertIsNone(run_eval.derive_family([]))
        self.assertEqual(run_eval.derive_family(["D1", "D3"]), run_eval.MULTIPLE_FAMILIES)

    def test_phrase_check_is_case_insensitive_including_turkish_dotted_i(self) -> None:
        self.assertIn("i̇", "İ".lower())  # Python'un varsayilani; fold bunu engellemeli
        self.assertEqual(run_eval.fold("İSTEK ORDERS:READ"), "istek orders:read")


class MetricsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="destekizi_eval_"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_known_inputs_give_expected_metrics(self) -> None:
        expected = run_eval.load_expected(write_expected(self.root, {"X1": CHECKS, "X2": CHECKS}))
        run_a = run_eval.evaluate_run(run_eval.load_run(
            write_run(self.root, "a", "A", {"X1": GOOD, "X2": GOOD})), expected)
        run_c = run_eval.evaluate_run(run_eval.load_run(
            write_run(self.root, "c", "C", {"X1": BAD, "X2": None})), expected)

        self.assertEqual(run_a["teknik_tamamlanan"], 2)
        self.assertEqual(run_a["durum"], (2, 2))
        self.assertEqual(run_a["aile"], (2, 2))
        self.assertEqual(run_a["gerekli_kaynak"], (2, 2))
        self.assertEqual(run_a["yasak_kaynak"], (0, 2))
        self.assertEqual(run_a["yasak_ifade"], (0, 2))
        self.assertEqual(run_a["gerekli_ifade"], (0, 2))

        self.assertEqual(run_c["teknik_tamamlanan"], 1)
        self.assertEqual(run_c["basarisizlik_turleri"], {"timeout": 1})
        self.assertEqual(run_c["per_case"]["X1"]["durum"], "bilgi_gerekli")
        self.assertEqual(run_c["per_case"]["X1"]["aile"], run_eval.MULTIPLE_FAMILIES)
        self.assertEqual(run_c["durum"], (0, 2))  # basarisiz vaka dogru sayilmaz
        self.assertEqual(run_c["aile"], (0, 2))
        self.assertEqual(run_c["gerekli_kaynak"], (1, 2))  # X1'de D1 var, X2 yanit yok
        # Cevabi olmayan X2 yasak kontrollerinde "temiz" sayilmaz; paydaya girmez.
        self.assertEqual(run_c["yasak_kaynak"], (1, 1))
        self.assertEqual(run_c["yasak_ifade"], (1, 1))
        self.assertIsNone(run_c["per_case"]["X2"]["yasak_kaynak_ihlali"])
        self.assertIsNone(run_c["per_case"]["X2"]["yasak_ifadeler_bulunan"])
        self.assertEqual(run_c["cevap_yok"], ["X2"])
        self.assertEqual(run_c["per_case"]["X1"]["yasak_ifadeler_bulunan"], ["süresi doldu"])
        self.assertEqual(run_c["gerekli_ifade"], (2, 2))
        self.assertEqual(run_c["karisiklik"],
                         {"taslak_hazir": {"bilgi_gerekli": 1, run_eval.UNDETERMINED: 1}})
        self.assertEqual(run_c["istemci_sure_s"]["adet"], 1)  # yalniz basarili vaka

        report = run_eval.render_report([run_a, run_c], expected)
        self.assertIn("| Durum | 2: X1, X2 | 0 |", report)
        self.assertIn("| Durum doğru | 2'de 2 | 2'de 0 |", report)

    def test_missing_or_partial_machine_checks_do_not_crash(self) -> None:
        expected = run_eval.load_expected(write_expected(
            self.root, {"X1": None, "X2": {"beklenen_durum": "taslak_hazir"}, "X3": {}}))
        ev = run_eval.evaluate_run(run_eval.load_run(
            write_run(self.root, "r", None, {"X1": GOOD, "X2": GOOD, "X3": GOOD, "X9": GOOD})),
            expected)
        self.assertEqual(ev["durum"], (1, 1))
        self.assertEqual(ev["aile"], (0, 0))
        self.assertEqual(ev["gerekli_ifade"], (0, 0))
        self.assertEqual(ev["run"]["mode"], "C")
        self.assertIsNotNone(ev["run"]["mode_note"])
        report = run_eval.render_report([ev], expected)
        self.assertIn("kontrol yok", report)
        self.assertIn("makine_kontrolleri alanı olmayan vakalar: X1", report)

    def test_answer_without_kaynaklar_section_is_not_clean_on_forbidden_sources(self) -> None:
        expected = run_eval.load_expected(write_expected(self.root, {"X1": CHECKS}))
        no_section = "Bulgular:\n- D3 kullanıldı.\n\nSonraki adım:\n- Bekleyin."
        ev = run_eval.evaluate_run(run_eval.load_run(
            write_run(self.root, "r", "C", {"X1": no_section})), expected)
        self.assertIsNone(ev["per_case"]["X1"]["yasak_kaynak_ihlali"])
        self.assertEqual(ev["yasak_kaynak"], (0, 0))
        self.assertFalse(ev["per_case"]["X1"]["gerekli_kaynak_tamam"])

    def test_failed_record_with_partial_content_does_not_pass_phrase_checks(self) -> None:
        # run.py, truncated_length kaydinda kesilmis metni content alaninda tutar.
        expected = run_eval.load_expected(write_expected(self.root, {"X1": CHECKS}))
        run_dir = write_run(self.root, "r", "C", {"X1": GOOD})
        record = json.loads((run_dir / "cases.jsonl").read_text(encoding="utf-8"))
        record.update(ok=False, failure_kind="truncated_length")
        (run_dir / "cases.jsonl").write_text(json.dumps(record, ensure_ascii=False) + "\n",
                                             encoding="utf-8")
        ev = run_eval.evaluate_run(run_eval.load_run(run_dir), expected)
        case = ev["per_case"]["X1"]
        self.assertEqual(case["gerekli_ifadeler_eksik"], ["orders:read"])
        self.assertFalse(case["gerekli_kaynak_tamam"])
        self.assertIsNone(case["yasak_ifadeler_bulunan"])
        self.assertEqual(ev["gerekli_ifade"], (1, 1))  # (eksik vaka, kontrol edilen)
        self.assertEqual(ev["cevap_yok"], ["X1"])
        self.assertEqual(ev["basarisizlik_turleri"], {"truncated_length": 1})

    def test_duplicate_case_in_run_file_is_reported(self) -> None:
        run_dir = write_run(self.root, "r", "C", {"X1": GOOD})
        line = (run_dir / "cases.jsonl").read_text(encoding="utf-8")
        (run_dir / "cases.jsonl").write_text(line + line, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "yinelenen case_id: X1"):
            run_eval.load_run(run_dir)

    def test_invalid_machine_checks_are_rejected_not_silently_skipped(self) -> None:
        bad_blocks = (
            {"beklenen_durumu": "taslak_hazir"},       # yazim hatali anahtar
            {"beklenen_durum": "hazir"},               # gecersiz deger
            {"beklenen_aile": "odeme"},                # gecersiz aile
            {"yasak_ifadeler": "süresi doldu"},        # liste degil
        )
        for block in bad_blocks:
            with self.subTest(block=block):
                path = write_expected(self.root, {"X1": block})
                with self.assertRaises(ValueError):
                    run_eval.load_expected(path)

    def test_duplicate_or_corrupt_rows_are_reported(self) -> None:
        path = self.root / "expected.jsonl"
        path.write_text('{"case_id": "X1"}\n{"case_id": "X1"}\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "yinelenen"):
            run_eval.load_expected(path)
        run_dir = write_run(self.root, "r", "C", {"X1": GOOD})
        with (run_dir / "cases.jsonl").open("a", encoding="utf-8") as handle:
            handle.write("{bozuk\n")
        with self.assertRaisesRegex(ValueError, "satir 2"):
            run_eval.load_run(run_dir)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            code = run_eval.main([str(run_dir), "--expected", str(write_expected(self.root, {}))])
        self.assertEqual(code, 2)
        self.assertIn("satir 2", err.getvalue())

    def test_interrupted_run_state_is_shown_in_report(self) -> None:
        expected = run_eval.load_expected(write_expected(self.root, {"X1": CHECKS, "X2": CHECKS}))
        run_dir = write_run(self.root, "r", "C", {"X1": GOOD})
        (run_dir / "summary.json").write_text(json.dumps({"calisma_durumu": "yarida_kesildi"}),
                                              encoding="utf-8")
        other = write_run(self.root, "s", "A", {"X1": GOOD, "X2": GOOD})
        evs = [run_eval.evaluate_run(run_eval.load_run(d), expected) for d in (run_dir, other)]
        report = run_eval.render_report(evs, expected)
        self.assertIn("yarida_kesildi", report)
        self.assertIn("özet yok", report)
        self.assertEqual(evs[0]["cevap_yok"], ["X2"])

    def test_report_states_limits_at_start_and_end_and_has_no_percentages(self) -> None:
        expected = run_eval.load_expected(write_expected(self.root, {"X1": CHECKS}))
        ev = run_eval.evaluate_run(run_eval.load_run(write_run(self.root, "r", "A", {"X1": GOOD})),
                                   expected)
        report = run_eval.render_report([ev], expected)
        lines = [line for line in report.splitlines() if line.strip()]
        self.assertTrue(lines[1].startswith("> **Sınır:**"))
        self.assertTrue(lines[-1].startswith("> **Sınır:**"))
        self.assertIn("henüz yapılmamıştır", report)
        self.assertNotIn("%", report)

    def test_report_is_deterministic(self) -> None:
        expected_path = write_expected(self.root, {"X1": CHECKS, "X2": CHECKS})
        dirs = [str(write_run(self.root, "a", "A", {"X1": GOOD, "X2": BAD})),
                str(write_run(self.root, "c", "C", {"X1": BAD, "X2": GOOD}))]
        outputs = []
        for index in range(2):
            out = self.root / f"rapor{index}.md"
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(run_eval.main(dirs + ["--expected", str(expected_path),
                                                       "--out", str(out)]), 0)
            outputs.append(out.read_bytes())
        self.assertEqual(outputs[0], outputs[1])


class RealDataTest(unittest.TestCase):
    """Gercek vakalar + gercek cevap anahtari; A modu sahte servis olmadan calisir."""

    def test_mode_a_on_real_cases_passes_every_machine_check(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="destekizi_eval_"))
        self.addCleanup(shutil.rmtree, root, True)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(run.main(["--mode", "A", "--results-root", str(root)]), 0)
        run_dir = next(root.iterdir())
        expected = run_eval.load_expected(run_eval.DEFAULT_EXPECTED)
        ev = run_eval.evaluate_run(run_eval.load_run(run_dir), expected)
        n = len(expected)
        self.assertEqual(ev["teknik_tamamlanan"], n)
        self.assertEqual(ev["durum"], (n, n))
        self.assertEqual(ev["aile"], (n, n))
        self.assertEqual(ev["yasak_ifade"][0], 0)
        self.assertEqual(ev["gerekli_ifade"][0], 0)
        # Metinden turetilen durum, kural motorunun ic karariyla ayni olmali.
        for record in run_eval.load_run(run_dir)["records"].values():
            self.assertEqual(ev["per_case"][record["case_id"]]["durum"],
                             record["kural_karari"]["durum"], record["case_id"])


if __name__ == "__main__":
    unittest.main()
