"""Independent workflow behavior tests against public APIs and actual artifacts.

No engine preparation or network request is permitted. Real engines must already exist.
Set MINGXUE_WORKFLOW_EVIDENCE_DIR to retain each test workspace for inspection.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import html
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", ROOT))
if not (SKILL / "scripts/workflow.py").is_file():
    SKILL = ROOT / "package/mingxue-master"
sys.dont_write_bytecode = True
sys.path.insert(0, str(SKILL / "scripts"))
import workflow
import ziwei
import astrology
from project_store import ProjectError, project_lock


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def png(color=0, width=60, height=40):
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress((b"\x00" + bytes([color] * width * 3)) * height)) + chunk(b"IEND", b""))


def birth_source(systems=None):
    return {"schema_version": 1,
            "birth": {"date": "2000-08-16", "time": "23:30:00", "timezone": "Asia/Shanghai", "gender": "female"},
            "location": {"latitude": 31.23, "longitude": 121.47},
            "topic": "结构核对", "question": "固定合成样例",
            "systems": systems or ["bazi", "ziwei", "astrology"], "profile": "baseline"}


def name_input():
    return {"surname": "李", "given": "明", "strokes": [7, 8], "surname_reading": "lǐ", "given_reading": "míng"}


class WorkflowV5Tests(unittest.TestCase):
    def setUp(self):
        evidence = os.environ.get("MINGXUE_WORKFLOW_EVIDENCE_DIR")
        if evidence:
            parent = Path(evidence)
            parent.mkdir(parents=True, exist_ok=True)
            self.folder = Path(tempfile.mkdtemp(prefix=self._testMethodName + "-", dir=parent))
        else:
            temporary = tempfile.TemporaryDirectory(prefix="mingxue-workflow-test-")
            self.addCleanup(temporary.cleanup)
            self.folder = Path(temporary.name)
        self.workspace = self.folder / "project"
        self.calls = []
        real_dispatch = workflow.dispatch

        def guarded_dispatch(spec, args, **kwargs):
            self.assertFalse(kwargs.get("prepare", False), "Calculations/probes must never prepare engines")
            self.assertFalse(str(spec.get("script", "")).startswith("prepare_"))
            self.calls.append({"system": spec["id"], "args": list(args), "prepare": False})
            return real_dispatch(spec, args, **kwargs)

        self.addCleanup(patch.stopall)
        patch.object(workflow, "dispatch", side_effect=guarded_dispatch).start()
        patch("urllib.request.urlopen", side_effect=AssertionError("Network is forbidden in workflow acceptance tests")).start()
        self.addCleanup(self.record_calls)

    def record_calls(self):
        if os.environ.get("MINGXUE_WORKFLOW_EVIDENCE_DIR"):
            (self.folder / "dispatch-audit.json").write_text(json.dumps(self.calls, ensure_ascii=False, indent=2), encoding="utf-8")

    def result(self, response, system):
        status = workflow.project_status(self.workspace)
        self.assertEqual(status["active_revision"], response["revision"])
        path = self.workspace / status["components"][system]["file"]
        self.assertEqual(sha(path), status["components"][system]["sha256"])
        return read(path)

    def require_engines(self, *systems):
        for system in systems:
            if system == "ziwei":
                directory = ziwei.engine_directory(os.environ.get("MINGXUE_TEST_ZIWEI_ENGINE"))
                if not directory.is_dir():
                    self.skipTest("Already-prepared local Ziwei engine is required; no install is allowed")
            else:
                directory = astrology.engine_directory(os.environ.get("MINGXUE_TEST_ASTRO_ENGINE"))
                if not directory.is_dir():
                    self.skipTest("Already-prepared local astronomy engine is required; no install is allowed")

    def test_first_run_produces_readable_report_json_and_consistent_component_files(self):
        self.require_engines("ziwei", "astrology")
        source = birth_source(["bazi", "ziwei", "astrology", "names"])
        source["name"] = name_input()
        response = workflow.run_project(self.workspace, source)
        self.assertEqual(response["status"], "ready")
        self.assertEqual(set(response["selected_systems"]), set(source["systems"]))
        self.assertEqual(set(response["states"].values()), {"ready"})
        self.assertEqual(response["reused"], [])
        self.assertGreater(Path(response["report"]).stat().st_size, 1000)
        self.assertIn("<html", Path(response["report"]).read_text(encoding="utf-8"))
        report = read(response["report_json"])
        self.assertEqual(report["revision"], response["revision"])
        self.assertEqual(report["topic"], source["topic"])
        self.assertEqual({panel["system"] for panel in report["panels"]}, set(source["systems"]))
        for panel in report["panels"]:
            self.assertEqual(sha(self.workspace / panel["result_file"]), panel["result_sha256"])
            self.assertTrue(panel["facts"])
        self.assertEqual(len(self.result(response, "ziwei")["chart"]["palaces"]), 12)
        self.assertEqual(len(self.result(response, "astrology")["candidates"][0]["planets"]), 10)

    def test_topic_change_reuses_actual_random_cards_and_cast_without_resampling(self):
        source = {"schema_version": 1, "systems": ["tarot", "iching"], "topic": "第一次主题",
                  "options": {"tarot": {"spread": "three"}, "iching": {"method": "coins"}}}
        first = workflow.run_project(self.workspace, source)
        cards, gua = self.result(first, "tarot"), self.result(first, "iching")
        self.assertEqual(len(cards["cards"]), 3)
        self.assertEqual(len(gua["lines_bottom_to_top"]), 6)
        call_count = len(self.calls)
        second = workflow.run_project(self.workspace, patch={"topic": "第二次主题", "question": "仅修改报告问题"})
        self.assertEqual(set(second["reused"]), {"tarot", "iching"})
        self.assertEqual(second["recomputed"], [])
        self.assertEqual(self.result(second, "tarot"), cards)
        self.assertEqual(self.result(second, "iching"), gua)
        self.assertEqual(len(self.calls), call_count, "An independent draw/cast was invoked during topic-only update")
        self.assertEqual(read(second["report_json"])["topic"], "第二次主题")
        history = workflow.project_status(self.workspace)["history"]
        self.assertEqual([item["validity"] for item in history], ["superseded", "active"])

    def test_birth_correction_refreshes_shared_chains_but_reuses_independent_name_cards_and_cast(self):
        self.require_engines("ziwei", "astrology")
        source = birth_source(["bazi", "ziwei", "astrology", "names", "tarot", "iching"])
        source["name"] = name_input()
        source["options"] = {"tarot": {"spread": "single"}, "iching": {"method": "coins"}}
        first = workflow.run_project(self.workspace, source)
        old = {system: self.result(first, system) for system in source["systems"]}
        second = workflow.run_project(self.workspace, patch={"birth": {"date": "2000-08-17"}})
        self.assertEqual(set(second["recomputed"]), {"bazi", "ziwei", "astrology"})
        self.assertEqual(set(second["reused"]), {"names", "tarot", "iching"})
        shared = self.result(second, "bazi")
        self.assertEqual(shared["input"]["date"], "2000-08-17")
        expected_hash = hashlib.sha256(json.dumps(shared["input"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        for system in ("ziwei", "astrology"):
            current = self.result(second, system)
            self.assertEqual(current["source_chart"]["input_hash"], expected_hash)
            self.assertNotEqual(current["source_chart"], old[system]["source_chart"])
        for system in ("names", "tarot", "iching"):
            self.assertEqual(self.result(second, system), old[system])

    def test_name_correction_preserves_birth_calculation(self):
        source = birth_source(["bazi", "names"])
        source["name"] = name_input()
        first = workflow.run_project(self.workspace, source)
        original = self.result(first, "bazi")
        second = workflow.run_project(self.workspace, patch={"name": {"given": "白", "given_reading": "bái", "strokes": [7, 5]}})
        self.assertEqual(second["reused"], ["bazi"])
        self.assertEqual(second["recomputed"], ["names"])
        self.assertEqual(self.result(second, "bazi"), original)
        self.assertEqual(self.result(second, "names")["name"], "李白")

    def test_candidate_name_comparison_contains_real_candidates_and_reuses_birth_on_edit(self):
        source = birth_source(["bazi", "names"])
        source["name"] = {"surname": "李", "surname_reading": "lǐ", "candidates": [
            {"given": "明", "given_reading": "míng"}, {"given": "白", "given_reading": "bái"}]}
        first = workflow.run_project(self.workspace, source)
        original_birth = self.result(first, "bazi")
        comparison = self.result(first, "names")
        self.assertEqual([item["name"] for item in comparison["candidates"]], ["李明", "李白"])
        self.assertTrue(all(item["five_grids"] for item in comparison["candidates"]))
        self.assertNotEqual(comparison["candidates"][0]["five_grids"], comparison["candidates"][1]["five_grids"])
        second = workflow.run_project(self.workspace, patch={"name": {"candidates": [
            {"given": "白", "given_reading": "bái"}]}})
        self.assertEqual(second["reused"], ["bazi"])
        self.assertEqual(second["recomputed"], ["names"])
        self.assertEqual(self.result(second, "bazi"), original_birth)
        self.assertEqual([item["name"] for item in self.result(second, "names")["candidates"]], ["李白"])

    def test_missing_engine_is_partial_then_same_input_retries_after_local_cache_restoration(self):
        self.require_engines("ziwei")
        existing = ziwei.engine_directory(os.environ.get("MINGXUE_TEST_ZIWEI_ENGINE"))
        recovered = self.folder / "restored-engine"
        source = birth_source(["bazi", "ziwei"])
        source["options"] = {"ziwei": {"engine_dir": str(recovered)}}
        first = workflow.run_project(self.workspace, source)
        self.assertEqual(first["status"], "partial")
        self.assertNotEqual(first["states"]["ziwei"], "ready")
        failed = self.result(first, "ziwei")
        self.assertNotIn("chart", failed)
        shutil.copytree(existing, recovered)
        second = workflow.run_project(self.workspace, source)
        self.assertEqual(second["states"]["ziwei"], "ready")
        self.assertIn("ziwei", second["recomputed"])
        self.assertEqual(len(self.result(second, "ziwei")["chart"]["palaces"]), 12)
        self.assertEqual(second["reused"], ["bazi"])

    def test_explicit_null_time_preserves_candidates_and_refuses_complete_ziwei(self):
        self.require_engines("ziwei", "astrology")
        first = workflow.run_project(self.workspace, birth_source())
        response = workflow.run_project(self.workspace, patch={"birth": {"time": None}})
        self.assertEqual(response["status"], "partial")
        self.assertEqual(set(response["recomputed"]), {"bazi", "ziwei", "astrology"})
        bazi = self.result(response, "bazi")
        self.assertFalse(bazi["time_known"])
        self.assertIsNone(bazi["input"]["time"])
        self.assertIsNone(bazi["pillars"]["hour"])
        self.assertGreaterEqual(len(bazi["candidates"]), 12)
        self.assertNotEqual(response["states"]["ziwei"], "ready")
        self.assertNotIn("chart", self.result(response, "ziwei"))
        astro = self.result(response, "astrology")
        self.assertEqual(astro["candidates"], [])
        self.assertTrue(astro["sun_ranges"])
        self.assertNotEqual(first["revision"], response["revision"])

    def test_conflicting_longitudes_are_rejected_before_workspace_writes(self):
        source = birth_source(["bazi"])
        source["birth"]["longitude"] = 100
        with self.assertRaises((ProjectError, ValueError)):
            workflow.run_project(self.workspace, source)
        self.assertFalse(self.workspace.exists())

    def test_unknown_fields_wrong_types_and_duplicate_routes_are_rejected(self):
        original = birth_source(["bazi"])
        mutations = [{"unrecognized": 1}, {"schema_version": True}, {"systems": ["bazi", "八字"]},
                     {"systems": ["imaginary"]}, {"birth": {"date": "2000-08-16", "time": 23}},
                     {"settings": {"bazi": {"sect": True}}}, {"options": {"tarot": {"auto_publish": True}}}]
        for index, mutation in enumerate(mutations):
            source = {**copy.deepcopy(original), **mutation}
            workspace = self.folder / ("invalid-" + str(index))
            with self.subTest(mutation=mutation), self.assertRaises((ProjectError, ValueError)):
                workflow.run_project(workspace, source)
            self.assertFalse(workspace.exists())

    def test_invalid_patch_does_not_change_active_revision_or_create_new_revision(self):
        first = workflow.run_project(self.workspace, birth_source(["bazi"]))
        pointer = (self.workspace / "project.json").read_bytes()
        versions = set((self.workspace / "versions").iterdir())
        with self.assertRaises((ProjectError, ValueError)):
            workflow.run_project(self.workspace, patch={"settings": {"bazi": {"sect": "1"}}})
        self.assertEqual((self.workspace / "project.json").read_bytes(), pointer)
        self.assertEqual(set((self.workspace / "versions").iterdir()), versions)
        self.assertEqual(workflow.project_status(self.workspace)["active_revision"], first["revision"])

    def test_lock_conflict_refuses_parallel_update_and_preserves_report(self):
        first = workflow.run_project(self.workspace, birth_source(["bazi"]))
        pointer = (self.workspace / "project.json").read_bytes()
        original_report = Path(first["report"]).read_bytes()
        with project_lock(self.workspace):
            with self.assertRaises((ProjectError, ValueError)):
                workflow.run_project(self.workspace, patch={"topic": "并发修改"})
        self.assertEqual((self.workspace / "project.json").read_bytes(), pointer)
        self.assertEqual(Path(first["report"]).read_bytes(), original_report)

    def test_interrupted_report_does_not_publish_head_and_orphan_number_is_not_reused(self):
        first = workflow.run_project(self.workspace, birth_source(["bazi"]))
        pointer = (self.workspace / "project.json").read_bytes()
        with patch.object(workflow, "build_report", side_effect=RuntimeError("injected report interruption")):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                workflow.run_project(self.workspace, patch={"topic": "处理中断"})
        self.assertEqual((self.workspace / "project.json").read_bytes(), pointer)
        self.assertEqual(workflow.project_status(self.workspace)["active_revision"], first["revision"])
        reserved = {path.name for path in (self.workspace / "versions").iterdir()}
        self.assertGreater(len(reserved), 1)
        second = workflow.run_project(self.workspace, patch={"topic": "恢复后版本"})
        self.assertNotIn(second["revision"], reserved)
        self.assertGreater(int(second["revision"][1:]), max(int(name[1:]) for name in reserved))
        self.assertEqual(len(workflow.project_status(self.workspace)["history"]), 2)

    def test_tampered_artifact_refuses_status_and_update_without_overwriting_head(self):
        first = workflow.run_project(self.workspace, birth_source(["bazi"]))
        pointer = (self.workspace / "project.json").read_bytes()
        status = workflow.project_status(self.workspace)
        target = self.workspace / status["components"]["bazi"]["file"]
        target.write_text('{"tampered":true}', encoding="utf-8")
        with self.assertRaises((ProjectError, ValueError)):
            workflow.project_status(self.workspace)
        with self.assertRaises((ProjectError, ValueError)):
            workflow.run_project(self.workspace, patch={"topic": "不能掩盖篡改"})
        self.assertEqual((self.workspace / "project.json").read_bytes(), pointer)
        self.assertTrue(Path(first["report"]).is_file())

    def test_workspace_isolation_is_bidirectional_for_resources_and_selected_external_cache(self):
        protected = self.folder / "protected"
        protected.mkdir()
        source = birth_source(["bazi"])
        with patch.dict(os.environ, {"MINGXUE_RESOURCE_DIR": str(protected)}):
            for workspace in (protected, protected / "project", self.folder):
                with self.subTest(workspace=workspace), self.assertRaises((ProjectError, ValueError)):
                    workflow.run_project(workspace, source)
            self.assertFalse((self.folder / "project.json").exists())
        source["options"] = {"ziwei": {"engine_dir": str(self.workspace / "cache")}}
        source["systems"] = ["ziwei"]
        with self.assertRaises((ProjectError, ValueError)):
            workflow.run_project(self.workspace, source)
        self.assertFalse(self.workspace.exists())
        with self.assertRaises((ProjectError, ValueError)):
            workflow.run_project(SKILL / "test-project-must-not-exist", birth_source(["bazi"]))

    def test_same_input_profile_comparison_contains_real_alternate_chart(self):
        source = birth_source(["bazi"])
        source["compare_profiles"] = ["bazi-23h"]
        response = workflow.run_project(self.workspace, source)
        base = self.result(response, "bazi")
        comparisons = read(response["report_json"])["comparisons"]
        self.assertEqual(len(comparisons), 1)
        item = comparisons[0]
        alternate = read(self.workspace / item["result_file"])
        self.assertNotEqual(base["pillars"]["day"], alternate["pillars"]["day"])
        self.assertEqual(base["input"]["date"], alternate["input"]["date"])
        self.assertEqual(base["input"]["time"], alternate["input"]["time"])
        self.assertFalse(item["difference"]["equal_chart"])
        self.assertGreater(item["difference"]["counts"]["convention_changes"], 0)
        self.assertGreater(item["difference"]["counts"]["chart_changes"], 0)

    def test_visual_snapshot_and_annotations_are_bound_to_exact_image_contents(self):
        image = self.folder / "observation.png"
        image.write_bytes(png())
        original_bytes, original_sha = image.read_bytes(), sha(image)
        annotations = self.folder / "annotations.json"
        annotations.write_text(json.dumps({"system": "palm", "image_sha256": original_sha,
            "observation_source": "user_visual_observation", "annotations": [
                {"region": "palm_outline", "geometry": "polyline", "points": [[1, 1], [20, 30]]}]}), encoding="utf-8")
        source = {"schema_version": 1, "systems": ["palm"],
                  "options": {"palm": {"image": str(image), "annotations": str(annotations)}}}
        first = workflow.run_project(self.workspace, source)
        payload = self.result(first, "palm")
        self.assertEqual(payload["image"]["sha256"], original_sha)
        self.assertFalse(payload["image_content_analysis"])
        self.assertEqual(payload["annotation"]["status"], "created")
        overlay = Path(first["report"]).parent / payload["annotation"]["file"]
        overlay_text = overlay.read_text(encoding="utf-8")
        self.assertIn(original_sha, overlay_text)
        self.assertIn(base64.b64encode(original_bytes).decode(), overlay_text)
        first_input = read(Path(first["report"]).with_name("input.json"))
        snapshot = Path(first_input["options"]["palm"]["image"])
        self.assertNotEqual(snapshot, image)
        self.assertEqual(snapshot.read_bytes(), original_bytes)
        image.write_bytes(png(color=255))
        second = workflow.run_project(self.workspace, source)
        current = self.result(second, "palm")
        self.assertNotEqual(current["image"]["sha256"], original_sha)
        self.assertEqual(current["annotation"]["status"], "not_generated")
        self.assertEqual(second["status"], "partial")
        self.assertEqual(snapshot.read_bytes(), original_bytes)
        self.assertEqual(overlay.read_text(encoding="utf-8"), overlay_text)

    def test_html_escapes_user_controlled_topic_question_and_result_text(self):
        attack = '<script>alert("synthetic")</script><img src=x onerror=alert(1)>'
        source = {"schema_version": 1, "topic": attack, "question": attack, "systems": ["tarot"],
                  "options": {"tarot": {"spread": "single", "seed": 7, "question": attack}}}
        response = workflow.run_project(self.workspace, source)
        rendered = Path(response["report"]).read_text(encoding="utf-8")
        self.assertNotIn(attack, rendered)
        self.assertNotIn("<img src=x", rendered)
        self.assertIn(html.escape(attack), rendered)
        self.assertEqual(read(response["report_json"])["topic"], attack)
        self.assertEqual(self.result(response, "tarot")["question"], attack)

    def test_cli_run_update_status_roundtrip_and_duplicate_json_key_rejection(self):
        source = self.folder / "source.json"
        source.write_text(json.dumps(birth_source(["bazi"])), encoding="utf-8")
        patch_file = self.folder / "patch.json"
        patch_file.write_text('{"topic":"CLI更新"}', encoding="utf-8")

        def cli(*args):
            return subprocess.run([sys.executable, "-X", "utf8", "-B", str(SKILL / "scripts" / "workflow.py"),
                                   *args, "--workspace", str(self.workspace)], capture_output=True, text=True, encoding="utf-8", timeout=60)

        first = cli("run", "--input", str(source))
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        update = cli("update", "--patch", str(patch_file))
        self.assertEqual(update.returncode, 0, update.stderr + update.stdout)
        status = cli("status")
        self.assertEqual(status.returncode, 0)
        self.assertEqual(json.loads(status.stdout)["active_revision"], json.loads(update.stdout)["revision"])
        self.assertEqual(json.loads(update.stdout)["reused"], ["bazi"])
        before = (self.workspace / "project.json").read_bytes()
        patch_file.write_text('{"topic":"one","topic":"two"}', encoding="utf-8")
        invalid = cli("update", "--patch", str(patch_file))
        self.assertEqual(invalid.returncode, 2)
        self.assertEqual(json.loads(invalid.stdout)["status"], "error")
        self.assertEqual((self.workspace / "project.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
