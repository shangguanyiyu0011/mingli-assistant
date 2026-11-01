"""Fixed-rule, calendar-boundary and visual-contract tests for three calculators."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", ROOT))
if not (SKILL / "scripts/traditional_casts.py").is_file():
    SKILL = ROOT / "package/mingxue-master"
sys.path.insert(0, str(SKILL / "scripts"))
import traditional_casts as t


def manual(**changes):
    return {**t.DEFAULT_PARAMS["jinkoujue"], **changes}


class InterfaceTests(unittest.TestCase):
    def test_default_results_are_real_structures_with_common_contract(self):
        expected = {"xiaoliuren": "six_palaces", "jinkoujue": "four_positions", "sukuyo": "mansion_wheel"}
        for system, params in t.DEFAULT_PARAMS.items():
            with self.subTest(system=system):
                value = t.calculate(system, params)
                for key in ("system", "status", "input", "rules", "limitations", "visualization", "summary"):
                    self.assertIn(key, value)
                self.assertEqual(value["status"], "calculated")
                self.assertEqual(value["visualization"]["kind"], expected[system])
                self.assertEqual(value["input"], params)
                self.assertTrue(value["rules"] and value["limitations"])

    def test_unknown_system_and_non_object_params_rejected(self):
        for system, params in (("vedic", {}), ("xiaoliuren", []), ("sukuyo", None), ([], {})):
            with self.assertRaises(ValueError):
                t.calculate(system, params)
        with self.assertRaises(ValueError):
            t.calculate("xiaoliuren", {"mode": "numbers", "numbers": [1, 1, 1], "other": 1})

    def test_no_resource_or_astronomy_needed_for_direct_table_modes(self):
        with patch.object(t, "_calendar_api", side_effect=AssertionError("must remain independent")):
            for system, params in t.DEFAULT_PARAMS.items():
                self.assertEqual(t.calculate(system, params)["status"], "calculated")


class XiaoLiuRenTests(unittest.TestCase):
    def test_independent_three_number_example_and_inclusive_start(self):
        value = t.calculate("xiaoliuren", {"mode": "numbers", "numbers": [3, 5, 7]})
        self.assertEqual([p["palace"]["name"] for p in value["three_positions"]], ["速喜", "大安", "大安"])
        self.assertEqual([(s["start_index"], s["end_index"]) for s in value["steps"]], [(0, 2), (2, 0), (0, 0)])
        all_one = t.calculate("xiaoliuren", {"numbers": [1, 1, 1]})
        self.assertEqual([s["end_palace"] for s in all_one["steps"]], ["大安"] * 3)
        multiple = t.calculate("xiaoliuren", {"numbers": [6, 1, 1]})
        self.assertEqual([s["end_palace"] for s in multiple["steps"]], ["空亡"] * 3)

    def test_lunar_count_and_report_count_match_for_declared_equivalent_inputs(self):
        for month, day, hour, expected in ((1, 1, "子", "大安"), (1, 2, "丑", "速喜"), (12, 30, "亥", "赤口")):
            value = t.calculate("xiaoliuren", {"mode": "lunar", "lunar_month": month, "lunar_day": day, "hour_branch": hour})
            numbers = t.calculate("xiaoliuren", {"mode": "numbers", "numbers": [month, day, t.BRANCHES.index(hour) + 1]})
            self.assertEqual(value["final_palace"]["name"], expected)
            self.assertEqual([s["end_index"] for s in value["steps"]], [s["end_index"] for s in numbers["steps"]])

    def test_six_periodicity_and_large_number_preview_are_bounded(self):
        base = t.calculate("xiaoliuren", {"numbers": [3, 5, 7]})
        for index in range(3):
            values = [3, 5, 7]
            values[index] += 6
            actual = t.calculate("xiaoliuren", {"numbers": values})
            self.assertEqual([s["end_index"] for s in actual["steps"]], [s["end_index"] for s in base["steps"]])
        huge = t.calculate("xiaoliuren", {"numbers": [1_000_000_000, 1, 1]})
        self.assertLessEqual(len(huge["steps"][0]["path_preview_indices"]), 12)
        self.assertTrue(huge["steps"][0]["preview_truncated"])
        self.assertGreater(huge["steps"][0]["full_cycles"], 0)

    def test_invalid_counts_mixed_modes_and_dates_are_rejected(self):
        cases = [{"numbers": [0, 1, 1]}, {"numbers": [-1, 1, 1]}, {"numbers": [True, 1, 1]},
                 {"numbers": [1.5, 2, 3]}, {"numbers": [1, 2]}, {"numbers": [1, 2, 3], "hour_branch": "子"},
                 {"mode": "lunar", "lunar_month": 13, "lunar_day": 1, "hour_branch": "子"},
                 {"mode": "lunar", "lunar_month": 1, "lunar_day": 31, "hour_branch": "子"},
                 {"mode": "lunar", "lunar_month": 1, "lunar_day": 1, "hour_branch": "子时"}]
        for params in cases:
            with self.subTest(params=params), self.assertRaises(ValueError):
                t.calculate("xiaoliuren", params)

    def test_visual_board_is_six_distinct_cells_and_three_steps(self):
        value = t.calculate("xiaoliuren", t.DEFAULT_PARAMS["xiaoliuren"])
        self.assertEqual(len(value["visualization"]["nodes"]), 6)
        self.assertEqual(len({(n["row"], n["column"]) for n in value["palaces"]}), 6)
        self.assertEqual(len(value["steps"]), 3)
        self.assertEqual(value["visualization"]["selected_index"], value["final_palace"]["index"])


class JinKouJueTests(unittest.TestCase):
    def test_publisher_fixed_four_position_example(self):
        value = t.calculate("jinkoujue", manual())
        rows = value["four_positions"]
        self.assertEqual([r["label"] for r in rows], ["人元", "贵神", "将神", "地分"])
        self.assertEqual(rows[0]["stem"], "丙")
        self.assertEqual((rows[1]["name"], rows[1]["branch"]), ("白虎", "申"))
        self.assertEqual((rows[2]["name"], rows[2]["branch"]), ("功曹", "寅"))
        self.assertEqual(rows[3]["branch"], "午")
        self.assertEqual((rows[1]["dun_stem"], rows[2]["dun_stem"]), ("戊", "壬"))
        self.assertFalse(value["candidates"][0]["calendar_verified"])

    def test_five_rat_dun_all_ten_day_stems(self):
        expected = "甲丙戊庚壬甲丙戊庚壬"
        for day, first in zip(t.STEMS, expected):
            self.assertEqual(t._zi_stem(day, "子"), first)
            self.assertEqual(t._zi_stem(day, "亥"), t.STEMS[(t.STEMS.index(first) + 11) % 10])

    def test_noble_anchor_direction_reverses_for_xin_day(self):
        value = t.calculate("jinkoujue", manual(day_pillar="辛巳", hour_branch="午", earth_branch="巳"))
        noble = value["four_positions"][1]
        self.assertEqual((noble["name"], noble["branch"]), ("螣蛇", "巳"))
        step = value["candidates"][0]["steps"][1]
        self.assertEqual((step["anchor_branch"], step["direction"]), ("午", "reverse"))

    def test_day_night_school_changes_are_explicit(self):
        default = t.calculate("jinkoujue", manual(hour_branch="辰"))
        other = t.calculate("jinkoujue", manual(hour_branch="辰", day_night_rule="mao_shen_day"))
        self.assertEqual(default["candidates"][0]["steps"][1]["day_night"], "night")
        self.assertEqual(other["candidates"][0]["steps"][1]["day_night"], "day")
        self.assertNotEqual(default["four_positions"][1]["name"], other["four_positions"][1]["name"])

    def test_two_full_plates_are_permutations_with_one_selection(self):
        value = t.calculate("jinkoujue", manual())["candidates"][0]
        self.assertEqual({x["general_branch"] for x in value["general_plate"]}, set(t.BRANCHES))
        self.assertEqual(len({x["noble_name"] for x in value["noble_plate"]}), 12)
        self.assertEqual(sum(x["selected"] for x in value["general_plate"]), 1)
        self.assertEqual(sum(x["selected"] for x in value["noble_plate"]), 1)
        self.assertEqual(len(value["relations"]), 6)

    def test_datetime_jie_he_matches_publisher_but_qi_rule_is_separate(self):
        params = {"mode": "datetime", "date": "2015-10-18", "time": "14:32:00", "timezone": "Asia/Shanghai", "earth_branch": "午"}
        jie = t.calculate("jinkoujue", {**params, "month_general_rule": "month_branch_he"})
        qi = t.calculate("jinkoujue", {**params, "month_general_rule": "solar_qi"})
        self.assertEqual(jie["candidates"][0]["day_pillar"], "丁卯")
        self.assertEqual(jie["candidates"][0]["hour_branch"], "未")
        self.assertEqual(jie["candidates"][0]["month_general_branch"], "卯")
        self.assertEqual(jie["four_positions"], t.calculate("jinkoujue", manual())["four_positions"])
        self.assertEqual(qi["candidates"][0]["month_general_branch"], "辰")

    def test_qi_exact_second_and_whole_minute_candidates(self):
        params = {"mode": "datetime", "date": "2025-06-21", "timezone": "Asia/Shanghai", "earth_branch": "午"}
        before = t.calculate("jinkoujue", {**params, "time": "10:42:15"})
        at = t.calculate("jinkoujue", {**params, "time": "10:42:16"})
        minute = t.calculate("jinkoujue", {**params, "time": "10:42"})
        self.assertEqual(before["candidates"][0]["month_general_branch"], "申")
        self.assertEqual(at["candidates"][0]["month_general_branch"], "未")
        self.assertEqual({c["month_general_branch"] for c in minute["candidates"]}, {"申", "未"})
        self.assertEqual(minute["status"], "calculated_with_candidates")
        self.assertNotIn("four_positions", minute)

    def test_dst_gap_and_fold_and_separate_23_day_convention(self):
        params = {"mode": "datetime", "date": "2024-03-10", "time": "02:30:00", "timezone": "America/New_York", "earth_branch": "子"}
        with self.assertRaisesRegex(ValueError, "does not exist"):
            t.calculate("jinkoujue", params)
        fold = t.calculate("jinkoujue", {**params, "date": "2024-11-03", "time": "01:30:00"})
        self.assertEqual(fold["calendar_context"]["time_context"]["fold_status"], "unresolved")
        self.assertEqual(len(fold["candidates"][0]["valid_time_ranges"]), 2)
        late = t.calculate("jinkoujue", {**params, "date": "2005-12-25", "time": "23:30:00", "timezone": "Asia/Shanghai"})
        self.assertEqual(late["candidates"][0]["day_pillar"], "癸未")
        self.assertEqual(late["convention_alternatives"][0]["day_pillar"], "甲申")

    def test_invalid_or_mixed_modes_do_not_silently_replace_inputs(self):
        cases = [manual(day_pillar="甲丑"), manual(hour_branch="no"), manual(month_general_branch="子时"),
                 manual(date="2025-01-01"), manual(month_general_rule="solar_qi"),
                 {"mode": "datetime", "date": "2025-01-01", "time": "12:00", "earth_branch": "子"}]
        for params in cases:
            with self.subTest(params=params), self.assertRaises(ValueError):
                t.calculate("jinkoujue", params)


class SukuyoTests(unittest.TestCase):
    def test_all_twelve_first_day_anchors_and_27_not_28_or_vedic(self):
        expected = "室奎胃毕参鬼张角氐心斗虚"
        self.assertEqual(len(t.MANSIONS), 27)
        self.assertNotIn("牛", t.MANSIONS)
        for month, name in enumerate(expected, 1):
            value = t.calculate("sukuyo", {"birth": {"month": month, "day": 1}})
            self.assertEqual(value["birth_mansion"]["name"], name)
        self.assertEqual(len(value["visualization"]["nodes"]), 27)

    def test_classical_fixed_examples_around_month_full_moon(self):
        for day, expected in ((5, "毕"), (14, "轸"), (15, "角"), (16, "亢"), (17, "氐")):
            value = t.calculate("sukuyo", {"birth": {"month": 2, "day": day}})
            self.assertEqual(value["birth_mansion"]["name"], expected)

    def test_month_reset_is_table_based_including_duplicate_days(self):
        a = t.calculate("sukuyo", {"birth": {"month": 1, "day": 30}})
        b = t.calculate("sukuyo", {"birth": {"month": 2, "day": 1}})
        self.assertEqual(a["birth_mansion"]["name"], "奎")
        self.assertEqual(a["birth_mansion"]["name"], b["birth_mansion"]["name"])

    def test_three_nines_relations_have_direction_and_symmetric_family(self):
        for day in range(1, 28):
            a = {"month": 2, "day": 15}
            b = {"month": 2, "day": day}
            first = t.calculate("sukuyo", {"birth": a, "partner": b})["partner_relation"]
            reverse = t.calculate("sukuyo", {"birth": b, "partner": a})["partner_relation"]
            self.assertEqual(first["family"], reverse["family"])
            self.assertEqual(first["source_to_target"], reverse["target_to_source"])
            self.assertEqual((first["forward_steps"] + reverse["forward_steps"]) % 27, 0)
        special = t.calculate("sukuyo", {"birth": {"month": 2, "day": 15}, "target": {"month": 2, "day": 24}})
        self.assertEqual(special["daily_relation"]["source_to_target"], "业")
        self.assertEqual(special["daily_relation"]["target_to_source"], "胎")
        self.assertEqual(special["daily_relation"]["family"], "业胎")

    def test_solar_conversion_is_explicit_china_lunar_version(self):
        value = t.calculate("sukuyo", {"birth": {"calendar": "solar", "date": "2024-02-10"},
                                      "target": {"calendar": "solar", "date": "2024-02-11"}})
        self.assertEqual(value["birth_mansion"]["name"], "室")
        self.assertEqual(value["daily_mansion"]["name"], "壁")
        self.assertEqual(value["daily_relation"]["source_to_target"], "荣")
        self.assertEqual(value["birth_mansion"]["lunar"]["month"], 1)
        self.assertEqual(value["birth_mansion"]["lunar"]["day"], 1)
        self.assertTrue(value["birth_mansion"]["lunar"]["date_verified"])

    def test_leap_convention_and_actual_month_validation(self):
        regular = t.calculate("sukuyo", {"birth": {"month": 2, "day": 1}})
        leap = t.calculate("sukuyo", {"birth": {"year": 2023, "month": 2, "day": 1, "leap": True}})
        self.assertEqual(regular["birth_mansion"]["name"], leap["birth_mansion"]["name"])
        for params in ({"birth": {"year": 2024, "month": 2, "day": 1, "leap": True}},
                       {"birth": {"year": 2024, "month": 1, "day": 30}},
                       {"birth": {"month": 1, "day": 31}}, {"birth": {"month": True, "day": 1}},
                       {"birth": {"month": 2, "day": 1}, "leap_rule": "split15"}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                t.calculate("sukuyo", params)

    def test_target_is_optional_and_never_defaults_to_today(self):
        value = t.calculate("sukuyo", {"birth": {"month": 2, "day": 17}})
        self.assertIsNone(value["daily_mansion"])
        self.assertIsNone(value["daily_relation"])
        self.assertIsNone(value["visualization"]["daily_index"])


class CliTests(unittest.TestCase):
    def test_probe_and_three_real_stdout_only_calls(self):
        command = [sys.executable, "-X", "utf8", "-B", str(SKILL / "scripts/traditional_casts.py")]
        probe = subprocess.run([*command, "--probe"], capture_output=True, encoding="utf-8", check=False)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(set(json.loads(probe.stdout)["systems"]), set(t.DEFAULT_PARAMS))
        with tempfile.TemporaryDirectory() as scratch:
            for system, params in t.DEFAULT_PARAMS.items():
                completed = subprocess.run([*command, system, "--params", json.dumps(params, ensure_ascii=False)],
                                           capture_output=True, encoding="utf-8", cwd=scratch, check=False)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                self.assertEqual(json.loads(completed.stdout)["system"], system)
            self.assertEqual(list(Path(scratch).iterdir()), [])

    def test_cli_invalid_json_and_zero_give_json_errors(self):
        command = [sys.executable, "-X", "utf8", "-B", str(SKILL / "scripts/traditional_casts.py"), "xiaoliuren", "--params"]
        for text in ("{", "[]", '{"numbers":[0,1,2]}', '{"numbers":[NaN,1,2]}', '{"numbers":[1,1,1],"numbers":[2,2,2]}'):
            value = subprocess.run([*command, text], capture_output=True, encoding="utf-8", check=False)
            self.assertEqual(value.returncode, 2)
            parsed = json.loads(value.stdout)
            self.assertEqual(parsed["status"], "error")
            self.assertTrue(all(k in parsed for k in ("system", "input", "rules", "limitations")))
            self.assertEqual(value.stderr, "")


if __name__ == "__main__":
    unittest.main()
