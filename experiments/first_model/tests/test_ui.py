"""Arayuzun saf fonksiyonlari: servis yanitini ekran alanlarina cevirme.

Yalnizca standart kutuphane; Gradio kurulu olmadan calisir ve Gradio sunucusu
baslatmaz. Gercek bir servis veya model kullanilmaz.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = TESTS_DIR.parent
for _path in (EXPERIMENT_DIR, TESTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import inputs  # noqa: E402
import pipeline  # noqa: E402
import ui  # noqa: E402


def ok_body(**overrides) -> dict:
    body = {
        "case_id": "C01", "mod": "A", "ok": True, "failure_kind": None,
        "content": "Bulgular: x\nKaynaklar: D1", "kaynak_secimi": "elle",
        "kullanilan_kaynaklar": ["D1"], "uygunluk_motoru_acik": True,
        "elenen_kaynaklar": {}, "belirsiz_kaynaklar": [], "maskelenen_alanlar": [],
        "client_elapsed_s": 0.001, "arama_suresi_s": None,
    }
    body.update(overrides)
    return body


def dev_record(case_id: str) -> dict:
    """Servisin dondurdugu kaydin aynisi: pipeline.analyze_case ciktisi (A modu)."""
    case = next(c for c in inputs.load_cases(EXPERIMENT_DIR / "cases.jsonl") if c["case_id"] == case_id)
    record = pipeline.analyze_case(
        case, mode="A", sources=inputs.load_sources(EXPERIMENT_DIR / "docs.json"),
        system_prompt="", retriever=None, applicability_on=True, host="", model="",
        options={}, timeout=1,
    )
    return json.loads(json.dumps(record, ensure_ascii=False))


class RenderSuccessTest(unittest.TestCase):
    def test_success_fills_every_field(self) -> None:
        fields = ui.render_response(200, ok_body())
        self.assertIn("Taslak hazir", fields["durum"])
        self.assertEqual(fields["taslak"], "Bulgular: x\nKaynaklar: D1")
        self.assertEqual(fields["kullanilan"], "D1")
        self.assertEqual(fields["uygunluk"], "Elenen kaynak yok.")
        self.assertEqual(fields["maskeleme"], "Maskelenecek deger bulunmadi.")
        self.assertEqual(fields["sure"], "Analiz suresi: 0.001 s")

    def test_eliminated_sources_show_reason_codes(self) -> None:
        # Gercek kayit: C14 (v2) vakasinda D4 (v1) kaynagi elenir.
        fields = ui.render_response(200, dev_record("C14"))
        self.assertIn("D4: surum_uyusmazligi", fields["uygunluk"])
        self.assertNotIn("D4", fields["kullanilan"])
        self.assertTrue(fields["taslak"])

    def test_uncertain_sources_are_listed(self) -> None:
        fields = ui.render_response(200, ok_body(belirsiz_kaynaklar=["D3"]))
        self.assertIn("belirsiz", fields["uygunluk"])
        self.assertIn("D3", fields["uygunluk"])

    def test_disabled_filter_is_stated(self) -> None:
        body = ok_body(uygunluk_motoru_acik=False, elenen_kaynaklar=None, belirsiz_kaynaklar=None)
        self.assertIn("kapali", ui.render_response(200, body)["uygunluk"])

    def test_masked_paths_are_shown_without_values(self) -> None:
        body = ok_body(maskelenen_alanlar=["request.headers.Authorization", "ticket"])
        fields = ui.render_response(200, body)
        self.assertIn("request.headers.Authorization", fields["maskeleme"])
        self.assertIn("ticket", fields["maskeleme"])

    def test_search_duration_is_shown_when_present(self) -> None:
        fields = ui.render_response(200, ok_body(kaynak_secimi="arama", arama_suresi_s=0.25))
        self.assertIn("arama: 0.25 s", fields["sure"])
        self.assertIn("anlamsal arama", fields["durum"])

    def test_200_without_completed_record_is_not_success(self) -> None:
        for body in (ok_body(ok=False), None, [], {"detail": "x"}):
            with self.subTest(body=body):
                fields = ui.render_response(200, body)
                self.assertNotIn("Taslak hazir", fields["durum"])
                self.assertEqual(fields["taslak"], "")


class RenderErrorTest(unittest.TestCase):
    def assert_plain(self, fields: dict) -> None:
        self.assertTrue(fields["durum"])
        for value in fields.values():
            self.assertNotIn("{", value)  # ham JSON yok
            self.assertNotIn("Traceback", value)
        self.assertEqual(fields["taslak"], "")

    def test_422_names_fields_and_turkish_rule(self) -> None:
        body = {"detail": [
            {"loc": ["body"], "msg": "Value error, A ve C modu elle atanmis kaynak ister: "
                                    "vaka.source_ids bos olamaz", "type": "value_error"},
            {"loc": ["body", "vaka", "ticket"], "msg": "String should have at most 4000 characters",
             "type": "string_too_long"},
        ]}
        fields = ui.render_response(422, body)
        self.assert_plain(fields)
        self.assertIn("Istek gecersiz", fields["durum"])
        self.assertIn("A ve C modu elle atanmis kaynak ister", fields["durum"])
        self.assertIn("vaka.ticket", fields["durum"])
        self.assertNotIn("String should", fields["durum"])

    def test_502_503_504_have_distinct_turkish_sentences(self) -> None:
        seen = set()
        for status in (502, 503, 504):
            with self.subTest(status=status):
                fields = ui.render_response(status, {"detail": "Arama kullanilamiyor: paket yok"})
                self.assert_plain(fields)
                self.assertTrue(fields["durum"].startswith(ui.STATUS_MESSAGES[status]))
                self.assertIn("Servis aciklamasi: Arama kullanilamiyor", fields["durum"])
                seen.add(ui.STATUS_MESSAGES[status])
        self.assertEqual(len(seen), 3)

    def test_error_without_json_body_still_has_a_sentence(self) -> None:
        for status in (422, 502, 503, 504):
            with self.subTest(status=status):
                fields = ui.render_response(status, None)
                self.assert_plain(fields)
                self.assertNotIn("Servis aciklamasi", fields["durum"])

    def test_500_shows_error_id_only(self) -> None:
        fields = ui.render_response(500, {"detail": "Beklenmeyen sunucu hatasi.", "hata_kimligi": "abc123"})
        self.assert_plain(fields)
        self.assertIn("abc123", fields["durum"])


class RequestAndTransportTest(unittest.TestCase):
    def test_request_body_for_case_and_free_text(self) -> None:
        self.assertEqual(ui.build_request("A", ui.INPUT_CASE, "C03", "", True, 5),
                         {"mod": "A", "uygunluk_motoru": True, "case_id": "C03"})
        self.assertEqual(ui.build_request("B", ui.INPUT_TEXT, "C03", "  siparis 500  ", False, 5.0),
                         {"mod": "B", "uygunluk_motoru": False, "top_k": 5,
                          "vaka": {"case_id": ui.FREE_TEXT_CASE_ID, "ticket": "siparis 500"}})
        with self.assertRaises(ValueError):
            ui.build_request("B", ui.INPUT_TEXT, None, "   ", True, 3)

    def test_unreachable_service_has_its_own_message(self) -> None:
        with socket.socket() as sock:  # bos bir port bul; dinleyen yok
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        fields = ui.post_analysis(url, {"mod": "A", "case_id": "C01"}, timeout=5)
        self.assertIn("Servise ulasilamadi", fields["durum"])
        self.assertIn(url, fields["durum"])

    def test_silent_service_is_reported_as_timeout_not_unreachable(self) -> None:
        with socket.socket() as server:  # baglantiyi kabul eder, hic yanit vermez
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            url = f"http://127.0.0.1:{server.getsockname()[1]}"
            fields = ui.post_analysis(url, {"mod": "A", "case_id": "C01"}, timeout=0.5)
        self.assertIn("yanit vermedi", fields["durum"])
        self.assertNotIn("ulasilamadi", fields["durum"])

    def test_truncated_body_is_an_error_not_an_exception(self) -> None:
        # Servis gercekte 500 bayt bildirip 9 bayt gonderir ve baglantiyi kapatir.
        import threading
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)

            def reply() -> None:
                conn, _ = server.accept()
                with conn:
                    received = b""
                    while not received.endswith(b"}"):  # istegin tamami (JSON govde) okunur
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        received += chunk
                    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                                 b"Content-Length: 500\r\n\r\n{\"ok\": tr")

            worker = threading.Thread(target=reply, daemon=True)
            worker.start()
            url = f"http://127.0.0.1:{server.getsockname()[1]}"
            fields = ui.post_analysis(url, {"mod": "A", "case_id": "C01"}, timeout=5)
            worker.join(5)
        self.assertIn("yarim veya bozuk", fields["durum"])
        self.assertEqual(fields["taslak"], "")

    def test_module_imports_without_gradio_or_site_packages(self) -> None:
        done = subprocess.run(
            [sys.executable, "-I", "-S", "-c",
             "import sys; sys.path.insert(0, sys.argv[1]); import ui; "
             "assert 'gradio' not in sys.modules; print('ok')", str(EXPERIMENT_DIR)],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == "__main__":
    unittest.main()
