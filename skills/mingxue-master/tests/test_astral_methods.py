"""Astral event structures: real ephemeris, explicit conventions, visual data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", HERE))
if not (SKILL / "scripts/astral_methods.py").is_file():
    SKILL = HERE / "package/mingxue-master"
sys.path.insert(0, str(SKILL / "scripts"))
import astral_methods as astral
import astrology as astro

EVENT = {"date": "2024-04-08", "time": "18:00:00", "timezone": "UTC", "longitude": 0.0, "latitude": 51.48}
QUESTION = {"question": "这次沟通有哪些需要核实的信息？", "quesited_house": 3}


class AstralContractTests(unittest.TestCase):
    def test_missing_event_data_never_invents_time_or_coordinates(self):
        for system in astral.SYSTEMS:
            result = astral.calculate(system, {"date": "2024-04-08"})
            self.assertEqual(result["status"], "needs_input")
            self.assertIn("time", result["required"])
            self.assertIn("longitude", result["required"])
            self.assertIsNone(result["wheel"])
            self.assertEqual(result["candidates"], [])

    def test_invalid_inputs_are_json_results(self):
        options = [{"latitude": True}, {"longitude": 181}, {"node_model": "guess"}, {"unexpected": "ignored?"},
                   {"ziqi": {"model": "mean_cycle"}}, {"fold": True}]
        for changes in options:
            with self.subTest(changes=changes):
                result = astral.calculate("qizheng", dict(EVENT, **changes))
                self.assertEqual(result["status"], "invalid_input")
                self.assertIsNone(result["wheel"])
        result = astral.calculate("horary", dict(EVENT, **QUESTION, zodiac="sidereal", ayanamsa="lahiri"))
        self.assertEqual(result["status"], "invalid_input")
        for params in ({"longitude": float("nan")}, [], "text"):
            result = astral.calculate("qizheng", params)
            self.assertEqual(result["status"], "invalid_input")
            json.dumps(result, allow_nan=False)

    def test_dignity_known_traditional_sign_fixtures(self):
        fixtures = [("Sun", 0, {"exaltation"}), ("Sun", 4, {"domicile"}), ("Venus", 5, {"fall"}),
                    ("Mercury", 11, {"detriment", "fall"}), ("Saturn", 3, {"detriment"}), ("Mars", 9, {"exaltation"})]
        for name, sign, expected in fixtures:
            row = astral.dignities([{"name": name, "sign_index": sign, "sign": astro.SIGNS[sign]}])[0]
            self.assertEqual(set(row["dignities"]), expected)
        self.assertEqual(astral.dignities([{"name": "Uranus", "sign_index": 10, "sign": "Aquarius"}]), [])

    def test_polar_clockwise_cusp_sectors_are_not_reversed_silently(self):
        houses = {"cusps": [{"house": i + 1, "longitude": (-30 * i) % 360} for i in range(12)]}
        points = [{"longitude": 345, "house_longitude_only": 12}, {"longitude": 315}]
        astral._assign_houses(points, houses)
        self.assertEqual(houses["longitude_sector_direction"], "clockwise_zodiac")
        self.assertEqual([p["house_longitude_only"] for p in points], [1, 2])

    def test_missing_engine_has_no_automatic_download_or_fake_wheel(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "external-engine"
            with patch("urllib.request.urlopen", side_effect=AssertionError("offline")):
                result = astral.calculate("qizheng", dict(EVENT, engine_dir=str(missing)))
            self.assertEqual(result["status"], "engine_unavailable")
            self.assertIsNone(result["wheel"])
            self.assertFalse(missing.exists())


class AstralEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = astro.engine_directory()
        probe = astro.probe(cls.engine)
        if not probe["available"]:
            raise unittest.SkipTest("Explicit fixed astrology engine preparation required: " + probe["reason"])

    def run_chart(self, system="qizheng", **changes):
        params = dict(EVENT, engine_dir=str(self.engine))
        if system == "horary":
            params.update(QUESTION)
        params.update(changes)
        return astral.calculate(system, params)

    def test_seven_physical_bodies_and_four_distinct_remainder_kinds(self):
        result = self.run_chart()
        self.assertEqual(result["status"], "partial")
        row = result["candidates"][0]
        self.assertEqual({p["id"] for p in row["bodies"]}, set(astral.SEVEN))
        self.assertTrue(all(p["kind"] == "physical_body" for p in row["bodies"]))
        four = {p["id"]: p for p in row["four_remainders"]}
        self.assertEqual(len(four), 4)
        self.assertTrue(all(not p["observable_body"] for p in four.values()))
        self.assertEqual(four["Ziqi"]["status"], "not_calculated")
        self.assertIsNone(four["Ziqi"]["longitude"])
        self.assertAlmostEqual(astro.angular_distance(four["Rahu"]["longitude"], four["Ketu"]["longitude"]), 180)
        self.assertEqual(row["lunar_mansions"]["status"], "not_calculated")
        self.assertEqual(len(row["wheel"]["points"]), 11)
        self.assertAlmostEqual(row["wheel"]["anchor_longitude"], row["houses"]["ascendant"]["longitude"])

    def test_ziqi_reference_is_explicit_and_math_does_not_claim_observability(self):
        reference = {"model": "mean_cycle", "epoch_utc": "2000-01-01T12:00:00Z", "epoch_longitude": 42.0,
                     "period_days": 100.0, "reference_label": "test convention, not a historical calibrated ephemeris"}
        result = self.run_chart(date="2000-01-01", time="12:00:00", ziqi=reference)
        self.assertEqual(result["status"], "calculated")
        z = result["candidates"][0]["four_remainders"][3]
        self.assertAlmostEqual(z["longitude"], 42.0, places=8)
        later = self.run_chart(date="2000-01-02", time="12:00:00", ziqi=reference)
        self.assertAlmostEqual(later["candidates"][0]["four_remainders"][3]["longitude"], 45.6, places=6)
        self.assertEqual(z["kind"], "conventional_point")
        self.assertIn("not independently verified", z["algorithm"]["calibration"])
        point = next(p for p in result["wheel"]["points"] if p["id"] == "Ziqi")
        self.assertEqual(point["plot_style"], "dashed")

    def test_node_type_and_direction_are_real_distinct_choices(self):
        point = {"date": "2000-01-01", "time": "12:00:00"}
        mean = self.run_chart(**point)["candidates"][0]["four_remainders"]
        true = self.run_chart(node_model="true", **point)["candidates"][0]["four_remainders"]
        reverse = self.run_chart(node_orientation="descending", **point)["candidates"][0]["four_remainders"]
        self.assertGreater(astro.angular_distance(mean[0]["longitude"], true[0]["longitude"]), 0.1)
        self.assertAlmostEqual(mean[0]["longitude"], reverse[1]["longitude"], places=8)
        self.assertAlmostEqual(mean[1]["longitude"], reverse[0]["longitude"], places=8)
        self.assertEqual(mean[0]["glyph"], reverse[1]["glyph"])
        self.assertEqual(mean[1]["glyph"], reverse[0]["glyph"])
        self.assertEqual(mean[0]["algorithm"]["api_body"], "MEAN_NODE")
        self.assertEqual(mean[2]["algorithm"]["api_body"], "MEAN_APOG")

    def test_independent_jpl_sun_moon_mercury_points(self):
        result = self.run_chart(date="2000-01-01", time="12:00:00")
        bodies = {p["id"]: p for p in result["candidates"][0]["bodies"]}
        expected = {"Sun": 280.3689092, "Moon": 223.3237860, "Mercury": 271.8892699}
        for name, longitude in expected.items():
            self.assertLess(astro.angular_distance(bodies[name]["longitude"], longitude) * 3600, 1)

    def test_real_dst_physical_time_and_unresolved_fold_do_not_choose_first(self):
        china = self.run_chart(date="1990-05-02", time="12:30:00", timezone="Asia/Shanghai", longitude=121.47, latitude=31.23)
        self.assertEqual(china["candidates"][0]["utc"], "1990-05-02T03:30:00+00:00")
        folded = self.run_chart(date="2024-11-03", time="01:30:00", timezone="America/New_York", longitude=-74.01, latitude=40.71)
        self.assertEqual(len(folded["candidates"]), 2)
        self.assertIsNone(folded["wheel"])
        self.assertEqual([r["utc"] for r in folded["candidates"]], ["2024-11-03T05:30:00+00:00", "2024-11-03T06:30:00+00:00"])
        gap = self.run_chart(date="2024-03-10", time="02:30:00", timezone="America/New_York")
        self.assertEqual(gap["status"], "invalid_input")
        self.assertIsNone(gap["wheel"])

    def test_minute_interval_is_explicit_and_has_endpoint_wheel(self):
        result = self.run_chart("horary", time="18:00")
        self.assertEqual(result["status"], "partial")
        row = result["candidates"][0]
        self.assertTrue(row["representative_only"])
        self.assertTrue(row["valid_utc_range"]["end_exclusive"])
        self.assertEqual(row["end_limit"]["utc"], "2024-04-08T18:01:00+00:00")
        self.assertNotEqual(row["wheel"]["points"][1]["longitude"], row["end_limit"]["wheel"]["points"][1]["longitude"])

    def test_horary_local_applying_and_separating_flip_across_new_moon(self):
        phases = []
        for clock in ("18:00:00", "19:00:00"):
            result = self.run_chart("horary", time=clock)
            row = result["candidates"][0]
            aspect = next(a for a in row["aspects"] if {a["body_a"], a["body_b"]} == {"Sun", "Moon"})
            phases.append(aspect["phase"])
            self.assertTrue(aspect["local_trend_only"])
            self.assertEqual(aspect["sampling_seconds_each_side"], 60)
            self.assertIsNone(result["judgement"])
            self.assertEqual(row["houses"]["system_code"], "R")
            self.assertEqual(len(row["dignities"]), 7)
            sun = next(d for d in row["dignities"] if d["body"] == "Sun")
            self.assertIn("exaltation", sun["dignities"])
        self.assertEqual(phases, ["applying", "separating"])

    def test_polar_house_unavailability_preserves_real_planets(self):
        result = self.run_chart("horary", latitude=80, house_system="P")
        row = result["candidates"][0]
        self.assertEqual(result["status"], "partial")
        self.assertEqual(row["houses"]["status"], "unavailable")
        self.assertFalse(row["houses"]["automatic_fallback"])
        self.assertEqual(len(row["bodies"]), 10)
        self.assertIsNone(row["significators"]["querent"])

    def test_real_polar_regiomontanus_clockwise_order_is_recorded(self):
        result = self.run_chart("horary", date="2024-01-01", time="12:00:00", latitude=80, house_system="R")
        row = result["candidates"][0]
        self.assertEqual(row["houses"]["status"], "calculated")
        self.assertEqual(row["houses"]["longitude_sector_direction"], "clockwise_zodiac")
        self.assertTrue(all(1 <= body["house_longitude_only"] <= 12 for body in row["bodies"]))

    def test_sidereal_qizheng_is_explicit_and_not_mixed_with_horary_dignities(self):
        tropical = self.run_chart()
        sidereal = self.run_chart(zodiac="sidereal", ayanamsa="lahiri")
        self.assertEqual(sidereal["zodiac"], {"type": "sidereal", "ayanamsa": "lahiri"})
        a = tropical["candidates"][0]["four_remainders"][0]["longitude"]
        b = sidereal["candidates"][0]["four_remainders"][0]["longitude"]
        self.assertAlmostEqual(astro.angular_distance(a, b), sidereal["candidates"][0]["ayanamsa_degrees"], delta=0.01)

    def test_cli_json_and_offline_probe_end_to_end(self):
        command = [sys.executable, "-X", "utf8", "-B", str(SKILL / "scripts/astral_methods.py")]
        run = subprocess.run(command + ["--probe", "--engine-dir", str(self.engine)], capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(json.loads(run.stdout)["engine"]["available"])
        params = dict(EVENT, **QUESTION, engine_dir=str(self.engine))
        run = subprocess.run(command + ["horary", "--params", json.dumps(params, ensure_ascii=False)], capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["system"], "horary")


if __name__ == "__main__":
    unittest.main()
