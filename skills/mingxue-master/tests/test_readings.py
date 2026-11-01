"""Interpretation binding, invalidation and safe report publishing."""
import copy
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
from project_store import ProjectError, read_json


class BoundReadingTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="mingxue-reading-")
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name) / "project"
        self.input = {"birth": {"date": "2000-08-16", "time": "04:30:00", "timezone": "Asia/Shanghai"},
                      "systems": ["bazi"], "topic": "结构解释", "question": "比较已知结构"}
        self.first = workflow.run_project(self.root, self.input)
        self.report = read_json(self.first["report_json"])
        self.reading = {"text": "本轮解释：仅根据实际四柱与明确计算规则整理。<script>untrusted()</script>",
                        "result_sha256": self.report["panels"][0]["result_sha256"],
                        "question_hash": self.report["question_hash"],
                        "basis": [{"kind": "calculation", "pointer": "/pillars", "label": "本次四柱"},
                                  {"kind": "reference", "file": "references/calculation-rules.md", "label": "计算约定"}]}

    def apply_reading(self):
        return workflow.run_project(self.root, patch={"readings": {"bazi": self.reading}})

    def test_bound_interpretation_reuses_calculation_and_is_html_escaped(self):
        result = self.apply_reading()
        report = read_json(result["report_json"])
        self.assertEqual(result["reused"], ["bazi"])
        self.assertEqual(result["interpretation_needed"], [])
        self.assertEqual(report["panels"][0]["reading_status"], "applied")
        self.assertEqual(report["panels"][0]["traditional_interpretation"]["text"], self.reading["text"])
        markup = Path(result["report"]).read_text(encoding="utf-8")
        self.assertIn("&lt;script&gt;untrusted()&lt;/script&gt;", markup)
        self.assertNotIn("<script>untrusted()</script>", markup)
        self.assertEqual(workflow.project_status(self.root)["active_revision"], result["revision"])

    def test_birth_correction_removes_stale_reading_from_visible_report(self):
        before = self.apply_reading()
        old_bytes = Path(before["report"]).read_bytes()
        changed = workflow.run_project(self.root, patch={"birth": {"time": "08:15:00"}})
        panel = read_json(changed["report_json"])["panels"][0]
        self.assertEqual(changed["recomputed"], ["bazi"])
        self.assertEqual(panel["reading_status"], "stale")
        self.assertIsNone(panel["traditional_interpretation"])
        self.assertNotIn("本轮解释：", Path(changed["report"]).read_text(encoding="utf-8"))
        self.assertEqual(Path(before["report"]).read_bytes(), old_bytes)

    def test_question_correction_keeps_chart_but_invalidates_old_interpretation(self):
        self.apply_reading()
        changed = workflow.run_project(self.root, patch={"question": "改为讨论另一专题"})
        report = read_json(changed["report_json"])
        self.assertEqual(changed["reused"], ["bazi"])
        self.assertEqual(report["panels"][0]["result_sha256"], self.reading["result_sha256"])
        self.assertEqual(report["panels"][0]["reading_status"], "stale")
        self.assertNotEqual(report["question_hash"], self.reading["question_hash"])

    def test_wrong_result_hash_is_not_applied(self):
        reading = copy.deepcopy(self.reading)
        reading["result_sha256"] = "0" * 64
        changed = workflow.run_project(self.root, patch={"readings": {"bazi": reading}})
        panel = read_json(changed["report_json"])["panels"][0]
        self.assertEqual(panel["reading_status"], "stale")
        self.assertIsNone(panel["traditional_interpretation"])

    def test_nonexistent_pointer_is_not_published_as_supported_interpretation(self):
        reading = copy.deepcopy(self.reading)
        reading["basis"] = [{"kind": "calculation", "pointer": "/does-not-exist"}]
        changed = workflow.run_project(self.root, patch={"readings": {"bazi": reading}})
        panel = read_json(changed["report_json"])["panels"][0]
        self.assertEqual(panel["reading_status"], "invalid_basis")
        self.assertIsNone(panel["traditional_interpretation"])

    def test_reference_escape_rejected_without_advancing_active_revision(self):
        reading = copy.deepcopy(self.reading)
        reading["basis"] = [{"kind": "reference", "file": "references/../../outside.md", "label": "不可用"}]
        with self.assertRaises(ProjectError):
            workflow.run_project(self.root, patch={"readings": {"bazi": reading}})
        self.assertEqual(workflow.project_status(self.root)["active_revision"], self.first["revision"])

    def test_explicit_null_clears_old_interpretations_and_optional_input_groups(self):
        self.apply_reading()
        changed = workflow.run_project(self.root, patch={"readings": None, "location": None,
            "settings": None, "options": None, "compare_profiles": None})
        panel = read_json(changed["report_json"])["panels"][0]
        self.assertEqual(changed["reused"], ["bazi"])
        self.assertEqual(panel["reading_status"], "not_provided")


if __name__ == "__main__":
    unittest.main()
