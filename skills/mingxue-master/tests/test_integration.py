"""Public entrypoints retain independent case-quality and local-readiness evidence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", HERE))
if not (SKILL / "scripts/chart.py").is_file():
    SKILL = HERE / "package/mingxue-master"
sys.path.insert(0, str(SKILL / "scripts"))
from resources import get_resources
from case_audit import load_quality_index
from case_lookup import load_cases
import doctor


class IntegrationTests(unittest.TestCase):
    def test_query_retains_explicit_variant_quality_without_rewriting_record(self):
        root = get_resources()
        database = root / "references/upstream/tongren-mingdian-skillpack/data/命例库.jsonl"
        audit, by_id = load_quality_index(root / "references/case-quality.json", database)
        records, issues = load_cases(root)
        self.assertFalse(issues)
        record = next(r for r in records if "conflicting_variant_pillars" in by_id[r["id"]]["flags"])
        values = [record["pillars"][k] for k in ("year", "month", "day", "hour")]
        self.assertTrue(all(values))
        result = subprocess.run([sys.executable, "-X", "utf8", "-B", str(SKILL / "scripts/case_lookup.py"),
            "--bazi", " ".join(values), "--limit", "100", "--json"],
            capture_output=True, text=True, encoding="utf-8", timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        found = next(r for group in payload["groups"].values() for r in group if r["id"] == record["id"])
        self.assertEqual(found["quality"], by_id[record["id"]])
        self.assertEqual(found["variants"], record["variants"])
        self.assertEqual(found["pillars"], record["pillars"])
        self.assertEqual(payload["database"]["quality_audit"], audit["summary"])
        self.assertEqual(audit["summary"]["exact_duplicate_groups"], 0)
        self.assertEqual(audit["summary"]["legacy_fingerprint_collision_groups"], 1)

    def test_doctor_checks_time_details_quality_without_network(self):
        with mock.patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("Network access forbidden")):
            result = doctor.diagnose()
        self.assertTrue(result["ok"], result)
        checks = {r["name"]: r for r in result["checks"]}
        self.assertTrue(checks["timezone_database"]["ok"])
        self.assertEqual(checks["timezone_resolution"]["detail"]["fold_offsets_seconds"], [-14400, -18000])
        self.assertTrue(checks["pillar_details"]["detail"]["complete"])
        self.assertEqual(checks["case_quality"]["detail"]["records"], 2032)


if __name__ == "__main__":
    unittest.main()
