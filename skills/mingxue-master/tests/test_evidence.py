"""Evidence-link integrity and conservative case-audit boundary regressions."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", HERE))
if not (SKILL / "scripts/case_audit.py").is_file():
    SKILL = HERE / "package/mingxue-master"
sys.path.insert(0, str(SKILL / "scripts"))
import case_audit


def example(case_id="a", *, name=None, hour="甲子", summary="同一段古籍命例摘记"):
    return {"id": case_id, "name": name, "aliases": [],
            "pillars": {"year": "甲子", "month": "丙寅", "day": "戊辰", "hour": hour},
            "hour_basis": "原文四柱", "summary": summary, "birth_text": None,
            "sources": ["古籍甲"], "variants": [], "evidence_id": "CASE-00001",
            "verification_status": "unverified_historical_record"}


class ClassicEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = SKILL / "references/classics"
        cls.index = json.loads((root / "index.json").read_text(encoding="utf-8"))
        cls.checks = json.loads((root / "text-checks.json").read_text(encoding="utf-8"))

    def test_all_cards_have_resolvable_checked_text_and_scoped_claims(self):
        cards = self.index["cards"]
        self.assertEqual(len(cards), 16)
        self.assertEqual(len({c["evidence_id"] for c in cards}), len(cards))
        sources = {s["source_id"]: s for s in self.index["sources"]}
        checks = {c["evidence_id"]: c for c in self.checks["checks"]}
        self.assertEqual(set(checks), {c["evidence_id"] for c in cards})
        for card in cards:
            with self.subTest(card=card["evidence_id"]):
                self.assertRegex(card["evidence_id"], r"^CL-(?:ZP|DT|SF)-\d{3}$")
                source = sources[card["source_id"]]
                self.assertEqual(card["book"], source["book"])
                self.assertTrue(source["url"].startswith("https://"))
                self.assertRegex(source["access_date"], r"^\d{4}-\d{2}-\d{2}$")
                self.assertTrue(source["version"])
                self.assertTrue(source["base_edition_status"])
                self.assertTrue(card["location"])
                self.assertTrue(card["direct_supports"])
                self.assertTrue(card["does_not_support"])
                self.assertEqual(card["verification_status"], "verified_text")
                self.assertIn("不核验", card["verification_scope"])
                checked = checks[card["evidence_id"]]
                literals = [card["quote"]] + card.get("additional_quotes", [])
                self.assertEqual(literals, checked["checked_literals"])
                self.assertEqual(checked["source_id"], card["source_id"])
                self.assertEqual(checked["location"], card["location"])
                self.assertEqual(hashlib.sha256("\n".join(literals).encode("utf-8")).hexdigest(),
                                 checked["quote_sha256"])

    def test_quote_budget_is_per_book_and_scan_locations_are_specific(self):
        counts = Counter()
        for card in self.index["cards"]:
            for quote in [card["quote"]] + card.get("additional_quotes", []):
                counts[card["book"]] += len(re.findall(r"[\u3400-\u9fff]|[A-Za-z0-9]+", quote))
            if card["book"] == "子平真诠":
                self.assertIn("PDF", card["location"])
                self.assertIn("原页", card["location"])
                self.assertTrue(all(1 <= p <= 287 for p in card["pdf_pages"]))
        self.assertEqual(set(counts), {"子平真诠", "滴天髓", "神峰通考"})
        for book, count in counts.items():
            self.assertLessEqual(count, 25, (book, count))
        scan = next(s for s in self.index["sources"] if s["source_id"] == "SRC-ZP-01")
        self.assertRegex(scan["source_file_sha256"], r"^[a-f0-9]{64}$")

    def test_module_card_references_do_not_dangle(self):
        known = {c["evidence_id"] for c in self.index["cards"]}
        for path in (SKILL / "references/modules").glob("*.md"):
            referenced = set(re.findall(r"CL-(?:ZP|DT|SF)-\d{3}", path.read_text(encoding="utf-8")))
            self.assertFalse(referenced - known, (path.name, referenced - known))


class CaseAuditTests(unittest.TestCase):
    def test_exact_content_groups_keep_every_record_and_ignore_only_metadata(self):
        a = example()
        b = deepcopy(a)
        b.update(id="b", evidence_id="CASE-00002", sources=["古籍乙"], record_fingerprint="old")
        before = deepcopy([a, b])
        audit = case_audit.audit_records([a, b])
        self.assertEqual([a, b], before)
        self.assertEqual(audit["summary"]["records"], 2)
        self.assertEqual(audit["summary"]["exact_duplicate_groups"], 1)
        group = audit["groups"]["exact_content_duplicates"][0]
        self.assertEqual({r["id"] for r in group["members"]}, {"a", "b"})
        self.assertEqual(group["action"], "retain_all")

    def test_unnamed_equal_pillars_different_narrative_are_not_duplicates(self):
        a, b = example("a", summary="一人从军"), example("b", summary="另一人经商")
        result = case_audit.audit_records([a, b])
        self.assertFalse(result["groups"]["exact_content_duplicates"])
        self.assertFalse(result["groups"]["same_name_different_pillars"])

    def test_empty_templates_and_stored_hash_collisions_never_merge_people(self):
        a, b = example("a", summary=None), example("b", summary=None)
        for record in (a, b):
            record["pillars"] = dict.fromkeys(case_audit.PILLARS)
            record["record_fingerprint"] = "legacy-collision"
        b["birth_text"] = "1970-01-01 08:20"
        result = case_audit.audit_records([a, b])
        self.assertFalse(result["groups"]["exact_content_duplicates"])
        self.assertEqual(len(result["groups"]["legacy_fingerprint_collisions"]), 1)
        self.assertEqual(result["summary"]["records"], 2)
        b["birth_text"] = None
        self.assertFalse(case_audit.audit_records([a, b])["groups"]["exact_content_duplicates"])

    def test_named_conflict_uses_explicit_name_and_known_differing_pillar(self):
        a, b = example("a", name=" 某甲 "), example("b", name="某甲")
        b["pillars"]["hour"] = "丙寅"
        result = case_audit.audit_records([a, b])
        self.assertEqual(len(result["groups"]["same_name_different_pillars"]), 1)
        # Unknown hour is incomplete information, not a conflicting hour.
        b["pillars"]["hour"] = None
        self.assertFalse(case_audit.audit_records([a, b])["groups"]["same_name_different_pillars"])
        # An alias might be a role or an extraction error: do not infer identity.
        b["name"], b["aliases"], b["pillars"]["hour"] = "某乙", ["某甲"], "丙寅"
        self.assertFalse(case_audit.audit_records([a, b])["groups"]["same_name_different_pillars"])

    def test_missing_hour_does_not_claim_absence_of_time_in_birth_text(self):
        record = example(hour=None)
        record["hour_basis"] = None
        record["birth_text"] = "1970-01-01 08:20出生，尚未换算四柱"
        quality = case_audit.audit_records([record])["records"][0]
        self.assertIn("missing_hour", quality["flags"])
        self.assertNotIn("uncertain_hour", quality["flags"])
        for basis, text in (("推定", None), ("占位", None), ("记载", "出生时辰可靠度：低"),
                            ("缺失", "时辰未知")):
            record["hour_basis"], record["birth_text"] = basis, text
            self.assertIn("uncertain_hour", case_audit.audit_records([record])["records"][0]["flags"])

    def test_variants_and_original_births_stay_unverified(self):
        record = example(name="某甲")
        record["variants"] = [{"pillars": {"hour": "丙寅"}}, {"pillars": {"hour": None}}]
        quality = case_audit.audit_records([record])["records"][0]
        self.assertEqual(quality["conflicting_variant_numbers"], [1])
        self.assertEqual(quality["birth_verification_status"], "unverified_historical_record")
        self.assertEqual(len(record["variants"]), 2)

    def test_load_refuses_changed_library_and_invalid_rows_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database, index = root / "cases.jsonl", root / "quality.json"
            database.write_text(json.dumps(example(), ensure_ascii=False) + "\n", encoding="utf-8")
            audit = case_audit.audit_library(database)
            index.write_text(json.dumps(audit), encoding="utf-8")
            _, by_id = case_audit.load_quality_index(index, database)
            self.assertIn("a", by_id)
            database.write_text(json.dumps(example("b")), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "stale"):
                case_audit.load_quality_index(index, database)
            database.write_text('{"id":"a","id":"b"}\n', encoding="utf-8")
            audit = case_audit.audit_library(database)
            self.assertEqual(audit["summary"]["records"], 0)
            self.assertEqual(audit["summary"]["issues"], 1)

    def test_supplied_index_is_reproducible_and_all_records_are_retained(self):
        resource = Path(os.environ.get("MINGXUE_TEST_RESOURCE_ROOT", HERE / "runtime"))
        if not resource.is_dir():
            from resources import get_resources
            resource = get_resources()
        database = resource / "references/upstream/tongren-mingdian-skillpack/data/命例库.jsonl"
        saved = resource / "references/case-quality.json"
        expected = case_audit.audit_library(database)
        actual, by_id = case_audit.load_quality_index(saved, database)
        self.assertEqual(actual, expected)
        self.assertEqual(expected["summary"]["records"], 2032)
        self.assertEqual(len(by_id), 2032)
        self.assertTrue(all(q["birth_verification_status"] == "unverified_historical_record"
                            for q in expected["records"]))


if __name__ == "__main__":
    unittest.main()
