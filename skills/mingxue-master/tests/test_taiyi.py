"""Offline validation and explicitly enabled real isolated Taiyi fixture checks."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get('MINGXUE_TEST_SKILL_ROOT') or (ROOT/'package/mingxue-master' if (ROOT/'package/mingxue-master').is_dir() else ROOT))
sys.path.insert(0, str(SKILL / "scripts"))
import taiyi
import prepare_taiyi

PARAMS = {"date": "2026-03-24", "time": "12:30", "mode": "hour", "method": 1}
FIXTURES = json.loads(r'''{"year-0":[55,10155943,16,3,22,3],"year-1":[55,1938583,16,3,22,3],"year-2":[43,10156219,8,17,1,8],"year-3":[55,10155943,16,3,22,3],"month-0":[4,121871308,25,17,10,2],"month-1":[4,23262988,25,17,10,2],"month-2":[4,121874620,25,17,10,2],"month-3":[4,121871308,25,17,10,2],"day-0":[70,708056854,30,4,15,9],"day-1":[69,708056853,16,32,8,8],"day-2":[70,708056854,30,4,15,9],"day-3":[65,585497,15,1,34,7],"hour-0":[43,8496682243,8,17,1,8],"hour-1":[1,8374835251,7,13,14,8],"hour-2":[7,8374835239,8,25,9,3],"hour-3":[43,43,8,17,1,8]}''')

def fake_raw():
    return {"局式": {"文": "陽遁一局", "數": 1}, "主算": [7], "客算": [13], "定算": [14],
            "十六宮分佈": {key: ["太乙"] if key == "子" else [] for key in taiyi.RING + ["中"]},
            "八門分佈": {"8": "休"}, "太乙落宮": 8, "太乙": "子", "文昌": ["申", ""]}

class OfflineTaiyiTests(unittest.TestCase):
    def test_validates_modes_method_clock_and_explicit_convention(self):
        cases = [({}, "needs_input"), ({**PARAMS, "time": None}, "needs_input"),
                 ({**PARAMS, "date": "2026-02-30"}, "invalid_input"),
                 ({**PARAMS, "time": "24:00"}, "invalid_input"),
                 ({**PARAMS, "date": "1899-12-31"}, "unsupported_range"),
                 ({**PARAMS, "mode": "minute"}, "unsupported_mode"),
                 ({**PARAMS, "mode": "life"}, "unsupported_mode"),
                 ({**PARAMS, "method": True}, "invalid_input"),
                 ({**PARAMS, "method": 4}, "invalid_input"),
                 ({**PARAMS, "timezone": "America/New_York"}, "unsupported_convention"),
                 ({**PARAMS, "auto_ai": True}, "invalid_input")]
        with patch.object(taiyi, "_call_engine") as engine:
            for params, status in cases:
                with self.subTest(params=params):
                    self.assertEqual(taiyi.calculate(params)["status"], status)
            engine.assert_not_called()

    def test_no_engine_is_structured_and_no_network_or_process(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(taiyi.subprocess, "run") as runner, \
             patch.object(prepare_taiyi, "download_artifact") as download:
            result = taiyi.calculate(dict(PARAMS, engine_dir=folder))
            self.assertEqual(result["status"], "needs_setup")
            self.assertIn("--engine-dir", result["prepare_command"])
            runner.assert_not_called()
            download.assert_not_called()

    def test_probe_missing_cache_does_not_prepare(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(prepare_taiyi, "download_artifact") as download:
            result = taiyi.probe(folder)
            self.assertEqual(result["status"], "needs_setup")
            self.assertFalse(result["available"])
            download.assert_not_called()

    def test_persistent_default_and_explicit_cache(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"MINGXUE_TAIYI_ENGINE": folder}):
            self.assertEqual(taiyi.engine_directory(), Path(folder))
            result = taiyi.calculate(dict(PARAMS, engine_dir="relative-cache"))
            self.assertEqual(result["status"], "invalid_input")

    def test_nine_visual_groups_keep_all_sixteen_original_positions(self):
        raw = fake_raw()
        raw["十六宮分佈"]["寅"] = ["天乙"]
        result = taiyi._adapt(raw, PARAMS, 100, {"year": 2026})
        self.assertEqual(len(result["nine_palaces"]), 9)
        self.assertEqual(len(result["sixteen_palaces"]), 16)
        by_num = {item["number"]: item for item in result["nine_palaces"]}
        self.assertEqual(by_num[8]["name"], "子")
        self.assertEqual((by_num[1]["row"], by_num[1]["col"]), (0, 0))
        self.assertIn({"name": "天乙", "position": "寅"}, by_num[3]["stars"])
        self.assertEqual(by_num[8]["door"], "休")
        labels = [p["position"] for item in result["nine_palaces"] for p in item["sub_palaces"]]
        self.assertEqual(set(labels), set(taiyi.RING + ["中"]))
        self.assertEqual(len(labels), 17)

    def test_incomplete_real_board_rejected(self):
        for field in ("局式", "主算", "十六宮分佈"):
            raw = fake_raw()
            raw.pop(field)
            with self.assertRaises(taiyi.TaiyiError):
                taiyi._adapt(raw, PARAMS, 100, {})

    def test_adapter_does_not_return_raw_ai_or_predictions(self):
        raw = fake_raw()
        raw["AI_PROMO"] = "not part of a calculation result"
        with patch.object(taiyi, "_call_engine", return_value={"raw": raw, "accumulated": 100, "lunar": {}, "runtime": "3.11.9"}):
            result = taiyi.calculate(PARAMS)
        self.assertEqual(result["status"], "ok")
        self.assertNotIn("AI_PROMO", json.dumps(result))
        self.assertFalse(result["rules"]["ai_enabled"])
        self.assertFalse(result["rules"]["game_theory_enabled"])

    def test_archive_hash_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "bad.zip"
            archive.write_bytes(b"not an archive")
            with self.assertRaises(taiyi.TaiyiError) as error:
                taiyi.archive_files("source", archive)
            self.assertEqual(error.exception.status, "engine_integrity_error")

    def test_zip_traversal_rejected_even_with_matching_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "bad.zip"
            with zipfile.ZipFile(archive, "w") as stream:
                stream.writestr("../escape.py", "bad")
            artifact = dict(taiyi.ARTIFACTS["source"], sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
            with patch.dict(taiyi.ARTIFACTS, {"source": artifact}), self.assertRaises(taiyi.TaiyiError):
                taiyi.archive_files("source", archive)

    def test_manifest_cannot_bless_changed_extracted_content(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "python").mkdir()
            (root / "runtime").mkdir()
            expected = {}
            for name in taiyi.ARTIFACTS:
                path = root / "python" / (name + ".data")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixed")
                expected[path.relative_to(root).as_posix()] = hashlib.sha256(b"fixed").hexdigest()
            marker = {"commit": taiyi.ENGINE_COMMIT, "adapter_abi": taiyi.ENGINE_ABI, "files": expected}
            (root / "engine.json").write_text(json.dumps(marker), encoding="utf-8")
            with patch.object(taiyi, "archive_files", side_effect=lambda name, path: {f"python/{name}.data": b"fixed"}):
                self.assertEqual(taiyi.verify_engine(root)["status"], "verified")
                (root / "python/source.data").write_bytes(b"changed")
                marker["files"]["python/source.data"] = hashlib.sha256(b"changed").hexdigest()
                (root / "engine.json").write_text(json.dumps(marker), encoding="utf-8")
                with self.assertRaises(taiyi.TaiyiError):
                    taiyi.verify_engine(root)

    def test_explicit_prepare_is_external_pinned_and_no_install_scripts(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "engine"
            with patch.object(prepare_taiyi, "download_artifact") as download, \
                 patch.object(prepare_taiyi, "archive_files", side_effect=lambda name, path: {f"python/{name}.data": b"fixed"}), \
                 patch.object(prepare_taiyi, "verify_engine", return_value={"status": "verified"}), \
                 patch.object(prepare_taiyi, "probe", return_value={"available": True}), \
                 patch.object(taiyi.subprocess, "run") as runner:
                result = prepare_taiyi.prepare(target)
            self.assertEqual(result["status"], "ready")
            self.assertEqual(len(download.call_args_list), len(taiyi.ARTIFACTS))
            self.assertFalse(result["scripts_executed"])
            runner.assert_not_called()
            self.assertTrue((target / "engine.json").is_file())
            self.assertFalse((ROOT / "package/mingxue-master/engine.json").is_file())

@unittest.skipUnless(os.environ.get("MINGXUE_TEST_TAIYI_ENGINE"), "explicit existing isolated engine only; no automatic download")
class RealTaiyiTests(unittest.TestCase):
    def call(self, **kwargs):
        return taiyi.calculate({**PARAMS, "engine_dir": os.environ["MINGXUE_TEST_TAIYI_ENGINE"], **kwargs})

    def test_all_sixteen_mode_method_fixture_boards(self):
        for key, expected in FIXTURES.items():
            mode, method = key.split("-")
            with self.subTest(mode=mode, method=method):
                value = self.call(mode=mode, method=int(method))
                self.assertEqual(value["status"], "ok", value.get("message"))
                c = value["chart"]
                observed = [c["bureau"]["數"], c["accumulated_number"], c["host_count"], c["guest_count"], c["fixed_count"], c["positions"]["太乙落宮"]]
                self.assertEqual(observed, expected)
                self.assertEqual(len(c["nine_palaces"]), 9)
                self.assertEqual(len(c["sixteen_palaces"]), 16)
                self.assertEqual(value["engine"]["runtime"], "3.11.9")

    def test_day_method_three_integral_type_fix_preserves_formula_value(self):
        result = self.call(mode="day", method=3)
        c = result["chart"]
        lunar = c["lunar"]
        formula = round((lunar["year"] - 423) * (235 / 19) * 29.5306 + lunar["day"], 0)
        self.assertEqual(c["accumulated_number"], formula)
        self.assertIs(type(c["accumulated_number"]), int)
        self.assertEqual(c["accumulated_number"], 585497)

    def test_zero_bureau_boundary_is_rejected_not_fabricated(self):
        value = self.call(time="10:30", mode="hour", method=1)
        self.assertEqual(value["status"], "unsupported_boundary")
        self.assertNotIn("chart", value)

    def test_month_end_late_zi_and_cny_boundary(self):
        end = self.call(date="2026-01-31", time="23:30", mode="hour")
        before = self.call(date="2026-02-16", time="23:30", mode="year")
        after = self.call(date="2026-02-17", time="00:30", mode="year")
        self.assertEqual(end["status"], "ok")
        self.assertEqual(before["chart"]["lunar"]["year"], 2025)
        self.assertEqual(after["chart"]["lunar"]["year"], 2026)
        self.assertEqual(after["chart"]["accumulated_number"] - before["chart"]["accumulated_number"], 1)
        self.assertEqual(before["chart"]["positions"]["干支"][2], after["chart"]["positions"]["干支"][2])

    def test_leap_month_is_explicit(self):
        value = self.call(date="2023-04-06", time="12:30", mode="month")
        self.assertTrue(value["chart"]["lunar"]["is_leap"])
        self.assertEqual(value["chart"]["lunar"]["month"], 2)
        self.assertEqual(value["chart"]["lunar"]["day"], 16)

    def test_real_probe_is_offline_verified(self):
        value = taiyi.probe(os.environ["MINGXUE_TEST_TAIYI_ENGINE"])
        self.assertEqual(value["status"], "available")
        self.assertEqual(value["engine"]["integrity"], "verified")
        self.assertFalse(value["network_access"])

    def test_official_engine_example_bureau_and_lunar_fixture(self):
        # Verify the fixed engine's own documented historical fixture without
        # exposing historical calendar interpretation in the public adapter.
        params = {"date": "1552-09-24", "time": "00:00", "mode": "year", "method": 1,
                  "year": 1552, "month": 9, "day": 24, "hour": 0, "minute": 0}
        value = taiyi._call_engine(Path(os.environ["MINGXUE_TEST_TAIYI_ENGINE"]), "calculate", params)
        self.assertEqual(value["raw"]["局式"]["數"], 13)
        self.assertEqual(value["raw"]["農曆"], {"年": 1552, "月": 9, "日": 7})
        self.assertEqual(taiyi.calculate(params)["status"], "invalid_input")

if __name__ == "__main__":
    unittest.main()

