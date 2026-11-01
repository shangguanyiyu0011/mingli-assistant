"""Form contract, no implicit draw, isolated real personal/pair publication."""
import copy
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get('MINGXUE_TEST_SKILL_ROOT') or (HERE/'package/mingxue-master' if (HERE/'package/mingxue-master').is_dir() else HERE))
sys.path.insert(0, str(SKILL / "scripts"))
import intake_flow as intake
import workflow


def request(mode="single", systems="auto"):
    people = [{"person": {"name": "甲方合成示例"},
               "birth": {"date": "2000-08-16", "calendar": "solar", "timezone": "Asia/Shanghai", "time": None}}]
    if mode == "pair":
        people.append({"person": {"name": "乙方合成示例"},
                       "birth": {"date": "1997-03-24", "calendar": "solar", "timezone": "Asia/Shanghai", "time": None}})
    return {"mode": mode, "people": people, "preferences": {"systems": systems, "depth": "brief"}}


def committed(job, label="a"):
    project = job / ("project-" + label)
    state = workflow.project_status(project)
    directory = Path(state["report"]).parent
    load = lambda path: json.loads(path.read_text(encoding="utf-8"))
    return load(directory / "input.json"), load(directory / "report.json"), {
        name: load(project / record["file"]) for name, record in state["components"].items()}


class FormPolicyTests(unittest.TestCase):
    def test_unknown_clock_keeps_null_and_never_splits_person_label(self):
        incoming = request()
        incoming["people"][0]["person"]["name"] = "王小明"
        saved = copy.deepcopy(incoming)
        plan = intake.plan_request(incoming)
        flow = plan["people"][0]["workflow_input"]
        self.assertEqual(incoming, saved)
        self.assertIsNone(flow["birth"]["time"])
        self.assertEqual(flow["systems"], ["bazi", "numerology", "sukuyo"])
        self.assertNotIn("name", flow)
        self.assertNotIn("ziwei", flow["systems"])

    def test_auto_adds_only_supported_conditions_and_explicit_separate_name(self):
        incoming = request()
        person = incoming["people"][0]
        person["birth"].update(time="08:26", gender="female")
        person["location"] = {"latitude": 31.23, "longitude": 121.47}
        person["name"] = {"surname": "王", "given": "明", "strokes": [4, 8]}
        flow = intake.plan_request(incoming)["people"][0]["workflow_input"]
        self.assertEqual(set(flow["systems"]), {"bazi", "numerology", "sukuyo", "ziwei", "astrology", "names"})
        self.assertEqual(flow["name"], person["name"])
        self.assertFalse(flow["deferred"])

    def test_questionnaire_cannot_overwrite_birth_and_preserves_readable_answers(self):
        incoming = request()
        incoming["preferences"].update(question="如何安排学习？", answers={"修正生日": "其实想换职业", "关注": ["沟通", "时间安排"]})
        flow = intake.plan_request(incoming)["people"][0]["workflow_input"]
        self.assertEqual(flow["birth"]["date"], "2000-08-16")
        self.assertEqual(flow["questionnaire"], incoming["preferences"]["answers"])
        self.assertEqual(flow["question"], "如何安排学习？")

    def test_invalid_second_person_is_rejected_before_any_write_or_execution(self):
        incoming = request("pair")
        incoming["people"][1]["birth"]["date"] = "2001-02-30"
        with tempfile.TemporaryDirectory() as temporary, patch.object(workflow, "run_project") as run:
            root = Path(temporary) / "never-created"
            result = intake.submit(root, incoming)
            self.assertEqual(result["status"], "invalid_input")
            self.assertFalse(root.exists())
            self.assertIsNone(result["job_id"])
            run.assert_not_called()

    def test_user_path_engine_and_save_parameters_are_rejected(self):
        variants = []
        for key in ("reports_root", "workspace", "output"):
            value = request(); value[key] = r"C:\untrusted\file"; variants.append(value)
        for system, key in (("astrology", "engine_dir"), ("names", "dictionary_dir"), ("palm", "image"), ("iching", "cast_chart")):
            value = request(); value["method_options"] = {system: {key: r"C:\untrusted\file"}}; variants.append(value)
        value = request(); value["people"][0]["birth"]["longitude"] = 120; variants.append(value)
        for incoming in variants:
            with self.subTest(incoming=incoming), tempfile.TemporaryDirectory() as temporary, patch.object(workflow, "run_project") as run:
                root = Path(temporary) / "reports"
                result = intake.submit(root, incoming)
                self.assertEqual(result["status"], "invalid_input")
                self.assertFalse(root.exists())
                run.assert_not_called()

    def test_strict_numbers_unknown_keys_and_cross_rules_preflight(self):
        variants = []
        for location in ({"latitude": float("nan"), "longitude": 120}, {"latitude": True, "longitude": 120}, {"longitude": 120}):
            value = request(); value["people"][0]["location"] = location; variants.append(value)
        for options in ({"bazi": {"sect": True}}, {"tarot": {"seed": True}}, {"bazi": {"true_solar": 1}},
                        {"numerology": {"latin_name": "汉字"}}, {"ziwei": {"scope": "daily", "target_time": "09:00", "target_time_index": 4}},
                        {"ziwei": {"target_date": "2026-10-31"}}, {"sukuyo": {"partner": {"month": 4}}},
                        {"jinkoujue": {"mode": "manual", "month_general_rule": "solar_qi"}},
                        {"jinkoujue": {"mode": "datetime", "month_general_rule": "explicit"}}, {"tarot": {"unexpected": 1}}):
            value = request(); value["method_options"] = options; variants.append(value)
        value = request(); value["preferences"]["virtual_draws"] = "true"; variants.append(value)
        for incoming in variants:
            with self.subTest(incoming=incoming), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "reports"
                self.assertEqual(intake.submit(root, incoming)["status"], "invalid_input")
                self.assertFalse(root.exists())

    def test_invalid_lunar_day_and_nonexistent_clock_fail_before_jobs(self):
        variants = []
        value = request(); value["people"][0]["birth"].update(date="2000-02-30", calendar="lunar", leap=True); variants.append(value)
        value = request(); value["people"][0]["birth"].update(date="2024-03-10", time="02:30", timezone="America/New_York"); variants.append(value)
        value = request(); value["method_options"] = {"bazi": {"fold": 1}}; variants.append(value)
        for incoming in variants:
            with self.subTest(incoming=incoming), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "reports"
                self.assertEqual(intake.submit(root, incoming)["status"], "invalid_input")
                self.assertFalse(root.exists())

    def test_missing_basics_and_person_count_have_no_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "reports"
            incoming = request(); del incoming["people"][0]["birth"]["timezone"]
            self.assertEqual(intake.submit(root, incoming)["status"], "needs_input")
            incoming = request("pair"); incoming["people"].pop()
            self.assertEqual(intake.submit(root, incoming)["status"], "invalid_input")
            self.assertFalse(root.exists())

    def test_all_25_selected_keep_every_entry_and_missing_methods_are_deferred(self):
        systems = [item["id"] for item in intake.registry()]
        self.assertEqual(len(systems), 25)
        flow = intake.plan_request(request(systems=systems))["people"][0]["workflow_input"]
        self.assertEqual(flow["systems"], systems)
        self.assertEqual(set(flow["deferred"]), set(systems) - {"bazi", "numerology", "sukuyo"})
        self.assertTrue(all(item["reason"] and item["required_inputs"] for item in flow["deferred"].values()))

    def test_missing_or_unauthorized_virtual_methods_do_not_draw_even_with_seed(self):
        systems = ["iching", "yilin", "lingqijing", "tarot", "lenormand", "geomancy"]
        incoming = request(systems=systems)
        incoming["method_options"] = {"iching": {"method": "coins", "seed": 9}, "yilin": {"method": "coins", "seed": 9},
                                      "lingqijing": {"method": "toss", "seed": 9}, "tarot": {"seed": 9},
                                      "lenormand": {"seed": 9}, "geomancy": {"seed": 9}}
        with patch("iching.coin_cast", side_effect=AssertionError("unexpected draw")), \
             patch("classic_oracles._sample_bits", side_effect=AssertionError("unexpected draw")), \
             patch("symbolic.tarot", side_effect=AssertionError("unexpected draw")):
            plan = intake.plan_request(incoming)
        self.assertEqual(set(plan["people"][0]["workflow_input"]["deferred"]), set(systems))
        self.assertTrue(all(item["optional"] for item in plan["questions"]))

    def test_manual_zero_boundary_chess_and_real_lines_are_not_virtual_draws(self):
        incoming = request(systems=["yilin", "lingqijing", "iching", "xiaoliuren"])
        incoming["method_options"] = {"yilin": {"method": "pair", "base": 1, "changed": 64},
                                      "lingqijing": {"method": "counts", "counts": [0, 4, 0]},
                                      "iching": {"lines": [6, 7, 8, 9, 7, 8]},
                                      "xiaoliuren": {"mode": "numbers", "numbers": [3, 5, 7]}}
        flow = intake.plan_request(incoming)["people"][0]["workflow_input"]
        self.assertFalse(flow["deferred"])
        self.assertEqual(flow["options"]["lingqijing"]["params"]["counts"], [0, 4, 0])
        self.assertEqual(flow["options"]["iching"]["method"], "manual")
        self.assertNotIn("cast_date", flow["options"]["iching"])

    def test_cast_is_explicit_and_does_not_borrow_birth_or_birth_coordinates(self):
        incoming = request(systems=["horary", "taiyi", "jinkoujue", "electional", "xiaoliuren"])
        incoming["people"][0]["birth"].update(time="08:26", gender="male")
        incoming["people"][0]["location"] = {"latitude": 31, "longitude": 121}
        incoming["preferences"]["question"] = "如何准备考试？"
        flow = intake.plan_request(incoming)["people"][0]["workflow_input"]
        self.assertEqual(set(flow["deferred"]), set(incoming["preferences"]["systems"]))
        self.assertNotIn("date", flow["options"]["horary"]["params"])
        incoming["preferences"]["cast"] = {"date": "2026-10-31", "time": "18:00", "timezone": "Asia/Shanghai"}
        incoming["method_options"] = {"taiyi": {"mode": "day", "method": 0}, "jinkoujue": {"earth_branch": "卯"}}
        flow = intake.plan_request(incoming)["people"][0]["workflow_input"]
        self.assertEqual(set(flow["deferred"]), {"horary"})
        self.assertNotIn("latitude", flow["options"]["horary"]["params"])
        self.assertEqual(flow["options"]["taiyi"]["params"]["date"], "2026-10-31")
        self.assertEqual(flow["birth"]["date"], "2000-08-16")

    def test_horary_explicit_event_coordinates_conflicts_are_rejected(self):
        incoming = request(systems=["horary"])
        incoming["preferences"].update(question="独立问题", cast={"date": "2026-10-31", "time": "18:00", "timezone": "Asia/Shanghai", "latitude": 30, "longitude": 120})
        flow = intake.plan_request(incoming)["people"][0]["workflow_input"]
        self.assertFalse(flow["deferred"])
        self.assertEqual(flow["options"]["horary"]["params"]["latitude"], 30)
        incoming["method_options"] = {"horary": {"latitude": 29, "longitude": 120}}
        with self.assertRaises(intake.IntakeError):
            intake.plan_request(incoming)

    def test_ziwei_flow_missing_target_clock_is_deferred(self):
        incoming = request(systems=["ziwei"])
        incoming["people"][0]["birth"].update(time="08:26", gender="female")
        incoming["method_options"] = {"ziwei": {"scope": "daily", "target_date": "2026-10-31"}}
        flow = intake.plan_request(incoming)["people"][0]["workflow_input"]
        self.assertIn("ziwei", flow["deferred"])
        incoming["method_options"]["ziwei"]["target_time_index"] = 0
        self.assertFalse(intake.plan_request(incoming)["people"][0]["workflow_input"]["deferred"])

    def test_root_isolation_is_bidirectional(self):
        with tempfile.TemporaryDirectory() as temporary:
            protected = Path(temporary) / "protected"
            protected.mkdir()
            with patch.object(intake, "protected_output_roots", return_value=(protected,)), patch.object(workflow, "run_project") as run:
                for root in (protected, protected / "reports", protected.parent):
                    self.assertEqual(intake.submit(root, request())["status"], "invalid_input")
                self.assertEqual(list(protected.iterdir()), [])
                run.assert_not_called()
            with self.assertRaises(intake.IntakeError):
                intake._reports_root("relative-reports")

    def test_single_file_check_rejects_relative_and_external_dependencies(self):
        valid = '<html><style>.x{background:url(data:image/png;base64,AA==)}</style><a href="#local">x</a></html>'
        self.assertEqual(intake._offline_html(valid), valid)
        for body in ('<img src="x.png">', '<link href="https://example.invalid/a.css">', '<style>.x{background:url(images/a.png)}</style>', '<style>@import "a.css";</style>', '<img srcset="data:image/png;base64,AA==, https://example.invalid/x.png 2x">'):
            with self.subTest(body=body), self.assertRaises(intake.IntakeError):
                intake._offline_html("<html>" + body + "</html>")

    def test_filesystem_and_internal_errors_never_leak_paths_in_response(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "reports"
            secret = str(root / "secret-engine")
            planned = intake.plan_request(request())
            with patch.object(intake, "plan_request", return_value=planned), patch.object(Path, "mkdir", side_effect=OSError(secret)):
                result = intake.submit(root, request())
            self.assertEqual(result["status"], "error")
            self.assertNotIn(secret, json.dumps(result))
            with patch.object(workflow, "run_project", side_effect=RuntimeError(secret)):
                result = intake.submit(root, request())
            self.assertEqual(result["status"], "error")
            self.assertNotIn(secret, json.dumps(result))
            self.assertFalse(list((root / result["job_id"]).glob("*.html")))


class ActualReportTests(unittest.TestCase):
    def assert_public_files(self, root, response, expected):
        self.assertIn(response["status"], ("ready", "partial"), response)
        self.assertRegex(response["job_id"], r"^[0-9a-f]{32}$")
        self.assertEqual({item["filename"] for item in response["files"]}, set(expected))
        self.assertNotIn(str(root), json.dumps(response, ensure_ascii=False))
        job = root / response["job_id"]
        for item in response["files"]:
            self.assertEqual(item["url"], "/files/" + response["job_id"] + "/" + item["filename"])
            page = (job / item["filename"]).read_text(encoding="utf-8")
            self.assertEqual(intake._offline_html(page), page)
            self.assertGreater(len(page), 4000)
        self.assertNotIn("submitted-input.json", {item["filename"] for item in response["files"]})
        return job

    def test_actual_single_is_committed_with_candidates_and_default_no_prepare(self):
        incoming = request()
        incoming["people"][0]["person"]["name"] = '甲<script>alert("x")</script>'
        incoming["preferences"]["answers"] = {"当前关注": ["学习", "安排"]}
        original = workflow.run_project
        with tempfile.TemporaryDirectory() as temporary, patch.object(workflow, "run_project", wraps=original) as run:
            root = Path(temporary) / "reports"
            result = intake.submit(root, incoming)
            job = self.assert_public_files(root, result, ["personal-a.html"])
            self.assertIs(run.call_args.kwargs["prepare_engines"], False)
            source, report, payloads = committed(job)
            self.assertIsNone(source["birth"]["time"])
            self.assertGreater(len(payloads["bazi"]["candidates"]), 1)
            self.assertEqual(source["questionnaire"], incoming["preferences"]["answers"])
            self.assertEqual(source["person"]["name"], incoming["people"][0]["person"]["name"])
            page = (job / "personal-a.html").read_text(encoding="utf-8")
            self.assertNotIn('<script>alert("x")</script>', page)
            self.assertIn("&lt;script&gt;", page)
            self.assertTrue(report["panels"])

    def test_actual_pair_reads_two_separate_commits_and_preserves_original_births(self):
        incoming = request("pair")
        incoming["preferences"]["relationship"] = "合作伙伴"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "reports"
            result = intake.submit(root, incoming)
            job = self.assert_public_files(root, result, ["personal-a.html", "personal-b.html", "pair.html"])
            a, _, ap = committed(job, "a")
            b, _, bp = committed(job, "b")
            self.assertEqual(a["birth"]["date"], "2000-08-16")
            self.assertEqual(b["birth"]["date"], "1997-03-24")
            self.assertNotEqual(ap["bazi"]["input"]["date"], bp["bazi"]["input"]["date"])
            self.assertNotEqual({item["pillars"]["day"] for item in ap["bazi"]["candidates"]},
                                {item["pillars"]["day"] for item in bp["bazi"]["candidates"]})
            comparison = json.loads((job / "private-pair-comparison.json").read_text(encoding="utf-8"))
            self.assertEqual(comparison["relationship"], "合作伙伴")
            self.assertEqual(comparison["people"], ["甲方合成示例", "乙方合成示例"])
            self.assertEqual(comparison["person_records"][0]["birth"]["date"], a["birth"]["date"])
            self.assertTrue(any(panel["facts"] for panel in comparison["panels"]))
            self.assertNotEqual(json.loads((job / "project-a" / "project.json").read_text(encoding="utf-8"))["project_id"],
                                json.loads((job / "project-b" / "project.json").read_text(encoding="utf-8"))["project_id"])

    def test_actual_all_25_retains_missing_entries_without_casting(self):
        incoming = request(systems=[item["id"] for item in intake.registry()])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "reports"
            result = intake.submit(root, incoming)
            job = self.assert_public_files(root, result, ["personal-a.html"])
            self.assertEqual(result["status"], "partial")
            source, _, payloads = committed(job)
            self.assertEqual(len(payloads), 25)
            for system in source["deferred"]:
                self.assertEqual(payloads[system]["status"], "needs_input", system)
                self.assertNotIn("cast_record", payloads[system])
                self.assertNotIn("cards", payloads[system])
            self.assertEqual({item["system"] for item in result["questions"]}, set(source["deferred"]))

    def test_actual_authorized_virtual_draws_have_replayable_records(self):
        incoming = request(systems=["yilin", "lingqijing"])
        incoming["preferences"]["virtual_draws"] = True
        incoming["method_options"] = {"yilin": {"method": "coins", "seed": 314159}, "lingqijing": {"method": "toss", "seed": 271828}}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "reports"
            first = intake.submit(root, incoming)
            one = self.assert_public_files(root, first, ["personal-a.html"])
            second = intake.submit(root, incoming)
            two = self.assert_public_files(root, second, ["personal-a.html"])
            self.assertNotEqual(first["job_id"], second["job_id"])
            _, _, a = committed(one); _, _, b = committed(two)
            for system in ("yilin", "lingqijing"):
                self.assertEqual(a[system]["status"], "calculated")
                self.assertEqual(a[system]["cast_record"], b[system]["cast_record"])
                self.assertEqual(a[system]["oracle"], b[system]["oracle"])
                self.assertNotIn("bazi", a)

    def test_actual_missing_solar_longitude_defers_shared_charts_and_keeps_independent_results(self):
        incoming = request()
        incoming["people"][0]["birth"].update(time="08:26", gender="female")
        incoming["method_options"] = {"bazi": {"true_solar": True}}
        plan = intake.plan_request(incoming)
        flow = plan["people"][0]["workflow_input"]
        self.assertEqual(set(flow["deferred"]), {"bazi", "ziwei"})
        self.assertIs(flow["settings"]["bazi"]["true_solar"], True)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "reports"
            result = intake.submit(root, incoming)
            job = self.assert_public_files(root, result, ["personal-a.html"])
            self.assertEqual(result["status"], "partial")
            source, _, payloads = committed(job)
            self.assertIs(source["settings"]["bazi"]["true_solar"], True)
            self.assertEqual(payloads["bazi"]["status"], "needs_input")
            self.assertEqual(payloads["ziwei"]["status"], "needs_input")
            self.assertEqual(payloads["sukuyo"]["status"], "calculated")
            self.assertIn("life_path", payloads["numerology"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
