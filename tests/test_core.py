import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import zstandard

from database import date_bounds
from exporter import safe_filename, text_content


class CoreChecks(unittest.TestCase):
    def test_date_range_is_inclusive_by_day(self):
        lower, upper = date_bounds("2026-10-18", "2026-10-18")
        self.assertEqual(datetime.fromtimestamp(lower).strftime("%Y-%m-%d"), "2026-10-18")
        self.assertEqual(datetime.fromtimestamp(upper).strftime("%Y-%m-%d"), "2026-10-19")

    def test_reversed_date_range_is_rejected(self):
        with self.assertRaises(ValueError):
            date_bounds("2026-10-19", "2026-10-18")

    def test_plain_and_zstd_text_payloads(self):
        self.assertEqual(text_content("  普通文本  "), "普通文本")
        payload = zstandard.ZstdCompressor().compress("压缩文本".encode("utf-8"))
        self.assertEqual(text_content(payload), "压缩文本")

    def test_windows_filename_characters_are_removed(self):
        self.assertEqual(safe_filename('a/b:c?d*e'), "a_b_c_d_e")


if __name__ == "__main__":
    unittest.main()
