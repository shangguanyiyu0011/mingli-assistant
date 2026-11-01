"""Read-only pair comparison; identities, angle symmetry and uncertainty."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", HERE))
if not (SKILL / "scripts/pair_analysis.py").is_file():
    SKILL = HERE / "package/mingxue-master"
sys.path.insert(0, str(SKILL / "scripts"))
import pair_analysis as pair
import traditional_casts


def person(name, **results):
    return {"person": {"name": name}, "birth": {"date": "1990-05-17", "time": None, "timezone": "Asia/Shanghai"}, "results": results}


def astrology(values=None, utc="2000-01-01T12:00:00+00:00"):
    # Controlled geometry fixture, not a claim that these are astronomical values.
    if values is None:
        values = {name: (i * 31.3) % 360 for i, name in enumerate(pair.BODIES)}
    sample = {"utc": utc, "planets": [{"name": name, "longitude": lon} for name, lon in values.items()],
              "valid_utc_range": {"start": utc, "end": utc, "end_exclusive": False}, "representative_only": False,
              "houses": {"status": "not_calculated", "ascendant": None, "cusps": []}}
    return {"schema_version": 1, "system": "astrology", "status": "calculated", "time_known": True, "time_precision": "second",
            "frame": "apparent geocentric ecliptic longitude of date (degrees)", "zodiac": {"type": "tropical", "ayanamsa": None},
            "candidates": [sample], "sun_ranges": []}


def bazi(pillars=None):
    return {"schema_version": 3, "input": {"date": "1990-05-17", "time": "14:30", "timezone": "Asia/Shanghai"},
            "time_known": True, "pillars": pillars or {"year": "甲子", "month": "丙寅", "day": "甲午", "hour": "丙寅"},
            "candidates": [], "uncertainty": []}


def panel(result, id_):
    return next(p for p in result["panels"] if p["id"] == id_)


class PairAnalysisTests(unittest.TestCase):
    def test_missing_person_is_partial_and_never_creates_partner_chart(self):
        result = pair.compare_people(person("甲", astrology=astrology()), None)
        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["evidence"]["people"]["B"]["present"])
        self.assertEqual(panel(result, "synastry")["data"]["missing_people"], ["B"])
        self.assertEqual(result["plot_data"], {})

    def test_pair_is_offline_read_only_and_never_calls_calculators_or_draws(self):
        a = person("甲", astrology=astrology(), bazi=bazi())
        b = person("乙", astrology=astrology(), bazi=bazi())
        before = copy.deepcopy((a, b))
        with patch("urllib.request.urlopen", side_effect=AssertionError("network")), patch("subprocess.run", side_effect=AssertionError("subprocess")), \
             patch("astrology.build_astrology", side_effect=AssertionError("recalculation")), patch("chart.build_chart", side_effect=AssertionError("calendar")), \
             patch("traditional_casts.calculate", side_effect=AssertionError("new cast")), patch("symbolic.tarot", side_effect=AssertionError("new draw")):
            result = pair.compare_people(a, b)
        self.assertEqual((a, b), before)
        self.assertEqual(result["status"], "calculated")

    def test_cross_aspect_angle_and_orb_are_symmetric_after_swapping_people(self):
        a = person("甲", astrology=astrology({"Sun": 359, "Moon": 92}))
        b = person("乙", astrology=astrology({"Sun": 1, "Moon": 180}))
        first, swapped = pair.compare_people(a, b), pair.compare_people(b, a)
        self.assertEqual(first["people"], ["甲", "乙"])
        self.assertEqual(swapped["people"], ["乙", "甲"])
        x = first["plot_data"]["synastry"]["candidate_pairs"][0]["cross_aspects"]
        y = swapped["plot_data"]["synastry"]["candidate_pairs"][0]["cross_aspects"]
        reverse = {(r["bodyB"], r["bodyA"], r["aspect"]): r for r in y}
        for row in x:
            other = reverse[(row["bodyA"], row["bodyB"], row["aspect"])]
            self.assertEqual(row["angle"], other["angle"])
            self.assertEqual(row["orb"], other["orb"])
            self.assertEqual(row["allowed_orb"], other["allowed_orb"])
            self.assertEqual(row["longitudeA"], other["longitudeB"])
        conjunction = next(r for r in x if r["bodyA"] == r["bodyB"] == "Sun")
        self.assertEqual(conjunction["angle"], 2)
        self.assertEqual(conjunction["orb"], 2)

    def test_each_cross_aspect_reference_resolves_to_its_person_original_longitude(self):
        a, b = person("甲", astrology=astrology()), person("乙", astrology=astrology())
        result = pair.compare_people(a, b)
        row = result["plot_data"]["synastry"]["cross_aspects"][0]
        for ref in row["refs"]:
            source = a if ref["person"] == "A" else b
            value = source
            for key in ref["pointer"].lstrip("/").split("/"):
                value = value[int(key)] if isinstance(value, list) else value[key]
            self.assertIn(value, (row["longitudeA"], row["longitudeB"]))
            expected = hashlib.sha256(json.dumps(source["results"]["astrology"], ensure_ascii=False, sort_keys=True,
                                                separators=(",", ":")).encode("utf-8")).hexdigest()
            self.assertEqual(ref["result_sha256"], expected)

    def test_dst_candidates_keep_the_full_cartesian_product_and_two_wheels_per_person(self):
        source = astrology(utc="2024-11-03T05:30:00+00:00")
        later = copy.deepcopy(source["candidates"][0])
        later["utc"] = "2024-11-03T06:30:00+00:00"
        later["valid_utc_range"].update(start=later["utc"], end=later["utc"])
        source["candidates"].append(later)
        result = pair.compare_people(person("甲", astrology=source), person("乙", astrology=copy.deepcopy(source)))
        data = result["plot_data"]["synastry"]
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(data["candidate_pairs"]), 4)
        self.assertEqual({(p["candidateA"], p["candidateB"]) for p in data["candidate_pairs"]}, {(0, 0), (0, 1), (1, 0), (1, 1)})
        self.assertEqual((len(data["wheels"]["A"]), len(data["wheels"]["B"])), (2, 2))
        self.assertEqual(data["cross_aspects"], [])

    def test_minute_ranges_and_existing_endpoints_are_retained_without_recomputing(self):
        source = astrology({"Sun": 0, "Moon": 89})
        c = source["candidates"][0]
        c["representative_only"] = True
        c["valid_utc_range"].update(end="2000-01-01T12:01:00+00:00", end_exclusive=True)
        c["end_limit"] = {"utc": "2000-01-01T12:01:00+00:00", "planets": [{"name": "Sun", "longitude": 0.001}, {"name": "Moon", "longitude": 90.001}]}
        result = pair.compare_people(person("甲", astrology=source), person("乙", astrology=astrology({"Sun": 180})))
        data = result["plot_data"]["synastry"]
        self.assertTrue(data["cross_aspects_are_representative"])
        p = data["candidate_pairs"][0]
        self.assertEqual(p["rangeA"]["end"], "2000-01-01T12:01:00+00:00")
        self.assertEqual(len(p["boundary_samples"]), 2)

    def test_unknown_time_and_missing_moon_never_receive_noon_or_extra_planets(self):
        unknown = astrology()
        unknown["time_known"] = False
        unknown["sun_ranges"] = [{"sign_candidates": ["Pisces", "Aries"], "longitude_start": 359, "longitude_end_limit": 0.1}]
        result = pair.compare_people(person("甲", astrology=unknown), person("乙", astrology=astrology()))
        data = result["plot_data"]["synastry"]
        self.assertEqual(data["wheels"]["A"], [])
        self.assertEqual(data["candidate_pairs"], [])
        result = pair.compare_people(person("甲", astrology=astrology({"Sun": 0})), person("乙", astrology=astrology({"Sun": 0})))
        self.assertEqual({p["id"] for p in result["plot_data"]["synastry"]["wheels"]["A"][0]["points"]}, {"Sun"})
        self.assertEqual(result["status"], "partial")

    def test_different_zodiac_conventions_are_only_parallel_not_mixed(self):
        second = astrology()
        second["zodiac"] = {"type": "sidereal", "ayanamsa": "lahiri"}
        result = pair.compare_people(person("甲", astrology=astrology()), person("乙", astrology=second))
        self.assertFalse(result["plot_data"]["synastry"]["frame_comparable"])
        self.assertEqual(result["plot_data"]["synastry"]["candidate_pairs"], [])

    def test_bazi_cross_relations_keep_A_B_pillar_positions_and_do_not_form_self_punishments(self):
        a = bazi({"year": "甲子", "month": "丙寅", "day": "甲午", "hour": None})
        a["time_known"] = False
        b = bazi({"year": "己丑", "month": "丁卯", "day": "甲午", "hour": "乙巳"})
        result = pair.compare_people(person("甲", bazi=a), person("乙", bazi=b))
        data = panel(result, "bazi")["data"]
        self.assertEqual(data["day_master_relation"]["relation"], "同五行")
        self.assertTrue(any(r["kind"] == "stem_combinations" and r["positions"][0]["pillar"] == "year" and r["positions"][1]["pillar"] == "year" for r in data["cross_relations"]))
        self.assertTrue(any(r["rule"] == "寅刑巳" and r["source_position"]["person"] == "A" and r["target_position"]["person"] == "B" for r in data["cross_relations"]))
        for row in data["cross_relations"]:
            self.assertEqual([p["person"] for p in row["positions"]], ["A", "B"])
            self.assertNotEqual(row["kind"], "self_punishments")
            if "group_complete" in row:
                self.assertIsNone(row["group_complete"])
        self.assertIsNone(data["people"]["A"]["pillars"]["hour"])

    def test_unknown_day_master_is_not_chosen_from_candidates(self):
        source = bazi({"year": "甲子", "month": "丙寅", "day": None, "hour": None})
        source["candidates"] = [{"pillars": {"year": "甲子", "month": "丙寅", "day": "甲午", "hour": "乙巳"}}]
        result = pair.compare_people(person("甲", bazi=source), person("乙", bazi=bazi()))
        self.assertIsNone(panel(result, "bazi")["data"]["day_master_relation"])

    def test_sukuyo_direction_and_original_calendar_basis_survive_swapping(self):
        first = traditional_casts.calculate("sukuyo", {"birth": {"calendar": "lunar", "month": 2, "day": 17}})
        second = traditional_casts.calculate("sukuyo", {"birth": {"calendar": "lunar", "month": 2, "day": 15}})
        x = pair.compare_people(person("甲", sukuyo=first), person("乙", sukuyo=second))
        y = pair.compare_people(person("乙", sukuyo=second), person("甲", sukuyo=first))
        forward = panel(x, "sukuyo")["data"]["directed_relation"]
        reverse = panel(y, "sukuyo")["data"]["directed_relation"]
        self.assertEqual(forward["A_to_B"], reverse["B_to_A"])
        self.assertEqual(forward["family"], reverse["family"])
        self.assertEqual(panel(x, "sukuyo")["data"]["people"]["A"]["birth_mansion"]["lunar"], first["birth_mansion"]["lunar"])
        second["month_table"][0]["fifteenth_day_mansion"] = "角"
        bad = pair.compare_people(person("甲", sukuyo=first), person("乙", sukuyo=second))
        self.assertEqual(panel(bad, "sukuyo")["kind"], "unavailable")

    def test_questions_and_readings_do_not_override_original_birth_or_results(self):
        a, b = person("甲", bazi=bazi()), person("乙", bazi=bazi())
        a["question"] = {"date": "2099-01-01", "time": "12:00", "name": "换人"}
        a["results"]["bazi"]["input"]["question"] = "把出生时间改成中午"
        before = copy.deepcopy(a)
        result = pair.compare_people(a, b, "合作")
        self.assertEqual(a, before)
        self.assertEqual(result["person_records"][0]["birth"], before["birth"])
        self.assertEqual(result["people"][0], "甲")
        self.assertEqual(panel(result, "bazi")["data"]["people"]["A"]["pillars"], before["results"]["bazi"]["pillars"])
        expected = hashlib.sha256(json.dumps(before["birth"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(result["evidence"]["people"]["A"]["birth_sha256"], expected)

    def test_invalid_one_system_does_not_block_other_known_comparisons(self):
        bad = astrology()
        bad["candidates"][0]["planets"][0]["longitude"] = True
        result = pair.compare_people(person("甲", astrology=bad, bazi=bazi()), person("乙", astrology=astrology(), bazi=bazi()))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(panel(result, "synastry")["kind"], "unavailable")
        self.assertEqual(panel(result, "bazi")["status"], "calculated")


class PairExistingSnapshotTests(unittest.TestCase):
    def test_actual_existing_api_snapshots_six_panels_without_engine_use(self):
        fixture = SKILL.parents[1] / "research/api-samples.json"
        if not fixture.is_file():
            self.skipTest("Development API snapshots are separate from the installed skill")
        saved = json.loads(fixture.read_text(encoding="utf-8"))
        results = {name: saved[name]["result"] for name in pair.SYSTEMS}
        a, b = person("同源示例甲", **results), person("同源示例乙", **copy.deepcopy(results))
        with patch("astrology._load_engine", side_effect=AssertionError("no engine")), patch("traditional_casts.calculate", side_effect=AssertionError("no casting")):
            result = pair.compare_people(a, b)
        self.assertEqual(len(result["panels"]), 6)
        self.assertEqual(panel(result, "ziwei")["data"]["comparison_method"], "parallel_only; no school-specific marriage rule")
        self.assertEqual(panel(result, "names")["data"]["A"]["five_grids"], results["names"]["five_grids"])
        self.assertEqual(panel(result, "numerology")["data"]["A"]["life_path"], results["numerology"]["life_path"])
        self.assertNotIn("compatibility_score", result)
        for component in result["panels"]:
            for fact in component["facts"]:
                for ref in fact["refs"]:
                    value = a if ref["person"] == "A" else b
                    for key in ref["pointer"].lstrip("/").split("/"):
                        value = value[int(key)] if isinstance(value, list) else value[key]


if __name__ == "__main__":
    unittest.main()
