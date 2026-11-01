import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", HERE))
if not (SKILL / "scripts/chart.py").is_file():
    SKILL = HERE / "package/mingxue-master"
sys.path.insert(0, str(SKILL / "scripts"))
import almanac


class AlmanacTests(unittest.TestCase):
    def test_chinese_new_year_and_unknown_hour(self):
        value = almanac.lookup("2024-02-10")
        self.assertEqual(value["records"][0]["lunar"], "二〇二四年正月初一")
        self.assertEqual(value["records"][0]["hour_table"]["status"], "not_calculated")
        self.assertFalse(value["calendar_basis"]["hour_known"])

    def test_date_range_is_continuous_and_membership_is_literal(self):
        value = almanac.lookup("2024-02-28", days=3, clock="07:30", topic="嫁娶")
        self.assertEqual([r["date"] for r in value["records"]], ["2024-02-28", "2024-02-29", "2024-03-01"])
        for row in value["records"]:
            self.assertEqual(row["topic_lookup"]["listed_yi"], "嫁娶" in row["yi"])
            self.assertEqual(row["topic_lookup"]["listed_ji"], "嫁娶" in row["ji"])
            self.assertEqual(row["hour_table"]["status"], "calculated")

    def test_bad_date_or_unbounded_range_is_rejected(self):
        for start, options in [("2023-02-29", {}), ("1500-01-01", {}),
                               ("2024-01-01", {"days": 0}), ("2024-01-01", {"days": 32}),
                               ("2024-01-01", {"days": True}), ("2024-01-01", {"clock": "07:30+08:00"})]:
            with self.subTest(start=start, options=options), self.assertRaises((ValueError, OverflowError)):
                almanac.lookup(start, **options)

    def test_jieqi_date_table_does_not_pick_an_unstated_noon_month(self):
        rows = [almanac.lookup("2024-02-04", clock=clock)["records"][0] for clock in (None, "12:00", "22:00")]
        self.assertTrue(all(row["yi"] == rows[0]["yi"] and row["ji"] == rows[0]["ji"] for row in rows))
        late = almanac.lookup("2024-02-04", clock="23:30")
        self.assertEqual(late["calendar_basis"]["day_change"], "00:00")
        self.assertIn("23:00", late["records"][0]["hour_table"]["day_change"])

    def test_cli_probe_and_bad_input_are_json(self):
        for args, expected in [(["--probe"], 0), (["--date", "not-a-date"], 2)]:
            result = subprocess.run([sys.executable, "-X", "utf8", "-B", str(SKILL / "scripts/almanac.py"), *args],
                capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, expected)
            self.assertEqual(json.loads(result.stdout)["system"], "electional")


if __name__ == "__main__":
    unittest.main()
