"""Synthetic shichen inputs retain real intervals through intake and workflow."""
import copy
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
SKILL = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(SKILL / "scripts"))
import astrology
import case_lookup
import chart
import intake_flow
import pair_analysis
import workflow
import ziwei


def request(branch="午", systems=None):
    return {"mode": "single", "people": [{"person": {"name": "时辰合成样例"},
        "birth": {"date": "2000-08-16", "time": None, "shichen": branch,
                  "calendar": "solar", "timezone": "Asia/Shanghai", "gender": "female"},
        "location": {"latitude": 31.23, "longitude": 121.47}}],
        "preferences": {"systems": systems or ["bazi"], "depth": "brief"}}


def build(branch="午", day="2000-08-16", **kwargs):
    return chart.build_chart(day, shichen=branch, timezone="Asia/Shanghai", **kwargs)


def duration(value):
    return sum((datetime.fromisoformat(r["end"]) - datetime.fromisoformat(r["start"])).total_seconds()
               for r in value["time_context"]["valid_utc_ranges"])


class ShichenTests(unittest.TestCase):
    def test_noon_is_a_full_interval_with_determined_pillars_and_no_exact_yun(self):
        value = build(gender="female")
        self.assertIsNone(value["input"]["time"])
        self.assertEqual(value["input"]["shichen"], "午")
        self.assertTrue(value["time_known"])
        self.assertEqual(value["time_precision"], "shichen")
        self.assertEqual(duration(value), 7200)
        self.assertEqual(value["time_context"]["valid_utc_ranges"], [{
            "start": "2000-08-16T03:00:00+00:00", "end": "2000-08-16T05:00:00+00:00", "end_exclusive": True}])
        self.assertTrue(all(value["pillars"].values()))
        self.assertEqual(value["pillars"], chart.build_chart("2000-08-16", "11:00:00", timezone="Asia/Shanghai")["pillars"])
        self.assertEqual(value["yun"]["status"], "not_calculated")
        self.assertNotIn("start_solar", value["yun"])
        self.assertNotIn("start_utc", value["yun"])

    def test_every_branch_uses_the_actual_two_hour_range(self):
        for index, branch in enumerate(chart.ZHI):
            value = build(branch)
            self.assertEqual(duration(value), 7200, branch)
            if index:
                ranges = value["candidates"][0]["time_ranges"]
                self.assertTrue(ranges[0]["original_start"].endswith(f"{index * 2 - 1:02d}:00:00"))

    def test_zi_keeps_early_and_late_on_same_civil_date(self):
        for sect in (1, 2):
            value = build("子", sect=sect)
            self.assertEqual(duration(value), 7200)
            self.assertEqual(value["time_context"]["valid_utc_ranges"], [
                {"start": "2000-08-15T16:00:00+00:00", "end": "2000-08-15T17:00:00+00:00", "end_exclusive": True},
                {"start": "2000-08-16T15:00:00+00:00", "end": "2000-08-16T16:00:00+00:00", "end_exclusive": True}])
            self.assertIn("early_late_zi_unresolved", [x["code"] for x in value["uncertainty"]])
            self.assertIsNone(value["pillars"]["hour"])
            self.assertEqual(value["pillars"]["day"] is None, sect == 1)
            with self.assertRaises(ziwei.ZiweiError) as caught:
                ziwei.resolve_chart(value)
            self.assertEqual(caught.exception.status, "ambiguous_input")

    def test_lichun_boundary_preserves_both_years_and_months(self):
        unknown = chart.build_chart("2024-02-04", timezone="Asia/Shanghai")
        term = next(x for x in unknown["solar_terms_on_date"] if x["name"] == "立春")
        hour = datetime.fromisoformat(term["local_civil_clock"]).hour
        branch = chart.ZHI[((hour + 1) // 2) % 12]
        value = build(branch, "2024-02-04")
        self.assertEqual(duration(value), 7200)
        self.assertIsNone(value["pillars"]["year"])
        self.assertIsNone(value["pillars"]["month"])
        self.assertIsNotNone(value["pillars"]["day"])
        self.assertIsNotNone(value["pillars"]["hour"])
        self.assertEqual(len(value["candidates"]), 2)
        with self.assertRaises(ziwei.ZiweiError) as caught:
            ziwei.resolve_chart(value)
        self.assertEqual(caught.exception.status, "ambiguous_input")

    def test_historical_dst_gap_and_fold_are_real_intervals(self):
        spring = chart.build_chart("2024-03-10", shichen="丑", timezone="America/New_York")
        self.assertEqual(duration(spring), 3600)
        self.assertIn("shichen_has_clock_gap", [x["code"] for x in spring["uncertainty"]])
        autumn = chart.build_chart("2024-11-03", shichen="丑", timezone="America/New_York")
        self.assertEqual(duration(autumn), 10800)
        self.assertEqual(autumn["time_context"]["fold_status"], "unresolved")
        for fold in (0, 1):
            selected = chart.build_chart("2024-11-03", shichen="丑", timezone="America/New_York", fold=fold)
            self.assertEqual(duration(selected), 7200)
            self.assertEqual(selected["time_context"]["fold_status"], "selected")

    def test_lunar_input_intersects_branch_with_real_china_calendar_date(self):
        value = chart.build_chart("2024-01-01", shichen="午", calendar="lunar", timezone="America/New_York")
        self.assertEqual(duration(value), 7200)
        self.assertEqual(value["chinese_calendar_solar_date"], "2024-02-10")
        self.assertEqual(value["solar"], "2024-02-09")
        self.assertTrue(all(value["pillars"].values()))

    def test_solar_clock_can_make_the_adopted_hour_ambiguous(self):
        value = build(longitude=116.4, true_solar=True)
        self.assertIsNone(value["pillars"]["hour"])
        self.assertGreater(len(value["candidates"]), 1)
        with self.assertRaises(ziwei.ZiweiError):
            ziwei.resolve_chart(value)

    def test_already_solar_shichen_edges_are_supplied_boundaries_not_unknown_minutes(self):
        for correction_flag in (False, True):
            value = build(longitude=121.47, time_basis="true-solar-time", gender="female", true_solar=correction_flag)
            codes = {item["code"] for item in value["uncertainty"]}
            self.assertNotIn("solar_clock_near_boundary", codes)
            self.assertNotIn("shichen_has_clock_gap", codes)
            self.assertIn("approximate_solar_clock", codes)
            self.assertEqual(len(value["candidates"]), 1)
            self.assertTrue(all(value["pillars"].values()))
            self.assertLess(duration(value), 7200)
            resolved = ziwei.resolve_chart(value)
            self.assertEqual(resolved["time_index"], 6)
            self.assertIsNone(resolved["adopted_clock"])

    def test_solar_clock_rate_is_not_a_civil_clock_gap(self):
        for clock in (None, "12:00"):
            value = chart.build_chart("2000-08-16", clock, timezone="Asia/Shanghai", longitude=121.47,
                                      time_basis="true-solar-time")
            codes = {item["code"] for item in value["uncertainty"]}
            self.assertFalse(codes & {"date_has_clock_gap", "minute_has_clock_gap", "shichen_has_clock_gap"})

    def test_already_solar_shichen_still_retains_real_term_and_zi_boundaries(self):
        for branch, day in (("申", "2024-02-04"), ("子", "2000-08-16")):
            value = build(branch, day, longitude=121.47, time_basis="true-solar-time")
            self.assertGreater(len(value["candidates"]), 1)
            if branch == "申":
                self.assertIsNone(value["pillars"]["year"])
                self.assertIsNone(value["pillars"]["month"])
            else:
                self.assertIsNone(value["pillars"]["hour"])
                self.assertEqual(len(value["time_context"]["valid_utc_ranges"]), 2)
            with self.assertRaises(ziwei.ZiweiError) as caught:
                ziwei.resolve_chart(value)
            self.assertEqual(caught.exception.status, "ambiguous_input")

    def test_invalid_branch_and_time_conflict_rejected_at_each_boundary(self):
        for invalid in ("午时", "", "甲", "子<script>", [], {}, True, 6):
            incoming = request()
            incoming["people"][0]["birth"]["shichen"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(intake_flow.IntakeError):
                intake_flow.normalize_request(incoming)
            with self.assertRaises(ValueError):
                build(invalid)
            with self.assertRaises(workflow.ProjectError):
                workflow.normalize_input({"birth": incoming["people"][0]["birth"], "systems": ["bazi"]})
        incoming = request()
        incoming["people"][0]["birth"]["time"] = "12:00"
        with self.assertRaises(intake_flow.IntakeError):
            intake_flow.plan_request(incoming)
        with self.assertRaises(ValueError):
            chart.build_chart("2000-08-16", "12:00", shichen="午")
        with self.assertRaises(workflow.ProjectError):
            workflow.normalize_input({"birth": incoming["people"][0]["birth"], "systems": ["bazi"]})

    def test_canonical_loader_roundtrips_old_and_new_inputs(self):
        for value in (build(), build("子"), chart.build_chart("2000-08-16", "12:00", timezone="Asia/Shanghai"),
                      chart.build_chart("2000-08-16", timezone="Asia/Shanghai")):
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "chart.json"
                path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
                self.assertEqual(case_lookup.load_chart(path), value)

    def test_native_shared_consumers_reject_branch_conflicts_or_lost_precision(self):
        for mutate in (lambda value: value["input"].update(shichen="恶意值"),
                       lambda value: value["input"].update(time="12:00"),
                       lambda value: value.update(time_precision="minute")):
            value = build()
            mutate(value)
            with self.assertRaises(ValueError):
                astrology.validate_chart(value)
            with self.assertRaises(ziwei.ZiweiError) as caught:
                ziwei.resolve_chart(value)
            self.assertEqual(caught.exception.status, "invalid_input")

    def test_normalize_plan_and_real_workflow_keep_branch_precision(self):
        for branch in ("午", "子"):
            incoming = request(branch)
            original = copy.deepcopy(incoming)
            normalized = intake_flow.normalize_request(incoming)
            plan = intake_flow.plan_request(normalized)
            flow = plan["people"][0]["workflow_input"]
            self.assertEqual(flow["birth"]["shichen"], branch)
            self.assertIsNone(flow["birth"]["time"])
            self.assertEqual(incoming, original)
            with tempfile.TemporaryDirectory() as temporary, patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
                project = Path(temporary) / "project"
                response = workflow.run_project(project, flow)
                state = workflow.project_status(project)
                result = json.loads((project / state["components"]["bazi"]["file"]).read_text(encoding="utf-8"))
                self.assertEqual(response["status"], "ready")
                self.assertEqual(result["input"]["shichen"], branch)
                self.assertIsNone(result["input"]["time"])
                self.assertEqual(result["time_precision"], "shichen")
                self.assertEqual(duration(result), 7200)

    def test_auto_plan_accepts_shichen_for_ziwei_and_safe_astrology(self):
        incoming = request()
        incoming["preferences"]["systems"] = "auto"
        flow = intake_flow.plan_request(incoming)["people"][0]["workflow_input"]
        self.assertIn("ziwei", flow["systems"])
        self.assertIn("astrology", flow["systems"])
        self.assertFalse(flow["deferred"])
        resolved = ziwei.resolve_chart(build(gender="female"))
        self.assertEqual(resolved["time_index"], 6)
        self.assertIsNone(resolved["adopted_clock"])


class ShichenEngineTests(unittest.TestCase):
    def test_intake_to_native_engines_preserves_precision_and_zi_ambiguity(self):
        if not astrology.probe()["available"] or ziwei.probe().get("status") != "available":
            self.skipTest("Prepared local engines/runtime unavailable; no preparation permitted")
        for branch in ("午", "子"):
            flow = intake_flow.plan_request(request(branch, ["bazi", "ziwei", "astrology"]))["people"][0]["workflow_input"]
            with tempfile.TemporaryDirectory() as temporary, patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
                project = Path(temporary) / "project"
                response = workflow.run_project(project, flow)
                state = workflow.project_status(project)
                payloads = {key: json.loads((project / item["file"]).read_text(encoding="utf-8"))
                            for key, item in state["components"].items()}
                self.assertEqual(response["status"], "partial")
                self.assertEqual(payloads["bazi"]["time_precision"], "shichen")
                self.assertEqual(payloads["astrology"]["mode"], "shichen_sun_ranges")
                self.assertEqual(payloads["astrology"]["candidates"], [])
                self.assertEqual(payloads["astrology"]["input"]["shichen"], branch)
                self.assertIsNone(payloads["astrology"]["input"]["time"])
                self.assertEqual(payloads["ziwei"]["status"], "ok" if branch == "午" else "ambiguous_input")

    def test_real_ziwei_uses_branch_without_adopted_minute(self):
        if ziwei.probe().get("status") != "available":
            self.skipTest("Prepared local Ziwei engine unavailable; no preparation permitted")
        value = ziwei.build_ziwei(chart=build(gender="female"))
        self.assertEqual(value["status"], "ok")
        self.assertEqual(value["input"]["time_index"], 6)
        self.assertEqual(value["input"]["time_precision"], "shichen")
        self.assertIsNone(value["input"]["adopted_clock"])
        self.assertEqual(len(value["chart"]["palaces"]), 12)
        solar = ziwei.build_ziwei(chart=build(gender="female", longitude=121.47, time_basis="true-solar-time"))
        self.assertEqual(solar["status"], "ok")
        self.assertEqual(solar["input"]["time_index"], 6)
        self.assertIsNone(solar["input"]["adopted_clock"])
        self.assertEqual(len(solar["chart"]["palaces"]), 12)

    def test_real_astrology_retains_only_safe_sun_ranges_and_pair_panel(self):
        if not astrology.probe()["available"]:
            self.skipTest("Prepared local astronomy engine/runtime unavailable; no preparation permitted")
        for branch in ("午", "子"):
            value = astrology.build_astrology(build(branch), latitude=31.23, longitude=121.47)
            self.assertEqual(value["status"], "partial")
            self.assertEqual(value["mode"], "shichen_sun_ranges")
            self.assertEqual(value["candidates"], [])
            self.assertEqual(len(value["sun_ranges"]), 1 if branch == "午" else 2)
            self.assertNotIn("houses", value)
            person = {"id": "A", "label": "合成样例", "results": {"astrology": value}}
            candidates, limits = pair_analysis._astro_candidates(person)
            self.assertEqual(candidates, [])
            self.assertTrue(limits)


if __name__ == "__main__":
    unittest.main()
