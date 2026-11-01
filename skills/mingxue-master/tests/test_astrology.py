"""Offline regression for isolated astronomy, uncertainty and shared UTC clocks."""
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", HERE))
if not (SKILL / "scripts/chart.py").is_file():
    SKILL = HERE / "package/mingxue-master"
sys.path.insert(0, str(SKILL / "scripts"))
import astrology as astro
import chart


def shared(instant="2000-01-01T12:00:00+00:00"):
    return {"schema_version": 3, "input": {}, "time_known": True, "time_precision": "second",
            "time_context": {"valid_utc_ranges": [{"start": instant, "end": instant, "end_exclusive": False}]}}


def selected_engine():
    override = os.environ.get("MINGXUE_ASTRO_ENGINE")
    development = SKILL.parents[1] / "engine-cache/astrology"
    return astro.engine_directory(override or (str(development) if development.is_dir() else None))


class AstrologyContractTests(unittest.TestCase):
    def test_missing_engine_is_clear_and_probe_never_downloads(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "engine-cache/astrology"
            with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
                status = astro.probe(missing)
                result = astro.build_astrology(shared(), engine_dir=missing)
            self.assertFalse(status["available"])
            self.assertIn("prepare_astrology.py", status["reason"])
            self.assertEqual(result["status"], "engine_unavailable")
            self.assertEqual(result["candidates"], [])
            self.assertIsNone(result["sun_sign"])
            self.assertEqual(result["sun_ranges"], [])

    def test_engine_and_output_cannot_pollute_skill_or_resources(self):
        for path in (SKILL, SKILL / "site-packages", SKILL / "cache"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                astro.validate_engine_directory(path)
            with self.subTest(path=path), self.assertRaises(ValueError):
                astro.write_result({}, path / "birth.json")
        with self.assertRaises(ValueError):
            astro.validate_engine_directory(Path(sys.prefix) / "Lib/site-packages")
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp) / "engine-cache/astrology"
            with self.assertRaises(ValueError):
                astro.write_result({}, cache / "private.json", cache)

    def test_tropical_and_sidereal_cannot_be_mixed(self):
        for kwargs in ({"zodiac": "sidereal"}, {"zodiac": "sidereal", "ayanamsa": "guess"},
                       {"zodiac": "tropical", "ayanamsa": "lahiri"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                astro.build_astrology(shared(), **kwargs)

    def test_bad_utc_and_unknown_time_point_are_rejected(self):
        for instant in ("2000-01-01T12:00:00", "2000-01-01T12:00:00+08:00", "nonsense"):
            with self.subTest(instant=instant), self.assertRaises(ValueError):
                astro.validate_chart(shared(instant))
        bad = shared()
        bad["time_known"] = False
        with self.assertRaisesRegex(ValueError, "Unknown birth time"):
            astro.validate_chart(bad)
        with self.assertRaises(ValueError):
            astro.build_astrology({"schema_version": 2})
        for coordinate in ({"latitude": 91}, {"longitude": float("nan")}, {"latitude": True}):
            with self.subTest(coordinate=coordinate), self.assertRaises(ValueError):
                astro.build_astrology(shared(), **coordinate)


class AstrologyRealEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = selected_engine()
        status = astro.probe(cls.engine)
        if not status["available"]:
            raise unittest.SkipTest("Explicit external engine preparation required: " + status["reason"])
        cls.swe = astro._load_engine(cls.engine)

    def calculate(self, value=None, **kwargs):
        return astro.build_astrology(value or shared(), engine_dir=self.engine, **kwargs)

    def test_official_known_planet_and_house_fixture(self):
        # Independent published library test point; analytical mode has a small
        # intentional difference from the file-based reference ephemeris.
        xx, flags, warning = self.swe.calc_ut(2452275.499255786, self.swe.SUN,
                                             self.swe.FLG_MOSEPH | self.swe.FLG_SPEED)
        self.assertLess(abs(xx[0] - 280.38296810621137), 0.00003)
        self.assertLess(abs(xx[3] - 1.0188772348975301), 0.00001)
        self.assertTrue(flags & self.swe.FLG_MOSEPH)
        cusps, axes = self.swe.houses_ex(2452275.499255786, 0, 0, b"P", 0)
        self.assertEqual(len(cusps), 13)
        self.assertEqual(cusps[0], 0)
        self.assertAlmostEqual(cusps[1], 191.0989364639854, places=8)
        self.assertAlmostEqual(cusps[10], 99.3768461762848, places=8)
        self.assertAlmostEqual(axes[0], 191.0989364639854, places=8)

    def test_engine_tamper_cannot_be_hidden_by_rewriting_its_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            copied = Path(temp) / "engine-cache/astrology"
            shutil.copytree(self.engine, copied)
            metadata = next((copied / "python").glob("*.dist-info/METADATA"))
            metadata.write_bytes(metadata.read_bytes() + b"\nchanged\n")
            manifest_path = copied / "engine.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"][metadata.relative_to(copied / "python").as_posix()] = hashlib.sha256(metadata.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = astro.probe(copied)
            self.assertFalse(result["available"])
            self.assertIn("pinned wheel", result["reason"])

    def test_independent_geocentric_ephemeris_points(self):
        # Fixed apparent ecliptic-of-date DE441 points at 2000-01-01 12:00 UTC;
        # provenance and exact API parameters are in the separate research record.
        expected = {"Sun": 280.3689092, "Moon": 223.3237860, "Mercury": 271.8892699}
        result = self.calculate()
        planets = {p["name"]: p for p in result["candidates"][0]["planets"]}
        for name, value in expected.items():
            with self.subTest(name=name):
                self.assertLess(astro.angular_distance(planets[name]["longitude"], value) * 3600, 1.0)
        self.assertEqual(result["sun_sign"], "Capricorn")

    def test_coordinates_missing_never_invents_ascendant_or_houses(self):
        for kwargs in ({}, {"longitude": 121.47}, {"latitude": 31.23}):
            with self.subTest(kwargs=kwargs):
                result = self.calculate(**kwargs)
                candidate = result["candidates"][0]
                self.assertEqual(len(candidate["planets"]), 10)
                self.assertEqual(candidate["houses"]["status"], "not_calculated")
                self.assertIsNone(candidate["houses"]["ascendant"])
                self.assertEqual(candidate["houses"]["cusps"], [])
                self.assertTrue(all("house_longitude_only" not in p for p in candidate["planets"]))

    def test_true_dst_shared_utc_and_fold_are_preserved(self):
        china = chart.build_chart("1990-05-02", "12:30:00", timezone="Asia/Shanghai")
        result = self.calculate(china, latitude=31.23, longitude=121.47)
        self.assertEqual(result["candidates"][0]["utc"], "1990-05-02T03:30:00+00:00")
        self.assertEqual(china["candidates"][0]["time"]["dst_seconds"], 3600)
        expected_hash = hashlib.sha256(json.dumps(china["input"], ensure_ascii=False, sort_keys=True,
                                                  separators=(",", ":")).encode("utf-8")).hexdigest()
        self.assertEqual(result["source_chart"], {"schema_version": 3, "input_hash": expected_hash})
        utc_result = self.calculate(shared("1990-05-02T03:30:00+00:00"), latitude=31.23, longitude=121.47)
        self.assertEqual(result["candidates"][0]["planets"], utc_result["candidates"][0]["planets"])
        ny = chart.build_chart("2024-11-03", "01:30:00", timezone="America/New_York")
        folds = self.calculate(ny, latitude=40.71, longitude=-74.01)
        self.assertEqual([c["utc"] for c in folds["candidates"]],
                         ["2024-11-03T05:30:00+00:00", "2024-11-03T06:30:00+00:00"])
        asc = [c["houses"]["ascendant"]["longitude"] for c in folds["candidates"]]
        self.assertGreater(astro.angular_distance(*asc), 5)
        with self.assertRaisesRegex(ValueError, "does not exist"):
            chart.build_chart("2024-03-10", "02:30:00", timezone="America/New_York")

    def test_solar_pillar_clock_does_not_move_planetary_instant(self):
        plain = chart.build_chart("2024-06-01", "12:00:00", timezone="Asia/Shanghai", longitude=75)
        solar = chart.build_chart("2024-06-01", "12:00:00", timezone="Asia/Shanghai", longitude=75, true_solar=True)
        self.assertEqual(self.calculate(plain)["candidates"][0]["planets"], self.calculate(solar)["candidates"][0]["planets"])

    def test_unknown_time_retains_full_day_and_sun_sign_crossing(self):
        value = chart.build_chart("2024-03-20", timezone="Asia/Shanghai")
        result = self.calculate(value, latitude=31.23, longitude=121.47)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["candidates"], [])
        self.assertIsNone(result["sun_sign"])
        self.assertEqual(result["sun_ranges"][0]["sign_candidates"], ["Pisces", "Aries"])
        period = result["sun_ranges"][0]
        self.assertEqual(period["start_utc"], "2024-03-19T16:00:00+00:00")
        self.assertEqual(period["end_utc"], "2024-03-20T16:00:00+00:00")
        self.assertTrue(period["end_exclusive"])
        self.assertTrue(period["sign_crossings"])
        # A local rollback date lasts 25 physical hours, never a fixed noon.
        ny = self.calculate(chart.build_chart("2024-11-03", timezone="America/New_York"))
        hours = sum((datetime.fromisoformat(r["end_utc"]) - datetime.fromisoformat(r["start_utc"])).total_seconds()
                    for r in ny["sun_ranges"]) / 3600
        self.assertEqual(hours, 25)

    def test_minute_precision_retains_exclusive_endpoint(self):
        result = self.calculate(chart.build_chart("2024-03-20", "11:06", timezone="Asia/Shanghai"))
        candidate = result["candidates"][0]
        self.assertTrue(candidate["representative_only"])
        self.assertTrue(candidate["valid_utc_range"]["end_exclusive"])
        self.assertEqual(candidate["planets"][0]["sign"], "Pisces")
        self.assertEqual(candidate["end_limit"]["planets"][0]["sign"], "Aries")
        self.assertIsNone(result["sun_sign"])

    def test_retrograde_aspects_and_explicit_house_system(self):
        result = self.calculate(chart.build_chart("2024-04-08", "18:00:00", timezone="UTC"),
                                latitude=40.71, longitude=-74.01, house_system="W")
        candidate = result["candidates"][0]
        mercury = next(p for p in candidate["planets"] if p["name"] == "Mercury")
        self.assertTrue(mercury["retrograde"])
        self.assertLess(mercury["longitude_speed_deg_per_day"], 0)
        conjunctions = [a for a in candidate["aspects"] if a["aspect"] == "conjunction"
                        and {a["body_a"], a["body_b"]} == {"Sun", "Moon"}]
        self.assertTrue(conjunctions)
        self.assertLess(conjunctions[0]["orb"], 1)
        self.assertEqual(candidate["houses"]["system_code"], "W")
        self.assertEqual(len(candidate["houses"]["cusps"]), 12)
        self.assertFalse(candidate["houses"]["automatic_fallback"])

    def test_polar_house_failure_is_partial_not_silent_system_substitution(self):
        result = self.calculate(latitude=80, longitude=0, house_system="P")
        candidate = result["candidates"][0]
        self.assertEqual(candidate["houses"]["status"], "unavailable")
        self.assertEqual(candidate["houses"]["system_code"], "P")
        self.assertFalse(candidate["houses"]["automatic_fallback"])
        self.assertEqual(candidate["houses"]["cusps"], [])
        self.assertEqual(len(candidate["planets"]), 10)
        explicit = self.calculate(latitude=80, longitude=0, house_system="W")
        self.assertEqual(explicit["candidates"][0]["houses"]["status"], "calculated")

    def test_sidereal_ayanamsa_and_real_lunar_mansion(self):
        tropical = self.calculate(latitude=0, longitude=0)
        sidereal = self.calculate(latitude=0, longitude=0, zodiac="sidereal", ayanamsa="lahiri")
        c = sidereal["candidates"][0]
        self.assertEqual(sidereal["zodiac"], {"type": "sidereal", "ayanamsa": "lahiri"})
        self.assertGreater(c["ayanamsa_degrees"], 23)
        self.assertLess(c["ayanamsa_degrees"], 25)
        moon = next(p for p in c["planets"] if p["name"] == "Moon")
        self.assertIn(moon["nakshatra"]["index"], range(1, 28))
        self.assertIn(moon["nakshatra"]["pada"], range(1, 5))
        self.assertTrue(all("nakshatra" not in p for p in tropical["candidates"][0]["planets"]))
        self.assertAlmostEqual(astro.angular_distance(tropical["candidates"][0]["planets"][0]["longitude"],
                                                      c["planets"][0]["longitude"]), c["ayanamsa_degrees"], delta=0.01)
        # Global native sidereal settings are explicitly reset on later calls.
        self.assertEqual(tropical["candidates"][0]["planets"], self.calculate(latitude=0, longitude=0)["candidates"][0]["planets"])

    def test_wrong_date_range_does_not_fabricate_a_chart(self):
        result = self.calculate(shared("4000-01-01T12:00:00+00:00"))
        self.assertEqual(result["status"], "unsupported_date")
        self.assertEqual(result["candidates"], [])

    def test_cli_end_to_end_shared_file_and_direct_birth(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "shared.json"
            output = Path(temp) / "chart.json"
            canonical = chart.build_chart("2000-01-01", "12:00:00", timezone="Etc/UTC")
            source.write_text(json.dumps(canonical, ensure_ascii=False), encoding="utf-8")
            command = [sys.executable, "-X", "utf8", "-B", str(SKILL / "scripts/astrology.py"),
                       "--engine-dir", str(self.engine), "--chart", str(source),
                       "--latitude", "0", "--longitude", "0", "--output", str(output), "--json"]
            run = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)
            result = json.loads(run.stdout)
            self.assertEqual(result, json.loads(output.read_text(encoding="utf-8")))
            self.assertEqual(result["status"], "calculated")
            self.assertEqual(result["candidates"][0]["utc"], "2000-01-01T12:00:00+00:00")
            command = [sys.executable, "-X", "utf8", "-B", str(SKILL / "scripts/astrology.py"),
                       "--engine-dir", str(self.engine), "--date", "1990-05-02", "--time", "12:30:00",
                       "--timezone", "Asia/Shanghai", "--latitude", "31.23", "--longitude", "121.47"]
            run = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout)["candidates"][0]["utc"], "1990-05-02T03:30:00+00:00")


if __name__ == "__main__":
    unittest.main()
