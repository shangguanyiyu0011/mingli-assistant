"""Dated horoscope checks, independent of the natal output contract."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", HERE))
if not (SKILL / "scripts/ziwei.py").is_file():
    SKILL = HERE / "package/mingxue-master"
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))
import ziwei
from test_ziwei import fake_chart, response, shared_chart


def flow_response(gender="female", scope="daily"):
    charts = [fake_chart()] if gender else [fake_chart("男"), fake_chart()]
    data = response(charts)
    layers = {}
    for level, offset in (("yearly", 1), ("monthly", 2), ("daily", 3)):
        stars = [[] for _ in range(12)]
        stars[offset] = [{"name": "测试流曜", "scope": level, "type": "soft"}]
        layers[level] = {"index": offset, "name": level, "heavenlyStem": "甲", "earthlyBranch": "子",
                         "palaceNames": ["流运宫" + str(x) for x in range(12)],
                         "mutagen": ["测试星3", "测试星2", "测试星1", "测试星0"], "stars": stars}
        if level == scope:
            break
    horoscope = {"solarDate": "2023-8-19", "lunarDate": "二〇二三年七月初四", "layers": layers,
                 "context": {"age": {"index": 9, "nominalAge": 24}, "decadal": {"index": 2}}}
    data["horoscopes"] = [copy.deepcopy(horoscope) for _ in charts]
    data["target_lunar"] = {"lunarYear": 2023, "lunarMonth": 7, "lunarDay": 4, "isLeap": False}
    return data


class OfflineFlowTests(unittest.TestCase):
    def build(self, **kwargs):
        return ziwei.build_ziwei("2000-08-16", index=2, gender="female", scope="daily",
                                 target_date="2023-08-19", target_time="03:12", **kwargs)

    def test_requires_explicit_target_and_scope_without_engine_call(self):
        for kwargs in ({"scope": "yearly"}, {"scope": "monthly", "target_date": "2023-08-19"},
                       {"target_date": "2023-08-19", "target_time": "03:12"},
                       {"scope": "daily", "target_date": "2023-08-19", "target_time": "24:00"},
                       {"scope": "daily", "target_date": "2023-08-19", "target_index": True},
                       {"scope": "daily", "target_date": "2023-08-19", "target_time": "03:12", "target_index": 2},
                       {"scope": "daily", "target_date": "2101-01-01", "target_index": 0},
                       {"scope": "daily", "target_date": "1999-01-01", "target_index": 0}):
            with patch.object(ziwei, "call_engine") as engine, self.assertRaises(ziwei.ZiweiError):
                ziwei.build_ziwei("2000-08-16", index=2, **kwargs)
            engine.assert_not_called()

    def test_real_flow_request_and_natal_are_separate(self):
        with patch.object(ziwei, "call_engine", return_value=flow_response()) as engine:
            result = self.build(horoscope_divide="exact")
        payload = engine.call_args.args[0]
        self.assertEqual(payload["scope"], "daily")
        self.assertEqual(payload["target"]["time_index"], 2)
        self.assertEqual(payload["settings"]["horoscope_divide"], "exact")
        self.assertEqual(set(result["horoscope"]["layers"]), {"yearly", "monthly", "daily"})
        self.assertEqual(result["natal_mutagens"][0]["star"], "测试星0")
        daily = result["horoscope"]["layers"]["daily"]
        self.assertEqual(daily["flow_mutagens"][0]["star"], "测试星3")
        self.assertEqual(daily["flow_mutagens"][0]["palace_index"], 3)
        self.assertTrue(all(s["scope"] == "daily" for p in daily["palaces"] for s in p["flow_stars"]))

    def test_absent_flow_not_substituted_with_natal(self):
        with patch.object(ziwei, "call_engine", return_value=response([fake_chart()])):
            with self.assertRaises(ziwei.ZiweiError) as error:
                self.build()
        self.assertEqual(error.exception.status, "engine_error")

    def test_natal_star_scope_cannot_masquerade_as_flow(self):
        data = flow_response()
        data["horoscopes"][0]["layers"]["daily"]["stars"][3][0]["scope"] = "origin"
        with patch.object(ziwei, "call_engine", return_value=data), self.assertRaises(ziwei.ZiweiError):
            self.build()

    def test_gender_unknown_uses_real_common_layers_but_suppresses_age_context(self):
        with patch.object(ziwei, "call_engine", return_value=flow_response(gender=None)) as engine:
            result = ziwei.build_ziwei("2000-08-16", index=2, scope="daily", target_date="2023-08-19", target_index=2)
        self.assertIsNone(engine.call_args.args[0]["gender"])
        self.assertEqual(result["horoscope"]["status"], "partial")
        self.assertEqual(result["horoscope"]["context"]["decadal"]["status"], "not_calculated")
        self.assertEqual(result["horoscope"]["context"]["age"]["status"], "not_calculated")
        self.assertEqual(len(result["horoscope"]["layers"]), 3)

    def test_gender_dependent_requested_layer_requires_input(self):
        data = flow_response(gender=None)
        data["horoscopes"][1]["layers"]["daily"]["index"] = 5
        with patch.object(ziwei, "call_engine", return_value=data), self.assertRaises(ziwei.ZiweiError) as error:
            ziwei.build_ziwei("2000-08-16", index=2, scope="daily", target_date="2023-08-19", target_index=2)
        self.assertEqual(error.exception.status, "needs_input")

    def test_flow_preserves_birth_input_chain(self):
        birth = shared_chart()
        with patch.object(ziwei, "call_engine", return_value=flow_response()) as engine:
            flow = ziwei.build_ziwei(chart=birth, scope="daily", target_date="2023-08-19", target_time="03:12")
        with patch.object(ziwei, "call_engine", return_value=response([fake_chart()])):
            natal = ziwei.build_ziwei(chart=birth)
        self.assertEqual(flow["source_chart"], natal["source_chart"])
        self.assertEqual(engine.call_args.args[0]["solar_date"], "2000-08-15")
        self.assertNotEqual(flow["target"]["date"], flow["input"]["solar_date"])

    def test_uncovered_age_context_suppresses_invalid_sentinels(self):
        data = flow_response()
        data["horoscopes"][0]["context"]["age"]["index"] = -1
        with patch.object(ziwei, "call_engine", return_value=data):
            result = self.build()
        self.assertEqual(result["horoscope"]["context"]["age"]["status"], "unavailable")


@unittest.skipUnless(os.environ.get("MINGXUE_TEST_ZIWEI_ENGINE"), "explicit prepared engine only; never downloads")
class RealFlowTests(unittest.TestCase):
    def build(self, target_date, target_time="03:12", **kwargs):
        options = dict(gender="female", engine_dir=os.environ["MINGXUE_TEST_ZIWEI_ENGINE"], scope="daily",
                       target_date=target_date, target_time=target_time)
        options.update(kwargs)
        return ziwei.build_ziwei("2000-08-16", index=2, **options)

    def test_official_horoscope_example(self):
        result = self.build("2023-08-19")
        layers = result["horoscope"]["layers"]
        self.assertEqual((layers["yearly"]["index"], layers["yearly"]["heavenlyStem"], layers["yearly"]["earthlyBranch"]), (1, "癸", "卯"))
        self.assertEqual(layers["yearly"]["mutagen"], ["破军", "巨门", "太阴", "贪狼"])
        self.assertEqual((layers["monthly"]["index"], layers["monthly"]["heavenlyStem"], layers["monthly"]["earthlyBranch"]), (3, "庚", "申"))
        self.assertEqual(layers["monthly"]["mutagen"], ["太阳", "武曲", "太阴", "天同"])
        self.assertEqual((layers["daily"]["index"], layers["daily"]["heavenlyStem"], layers["daily"]["earthlyBranch"]), (6, "己", "酉"))
        self.assertEqual(layers["daily"]["mutagen"], ["武曲", "贪狼", "天梁", "文曲"])
        self.assertEqual(result["horoscope"]["context"]["decadal"]["index"], 2)
        self.assertEqual(result["horoscope"]["context"]["age"]["nominalAge"], 24)
        for level, layer in layers.items():
            self.assertEqual(len(layer["palaces"]), 12)
            self.assertEqual(len(layer["flow_mutagens"]), 4)
            self.assertTrue(all(star["scope"] == level for group in layer["stars"] for star in group))
        self.assertNotEqual(layers["yearly"]["mutagen"], [s["star"] for s in result["natal_mutagens"]])

    def test_requested_hierarchy_not_fabricated_extra_layers(self):
        year = self.build("2023-08-19", scope="yearly")
        month = self.build("2023-08-19", scope="monthly")
        self.assertEqual(set(year["horoscope"]["layers"]), {"yearly"})
        self.assertEqual(set(month["horoscope"]["layers"]), {"yearly", "monthly"})

    def test_cny_boundary_and_independent_horoscope_year_divide(self):
        before = self.build("2023-01-21", "12:00")
        after = self.build("2023-01-22", "12:00")
        self.assertEqual(before["horoscope"]["layers"]["yearly"]["heavenlyStem"], "壬")
        self.assertEqual(after["horoscope"]["layers"]["yearly"]["heavenlyStem"], "癸")
        normal = self.build("2024-02-05", "12:00", horoscope_divide="normal")
        exact = self.build("2024-02-05", "12:00", horoscope_divide="exact")
        self.assertEqual(normal["horoscope"]["layers"]["yearly"]["heavenlyStem"], "癸")
        self.assertEqual(exact["horoscope"]["layers"]["yearly"]["heavenlyStem"], "甲")
        self.assertEqual(normal["chart"]["palaces"], exact["chart"]["palaces"])

    def test_leap_month_half_boundary_and_lunar_new_month(self):
        fifteenth = self.build("2023-04-05", "12:00")
        sixteenth = self.build("2023-04-06", "12:00")
        self.assertTrue(fifteenth["horoscope"]["target_lunar"]["isLeap"])
        self.assertEqual(fifteenth["horoscope"]["target_lunar"]["lunarDay"], 15)
        self.assertEqual(sixteenth["horoscope"]["target_lunar"]["lunarDay"], 16)
        self.assertNotEqual(fifteenth["horoscope"]["layers"]["monthly"]["index"], sixteenth["horoscope"]["layers"]["monthly"]["index"])
        no_fix = self.build("2023-04-06", "12:00", fix_leap=False)
        self.assertEqual(no_fix["horoscope"]["layers"]["monthly"], sixteenth["horoscope"]["layers"]["monthly"])
        new_month = self.build("2023-04-20", "12:00")
        self.assertEqual(new_month["horoscope"]["target_lunar"]["lunarDay"], 1)
        self.assertFalse(new_month["horoscope"]["target_lunar"]["isLeap"])

    def test_late_zi_actual_engine_day_stem_and_palace_index_conventions(self):
        forward = self.build("2023-08-19", "23:30", day_divide="forward")
        current = self.build("2023-08-19", "23:30", day_divide="current")
        next_day = self.build("2023-08-20", "00:30", day_divide="current")
        fday, cday, nday = [x["horoscope"]["layers"]["daily"] for x in (forward, current, next_day)]
        self.assertNotEqual(fday["heavenlyStem"], cday["heavenlyStem"])
        self.assertEqual(fday["heavenlyStem"], nday["heavenlyStem"])
        self.assertEqual(fday["index"], cday["index"])
        self.assertNotEqual(fday["index"], nday["index"])
        self.assertIn("仍使用目标原农历日", forward["horoscope"]["convention"]["late_zi"])

    def test_unknown_gender_flow_is_common_but_context_not_guessed(self):
        unknown = self.build("2023-08-19", gender=None)
        known = self.build("2023-08-19", gender="female")
        self.assertEqual(unknown["horoscope"]["layers"], known["horoscope"]["layers"])
        self.assertEqual(unknown["horoscope"]["context"]["age"]["status"], "not_calculated")
        self.assertIsNone(unknown["input"]["gender"])

    def test_host_timezone_does_not_change_explicit_target(self):
        args = [sys.executable, "-X", "utf8", "-B", str(SCRIPTS / "ziwei.py"), "--date", "2000-08-16",
                "--time-index", "2", "--gender", "female", "--scope", "daily", "--target-date", "2023-08-19",
                "--target-time", "03:12", "--engine-dir", os.environ["MINGXUE_TEST_ZIWEI_ENGINE"]]
        outputs = []
        for zone in ("UTC", "America/Los_Angeles"):
            env = dict(os.environ, TZ=zone)
            completed = subprocess.run(args, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30, check=True)
            outputs.append(json.loads(completed.stdout))
        self.assertEqual(outputs[0]["horoscope"], outputs[1]["horoscope"])


if __name__ == "__main__":
    unittest.main()
