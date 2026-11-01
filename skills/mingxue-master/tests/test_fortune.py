"""Unified route, input-chain and file-boundary regression checks."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", HERE))
if not (SKILL / "scripts/chart.py").is_file():
    SKILL = HERE / "package/mingxue-master"
sys.path.insert(0, str(SKILL / "scripts"))
import fortune
from chart import build_chart


def cli(*args):
    result = subprocess.run([sys.executable, "-X", "utf8", "-B", str(SKILL / "scripts/fortune.py"), *args],
        capture_output=True, text=True, encoding="utf-8", timeout=120)
    return result, json.loads(result.stdout)


class FortuneTests(unittest.TestCase):
    def test_registry_references_and_real_vs_reference_levels(self):
        rows = fortune.registry()
        self.assertEqual(len(rows), 25)
        self.assertEqual(len({r["id"] for r in rows}), 25)
        for row in rows:
            self.assertTrue((SKILL / row["reference"]).is_file())
            if row["script"]:
                self.assertTrue((SKILL / "scripts" / row["script"]).is_file())
        for name in ("qimen", "liuren", "human_design"):
            self.assertIsNone(fortune.find_system(name)["script"])

    def test_native_aliases_symbolic_and_visual_probe(self):
        for route in ("姓名学", "numerology", "tarot", "palm", "face", "qimen"):
            with self.subTest(route=route):
                result, value = cli(route, "--probe")
                self.assertEqual(result.returncode, 0, result.stderr)
                if route in ("palm", "face"):
                    self.assertEqual(value["payload"]["system"], route)
                    self.assertEqual(value["payload"]["observation_status"], "not_observed")
                    self.assertFalse(value["payload"]["image_content_analysis"])
                elif route == "qimen":
                    self.assertEqual(value["status"], "reference_only")

    def test_given_pillars_and_new_saved_native_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "provided.json"
            result, value = cli("bazi", "--bazi", "癸巳", "甲子", "丁酉", "甲辰", "--save", str(path))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), value["payload"])
            self.assertIsNone(value["payload"]["source_chart"])
            self.assertEqual(value["payload"]["details"]["day_master"]["character"], "丁")
            original = path.read_bytes()
            result, value = cli("bazi", "--bazi", "癸巳甲子丁酉甲辰", "--save", str(path))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(path.read_bytes(), original)

    def test_declared_links_mismatch_labels_and_result_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "a.json"
            z = root / "z.json"
            astro = root / "astro.json"
            a.write_text(json.dumps({"system": "bazi", "schema_version": 3, "input": {"date": "1990-05-02"}}), encoding="utf-8")
            digest = fortune._input_hash({"date": "1990-05-02"})
            z.write_text(json.dumps({"system": "ziwei", "source_chart": {"schema_version": 3, "input_hash": digest}}), encoding="utf-8")
            items = ["bazi=" + str(a), "ziwei=" + str(z)]
            value = fortune.bundle(items)
            self.assertEqual(value["input_chain"]["status"], "same_declared_input")
            self.assertIsNone(value["cross_system_conclusion"]["probability"])
            z.write_text(json.dumps({"system": "ziwei", "source_chart": {"schema_version": 3, "input_hash": "0" * 64}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "links differ"):
                fortune.bundle(items)
            self.assertEqual(fortune.bundle(items, allow_different_inputs=True)["input_chain"]["status"], "different_declared_inputs")
            value = fortune.bundle(["bazi@甲=" + str(a), "bazi@乙=" + str(a)])
            self.assertEqual([p["panel_id"] for p in value["panels"]], ["bazi@甲", "bazi@乙"])
            astro.write_text(json.dumps({"system": "astrology", "zodiac": {"type": "tropical"}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different system"):
                fortune.bundle(["bazi=" + str(astro)])
            with self.assertRaisesRegex(ValueError, "sidereal"):
                fortune.bundle(["vedic=" + str(astro)])

    def test_route_options_cannot_silently_override_system(self):
        for args in (["--zodiac=tropical", "--probe"], ["--zodiac", "tropical", "--probe"]):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, "sidereal"):
                fortune.dispatch(fortune.find_system("vedic"), args)
        for args in (["--system=face"], ["--system", "face"]):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, "must agree"):
                fortune.dispatch(fortune.find_system("palm"), args)

    def test_save_protects_env_explicit_and_named_engine_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for route in ("astrology", "ziwei"):
                explicit = root / ("custom-" + route)
                target = explicit / "private.json"
                result, value = cli(route, "--probe", "--engine-dir", str(explicit), "--save", str(target))
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(target.exists())
            with mock.patch.dict(os.environ, {"MINGXUE_ASTRO_ENGINE": str(root / "engine")}):
                with self.assertRaisesRegex(ValueError, "caches"):
                    fortune.validate_save_path(root / "engine" / "result.json")
            with self.assertRaisesRegex(ValueError, "caches"):
                fortune.validate_save_path(root / "engine-cache" / "result.json")
            path = root / "new.json"
            result, value = cli("tarot", "--spread", "single", "--save", str(path), "--output=" + str(root / "other.json"))
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(path.exists())

    def test_input_output_overlap_and_tampered_shared_chart_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.json"
            chart = build_chart("1990-05-02", "07:30", timezone="Asia/Shanghai")
            source.write_text(json.dumps(chart), encoding="utf-8")
            original = source.read_bytes()
            result, value = cli("bundle", "--item", "bazi=" + str(source), "--output", str(source))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(source.read_bytes(), original)
            process = subprocess.run([sys.executable, "-X", "utf8", "-B", str(SKILL / "scripts/astrology.py"),
                "--chart", str(source), "--output", str(source)], capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(source.read_bytes(), original)
            chart["pillars"]["day"] = "丙寅"
            source.write_text(json.dumps(chart), encoding="utf-8")
            for system in ("astrology", "ziwei"):
                result, value = cli(system, "--chart", str(source))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("modified", json.dumps(value))

    def test_visual_native_output_cannot_pollute_source(self):
        path = SKILL / "private-observations.json"
        result = subprocess.run([sys.executable, "-X", "utf8", "-B", str(SKILL / "scripts/visual_intake.py"),
            "--system", "palm", "--output", str(path)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(path.exists())
        self.assertFalse(json.loads(result.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
