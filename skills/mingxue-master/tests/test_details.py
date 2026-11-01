"""Structural pillar annotations: fixed examples and bundled-library parity."""
import importlib
import json
import os
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", HERE))
if not (SKILL / "scripts/pillar_details.py").is_file():
    SKILL = HERE / "package/mingxue-master"
sys.path.insert(0, str(SKILL / "scripts"))
import pillar_details as details


def pillars(year=None, month=None, day=None, hour=None):
    return dict(zip(("year", "month", "day", "hour"), (year, month, day, hour)))


def bundled_library():
    roots = list((HERE / "runtime").rglob("lunar_python")) if (HERE / "runtime").is_dir() else []
    if not roots:
        import resources
        roots = list(resources.get_resources().rglob("lunar_python"))
    libraries = [root for root in roots if (root / "__init__.py").is_file()]
    if len(libraries) != 1:
        raise AssertionError(f"Expected one bundled calendar library, found {len(libraries)}")
    sys.path.insert(0, str(libraries[0].parent))
    return importlib.import_module("lunar_python")


class StructuralDetailsTests(unittest.TestCase):
    def test_all_sixty_legal_pillars_have_fixed_nayin_pairs(self):
        # Two independent cycle-boundary examples and all 60 distinct values.
        self.assertEqual(len(set(details.JIAZI)), 60)
        for i, pillar in enumerate(details.JIAZI):
            with self.subTest(pillar=pillar):
                result = details.build_details(pillars(day=pillar))
                self.assertEqual(result["pillars"]["day"]["nayin"], details.NAYIN_NAMES[i // 2])
        self.assertEqual(details.NAYIN["甲子"], "海中金")
        self.assertEqual(details.NAYIN["癸亥"], "大海水")
        self.assertEqual(details.NAYIN["乙巳"], "覆灯火")

    def test_illegal_yinyang_pairs_and_schema_are_rejected(self):
        for value in ("甲丑", "乙子", "甲子extra", "", 1, [], True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                details.build_details(pillars(year=value))
        for bad in (None, [], {}, {"year": "甲子"}, {**pillars(), "extra": None}):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                details.build_details(bad)

    def test_five_elements_and_polarity_examples(self):
        result = details.build_details(pillars("甲子", "乙丑", "戊辰", "辛酉"))
        self.assertEqual(result["pillars"]["year"]["stem"], {"character": "甲", "element": "木", "polarity": "阳"})
        self.assertEqual(result["pillars"]["year"]["branch"], {"character": "子", "element": "水", "polarity": "阳"})
        self.assertEqual(result["pillars"]["month"]["branch"]["polarity"], "阴")
        self.assertEqual(result["pillars"]["hour"]["stem"]["element"], "金")

    def test_ten_god_matrix_fixed_yang_and_yin_rows(self):
        self.assertEqual([details.ten_god("甲", s) for s in "甲乙丙丁戊己庚辛壬癸"],
                         ["比肩", "劫财", "食神", "伤官", "偏财", "正财", "七杀", "正官", "偏印", "正印"])
        self.assertEqual([details.ten_god("乙", s) for s in "甲乙丙丁戊己庚辛壬癸"],
                         ["劫财", "比肩", "伤官", "食神", "正财", "偏财", "正官", "七杀", "正印", "偏印"])
        self.assertEqual(details.ten_god("癸", "戊"), "正官")
        self.assertEqual(details.ten_god("辛", "癸"), "食神")

    def test_hidden_stems_and_day_master_marker(self):
        result = details.build_details(pillars("己巳", "庚午", "甲辰", "乙亥"))
        self.assertEqual([(s["character"], s["ten_god"]) for s in result["pillars"]["year"]["hidden_stems"]],
                         [("丙", "食神"), ("庚", "七杀"), ("戊", "偏财")])
        self.assertEqual([s["character"] for s in result["pillars"]["day"]["hidden_stems"]], ["戊", "乙", "癸"])
        self.assertEqual(result["pillars"]["day"]["ten_god"], "比肩")
        self.assertTrue(result["pillars"]["day"]["is_day_master"])
        self.assertFalse(result["pillars"]["year"]["is_day_master"])

    def test_growth_yang_yin_and_earth_convention(self):
        expected = {("甲", "亥"): "长生", ("甲", "子"): "沐浴", ("甲", "戌"): "养",
                    ("乙", "午"): "长生", ("乙", "巳"): "沐浴", ("乙", "子"): "病",
                    ("戊", "寅"): "长生", ("己", "酉"): "长生", ("辛", "子"): "长生"}
        for pair, value in expected.items():
            with self.subTest(pair=pair):
                self.assertEqual(details.growth_stage(*pair), value)
        text = details.build_details(pillars(day="己巳"))["chosen_convention"]["growth_stage"]
        self.assertIn("阳顺阴逆", text["method"])
        self.assertIn("并非唯一标准", text["school_variation"])

    def test_unknown_day_keeps_independent_information(self):
        result = details.build_details(pillars("甲子", "乙丑", None, "丁卯"))
        self.assertIsNone(result["day_master"])
        self.assertIsNone(result["pillars"]["day"])
        self.assertEqual(result["pillars"]["year"]["nayin"], "海中金")
        self.assertEqual(result["relations"]["branch_combinations"][0]["positions"], ["year", "month"])
        for key in ("year", "month", "hour"):
            self.assertIsNone(result["pillars"][key]["ten_god"])
            self.assertIsNone(result["pillars"][key]["growth_stage"])
            self.assertTrue(all(s["ten_god"] is None for s in result["pillars"][key]["hidden_stems"]))

    def test_unknown_hour_does_not_complete_a_relationship(self):
        result = details.build_details(pillars("甲申", "甲子", "甲戌"))
        self.assertFalse(result["complete"])
        self.assertEqual(result["missing_pillars"], ["hour"])
        self.assertIsNone(result["pillars"]["hour"])
        self.assertEqual(result["relations"]["triple_harmonies"], [])

    def test_all_unknown_is_explicit_and_json_serializable(self):
        result = details.build_details(pillars())
        self.assertEqual(result["missing_pillars"], ["year", "month", "day", "hour"])
        self.assertTrue(all(v == [] for v in result["relations"].values()))
        self.assertEqual(json.loads(json.dumps(result, ensure_ascii=False)), result)

    def test_pair_relations_preserve_actual_positions(self):
        result = details.build_details(pillars("甲子", "己丑", "庚午", "乙未"))["relations"]
        self.assertEqual([(r["rule"], r["positions"]) for r in result["stem_combinations"]],
                         [("甲己", ["year", "month"]), ("乙庚", ["day", "hour"])])
        self.assertEqual([r["rule"] for r in result["branch_combinations"]], ["子丑", "午未"])
        self.assertEqual([r["rule"] for r in result["branch_clashes"]], ["子午", "丑未"])
        self.assertEqual([r["rule"] for r in result["branch_harms"]], ["子未", "丑午"])

    def test_breaks_can_coexist_with_combination(self):
        result = details.build_details(pillars("丙寅", "丁亥"))["relations"]
        self.assertEqual(result["branch_breaks"][0]["characters"], ["寅", "亥"])
        self.assertEqual(result["branch_combinations"][0]["characters"], ["寅", "亥"])

    def test_triples_require_all_three_and_keep_duplicate_positions(self):
        partial = details.build_details(pillars("甲申", "甲子"))["relations"]
        self.assertEqual(partial["triple_harmonies"], [])
        result = details.build_details(pillars("甲申", "甲子", "戊辰", "庚辰"))["relations"]["triple_harmonies"]
        self.assertEqual([r["positions"] for r in result], [["year", "month", "day"], ["year", "month", "hour"]])
        self.assertTrue(all(r["complete"] and r["rule"] == "申子辰" for r in result))
        self.assertTrue(all(r["traditional_element"] == "水" for r in result))

    def test_meetings_require_all_three(self):
        self.assertEqual(details.build_details(pillars("丙寅", "丁卯"))["relations"]["triple_meetings"], [])
        result = details.build_details(pillars("丙寅", "丁卯", "戊辰"))["relations"]["triple_meetings"]
        self.assertEqual([(r["rule"], r["positions"]) for r in result], [("寅卯辰", ["year", "month", "day"])])

    def test_directed_punishment_and_full_group_flag(self):
        partial = details.build_details(pillars("甲申", "乙巳"))["relations"]["punishments"]
        self.assertEqual([(r["rule"], r["positions"], r["group_complete"]) for r in partial],
                         [("巳刑申", ["month", "year"], False)])
        result = details.build_details(pillars("丙寅", "丁巳", "戊申"))["relations"]["punishments"]
        self.assertEqual({r["rule"] for r in result}, {"寅刑巳", "巳刑申", "申刑寅"})
        self.assertTrue(all(r["group_complete"] for r in result))
        earth = details.build_details(pillars("乙丑", "丙戌", "丁未"))["relations"]["punishments"]
        self.assertEqual({r["rule"] for r in earth}, {"丑刑戌", "戌刑未", "未刑丑"})

    def test_mutual_punishment_with_duplicate_positions(self):
        result = details.build_details(pillars("甲子", "乙卯", "丙子"))["relations"]["punishments"]
        self.assertEqual([r["positions"] for r in result], [["year", "month"], ["month", "day"]])
        self.assertTrue(all(r["direction"] == "mutual" for r in result))

    def test_self_punishment_requires_repetition_and_restricted_branches(self):
        self.assertEqual(details.build_details(pillars("甲辰"))["relations"]["self_punishments"], [])
        result = details.build_details(pillars("甲辰", "丙辰", "戊辰"))["relations"]["self_punishments"]
        self.assertEqual([r["positions"] for r in result], [["year", "month"], ["year", "day"], ["month", "day"]])
        self.assertEqual(details.build_details(pillars("甲子", "丙子"))["relations"]["self_punishments"], [])
        for branch in "午酉亥":
            matching = next(p for p in details.JIAZI if p[1] == branch)
            self.assertEqual(len(details.build_details(pillars(matching, matching))["relations"]["self_punishments"]), 1)

    def test_result_is_fresh_and_input_is_unchanged(self):
        source = pillars("甲子", "乙丑", "丙寅")
        before = source.copy()
        first = details.build_details(source)
        first["chosen_convention"]["growth_stage"]["starts"]["甲"] = "子"
        self.assertEqual(details.build_details(source)["chosen_convention"]["growth_stage"]["starts"]["甲"], "亥")
        self.assertEqual(source, before)


class BundledLibraryParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = bundled_library()
        cls.util = importlib.import_module("lunar_python.util.LunarUtil").LunarUtil

    def test_all_sixty_nayin_against_bundled_table(self):
        self.assertEqual(details.NAYIN, self.util.NAYIN)

    def test_all_hundred_ten_gods_against_bundled_table(self):
        for day in "甲乙丙丁戊己庚辛壬癸":
            for other in "甲乙丙丁戊己庚辛壬癸":
                with self.subTest(day=day, other=other):
                    self.assertEqual(details.ten_god(day, other), self.util.SHI_SHEN[day + other])

    def test_hidden_stems_elements_and_clashes_against_bundled_tables(self):
        for stem in "甲乙丙丁戊己庚辛壬癸":
            self.assertEqual(details.stem_info(stem)["element"], self.util.WU_XING_GAN[stem])
        for i, branch in enumerate("子丑寅卯辰巳午未申酉戌亥"):
            self.assertEqual(list(details.HIDDEN_STEMS[branch]), self.util.ZHI_HIDE_GAN[branch])
            self.assertEqual(details.branch_info(branch)["element"], self.util.WU_XING_ZHI[branch])
            self.assertTrue(any(set(pair) == {branch, self.util.CHONG[i]} for pair in details.PAIR_RULES["branch_clashes"]))

    def test_all_hundred_twenty_growth_positions_against_public_library_method(self):
        ec_type = importlib.import_module("lunar_python.EightChar").EightChar

        class Sample:
            def getDayGanExact2(self):
                return self.day

            def getDayGanIndexExact2(self):
                return "甲乙丙丁戊己庚辛壬癸".index(self.day)

            def getYearZhiIndexExact(self):
                return "子丑寅卯辰巳午未申酉戌亥".index(self.branch)

        sample = Sample()
        ec = ec_type.fromLunar(sample)
        for sample.day in "甲乙丙丁戊己庚辛壬癸":
            for sample.branch in "子丑寅卯辰巳午未申酉戌亥":
                with self.subTest(day=sample.day, branch=sample.branch):
                    self.assertEqual(details.growth_stage(sample.day, sample.branch), ec.getYearDiShi())

    def test_real_calendar_examples_against_library(self):
        for y, m, d, h in ((1990, 5, 2, 12), (2000, 1, 1, 0), (2024, 2, 4, 18), (1984, 8, 10, 9)):
            ec = self.lib.Solar.fromYmdHms(y, m, d, h, 0, 0).getLunar().getEightChar()
            result = details.build_details(pillars(ec.getYear(), ec.getMonth(), ec.getDay(), ec.getTime()))
            for key, prefix in (("year", "Year"), ("month", "Month"), ("day", "Day"), ("hour", "Time")):
                item = result["pillars"][key]
                self.assertEqual(item["nayin"], getattr(ec, "get" + prefix + "NaYin")())
                self.assertEqual(item["growth_stage"], getattr(ec, "get" + prefix + "DiShi")())
                self.assertEqual([s["ten_god"] for s in item["hidden_stems"]], getattr(ec, "get" + prefix + "ShiShenZhi")())
                if key != "day":
                    self.assertEqual(item["ten_god"], getattr(ec, "get" + prefix + "ShiShenGan")())


if __name__ == "__main__":
    unittest.main()
