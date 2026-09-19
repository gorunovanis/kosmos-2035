"""Organiser control vectors V01–V10, values taken from data/case/expected_checks.json (not retyped)."""
import unittest

from kosmo.api import CASE_DIR
from kosmo.case import load_expected_checks
from kosmo.vectors import run_vectors


class TestControlVectors(unittest.TestCase):
    def test_all_vectors_match_expected_checks(self):
        expected = load_expected_checks(CASE_DIR)
        actual = run_vectors()
        self.assertEqual({e["case_id"] for e in expected}, set(actual))
        for item in expected:
            cid = item["case_id"]
            for key, val in item["expected"].items():
                got = actual[cid][key]
                if isinstance(val, (int, float)):
                    self.assertAlmostEqual(float(got), float(val), places=9, msg=f"{cid}.{key}")
                else:
                    self.assertEqual(got, val, msg=f"{cid}.{key}")


if __name__ == "__main__":
    unittest.main()
