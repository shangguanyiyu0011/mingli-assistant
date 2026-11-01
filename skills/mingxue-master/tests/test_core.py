"""Offline regression tests for shared calendar input, query tiers and resources."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", HERE))
if not (SKILL / "scripts/chart.py").is_file():
    SKILL = HERE / "package/mingxue-master"
sys.path.insert(0, str(SKILL / "scripts"))
import chart
import case_lookup
import resources


def make_bundle(root, *, start=0, files=None):
    files = files or {"references/a.txt": b"a" * 100_000,
                      "references/子目录/b.txt": "verified data".encode()}
    assets = root / "assets"
    assets.mkdir()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    payload = buf.getvalue()
    checksum = hashlib.sha256(payload).hexdigest()
    manifest = {"schema_version": 1, "archive_sha256": checksum,
                "files": {n: {"size": len(v), "sha256": hashlib.sha256(v).hexdigest()}
                          for n, v in files.items()}}
    (assets / "resources-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (assets / "sources.sha256").write_text(checksum, encoding="ascii")
    split = len(payload) // 2
    for i, part in enumerate((payload[:split], payload[split:]), start):
        (assets / f"sources.zip.part{i:03}").write_bytes(part)
    return assets, manifest


class ResourceTests(unittest.TestCase):
    def test_cache_rebuilds_altered_missing_and_extra_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets, manifest = make_bundle(root)
            cache = root / "cache"
            dest = resources.get_resources(assets_dir=assets, cache_dir=cache, resource_dir="")
            (dest / "references/a.txt").write_bytes(b"corrupt")
            resources.get_resources(assets_dir=assets, cache_dir=cache, resource_dir="")
            self.assertEqual((dest / "references/a.txt").stat().st_size, 100_000)
            (dest / "references/a.txt").unlink()
            resources.get_resources(assets_dir=assets, cache_dir=cache, resource_dir="")
            (dest / "unlisted.txt").write_bytes(b"unexpected")
            resources.get_resources(assets_dir=assets, cache_dir=cache, resource_dir="")
            self.assertFalse((dest / "unlisted.txt").exists())
            self.assertEqual(resources.verify_tree(dest, manifest), dest)

    def test_part001_and_distribution_damage_even_with_good_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets, _ = make_bundle(root, start=1)
            resources.get_resources(assets_dir=assets, cache_dir=root / "cache", resource_dir="")
            (assets / "sources.zip.part001").write_bytes(b"damaged")
            with self.assertRaisesRegex(resources.ResourceError, "SHA-256"):
                resources.get_resources(assets_dir=assets, cache_dir=root / "cache", resource_dir="")

    def test_directory_override_is_fully_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets, manifest = make_bundle(root)
            dest = resources.get_resources(assets_dir=assets, cache_dir=root / "cache", resource_dir="")
            self.assertEqual(resources.get_resources(assets_dir=assets, resource_dir=dest), dest)
            (dest / "references/a.txt").write_bytes(b"altered")
            with self.assertRaisesRegex(resources.ResourceError, "SHA-256"):
                resources.get_resources(assets_dir=assets, resource_dir=dest)

    def test_unsafe_manifest_and_missing_part_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets, _ = make_bundle(root, files={"../escape.txt": b"bad"})
            with self.assertRaisesRegex(resources.ResourceError, "Invalid resource path"):
                resources.get_resources(assets_dir=assets, cache_dir=root / "cache", resource_dir="")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets, _ = make_bundle(root)
            (assets / "sources.zip.part001").rename(assets / "sources.zip.part002")
            with self.assertRaisesRegex(resources.ResourceError, "contiguous"):
                resources.get_resources(assets_dir=assets, cache_dir=root / "cache", resource_dir="")

    def test_concurrent_processes_share_only_completed_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets, manifest = make_bundle(root)
            program = ("import sys;sys.dont_write_bytecode=True;sys.path.insert(0,sys.argv[1]);"
                       "from resources import get_resources,verify_tree,read_manifest;"
                       "p=get_resources(assets_dir=sys.argv[2],cache_dir=sys.argv[3],resource_dir='');"
                       "verify_tree(p,read_manifest(sys.argv[2]));print(p.name)")
            commands = [subprocess.Popen([sys.executable, "-X", "utf8", "-c", program,
                          str(SKILL / "scripts"), str(assets), str(root / "cache")],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8") for _ in range(6)]
            for process in commands:
                out, err = process.communicate(timeout=60)
                self.assertEqual(process.returncode, 0, err)
                self.assertEqual(out.strip(), manifest["archive_sha256"])
            self.assertFalse(list((root / "cache").glob("*.staging-*")))


class CalendarTests(unittest.TestCase):
    def test_personal_output_cannot_pollute_skill_or_resource_cache(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            chart.write_json({"private": "birth data"}, SKILL / "personal.json")
        with self.assertRaisesRegex(ValueError, "outside"):
            chart.write_json({"private": "birth data"}, Path(tempfile.gettempdir()) / "mingxue-master-cache/personal.json")

    def test_invalid_dates_time_and_extra_api_options(self):
        for kwargs in ({"date_value": "2023-02-29"}, {"date_value": "2024-1-01"},
                       {"date_value": "2024-01-01", "time_value": "24:00"},
                       {"date_value": "2024-01-01", "time_value": "12:00+08:00"},
                       {"date_value": "2024-01-01", "leap": True},
                       {"date_value": "2024-01-01", "sect": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                chart.build_chart(**kwargs)

    def test_real_lunar_leap_month_and_day_count(self):
        value = chart.build_chart("2023-02-01", "12:00", calendar="lunar", leap=True)
        self.assertEqual(value["solar"], "2023-03-22")
        for value in ("2024-02-01", "2023-03-01"):
            with self.assertRaisesRegex(ValueError, "no leap"):
                chart.build_chart(value, calendar="lunar", leap=True)
        with self.assertRaisesRegex(ValueError, "only 29"):
            chart.build_chart("2023-02-30", calendar="lunar", leap=True)

    def test_23_and_midnight_day_change_conventions(self):
        before = chart.build_chart("2024-06-01", "22:59:59", sect=1)
        late1 = chart.build_chart("2024-06-01", "23:00:00", sect=1)
        late2 = chart.build_chart("2024-06-01", "23:00:00", sect=2)
        next_day = chart.build_chart("2024-06-02", "00:00:00", sect=2)
        self.assertEqual(before["pillars"]["day"], late2["pillars"]["day"])
        self.assertNotEqual(late1["pillars"]["day"], late2["pillars"]["day"])
        self.assertEqual(late1["pillars"]["day"], next_day["pillars"]["day"])
        self.assertEqual(len(late1["candidates"]), 1)
        self.assertEqual(late1["convention_alternatives"][0]["pillars"], late2["pillars"])

    def test_unknown_time_does_not_assert_noon_or_four_pillar_match(self):
        unknown = chart.build_chart("2024-06-01", sect=1)
        self.assertFalse(unknown["time_known"])
        self.assertIsNone(unknown["pillars"]["hour"])
        self.assertIsNone(unknown["pillars"]["day"])
        self.assertGreater(len(unknown["candidates"]), 1)
        self.assertTrue(all(q["hour"] is None for q in case_lookup.query_chart(unknown)))
        self.assertEqual(unknown["yun"]["status"], "not_calculated")

    def test_jieqi_day_keeps_both_year_month_candidates(self):
        unknown = chart.build_chart("2024-02-04", sect=2)
        self.assertIsNone(unknown["pillars"]["year"])
        self.assertIsNone(unknown["pillars"]["month"])
        instant = next(item["library_clock"] for item in unknown["solar_terms_on_date"] if item["name"] == "立春")
        dt = datetime.fromisoformat(instant)
        pre = chart.build_chart(dt.date().isoformat(), (dt - timedelta(seconds=1)).time().isoformat())
        post = chart.build_chart(dt.date().isoformat(), dt.time().isoformat())
        self.assertNotEqual(pre["pillars"]["year"], post["pillars"]["year"])
        minute = chart.build_chart(dt.date().isoformat(), dt.strftime("%H:%M"))
        if dt.second:
            self.assertIsNone(minute["pillars"]["month"])

    def test_yun_requires_explicit_gender_and_known_time(self):
        known = chart.build_chart("1990-05-02", "12:30", gender="female", timezone="Asia/Shanghai", yun_sect=2)
        self.assertEqual(known["yun"]["status"], "calculated")
        self.assertEqual(set(known["yun"]["start_offset"]), {"years", "months", "days", "hours"})
        self.assertEqual(len(known["yun"]["dayun"]), 8)
        self.assertTrue(known["corrections"]["dst"])
        self.assertEqual(known["input"]["timezone"], "Asia/Shanghai")
        self.assertEqual(chart.build_chart("1990-05-02", gender="female")["yun"]["status"], "not_calculated")
        self.assertEqual(chart.build_chart("1990-05-02", "12:30")["yun"]["status"], "not_calculated")

    def test_cli_chart_json_and_birth_query_are_consistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chart.json"
            with redirect_stdout(io.StringIO()):
                chart.main(["--date", "1990-05-02", "--time", "12:30", "--sect", "1", "--output", str(path)])
            saved = case_lookup.load_chart(path)
            direct = chart.build_chart("1990-05-02", "12:30", sect=1)
            self.assertEqual(saved, direct)
            outputs = []
            for argv in (["--chart", str(path), "--limit", "1", "--json"],
                         ["--birth", "1990-05-02", "--time", "12:30", "--sect", "1", "--limit", "1"]):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    case_lookup.main(argv)
                outputs.append(json.loads(buf.getvalue()))
            self.assertEqual(outputs[0], outputs[1])
            saved["pillars"]["day"] = "甲子"
            path.write_text(json.dumps(saved), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "canonical"):
                case_lookup.load_chart(path)


class LookupTests(unittest.TestCase):
    def test_illegal_cycle_and_surplus_text_are_rejected(self):
        for value in ("甲丑 乙丑 丙寅", "甲子 乙丑", "甲子 乙丑 丙寅 丁卯 戊辰", "甲子乙丑丙寅 note"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                case_lookup.parse_bazi(value)
        self.assertEqual(case_lookup.parse_bazi("甲子乙丑丙寅")["hour"], None)
        self.assertFalse(chart.is_valid_pillar("甲丑"))

    def test_disjoint_match_tiers_and_original_evidence_fields(self):
        def record(name, pillars):
            return {"id": name, "pillars": case_lookup.parse_bazi(pillars), "sources": ["古籍·卷一"],
                    "confidence": "source-supplied", "caution": "disputed", "variants": ["alternate text"]}
        query = case_lookup.parse_bazi("甲子 乙丑 丙寅 丁卯")
        records = [record("full", "甲子 乙丑 丙寅 丁卯"), record("three", "甲子 乙丑 丙寅 戊辰"),
                   record("two", "甲子 乙丑 戊辰 己巳"), record("day", "戊辰 己巳 丙寅 庚午"),
                   record("none", "戊辰 己巳 庚午 辛未")]
        result = case_lookup.lookup_cases(query, records)
        self.assertEqual(list(result["counts"].values()), [1, 1, 1, 1])
        self.assertEqual(result["groups"]["same_day"][0]["sources"], ["古籍·卷一"])
        self.assertEqual(result["groups"]["four_pillars"][0]["variants"], ["alternate text"])
        unknown = dict(query, hour=None)
        self.assertEqual(case_lookup.lookup_cases(unknown, records)["counts"]["four_pillars"], 0)

    def test_cli_refuses_mixed_or_extra_inputs(self):
        for argv in (["--bazi", "甲子乙丑丙寅", "--birth", "2000-01-01"],
                     ["--bazi", "甲子乙丑丙寅", "--time", "12:00"],
                     ["--bazi", "甲子乙丑丙寅", "--unknown"],
                     ["--birth", "2024-01-01", "--calendar", "solar", "--leap"]):
            with self.subTest(argv=argv), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                case_lookup.main(argv)


if __name__ == "__main__":
    unittest.main()
