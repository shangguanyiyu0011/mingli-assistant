"""Preset contracts plus real Bazi and optionally prepared Ziwei/astronomy regressions."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", ROOT))
if not (SKILL / "scripts/presets.py").is_file():
    SKILL = ROOT / "package/mingxue-master"
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))
import presets
import chart
import ziwei
import astrology


def keep_evidence(name, value):
    directory = os.environ.get("MINGXUE_PRESET_EVIDENCE_DIR")
    if directory:
        folder = Path(directory)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class PresetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.birth = {"date_value": "2000-08-16", "time_value": "23:30:00", "timezone": "Asia/Shanghai", "gender": "female"}
        cls.base = chart.build_chart(**cls.birth, **presets.resolve_profile("baseline")["settings"]["bazi"])

    def test_all_profiles_resolve_and_are_independent(self):
        profiles = presets.load_profiles()
        self.assertGreaterEqual(len(profiles), 4)
        for profile in profiles:
            with self.subTest(profile=profile["id"]):
                self.assertEqual(profile, presets.resolve_profile(profile["id"]))
                self.assertEqual(set(profile["settings"]), {"bazi", "ziwei", "astrology"})
        profiles[0]["settings"]["bazi"]["sect"] = 99
        self.assertEqual(presets.resolve_profile("baseline")["settings"]["bazi"]["sect"], 2)

    def test_supported_setting_vocabularies_match_actual_adapters(self):
        self.assertEqual(presets.RULES["astrology"]["house_system"][1], set(astrology.HOUSE_SYSTEMS))
        self.assertEqual(presets.RULES["astrology"]["ayanamsa"][1] - {None}, set(astrology.AYANAMSAS))

    def test_overrides_are_explicit_and_do_not_modify_registry(self):
        modified = presets.resolve_profile("baseline", {"bazi": {"sect": 1}, "astrology": {"house_system": "W"}})
        self.assertEqual(modified["settings"]["bazi"]["sect"], 1)
        self.assertIn("覆写", modified["label"])
        self.assertEqual(presets.resolve_profile("baseline")["settings"]["bazi"]["sect"], 2)

    def test_reject_unknown_and_wrong_type_overrides(self):
        invalid = [[], {"qimen": {}}, {"bazi": []}, {"bazi": {"timezone": "UTC"}},
                   {"bazi": {"sect": True}}, {"bazi": {"sect": "1"}}, {"bazi": {"true_solar": 0}},
                   {"ziwei": {"algorithm": "all-schools"}}, {"ziwei": {"fix_leap": 1}},
                   {"ziwei": {"scope": "yearly"}}, {"astrology": {"house_system": "guess"}},
                   {"astrology": {"zodiac": "sidereal"}}, {"astrology": {"ayanamsa": "lahiri"}}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(presets.PresetError):
                presets.resolve_profile("baseline", value)
        for ident in (None, "BASELINE", "unknown", " baseline"):
            with self.subTest(ident=ident), self.assertRaises(presets.PresetError):
                presets.resolve_profile(ident)

    def test_sidereal_transition_requires_consistent_ayanamsa(self):
        self.assertEqual(presets.resolve_profile("baseline", {"astrology": {"zodiac": "sidereal", "ayanamsa": "raman"}})["settings"]["astrology"]["ayanamsa"], "raman")
        with self.assertRaises(presets.PresetError):
            presets.resolve_profile("astrology-lahiri", {"astrology": {"zodiac": "tropical"}})
        self.assertIsNone(presets.resolve_profile("astrology-lahiri", {"astrology": {"zodiac": "tropical", "ayanamsa": None}})["settings"]["astrology"]["ayanamsa"])

    def test_real_23h_bazi_changes_day_and_reports_rule_separately(self):
        alternate = chart.build_chart(**self.birth, **presets.resolve_profile("bazi-23h")["settings"]["bazi"])
        self.assertNotEqual(self.base["pillars"]["day"], alternate["pillars"]["day"])
        diff = presets.compare_results(self.base, alternate)
        self.assertFalse(diff["equal_chart"])
        self.assertTrue(any(item["path"] == "/input/sect" for item in diff["convention_changes"]))
        self.assertTrue(any(item["path"] == "/pillars/day" for item in diff["chart_changes"]))
        keep_evidence("bazi-baseline", self.base)
        keep_evidence("bazi-23h", alternate)
        keep_evidence("bazi-23h-comparison", diff)

    def test_same_real_chart_has_no_false_changes(self):
        diff = presets.compare_results(self.base, copy.deepcopy(self.base))
        self.assertTrue(diff["equal_chart"])
        self.assertTrue(diff["equal_result"])
        self.assertEqual(sum(diff["counts"].values()), 0)

    def test_away_from_boundary_rule_can_change_without_chart_difference(self):
        left = chart.build_chart("2000-08-16", "12:00:00", timezone="Asia/Shanghai", sect=2)
        right = chart.build_chart("2000-08-16", "12:00:00", timezone="Asia/Shanghai", sect=1)
        diff = presets.compare_results(left, right)
        self.assertTrue(diff["equal_chart"])
        self.assertFalse(diff["equal_result"])
        self.assertGreater(diff["counts"]["convention_changes"], 0)

    def test_ignore_only_absolute_path_noise_and_keep_version_difference(self):
        left = copy.deepcopy(self.base)
        right = copy.deepcopy(self.base)
        left["engine"] = {"engine_dir": "C:/cache/a", "version": "1"}
        right["engine"] = {"engine_dir": "D:/cache/b", "version": "1"}
        diff = presets.compare_results(left, right)
        self.assertTrue(diff["equal_result"])
        self.assertEqual(diff["ignored_path_changes"]["count"], 1)
        right["engine"]["version"] = "2"
        self.assertFalse(presets.compare_results(left, right)["equal_result"])

    def test_reject_different_birth_or_subject(self):
        for edit in ({"date": "2000-08-17"}, {"time": "23:31:00"}, {"timezone": "UTC"}, {"longitude": 120.0}):
            changed = copy.deepcopy(self.base)
            changed["input"].update(edit)
            with self.subTest(edit=edit), self.assertRaises(presets.PresetError):
                presets.compare_results(self.base, changed)
        changed = copy.deepcopy(self.base)
        changed["subject_id"] = "different-person"
        with self.assertRaises(presets.PresetError):
            presets.compare_results(self.base, changed)

    def test_reject_fragments_errors_and_other_systems(self):
        for value in ({}, [], self.base["pillars"], presets.resolve_profile("baseline"),
                      {"schema_version": 1, "system": "qimen", "input": {}},
                      {"schema_version": 1, "system": "astrology", "status": "engine_unavailable", "input": {}}):
            with self.subTest(value=str(value)[:60]), self.assertRaises(presets.PresetError):
                presets.compare_results(self.base, value)

    def test_numeric_types_and_precise_calculation_differences_not_rounded(self):
        left, right = copy.deepcopy(self.base), copy.deepcopy(self.base)
        left["candidates"][0]["numeric_probe"] = {"typed": True, "value": 1.0}
        right["candidates"][0]["numeric_probe"] = {"typed": 1, "value": 1.000000000000001}
        diff = presets.compare_results(left, right)
        paths = {item["path"] for item in diff["chart_changes"]}
        self.assertIn("/candidates/0/numeric_probe/typed", paths)
        self.assertIn("/candidates/0/numeric_probe/value", paths)

    def test_output_is_bounded_but_difference_count_is_complete(self):
        left, right = copy.deepcopy(self.base), copy.deepcopy(self.base)
        left["candidates"][0]["many_values"] = list(range(150))
        right["candidates"][0]["many_values"] = list(range(1, 151))
        diff = presets.compare_results(left, right)
        self.assertTrue(diff["truncated"])
        self.assertEqual(diff["counts"]["chart_changes"], 150)
        self.assertEqual(len(diff["chart_changes"]), 100)
        self.assertEqual(diff["omitted_counts"]["chart_changes"], 50)

    def test_reject_non_json_cycles_and_excessive_depth(self):
        for value in (float("nan"), Path("a")):
            changed = copy.deepcopy(self.base)
            changed["extra"] = value
            with self.subTest(value=str(value)), self.assertRaises(presets.PresetError):
                presets.compare_results(self.base, changed)
        changed = copy.deepcopy(self.base)
        changed["extra"] = changed
        with self.assertRaises(presets.PresetError):
            presets.compare_results(self.base, changed)
        changed = copy.deepcopy(self.base)
        nested = changed
        for _ in range(presets.MAX_DEPTH + 1):
            nested["extra"] = {}
            nested = nested["extra"]
        with self.assertRaises(presets.PresetError):
            presets.compare_results(self.base, changed)

    def test_cli_list_resolve_and_absolute_compare_paths(self):
        script = SCRIPTS / "presets.py"
        def run(*args):
            return subprocess.run([sys.executable, "-X", "utf8", "-B", str(script), *args], capture_output=True, text=True, encoding="utf-8")
        self.assertIsInstance(json.loads(run("--list").stdout), list)
        self.assertEqual(json.loads(run("resolve", "baseline").stdout)["id"], "baseline")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "chart.json"
            path.write_text(json.dumps(self.base), encoding="utf-8")
            result = run("compare", "--left", str(path), "--right", str(path))
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue(json.loads(result.stdout)["equal_chart"])
            path.write_text('{"bazi":{"sect":1,"sect":2}}', encoding="utf-8")
            self.assertEqual(run("resolve", "baseline", "--overrides", str(path)).returncode, 2)
        self.assertEqual(run("compare", "--left", "relative.json", "--right", "relative.json").returncode, 2)
        invalid = run("unknown-command")
        self.assertEqual(invalid.returncode, 2)
        self.assertFalse(json.loads(invalid.stdout)["ok"])
        self.assertEqual(invalid.stderr, "")


@unittest.skipUnless(os.environ.get("MINGXUE_ZIWEI_ENGINE"), "Real Ziwei test needs explicitly prepared MINGXUE_ZIWEI_ENGINE")
class RealZiweiPresetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.birth = chart.build_chart("2000-08-16", "23:30:00", timezone="Asia/Shanghai", gender="female")
        cls.base = ziwei.build_ziwei(chart=cls.birth, **presets.resolve_profile("baseline")["settings"]["ziwei"])

    def test_real_late_zi_changes_actual_palaces(self):
        alternate = ziwei.build_ziwei(chart=self.birth, **presets.resolve_profile("late-zi-current")["settings"]["ziwei"])
        self.assertNotEqual(self.base["chart"]["palaces"], alternate["chart"]["palaces"])
        diff = presets.compare_results(self.base, alternate)
        self.assertFalse(diff["equal_chart"])
        self.assertTrue(any(item["path"] == "/convention/day_divide" for item in diff["convention_changes"]))
        self.assertGreater(diff["counts"]["chart_changes"], 0)
        keep_evidence("ziwei-baseline", self.base)
        keep_evidence("ziwei-late-zi-current", alternate)
        keep_evidence("ziwei-late-zi-comparison", diff)

    def test_real_same_chart_and_unknown_source_identity(self):
        self.assertTrue(presets.compare_results(self.base, copy.deepcopy(self.base))["equal_result"])
        changed = copy.deepcopy(self.base)
        changed["source_chart"]["input_hash"] = "0" * 64
        with self.assertRaises(presets.PresetError):
            presets.compare_results(self.base, changed)

    def test_different_target_period_or_scope_is_refused(self):
        changed = copy.deepcopy(self.base)
        changed["scope"] = "yearly"
        changed["target"] = {"date": "2027-01-01", "time": None, "time_index": 0}
        with self.assertRaises(presets.PresetError):
            presets.compare_results(self.base, changed)
        changed = copy.deepcopy(self.base)
        changed["target"] = {"date": "2027-01-01", "time": None, "time_index": 0}
        with self.assertRaises(presets.PresetError):
            presets.compare_results(changed, copy.deepcopy(changed))


@unittest.skipUnless(os.environ.get("MINGXUE_ASTRO_ENGINE"), "Real astronomy test needs explicitly prepared MINGXUE_ASTRO_ENGINE")
class RealAstrologyPresetTests(unittest.TestCase):
    def test_real_house_system_comparison_keeps_actual_changes(self):
        birth = chart.build_chart("2000-08-16", "23:30:00", timezone="Asia/Shanghai", longitude=121.47)
        left = astrology.build_astrology(birth, latitude=31.23, **presets.resolve_profile("baseline")["settings"]["astrology"])
        right = astrology.build_astrology(birth, latitude=31.23, **presets.resolve_profile("astrology-whole-sign")["settings"]["astrology"])
        self.assertEqual(left["status"], "calculated")
        self.assertEqual(right["status"], "calculated")
        diff = presets.compare_results(left, right)
        self.assertFalse(diff["equal_chart"])
        self.assertTrue(any(item["path"] == "/house_system/code" for item in diff["convention_changes"]))
        self.assertGreater(diff["counts"]["chart_changes"], 0)
        keep_evidence("astrology-baseline", left)
        keep_evidence("astrology-whole-sign", right)
        keep_evidence("astrology-house-comparison", diff)


if __name__ == "__main__":
    unittest.main()
