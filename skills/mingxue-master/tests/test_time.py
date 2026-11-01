"""Real-instant regression tests: historical clocks, terms and solar options."""
from contextlib import redirect_stdout
from datetime import datetime, timedelta
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", HERE))
if not (SKILL / "scripts/chart.py").is_file():
    SKILL = HERE / "package/mingxue-master"
sys.path.insert(0, str(SKILL / "scripts"))
import chart
import case_lookup
import time_conversion as tc


def first_time(value):
    return value["candidates"][0]["time"]


def instant(value):
    return datetime.fromisoformat(first_time(value)["utc"])


class TimeConversionTests(unittest.TestCase):
    def test_offline_iana_keys_and_neutral_version(self):
        root = chart.get_resources()
        self.assertTrue(tc.timezone_metadata(root)["iana_version"])
        self.assertEqual(tc.load_zone("Asia/Shanghai", root).key, "Asia/Shanghai")
        for key in ("../Asia/Shanghai", "Asia\\Shanghai", "/etc/localtime", "China guess", "Asia//Shanghai",
                    "C:/Asia/Shanghai", "Asia/Shanghai "):
            with self.subTest(key=key), self.assertRaises(ValueError):
                tc.load_zone(key, root)

    def test_default_timezone_is_explicitly_not_a_birthplace_inference(self):
        default = chart.build_chart("2024-06-01", "12:00:00")
        explicit = chart.build_chart("2024-06-01", "12:00:00", timezone="Asia/Shanghai")
        self.assertIsNone(default["input"]["timezone"])
        self.assertEqual(default["time_context"]["timezone_source"], "default")
        self.assertFalse(default["time_context"]["timezone_inferred_from_location"])
        self.assertEqual(default["pillars"], explicit["pillars"])
        self.assertEqual(instant(default), instant(explicit))
        self.assertEqual(explicit["time_context"]["timezone_source"], "explicit")

    def test_earlier_calendar_models_are_rejected_without_silent_conversion(self):
        for calendar in ("solar", "lunar"):
            for raw in ("0001-01-01", "1400-06-01", "1582-12-31"):
                with self.subTest(calendar=calendar, raw=raw), self.assertRaisesRegex(ValueError, "1583"):
                    chart.build_chart(raw, "12:00:00", calendar=calendar)

    def test_china_historical_dst_is_real_not_just_a_label(self):
        summer = chart.build_chart("1990-05-02", "12:30:00", timezone="Asia/Shanghai")
        winter = chart.build_chart("1990-01-02", "12:30:00", timezone="Asia/Shanghai")
        self.assertEqual(instant(summer).isoformat(), "1990-05-02T03:30:00+00:00")
        self.assertEqual(first_time(summer)["dst_seconds"], 3600)
        self.assertEqual(first_time(summer)["standard_clock"], "1990-05-02 11:30:00")
        self.assertEqual(first_time(summer)["library_clock"], "1990-05-02 11:30:00+08:00")
        self.assertEqual(first_time(summer)["chart_clock"], "1990-05-02 12:30:00")
        self.assertEqual(first_time(winter)["utc_offset_seconds"], 28800)
        self.assertEqual(first_time(winter)["dst_seconds"], 0)

    def test_china_historical_spring_gap_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            chart.build_chart("1991-04-14", "02:30:00", timezone="Asia/Shanghai")

    def test_new_york_spring_gap_is_rejected(self):
        for raw in ("02:00:00", "02:30", "02:59:59"):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, "does not exist"):
                chart.build_chart("2024-03-10", raw, timezone="America/New_York")
        before = chart.build_chart("2024-03-10", "01:59:59", timezone="America/New_York")
        after = chart.build_chart("2024-03-10", "03:00:00", timezone="America/New_York")
        self.assertEqual((instant(after) - instant(before)).total_seconds(), 1)

    def test_fold_retains_both_real_instants_even_with_identical_pillars(self):
        value = chart.build_chart("2024-11-03", "01:30:00", timezone="America/New_York", gender="male")
        self.assertEqual(len(value["candidates"]), 2)
        self.assertEqual(value["candidates"][0]["pillars"], value["candidates"][1]["pillars"])
        self.assertEqual([c["time"]["fold"] for c in value["candidates"]], [0, 1])
        self.assertEqual(value["time_context"]["fold_status"], "unresolved")
        self.assertEqual(value["yun"]["status"], "not_calculated")
        self.assertEqual(len(case_lookup.query_chart(value)), 1)

    def test_fold_selection_chooses_earlier_or_later_instant(self):
        values = [chart.build_chart("2024-11-03", "01:30:00", timezone="America/New_York", fold=n, gender="male")
                  for n in (0, 1)]
        self.assertEqual((instant(values[1]) - instant(values[0])).total_seconds(), 3600)
        self.assertTrue(all(len(v["candidates"]) == 1 for v in values))
        self.assertTrue(all(v["yun"]["status"] == "calculated" for v in values))
        with self.assertRaisesRegex(ValueError, "repeated"):
            chart.build_chart("2024-11-03", "03:30:00", timezone="America/New_York", fold=1)

    def test_partial_historical_fold_keeps_unique_seconds_for_either_choice(self):
        zone = tc.load_zone("Europe/Dublin", chart.get_resources())
        start = datetime(1916, 10, 1, 2, 25)
        end = start + timedelta(minutes=1)
        earlier = datetime(1916, 10, 1, 1, 50, 21, tzinfo=tc.UTC)
        later = datetime(1916, 10, 1, 2, 25, 21, tzinfo=tc.UTC)
        expected = {
            None: [(earlier, earlier + timedelta(minutes=1)), (later, later + timedelta(seconds=39))],
            0: [(earlier, earlier + timedelta(minutes=1))],
            1: [(earlier, earlier + timedelta(seconds=21)), (later, later + timedelta(seconds=39))],
        }
        for fold in (None, 0, 1):
            with self.subTest(fold=fold):
                self.assertEqual(tc.resolve_range(start, end, zone, "local-clock", fold=fold), expected[fold])
                value = chart.build_chart("1916-10-01", "02:25", timezone="Europe/Dublin", fold=fold)
                actual = [(datetime.fromisoformat(r["start"]), datetime.fromisoformat(r["end"]))
                          for r in value["time_context"]["valid_utc_ranges"]]
                self.assertEqual(actual, expected[fold])
                self.assertEqual(value["time_context"]["fold_status"], "unresolved" if fold is None else "selected")

    def test_partial_historical_fold_minute_covers_every_exact_second(self):
        zone = tc.load_zone("Europe/Dublin", chart.get_resources())
        start = datetime(1916, 10, 1, 2, 25)
        earlier = datetime(1916, 10, 1, 1, 50, 21, tzinfo=tc.UTC)
        later = datetime(1916, 10, 1, 2, 25, 21, tzinfo=tc.UTC)
        exact_sets = {None: set(), 0: set(), 1: set()}
        for second in range(60):
            raw = start + timedelta(seconds=second)
            points = tc.resolve_range(raw, raw + timedelta(microseconds=1), zone, "local-clock")
            instants = [a for a, _ in points]
            expected = [earlier + timedelta(seconds=second)]
            if second >= 21:
                expected.append(later + timedelta(seconds=second - 21))
            self.assertEqual(instants, expected, f"exact second {second}")
            exact_sets[None].update(instants)
            exact_sets[0].add(instants[0])
            exact_sets[1].add(instants[-1])
        for fold, exact in exact_sets.items():
            ranges = tc.resolve_range(start, start + timedelta(minutes=1), zone, "local-clock", fold=fold)
            covered = {a + timedelta(seconds=n) for a, b in ranges for n in range(int((b - a).total_seconds()))}
            self.assertEqual(covered, exact, f"fold={fold}")
        self.assertEqual([len(exact_sets[n]) for n in (None, 0, 1)], [99, 60, 60])
        for raw, count in (("02:25:00", 1), ("02:25:20", 1), ("02:25:21", 2), ("02:25:59", 2)):
            value = chart.build_chart("1916-10-01", raw, timezone="Europe/Dublin")
            self.assertEqual(len(value["time_context"]["valid_utc_ranges"]), count)

    def test_partial_historical_fold_has_same_lunar_and_solar_selection(self):
        lib = chart.calendar_library()
        lunar = lib.Solar.fromYmd(1916, 10, 1).getLunar()
        date_value = f"{lunar.getYear():04}-{abs(lunar.getMonth()):02}-{lunar.getDay():02}"
        for fold in (0, 1):
            solar = chart.build_chart("1916-10-01", "02:25", timezone="Europe/Dublin", fold=fold)
            converted = chart.build_chart(date_value, "02:25", calendar="lunar", leap=lunar.getMonth() < 0,
                                          timezone="Europe/Dublin", fold=fold)
            self.assertEqual(converted["time_context"]["valid_utc_ranges"], solar["time_context"]["valid_utc_ranges"])
            self.assertEqual(converted["pillars"], solar["pillars"])

    def test_standard_clock_is_not_de_dst_twice(self):
        standard = chart.build_chart("2024-03-10", "02:30:00", timezone="America/New_York", time_basis="standard-time")
        civil = chart.build_chart("2024-03-10", "03:30:00", timezone="America/New_York")
        self.assertEqual(instant(standard), instant(civil))
        self.assertEqual(first_time(standard)["chart_clock"], "2024-03-10 02:30:00")
        self.assertEqual(first_time(standard)["local_civil_clock"], "2024-03-10 03:30:00-04:00")
        self.assertEqual(first_time(standard)["standard_clock"], "2024-03-10 02:30:00")
        self.assertNotEqual(standard["pillars"]["hour"], civil["pillars"]["hour"])
        china = chart.build_chart("1990-05-02", "11:30:00", time_basis="standard-time")
        self.assertEqual(instant(china).isoformat(), "1990-05-02T03:30:00+00:00")
        self.assertEqual(first_time(china)["chart_clock"], "1990-05-02 11:30:00")

    def test_same_instant_uses_same_year_month_and_yun_across_timezones(self):
        shanghai = chart.build_chart("2024-06-01", "08:00:00", timezone="Asia/Shanghai", gender="female", yun_sect=2)
        ny = chart.build_chart("2024-05-31", "20:00:00", timezone="America/New_York", gender="female", yun_sect=2)
        self.assertEqual(instant(shanghai), instant(ny))
        for key in ("year", "month"):
            self.assertEqual(shanghai["pillars"][key], ny["pillars"][key])
        self.assertNotEqual(shanghai["pillars"]["day"], ny["pillars"]["day"])
        for key in ("start_offset", "start_utc", "jie", "dayun"):
            self.assertEqual(shanghai["yun"][key], ny["yun"][key])

    def test_lichun_boundary_is_same_real_instant_in_overseas_and_solar_clocks(self):
        unknown = chart.build_chart("2024-02-04")
        term = next(t for t in unknown["solar_terms_on_date"] if t["name"] == "立春")
        utc = datetime.fromisoformat(term["utc"])
        root = chart.get_resources()
        for zone_name in ("Asia/Shanghai", "America/New_York", "Pacific/Honolulu"):
            zone = tc.load_zone(zone_name, root)
            charts = []
            for current in (utc - timedelta(seconds=1), utc):
                raw = current.astimezone(zone)
                charts.append(chart.build_chart(raw.date().isoformat(), raw.time().isoformat(), timezone=zone_name))
            self.assertNotEqual(charts[0]["pillars"]["year"], charts[1]["pillars"]["year"])
            self.assertNotEqual(charts[0]["pillars"]["month"], charts[1]["pillars"]["month"])
            for current, solar in zip((utc - timedelta(seconds=1), utc), charts):
                raw = current.astimezone(zone)
                corrected = chart.build_chart(raw.date().isoformat(), raw.time().isoformat(), timezone=zone_name,
                                               longitude=-157.8, true_solar=True)
                self.assertEqual(corrected["pillars"]["year"], solar["pillars"]["year"])
                self.assertEqual(corrected["pillars"]["month"], solar["pillars"]["month"])

    def test_jie_crossing_birth_minute_retains_both_candidates_in_new_york(self):
        day = chart.build_chart("2024-02-04")
        term = next(t for t in day["solar_terms_on_date"] if t["name"] == "立春")
        raw = datetime.fromisoformat(term["utc"]).astimezone(tc.load_zone("America/New_York", chart.get_resources()))
        value = chart.build_chart(raw.date().isoformat(), raw.strftime("%H:%M"), timezone="America/New_York", gender="female")
        self.assertIsNone(value["pillars"]["year"])
        self.assertIsNone(value["pillars"]["month"])
        self.assertEqual(value["yun"]["status"], "not_calculated")

    def test_true_solar_does_not_change_real_instant_or_yun(self):
        raw = chart.build_chart("1990-05-02", "12:30:00", timezone="Asia/Shanghai", gender="female", yun_sect=2)
        solar = chart.build_chart("1990-05-02", "12:30:00", timezone="Asia/Shanghai", gender="female", yun_sect=2,
                                  true_solar=True, longitude=116.4)
        self.assertEqual(instant(raw), instant(solar))
        self.assertEqual(raw["yun"], solar["yun"])
        self.assertNotEqual(first_time(raw)["chart_clock"], first_time(solar)["chart_clock"])
        self.assertIn("formula", solar["time_context"]["solar_model"])
        self.assertIn("No guaranteed error bound", solar["time_context"]["solar_model"]["accuracy"])

    def test_solar_input_minute_does_not_assert_a_unique_yun_offset(self):
        value = chart.build_chart("2024-06-01", "12:00", time_basis="true-solar-time", longitude=116.4,
                                   gender="female", yun_sect=2)
        self.assertEqual(len(value["candidates"]), 1)
        self.assertEqual(value["yun"]["status"], "not_calculated")
        endpoints = value["yun"]["endpoint_candidates"]
        self.assertNotEqual(endpoints[0]["start_offset"], endpoints[1]["start_offset"])

    def test_solar_correction_is_independent_of_zone_and_dst_representation(self):
        local = chart.build_chart("1990-05-02", "12:30:00", true_solar=True, longitude=116.4)
        standard = chart.build_chart("1990-05-02", "11:30:00", time_basis="standard-time", true_solar=True, longitude=116.4)
        utc = chart.build_chart("1990-05-02", "03:30:00", timezone="Etc/UTC", true_solar=True, longitude=116.4)
        self.assertEqual(local["pillars"], standard["pillars"])
        self.assertEqual(local["pillars"], utc["pillars"])
        self.assertEqual(first_time(local)["chart_clock"], first_time(standard)["chart_clock"])
        self.assertEqual(first_time(local)["chart_clock"], first_time(utc)["chart_clock"])

    def test_already_solar_input_is_inverted_not_corrected_a_second_time(self):
        direct = chart.build_chart("2024-06-01", "12:00:00", timezone="America/New_York",
                                   time_basis="true-solar-time", longitude=-74)
        flagged = chart.build_chart("2024-06-01", "12:00:00", timezone="America/New_York",
                                    time_basis="true-solar-time", longitude=-74, true_solar=True)
        self.assertEqual(first_time(direct)["chart_clock"], "2024-06-01 12:00:00")
        self.assertEqual(instant(direct), instant(flagged))
        self.assertEqual(direct["pillars"], flagged["pillars"])
        self.assertEqual(first_time(direct)["correction_steps"][-1]["correction_from_supplied_seconds"], 0)
        for boundary in ("00:00:00", "01:00:00", "23:00:00"):
            value = chart.build_chart("2024-06-01", boundary, time_basis="true-solar-time", longitude=116.4)
            self.assertEqual(first_time(value)["chart_clock"], "2024-06-01 " + boundary)

    def test_solar_input_minute_crossing_china_midnight_retains_both_lunar_dates(self):
        options = {"time_basis": "true-solar-time", "longitude": 116.4}
        before = chart.build_chart("2024-06-01", "23:48:03", **options)
        after = chart.build_chart("2024-06-01", "23:48:04", **options)
        self.assertTrue(before["lunar"].endswith("四月廿五"))
        self.assertTrue(after["lunar"].endswith("四月廿六"))
        self.assertEqual(before["lunar_candidates"], [before["lunar"]])
        self.assertEqual(after["lunar_candidates"], [after["lunar"]])
        self.assertLess(instant(before), datetime(2024, 6, 1, 16, tzinfo=tc.UTC))
        self.assertGreater(instant(after), datetime(2024, 6, 1, 16, tzinfo=tc.UTC))
        value = chart.build_chart("2024-06-01", "23:48", **options)
        expected = sorted([before["lunar"], after["lunar"]])
        self.assertEqual(len(value["candidates"]), 1)
        self.assertIsNone(value["lunar"])
        self.assertEqual(value["lunar_candidates"], expected)
        for candidate in value["candidates"] + value["convention_alternatives"]:
            self.assertIsNone(candidate["lunar"])
            self.assertEqual(candidate["lunar_candidates"], expected)
            self.assertEqual(sorted({r["lunar"] for r in candidate["time_ranges"]}), expected)
        cells = value["candidates"][0]["time_ranges"]
        self.assertEqual(len(cells), 2)
        self.assertEqual(cells[0]["end_utc"], "2024-06-01T16:00:00+00:00")
        self.assertEqual(cells[1]["start_utc"], "2024-06-01T16:00:00+00:00")
        self.assertEqual(value["solar"], "2024-06-01")
        self.assertEqual(value["solar_candidates"], ["2024-06-01"])
        self.assertTrue(any(u["code"] == "within_input_calendar_dates" and u["fields"] == ["lunar"]
                            for u in value["uncertainty"]))

    def test_original_clock_dates_are_aggregated_when_solar_hour_spans_midnight(self):
        value = chart.build_chart("2024-04-25", calendar="lunar", timezone="Etc/UTC",
                                   true_solar=True, longitude=116.4)
        expected = ["2024-05-31", "2024-06-01"]
        self.assertIsNone(value["solar"])
        self.assertEqual(value["solar_candidates"], expected)
        self.assertIsNotNone(value["lunar"])
        combined = [c for c in value["candidates"] if len(c["solar_candidates"]) > 1]
        self.assertTrue(combined)
        for candidate in combined:
            self.assertIsNone(candidate["solar"])
            self.assertEqual(candidate["solar_candidates"], expected)
            self.assertEqual(sorted({r["solar"] for r in candidate["time_ranges"]}), expected)
            self.assertEqual(candidate["lunar_candidates"], [value["lunar"]])
            self.assertTrue(any(r["end_utc"] == "2024-06-01T00:00:00+00:00"
                                for r in candidate["time_ranges"]))
            self.assertTrue(any(r["start_utc"] == "2024-06-01T00:00:00+00:00"
                                for r in candidate["time_ranges"]))

    def test_solar_requires_explicit_longitude_and_valid_inputs(self):
        for kwargs in ({"true_solar": True}, {"time_basis": "true-solar-time"}, {"longitude": float("nan")},
                       {"longitude": 181}, {"longitude": True}, {"fold": True}, {"timezone": "Beijing"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                chart.build_chart("2024-06-01", "12:00:00", **kwargs)

    def test_unknown_civil_dates_keep_23_and_25_hours_without_invented_birthtime(self):
        for raw, seconds in (("2024-03-10", 23 * 3600), ("2024-11-03", 25 * 3600)):
            value = chart.build_chart(raw, timezone="America/New_York", gender="male")
            total = sum((datetime.fromisoformat(r["end"]) - datetime.fromisoformat(r["start"])).total_seconds()
                        for r in value["time_context"]["valid_utc_ranges"])
            self.assertEqual(total, seconds)
            self.assertIsNone(value["pillars"]["hour"])
            self.assertEqual(value["yun"]["status"], "not_calculated")
            self.assertTrue(all(q["hour"] is None for q in case_lookup.query_chart(value)))
        with self.assertRaisesRegex(ValueError, "requires"):
            chart.build_chart("2024-11-03", timezone="America/New_York", fold=1)

    def test_lunar_date_is_chinese_date_and_overseas_clock_date_is_solved(self):
        lunar = chart.build_chart("2024-01-01", "12:00:00", calendar="lunar", timezone="America/New_York")
        self.assertEqual(lunar["chinese_calendar_solar_date"], "2024-02-10")
        self.assertEqual(lunar["solar"], "2024-02-09")
        self.assertEqual(first_time(lunar)["library_clock"], "2024-02-10 01:00:00+08:00")
        direct = chart.build_chart("2024-02-09", "12:00:00", timezone="America/New_York")
        self.assertEqual(lunar["pillars"], direct["pillars"])
        unknown = chart.build_chart("2024-01-01", calendar="lunar", timezone="America/New_York")
        self.assertIsNone(unknown["solar"])
        self.assertIsNone(unknown["pillars"]["hour"])
        self.assertIsNotNone(unknown["lunar"])

    def test_details_are_derived_from_selected_pillars_for_every_branch(self):
        value = chart.build_chart("2024-06-01", "23:00:00", sect=1)
        from pillar_details import build_details
        self.assertEqual(value["details"], build_details(value["pillars"]))
        for candidate in value["candidates"] + value["convention_alternatives"]:
            self.assertEqual(candidate["details"], build_details(candidate["pillars"]))

    def test_v2_saved_chart_requires_explicit_recreation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.json"
            path.write_text(json.dumps({"schema_version": 2, "input": {}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "No silent migration"):
                case_lookup.load_chart(path)

    def test_cli_and_case_birth_use_identical_time_conversion(self):
        args = ["--time", "01:30:00", "--timezone", "America/New_York", "--fold", "1",
                "--longitude", "-74", "--true-solar"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chart.json"
            with redirect_stdout(io.StringIO()):
                chart.main(["--date", "2024-11-03", *args, "--output", str(path)])
            canonical = case_lookup.load_chart(path)
            out = io.StringIO()
            with redirect_stdout(out):
                case_lookup.main(["--birth", "2024-11-03", *args, "--limit", "1"])
            self.assertEqual(json.loads(out.getvalue())["chart"], canonical)


if __name__ == "__main__":
    unittest.main()
