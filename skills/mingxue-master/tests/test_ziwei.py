"""Offline adapter tests; optional real-engine checks require an explicit local path."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", HERE))
if not (SKILL / "scripts/ziwei.py").is_file():
    SKILL = HERE / "package/mingxue-master"
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))
import ziwei
import prepare_ziwei


def fake_chart(gender="女"):
    palaces = []
    for index in range(12):
        stars = [{"name": "测试星" + str(index), "type": "major", "scope": "origin"}]
        if index < 4:
            stars[0]["mutagen"] = ["禄", "权", "科", "忌"][index]
        palaces.append({"index": index, "name": "命宫" if index == 0 else "宫" + str(index),
                        "isBodyPalace": index == 1, "earthlyBranch": "子", "majorStars": stars,
                        "minorStars": [], "adjectiveStars": [], "decadal": {"range": [3, 12]},
                        "ages": [1], "changsheng12": "长生", "boshi12": "博士"})
    return {"gender": gender, "solarDate": "2000-08-16", "fiveElementsClass": "木三局", "palaces": palaces}


def response(charts):
    return {"status": "ok", "engine": {"name": "iztro", "version": "2.6.3", "abi": 1}, "charts": charts}


def shared_chart():
    return {"schema_version": 3, "time_known": True, "input": {"gender": "female"},
            "time_context": {"timezone": "America/New_York", "fold_status": "not_ambiguous"},
            "uncertainty": [], "candidates": [{"time": {"chart_clock": "2000-08-15 23:30:00", "chart_time_basis": "true-solar-time"}}]}


class OfflineZiweiTests(unittest.TestCase):
    def test_all_hour_boundaries(self):
        for value, expected in {"00:00": 0, "00:59:59": 0, "01:00": 1, "02:59": 1,
                                "03:00": 2, "22:59": 11, "23:00": 12, "23:59:59": 12}.items():
            self.assertEqual(ziwei.time_index(value), expected)
        for value in ("24:00", "23:60", "1:30", "00:00:60", None):
            with self.assertRaises(ziwei.ZiweiError):
                ziwei.time_index(value)

    def test_unknown_time_never_calls_engine(self):
        with patch.object(ziwei, "call_engine") as engine:
            with self.assertRaises(ziwei.ZiweiError) as error:
                ziwei.build_ziwei("2000-08-16")
            self.assertEqual(error.exception.status, "needs_input")
            engine.assert_not_called()

    def test_missing_cache_probe_does_not_install(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(ziwei.subprocess, "run") as runner:
            with self.assertRaises(ziwei.ZiweiError) as error:
                ziwei.probe(folder)
            self.assertEqual(error.exception.status, "needs_setup")
            runner.assert_not_called()

    def test_cache_cannot_pollute_skill(self):
        with self.assertRaises(ziwei.ZiweiError):
            ziwei.engine_directory(SCRIPTS / "cache")

    def test_wrong_version_does_not_run(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / "node_modules" / "iztro" / "package.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text('{"version":"0.0.0"}', encoding="utf-8")
            with patch.object(ziwei.subprocess, "run") as runner:
                with self.assertRaises(ziwei.ZiweiError) as error:
                    ziwei.probe(folder)
                self.assertEqual(error.exception.status, "needs_setup")
                runner.assert_not_called()

    def test_shared_uses_adopted_date_without_second_correction(self):
        data = shared_chart()
        with patch.object(ziwei, "call_engine", return_value=response([fake_chart()])) as engine:
            result = ziwei.build_ziwei(chart=data)
        payload = engine.call_args.args[0]
        self.assertEqual(payload["solar_date"], "2000-08-15")
        self.assertEqual(payload["time_index"], 12)
        self.assertEqual(result["input"]["time_basis"], "true-solar-time")
        self.assertIn("not the shared Bazi", result["convention"]["calendar_basis"])

    def test_source_chart_hash_identifies_shared_input_only(self):
        data = shared_chart()
        data["input"].update(date="2000-08-16", note="测试输入")
        expected = hashlib.sha256(json.dumps(data["input"], ensure_ascii=False, sort_keys=True,
                                             separators=(",", ":")).encode("utf-8")).hexdigest()
        with patch.object(ziwei, "call_engine", return_value=response([fake_chart()])):
            shared = ziwei.build_ziwei(chart=data)
            direct = ziwei.build_ziwei("2000-08-16", index=2, gender="female")
        self.assertEqual(shared["source_chart"], {"schema_version": 3, "input_hash": expected})
        self.assertIsNone(direct["source_chart"])

    def test_shared_unknown_and_multiple_rejected(self):
        for mutation, status in [(lambda d: d.update(time_known=False), "needs_input"),
                                 (lambda d: d["candidates"].append(copy.deepcopy(d["candidates"][0])), "ambiguous_input"),
                                 (lambda d: d["time_context"].update(fold_status="unresolved"), "ambiguous_input"),
                                 (lambda d: d["uncertainty"].append({"code": "solar_clock_near_boundary"}), "ambiguous_input")]:
            data = shared_chart()
            mutation(data)
            with self.assertRaises(ziwei.ZiweiError) as error:
                ziwei.resolve_chart(data)
            self.assertEqual(error.exception.status, status)

    def test_gender_not_inferred_and_dependent_fields_omitted(self):
        female, male = fake_chart(), fake_chart("男")
        female["palaces"][1]["adjectiveStars"] = [{"name": "只在一种规则下"}]
        with patch.object(ziwei, "call_engine", return_value=response([male, female])) as engine:
            result = ziwei.build_ziwei("2000-08-16", "03:30")
        self.assertIsNone(engine.call_args.args[0]["gender"])
        self.assertEqual(result["status"], "partial")
        self.assertIsNone(result["chart"]["gender"])
        for p in result["chart"]["palaces"]:
            self.assertNotIn("decadal", p)
            self.assertNotIn("ages", p)
        self.assertEqual(result["chart"]["palaces"][1]["adjectiveStars"], [])
        self.assertEqual(len(result["natal_mutagens"]), 4)

    def test_gender_conflict_rejected(self):
        with self.assertRaises(ziwei.ZiweiError):
            ziwei.build_ziwei(chart=shared_chart(), gender="male")

    def test_malformed_shared_objects_rejected_as_input(self):
        for mutation in (lambda d: d.update(time_context=[]), lambda d: d.update(input=[]),
                         lambda d: d.update(candidates=[None]), lambda d: d.update(uncertainty=[None])):
            data = shared_chart()
            mutation(data)
            with self.assertRaises(ziwei.ZiweiError):
                ziwei.resolve_chart(data)

    def test_rejects_bad_dates_indices_and_conflicts(self):
        for kwargs in ({"date_value": "1899-12-31", "index": 0}, {"date_value": "2000-02-30", "index": 0},
                       {"date_value": "2000-01-01", "index": 13}, {"date_value": "2000-01-01", "index": True},
                       {"date_value": "2000-01-01", "index": 1, "time_value": "03:00"},
                       {"date_value": "2000-01-01", "chart": shared_chart()}):
            with self.assertRaises(ziwei.ZiweiError):
                ziwei.build_ziwei(**kwargs)

    def test_missing_four_mutagens_rejected(self):
        chart = fake_chart()
        chart["palaces"][0]["majorStars"][0].pop("mutagen")
        with patch.object(ziwei, "call_engine", return_value=response([chart])):
            with self.assertRaises(ziwei.ZiweiError) as error:
                ziwei.build_ziwei("2000-08-16", index=2, gender="female")
            self.assertEqual(error.exception.status, "engine_error")

    def test_prepare_is_explicit_pinned_isolated_and_scripts_disabled(self):
        def package_files(name, source):
            return {f"node_modules/{name}/package.json": json.dumps({"version": prepare_ziwei.DEPENDENCY_PINS[name]}).encode("utf-8")}
        with tempfile.TemporaryDirectory() as folder, patch.object(prepare_ziwei, "find_node", return_value="node"), \
             patch.object(prepare_ziwei, "download_archive") as download, \
             patch.object(prepare_ziwei, "archive_files", side_effect=package_files), \
             patch.object(prepare_ziwei, "verify_engine_directory", return_value={"status": "verified"}), \
             patch.object(ziwei.subprocess, "run") as runner, \
             patch.object(prepare_ziwei, "probe", return_value={"status": "available"}):
            engine = Path(folder) / "isolated-engine"
            result = prepare_ziwei.prepare(engine)
            self.assertEqual([call.args[0] for call in download.call_args_list], list(prepare_ziwei.DEPENDENCY_PINS))
            self.assertEqual(prepare_ziwei.DEPENDENCY_PINS["iztro"], "2.6.3")
            self.assertEqual(set(prepare_ziwei.DEPENDENCY_PINS), set(prepare_ziwei.INTEGRITIES))
            self.assertEqual(result["status"], "ready")
            self.assertFalse(result["scripts_executed"])
            runner.assert_not_called()
            marker = json.loads((engine / "mingxue-engine.json").read_text(encoding="utf-8"))
            self.assertEqual(marker["integrity_schema_version"], 1)
            self.assertEqual(marker["dependency_pins"], prepare_ziwei.DEPENDENCY_PINS)

    def test_default_persistent_cache_and_override_priority(self):
        import runtime_paths
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True), \
             patch.object(runtime_paths, "engine_directory", return_value=Path(folder) / "default") as persistent:
            self.assertEqual(ziwei.engine_directory(), Path(folder) / "default")
            persistent.assert_called_once_with("ziwei", "2.6.3")
            persistent.reset_mock()
            with patch.dict(os.environ, {"MINGXUE_ZIWEI_ENGINE": str(Path(folder) / "env")}):
                self.assertEqual(ziwei.engine_directory(), Path(folder) / "env")
                self.assertEqual(ziwei.engine_directory(Path(folder) / "explicit"), Path(folder) / "explicit")
            persistent.assert_not_called()

    def test_new_manifest_integrity_checked_before_node(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / "node_modules" / "iztro" / "package.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text('{"version":"2.6.3"}', encoding="utf-8")
            (Path(folder) / "mingxue-engine.json").write_text('{"integrity_schema_version":1}', encoding="utf-8")
            with patch.object(prepare_ziwei, "verify_engine_directory", side_effect=ziwei.ZiweiError("engine_integrity_error", "tampered")) as verify, \
                 patch.object(ziwei.subprocess, "run") as runner:
                with self.assertRaises(ziwei.ZiweiError) as error:
                    ziwei.probe(folder)
                self.assertEqual(error.exception.status, "engine_integrity_error")
                verify.assert_called_once()
                runner.assert_not_called()

    def test_legacy_cache_remains_usable_and_explicitly_labeled(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / "node_modules" / "iztro" / "package.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text('{"version":"2.6.3"}', encoding="utf-8")
            value = json.dumps({"status": "available", "engine": {"abi": 1, "version": "2.6.3"}})
            with patch.object(prepare_ziwei, "verify_engine_directory") as verify, \
                 patch.object(ziwei, "node_executable", return_value="node"), \
                 patch.object(ziwei.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, value, "")):
                result = ziwei.probe(folder)
            verify.assert_not_called()
            self.assertEqual(result["engine"]["integrity"], "legacy_version_only")


@unittest.skipUnless(os.environ.get("MINGXUE_TEST_ZIWEI_ENGINE"), "explicit local engine required; no automatic download")
class RealEngineZiweiTests(unittest.TestCase):
    def setUp(self):
        self.directory = os.environ["MINGXUE_TEST_ZIWEI_ENGINE"]

    def test_official_sample_fields_and_mutagens(self):
        result = ziwei.build_ziwei("2000-08-16", index=2, gender="female", engine_dir=self.directory)
        chart = result["chart"]
        self.assertEqual(len(chart["palaces"]), 12)
        self.assertEqual(chart["lunarDate"], "二〇〇〇年七月十七")
        self.assertEqual(chart["chineseDate"], "庚辰 甲申 丙午 庚寅")
        self.assertEqual(chart["fiveElementsClass"], "木三局")
        self.assertEqual(chart["earthlyBranchOfSoulPalace"], "午")
        self.assertEqual(chart["earthlyBranchOfBodyPalace"], "戌")
        self.assertEqual(chart["soul"], "破军")
        self.assertEqual(chart["body"], "文昌")
        self.assertEqual({(v["star"], v["mutagen"]) for v in result["natal_mutagens"]},
                         {("太阳", "禄"), ("武曲", "权"), ("太阴", "科"), ("天同", "忌")})
        self.assertNotIn("copyright", json.dumps(chart))
        self.assertEqual(chart["palaces"][0]["surroundedPalaces"], {"target": 0, "opposite": 6, "wealth": 8, "career": 4})

    def test_probe_and_no_gender(self):
        self.assertEqual(ziwei.probe(self.directory)["status"], "available")
        result = ziwei.build_ziwei("2000-08-16", "03:30", engine_dir=self.directory)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["chart"]["palaces"]), 12)
        self.assertTrue(result["gender_dependent_omitted"])

    def test_day_divide_leap_and_algorithm_are_real_options(self):
        common = dict(engine_dir=self.directory, gender="female")
        forward = ziwei.build_ziwei("2000-08-16", "23:30", day_divide="forward", **common)
        current = ziwei.build_ziwei("2000-08-16", "23:30", day_divide="current", **common)
        self.assertNotEqual(forward["chart"]["palaces"], current["chart"]["palaces"])
        # 2023-04-10 is in the second half of leap month two.
        adjusted = ziwei.build_ziwei("2023-04-10", index=2, fix_leap=True, **common)
        unadjusted = ziwei.build_ziwei("2023-04-10", index=2, fix_leap=False, **common)
        self.assertNotEqual(adjusted["chart"]["earthlyBranchOfSoulPalace"], unadjusted["chart"]["earthlyBranchOfSoulPalace"])
        zhongzhou = ziwei.build_ziwei("2000-08-16", index=2, algorithm="zhongzhou", **common)
        self.assertEqual(zhongzhou["convention"]["algorithm"], "zhongzhou")


if __name__ == "__main__":
    unittest.main()
