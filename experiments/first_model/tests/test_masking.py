"""Maskeleme modulu (masking.py) ve akistaki yeri.

Uctan uca testler sahte Ollama servisiyle calisir; modele giden istek govdesi ve
cases.jsonl kaydi okunarak sir degerlerinin gecmedigi dogrulanir. Gercek model
kullanilmaz.
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = TESTS_DIR.parent
for _path in (EXPERIMENT_DIR, TESTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import masking  # noqa: E402
import retrieval  # noqa: E402
from fake_ollama import FakeOllama  # noqa: E402
from test_runner import latest_run_dir, make_workspace, run_main  # noqa: E402

M = masking.MASK

# Uctan uca testlerde aranacak sir degerleri (hicbiri ciktilarda gecmemeli).
SECRET_BEARER = "sk_live_TESTSIRRI_9f8e7d6c5b4a"
SECRET_KEY = "k-999-GIZLI-ANAHTAR"
SECRET_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.c2lnbmF0dXJlX3Rlc3Q"
SECRET_EMAIL = "musteri.test@ornek-firma.com"
SECRET_PHONE = "0532 123 45 67"
SECRET_PASSWORD = "Parola_TEST_123"
SECRETS = (SECRET_BEARER, SECRET_KEY, SECRET_JWT, SECRET_EMAIL, SECRET_PHONE, SECRET_PASSWORD,
           "532 123 45 67", "TESTSIRRI")


def secret_case(case_id: str = "C90") -> dict:
    return {
        "case_id": case_id,
        "ticket": f"401 aliyoruz. Iletisim: {SECRET_EMAIL}, tel {SECRET_PHONE}. Token: {SECRET_JWT}",
        "platform": "DemoCommerce",
        "environment": "test",
        "api_version": "v2",
        "request": {
            "method": "GET",
            "path": "/orders",
            "headers": {"Authorization": f"Bearer {SECRET_BEARER}", "X-Api-Key": SECRET_KEY},
            "body": {"credentials": [{"password": SECRET_PASSWORD}]},
        },
        "response": {"http_status": 401, "error_code": "DEMO_TOKEN_EXPIRED"},
        "source_ids": ["D1"],
    }


class HeaderTest(unittest.TestCase):
    def test_each_sensitive_header_is_masked(self) -> None:
        cases = {
            "Authorization": ("Bearer abc.def", "Bearer ***"),
            "Proxy-Authorization": ("Basic dXNlcjpwYXNz", "Basic ***"),
            "X-Api-Key": ("k-999", M),
            "Cookie": ("session=abc123; theme=dark", "session=***; theme=***"),
            "Set-Cookie": ("sid=xyz; Path=/; HttpOnly", "sid=***; Path=/; HttpOnly"),
        }
        for name, (value, want) in cases.items():
            with self.subTest(name=name):
                masked, changed = masking.mask_case({"headers": {name: value}})
                self.assertEqual(masked["headers"][name], want)
                self.assertEqual(changed, [f"headers.{name}"])

    def test_lowercase_and_mixed_case_header_names(self) -> None:
        masked, _ = masking.mask_case({"h": {"authorization": "Bearer abc", "X-API-KEY": "k-1"}})
        self.assertEqual(masked["h"], {"authorization": "Bearer ***", "X-API-KEY": M})

    def test_scheme_is_preserved_for_diagnosis(self) -> None:
        # KRITIK: maskelemeden sonra "baslik var mi, Bearer mi Basic mi?" cevaplanabilir.
        for scheme in ("Bearer", "Basic", "bearer", "Digest"):
            masked = masking.mask_header_value("Authorization", f"{scheme} gizli.deger==")
            self.assertEqual(masked, f"{scheme} ***")
            self.assertNotIn("gizli", masked)
        self.assertEqual(masking.mask_header_value("Authorization", "sadece-deger"), M)

    def test_empty_or_non_string_header_value_kept(self) -> None:
        for value in ("", None, True):
            self.assertEqual(masking.mask_header_value("Authorization", value), value)

    def test_non_string_header_values_are_masked(self) -> None:
        data = {"Authorization": ["Bearer abcdefghijk"], "X-Api-Key": 123456789,
                "Cookie": {"session": "s3cr3t"}}
        masked, changed = masking.mask_case(data)
        self.assertEqual(masked, {"Authorization": ["Bearer ***"], "X-Api-Key": M,
                                  "Cookie": {"session": M}})
        self.assertEqual(changed, ["Authorization", "X-Api-Key", "Cookie"])

    def test_name_variants_with_dash_underscore_case(self) -> None:
        data = {"X_API_KEY": "a", "api-key": "b", "accessToken": "c", "Refresh-Token": "d",
                "authorization_present": True, "request_id": "r1"}
        masked, _ = masking.mask_case(data)
        self.assertEqual(masked, {"X_API_KEY": M, "api-key": M, "accessToken": M,
                                  "Refresh-Token": M, "authorization_present": True,
                                  "request_id": "r1"})

    def test_non_sensitive_headers_unchanged(self) -> None:
        headers = {"Retry-After": "12", "Content-Type": "application/json",
                   "X-Demo-Retry-Ms": "20000", "X-Request-Id": "abc-123"}
        masked, changed = masking.mask_case({"headers": headers})
        self.assertEqual(masked["headers"], headers)
        self.assertEqual(changed, [])

    def test_presence_flag_is_not_touched(self) -> None:
        case = {"request": {"authorization_present": True}}
        self.assertEqual(masking.mask_case(case)[0], case)


class FieldTest(unittest.TestCase):
    def test_each_sensitive_field_is_masked(self) -> None:
        for field in sorted(masking.SENSITIVE_FIELDS):
            with self.subTest(field=field):
                masked, changed = masking.mask_case({"body": {field: "degerX1", "user": "ali"}})
                self.assertEqual(masked["body"], {field: M, "user": "ali"})
                self.assertEqual(changed, [f"body.{field}"])

    def test_field_names_case_insensitive_and_nested(self) -> None:
        data = {"a": {"b": {"Access_Token": "t1", "c": {"PASSWORD": "p"}}}}
        masked, changed = masking.mask_case(data)
        self.assertEqual(masked, {"a": {"b": {"Access_Token": M, "c": {"PASSWORD": M}}}})
        self.assertEqual(changed, ["a.b.Access_Token", "a.b.c.PASSWORD"])

    def test_objects_inside_lists(self) -> None:
        data = {"items": [{"token": "t1"}, {"name": "x"}, [{"secret": "s"}]]}
        masked, changed = masking.mask_case(data)
        self.assertEqual(masked, {"items": [{"token": M}, {"name": "x"}, [{"secret": M}]]})
        self.assertEqual(changed, ["items[0].token", "items[2][0].secret"])

    def test_nested_object_under_sensitive_field_is_hidden(self) -> None:
        masked, _ = masking.mask_case({"secret": {"inner": "x"}})
        self.assertEqual(masked, {"secret": M})

    def test_null_and_empty(self) -> None:
        self.assertEqual(masking.mask_case({}), ({}, []))
        self.assertEqual(masking.mask_case({"token": None}), ({"token": None}, []))

    def test_input_is_not_mutated(self) -> None:
        case = secret_case()
        before = copy.deepcopy(case)
        masking.mask_case(case)
        self.assertEqual(case, before)


class TextPatternTest(unittest.TestCase):
    def test_email_phone_jwt_bearer(self) -> None:
        samples = {
            f"yaz: {SECRET_EMAIL} lutfen": "yaz: <e-posta> lutfen",
            "tel +90 532 123 45 67 ya da 05321234567": "tel <telefon> ya da <telefon>",
            "tel 532-123-45-67": "tel <telefon>",
            f"jwt {SECRET_JWT} bitti": "jwt <jwt> bitti",
            f"Authorization: Bearer {SECRET_BEARER}": "Authorization: Bearer ***",
        }
        for text, want in samples.items():
            with self.subTest(text=text):
                self.assertEqual(masking.mask_text(text)[0], want)

    def test_key_value_embedded_in_text(self) -> None:
        samples = {
            'govde {"access_token":"opaque123","page":2}': 'govde {"access_token":"***","page":2}',
            "GET /orders?api_key=SEKRET1&token=T0K&page=2": "GET /orders?api_key=***&token=***&page=2",
            "password = hunter22 tamam": "password = *** tamam",
        }
        for text, want in samples.items():
            with self.subTest(text=text):
                self.assertEqual(masking.mask_text(text)[0], want)

    def test_diagnostic_text_untouched(self) -> None:
        for text in ("2026-05-20", "X-Demo-Retry-Ms: 20000", "DEMO_TOKEN_EXPIRED 401",
                     "Bearer şemasıyla gönderin", "Bearer ***", "limit=100, page_size=100",
                     "sipariş 5000000", "Tokenım var", "token süresi doldu mu",
                     "DEMO_TOKEN_EXPIRED"):
            with self.subTest(text=text):
                self.assertEqual(masking.mask_text(text), (text, []))

    def test_real_cases_have_nothing_to_mask(self) -> None:
        # Mevcut 18 vakada maskelenecek deger yok; ornek kosular gecerliligini korur.
        for line in (EXPERIMENT_DIR / "cases.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                case = json.loads(line)
                self.assertEqual(masking.mask_case(case), (case, []), case["case_id"])


class EndToEndTest(unittest.TestCase):
    """KRITIK: sir degeri modele giden istekte ve kayitta YOK."""

    def _run_c(self) -> tuple[list[dict], dict, str]:
        workspace = make_workspace([json.dumps(secret_case(), ensure_ascii=False)])
        with FakeOllama([{"kind": "ok"}]) as fake:
            code, output = run_main(workspace, fake, ["--no-warmup"])
            self.assertEqual(code, 0, output)
            bodies = list(fake.chat_requests)
        run_dir = latest_run_dir(workspace)
        return bodies, json.loads((run_dir / "cases.jsonl").read_text(encoding="utf-8")), \
            (run_dir / "cases.jsonl").read_text(encoding="utf-8")

    def test_secret_not_in_model_request(self) -> None:
        bodies, _, _ = self._run_c()
        sent = json.dumps(bodies, ensure_ascii=False)
        for secret in SECRETS:
            self.assertNotIn(secret, sent)
        user = bodies[-1]["messages"][1]["content"]
        self.assertIn("Bearer ***", user)  # tur korunur
        self.assertIn('"X-Api-Key": "***"', user)  # varlik korunur
        self.assertIn("<e-posta>", user)

    def test_secret_not_in_case_record(self) -> None:
        _, record, raw = self._run_c()
        for secret in SECRETS:
            self.assertNotIn(secret, raw)
        self.assertIn("request.headers.Authorization", record["maskelenen_alanlar"])
        self.assertIn("request.body.credentials[0].password", record["maskelenen_alanlar"])

    def test_masking_happens_before_retrieval(self) -> None:
        from test_retrieval import FakeEmbedder, _sources, _write_cache

        workspace = make_workspace([json.dumps(secret_case(), ensure_ascii=False)])
        embedder = FakeEmbedder(_sources(workspace / "docs.json"))
        cache = _write_cache(workspace, embedder)
        embedder.calls.clear()
        with mock.patch.object(retrieval, "load_embedder", return_value=embedder), \
                FakeOllama([{"kind": "ok"}]) as fake:
            code, output = run_main(workspace, fake, ["--mode", "B", "--embeddings", str(cache)])
        self.assertEqual(code, 0, output)
        (query,) = embedder.calls
        self.assertTrue(query.startswith("query: "))
        for secret in SECRETS:
            self.assertNotIn(secret, query)
        self.assertIn("<e-posta>", query)


if __name__ == "__main__":
    unittest.main()
