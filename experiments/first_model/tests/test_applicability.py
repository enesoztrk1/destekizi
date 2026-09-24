"""Uygulanabilirlik motoru testleri. Ag, model veya sahte servis kullanilmaz."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from datetime import date
from pathlib import Path

EXPERIMENT_DIR = Path(__file__).resolve().parents[1]
if str(EXPERIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_DIR))

import applicability as ap  # noqa: E402


def source(versions=("v1", "v2"), valid_from=None, valid_to=None, sid="S") -> dict:
    return {
        "source_id": sid,
        "api_versions": list(versions) if versions is not None else None,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "text": "x",
    }


D = date.fromisoformat
# Yururluk araligi 2026-06-01 (dahil) .. 2026-09-01 (haric).
RANGED = source(valid_from="2026-06-01", valid_to="2026-09-01")


class StatesAndReasonsTest(unittest.TestCase):
    """Uc durumun her biri ve her gerekce kodu en az bir girdiyle uretilir."""

    CASES = (
        # (aciklama, kaynak, olay tarihi, surum, beklenen durum, beklenen gerekce)
        ("uygun", RANGED, D("2026-07-01"), "v2", ap.UYGUN, ap.GEREKCE_UYGUN),
        ("surum uyusmuyor", source(versions=("v1",), valid_from="2026-01-01"),
         D("2026-07-01"), "v2", ap.UYGUN_DEGIL, ap.SURUM_UYUSMAZLIGI),
        ("henuz baslamamis", RANGED, D("2026-05-31"), "v2", ap.UYGUN_DEGIL, ap.YURURLUK_BASLAMAMIS),
        ("bitmis", RANGED, D("2026-09-02"), "v2", ap.UYGUN_DEGIL, ap.YURURLUK_BITMIS),
        ("vaka surumu yok", RANGED, D("2026-07-01"), None, ap.BELIRSIZ, ap.SURUM_BILINMIYOR),
        ("kaynak surumu yok", source(versions=None, valid_from="2026-01-01"),
         D("2026-07-01"), "v2", ap.BELIRSIZ, ap.KAYNAK_SURUMU_YOK),
        ("kaynak surum listesi bos", source(versions=(), valid_from="2026-01-01"),
         D("2026-07-01"), "v2", ap.BELIRSIZ, ap.KAYNAK_SURUMU_YOK),
        ("olay tarihi yok", RANGED, None, "v2", ap.BELIRSIZ, ap.TARIH_BILINMIYOR),
        ("kaynakta tarih yok", source(), D("2026-07-01"), "v2", ap.BELIRSIZ, ap.KAYNAK_TARIHI_YOK),
    )

    def test_each_state_and_reason(self) -> None:
        for name, src, when, version, state, reason in self.CASES:
            with self.subTest(name):
                self.assertEqual(ap.evaluate(src, when, version), ap.Karar(state, reason))

    def test_every_reason_code_is_covered_and_described(self) -> None:
        produced = {reason for *_, reason in self.CASES}
        self.assertEqual(produced, set(ap.GEREKCE_DURUMU))
        self.assertEqual(set(ap.GEREKCE_ACIKLAMASI), set(ap.GEREKCE_DURUMU))
        for name, src, when, version, state, reason in self.CASES:
            self.assertEqual(ap.GEREKCE_DURUMU[reason], state, name)


class DateBoundaryTest(unittest.TestCase):
    """Aralik: baslangic <= olay_tarihi < bitis."""

    def test_start_day_is_included(self) -> None:
        self.assertEqual(ap.evaluate(RANGED, D("2026-06-01"), "v2").durum, ap.UYGUN)

    def test_day_before_start_is_not_yet_valid(self) -> None:
        self.assertEqual(ap.evaluate(RANGED, D("2026-05-31"), "v2"),
                         ap.Karar(ap.UYGUN_DEGIL, ap.YURURLUK_BASLAMAMIS))

    def test_end_day_is_excluded(self) -> None:
        self.assertEqual(ap.evaluate(RANGED, D("2026-09-01"), "v2"),
                         ap.Karar(ap.UYGUN_DEGIL, ap.YURURLUK_BITMIS))

    def test_day_before_end_is_still_valid(self) -> None:
        self.assertEqual(ap.evaluate(RANGED, D("2026-08-31"), "v2").durum, ap.UYGUN)

    def test_open_start_means_always_started(self) -> None:
        src = source(valid_to="2026-06-01")
        self.assertEqual(ap.evaluate(src, D("1990-01-01"), "v2").durum, ap.UYGUN)
        self.assertEqual(ap.evaluate(src, D("2026-06-01"), "v2").gerekce, ap.YURURLUK_BITMIS)

    def test_open_end_means_still_valid(self) -> None:
        src = source(valid_from="2026-06-01")
        self.assertEqual(ap.evaluate(src, D("2099-12-31"), "v2").durum, ap.UYGUN)

    def test_both_dates_null_is_uncertain_never_silently_valid(self) -> None:
        karar = ap.evaluate(source(), D("2026-07-01"), "v2")
        self.assertNotEqual(karar.durum, ap.UYGUN)
        self.assertEqual(karar, ap.Karar(ap.BELIRSIZ, ap.KAYNAK_TARIHI_YOK))

    def test_unknown_event_date_is_uncertain_even_for_open_ranges(self) -> None:
        for src in (source(), source(valid_from="2026-06-01"), source(valid_to="2026-06-01")):
            with self.subTest(src=src):
                self.assertEqual(ap.evaluate(src, None, "v2"),
                                 ap.Karar(ap.BELIRSIZ, ap.TARIH_BILINMIYOR))

    def test_dates_are_compared_as_dates_not_text(self) -> None:
        # Gecersiz bicimler karsilastirmaya hic girmez; metin sirasi kullanilamaz.
        for bad in ("2026-6-1", "20260601", "2026-02-30", "2026-06-01T00:00", "01.06.2026", 20260601):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    ap.parse_date(bad, "alan")
        self.assertEqual(ap.parse_date("2026-06-01", "alan"), date(2026, 6, 1))
        self.assertIsNone(ap.parse_date(None, "alan"))


class PrecedenceTest(unittest.TestCase):
    """Kesin olumsuz karar, eksik bilgiden once gelir; sira sabittir."""

    def test_version_mismatch_wins_over_unknown_date(self) -> None:
        self.assertEqual(ap.evaluate(source(versions=("v1",)), None, "v2"),
                         ap.Karar(ap.UYGUN_DEGIL, ap.SURUM_UYUSMAZLIGI))

    def test_expired_wins_over_unknown_version(self) -> None:
        self.assertEqual(ap.evaluate(RANGED, D("2026-10-01"), None),
                         ap.Karar(ap.UYGUN_DEGIL, ap.YURURLUK_BITMIS))

    def test_version_mismatch_reported_before_date(self) -> None:
        src = source(versions=("v1",), valid_from="2026-06-01")
        self.assertEqual(ap.evaluate(src, D("2026-01-01"), "v2").gerekce, ap.SURUM_UYUSMAZLIGI)

    def test_unknown_version_reported_before_unknown_date(self) -> None:
        self.assertEqual(ap.evaluate(source(), None, None).gerekce, ap.SURUM_BILINMIYOR)

    def test_case_side_unknown_reported_before_source_side(self) -> None:
        self.assertEqual(ap.evaluate(source(), None, "v2").gerekce, ap.TARIH_BILINMIYOR)
        self.assertEqual(ap.evaluate(source(versions=None), D("2026-01-01"), None).gerekce,
                         ap.SURUM_BILINMIYOR)


class FilterTest(unittest.TestCase):
    SOURCES = {
        "V1": source(versions=("v1",), valid_from="2025-01-01", sid="V1"),
        "V2": source(versions=("v2",), valid_from="2025-01-01", sid="V2"),
        "OPEN": source(sid="OPEN"),
    }

    def test_version_mismatch_removes_source(self) -> None:
        case = {"case_id": "T", "api_version": "v2", "olay_tarihi": "2026-08-15"}
        filtre = ap.filter_sources(case, self.SOURCES, ["V1", "V2", "OPEN"])
        self.assertEqual(filtre.kullanilan, ("V2", "OPEN"))
        self.assertEqual(filtre.elenen, {"V1": ap.SURUM_UYUSMAZLIGI})
        self.assertEqual(filtre.belirsiz, ("OPEN",))
        self.assertEqual(filtre.kayit()["degerlendirilen_kaynaklar"]["V2"],
                         {"durum": ap.UYGUN, "gerekce": ap.GEREKCE_UYGUN})

    def test_no_usable_source_leaves_empty_list(self) -> None:
        case = {"case_id": "T", "api_version": "v1", "olay_tarihi": "2026-08-15"}
        filtre = ap.filter_sources(case, self.SOURCES, ["V2"])
        self.assertEqual(filtre.kullanilan, ())
        self.assertEqual(filtre.elenen, {"V2": ap.SURUM_UYUSMAZLIGI})

    def test_missing_and_null_event_date_are_both_unknown(self) -> None:
        for case in ({"case_id": "T", "api_version": "v2"},
                     {"case_id": "T", "api_version": "v2", "olay_tarihi": None}):
            filtre = ap.filter_sources(case, self.SOURCES, ["V2"])
            self.assertEqual(filtre.degerlendirilen["V2"].gerekce, ap.TARIH_BILINMIYOR)

    def test_invalid_event_date_is_an_error_not_unknown(self) -> None:
        case = {"case_id": "T", "api_version": "v2", "olay_tarihi": "15.08.2026"}
        with self.assertRaises(ValueError):
            ap.filter_sources(case, self.SOURCES, ["V2"])

    def test_same_input_same_result_and_inputs_not_mutated(self) -> None:
        case = {"case_id": "T", "api_version": "v2", "olay_tarihi": "2026-08-15"}
        before = (copy.deepcopy(case), copy.deepcopy(self.SOURCES))
        first = ap.filter_sources(case, self.SOURCES, ["V1", "V2", "OPEN"])
        second = ap.filter_sources(case, self.SOURCES, ["V1", "V2", "OPEN"])
        self.assertEqual(first, second)
        self.assertEqual(json.dumps(first.kayit()), json.dumps(second.kayit()))
        self.assertEqual((case, self.SOURCES), before)


class SourceValidationTest(unittest.TestCase):
    def test_bad_source_metadata_is_rejected(self) -> None:
        bad = (
            source(valid_from="2026-06-01", valid_to="2026-06-01"),  # bos aralik
            source(valid_from="2026-07-01", valid_to="2026-06-01"),  # ters aralik
            source(valid_from="2026/06/01"),
            {"source_id": "S", "api_versions": "v2"},
            {"source_id": "S", "api_versions": ["v2", ""]},
        )
        for src in bad:
            with self.subTest(src=src):
                with self.assertRaises(ValueError):
                    ap.validate_source(src)

    def test_real_sources_are_valid(self) -> None:
        docs = json.loads((EXPERIMENT_DIR / "docs.json").read_text(encoding="utf-8"))
        for src in docs["sources"]:
            ap.validate_source(src)


if __name__ == "__main__":
    unittest.main()
