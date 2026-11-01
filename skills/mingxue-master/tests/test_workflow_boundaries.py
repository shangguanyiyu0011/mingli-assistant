"""Executed presets and reported effective rules must agree with adapter results."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", HERE))
if not (SKILL / "scripts/workflow.py").is_file():
    SKILL = HERE / "package/mingxue-master"
sys.path.insert(0, str(SKILL / "scripts"))
import workflow
import ziwei


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class EffectiveRulesTests(unittest.TestCase):
    def test_explicit_birth_day_rule_is_reported_as_the_effective_rule(self):
        with tempfile.TemporaryDirectory(prefix="effective-bazi-") as temp:
            result = workflow.run_project(Path(temp) / "project", {"birth": {"date": "2000-08-16",
                "time": "23:30:00", "timezone": "Asia/Shanghai", "sect": 1}, "systems": ["bazi"]})
            report = read(result["report_json"])
            birth = read(Path(result["report_json"]).parent / "birth.json")
            self.assertEqual(report["selected_profile"]["id"], "baseline")
            self.assertEqual(report["selected_profile"]["settings"]["bazi"]["sect"], 2)
            self.assertEqual(report["effective_settings"]["bazi"]["sect"], birth["input"]["sect"])
            self.assertEqual(report["effective_settings"]["bazi"]["day_change"], "23:00")
            self.assertIn("23:00", Path(result["report"]).read_text(encoding="utf-8"))

    def flow(self, explicit=None):
        if ziwei.probe().get("status") != "available":
            self.skipTest("prepared local Ziwei engine required; no automatic download")
        with tempfile.TemporaryDirectory(prefix="effective-flow-") as temp:
            source = {"birth": {"date": "2000-08-16", "time": "03:30:00", "timezone": "Asia/Shanghai", "gender": "female"},
                "systems": ["ziwei"], "settings": {"ziwei": {"horoscope_divide": "exact"}},
                "options": {"ziwei": {"scope": "monthly", "target_date": "2026-02-10", "target_time": "12:30:00"}}}
            if explicit is not None:
                source["options"]["ziwei"]["horoscope_divide"] = explicit
            result = workflow.run_project(Path(temp) / "project", source)
            report = read(result["report_json"])
            payload = read(Path(result["report_json"]).parent / "results/ziwei.json")
            self.assertEqual(result["states"]["ziwei"], "ready")
            self.assertEqual(report["effective_settings"]["ziwei"]["horoscope_divide"], payload["convention"]["horoscope_divide"])
            return payload

    def test_profile_flow_rule_reaches_the_real_engine(self):
        payload = self.flow()
        self.assertEqual(payload["horoscope"]["convention"]["horoscope_divide"], "exact")
        yearly = payload["horoscope"]["layers"]["yearly"]
        self.assertEqual((yearly["heavenlyStem"], yearly["earthlyBranch"]), ("丙", "午"))

    def test_explicit_flow_options_override_profile_defaults(self):
        payload = self.flow("normal")
        self.assertEqual(payload["horoscope"]["convention"]["horoscope_divide"], "normal")
        yearly = payload["horoscope"]["layers"]["yearly"]
        self.assertEqual((yearly["heavenlyStem"], yearly["earthlyBranch"]), ("乙", "巳"))


if __name__ == "__main__":
    unittest.main()
