"""Pinned external character data, explicit reading choices and batch evidence."""
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", HERE))
if not (SKILL / "scripts/name_dictionary.py").is_file():
    SKILL = HERE / "package/mingxue-master"
sys.path.insert(0, str(SKILL / "scripts"))
import name_analysis as names
import name_dictionary as dictionary
import prepare_name_dictionary as preparation
from runtime_paths import engine_directory


class IndependentDictionaryTests(unittest.TestCase):
    def test_readings_are_extracted_without_silently_picking_customary_one(self):
        fields = {"kMandarin": "dān", "kTGHZ2013": "001.010:chán 002.020:dān 003.030:shàn",
                  "kHanyuPinyin": "10001.010:dān,shàn"}
        result = dictionary.reading_candidates(fields)
        self.assertEqual([r["pinyin"] for r in result], ["chán", "dān", "shàn"])
        self.assertIn("kMandarin", result[1]["properties"])
        entry = {"单": {"readings": result}}
        unresolved = dictionary.resolve_readings("单", entry, part="surname")
        self.assertIsNone(unresolved["pinyin"])
        self.assertEqual(unresolved["pending_inputs"][0]["reason"], "explicit_reading_choice_required")
        resolved = dictionary.resolve_readings("单", entry, "shàn", part="surname")
        self.assertEqual(resolved["pinyin"], "shàn")
        self.assertEqual(resolved["characters"][0]["source"], "user_choice_from_dictionary_candidates")

    def test_bad_reading_is_pending_not_a_guessed_correction(self):
        entries = {"单": {"readings": [{"pinyin": "shàn"}]}}
        result = dictionary.resolve_readings("单", entries, "shan4", part="surname")
        self.assertIsNone(result["pinyin"])
        self.assertIn("chosen_reading_not_in_dictionary", result["pending_inputs"][0]["reason"])
        with self.assertRaises(ValueError):
            dictionary.resolve_readings("欧阳", entries, "ōu", part="surname")

    def test_tone_insensitive_comparison_preserves_diaeresis_and_circumflex(self):
        self.assertEqual(dictionary.pinyin_key("LǙ", ignore_tone=True), "lü")
        self.assertNotEqual(dictionary.pinyin_key("lǜ", ignore_tone=True), dictionary.pinyin_key("lù", ignore_tone=True))
        self.assertNotEqual(dictionary.pinyin_key("ê", ignore_tone=True), dictionary.pinyin_key("e", ignore_tone=True))

    def test_missing_character_and_missing_fields_stay_missing(self):
        missing = dictionary.character_entry("龘", {})
        self.assertEqual(missing["status"], "not_found")
        partial = dictionary.character_entry("李", {"李": {"kTotalStrokes": "7"}})
        self.assertIn("definition_en", partial["pending_fields"])
        self.assertIn("mandarin_reading", partial["pending_fields"])
        self.assertIsNone(partial["definition"]["text"])

    def test_pinned_version_stroke_syntax_does_not_accept_old_two_locale_values(self):
        with self.assertRaises(dictionary.DictionaryError):
            dictionary.character_entry("李", {"李": {"kTotalStrokes": "7 8"}})

    def test_unicode17_extension_j_name_boundary_is_supported(self):
        self.assertEqual(names.validate_name(chr(0x323B0), "given"), chr(0x323B0))
        self.assertEqual(names.validate_name(chr(0x33479), "given"), chr(0x33479))
        with self.assertRaises(ValueError):
            names.validate_name(chr(0x3347A), "given")

    def test_missing_cache_probe_and_lookup_do_not_create_directories_or_network(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "unprepared"
            with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")), \
                    patch.object(preparation.urllib.request, "urlopen", side_effect=AssertionError("network forbidden")):
                self.assertEqual(dictionary.dictionary_status(destination)["status"], "needs_dictionary")
                self.assertEqual(dictionary.lookup_characters("李", destination)["status"], "needs_dictionary")
                result = names.analyze_name("李", "明", dictionary_dir=destination)
                self.assertEqual(result["status"], "needs_input")
                self.assertIsNone(result["five_grids"])
                self.assertEqual(names.probe(destination)["dictionary"]["status"], "needs_dictionary")
            self.assertFalse(destination.exists())

    def test_environment_override_and_protected_dictionary_paths(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"MINGXUE_NAME_DICTIONARY": temp}):
            self.assertEqual(dictionary.dictionary_directory(), Path(temp).resolve())
        for target in ("relative", SKILL, SKILL / "assets/character-data"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                dictionary.dictionary_directory(target)

    def test_malformed_manifest_is_a_structured_invalid_status(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            (target / "manifest.json").write_text("[]", encoding="utf-8")
            self.assertEqual(dictionary.dictionary_status(target)["status"], "invalid_dictionary")

    def test_legacy_explicit_counts_work_without_dictionary_and_remain_user_supplied(self):
        with patch.object(dictionary, "load_dictionary", side_effect=AssertionError("explicit counts need no dictionary")):
            result = names.analyze_name("欧阳", "修", [15, 17, 10], stroke_standard="用户指定康熙口径")
        self.assertEqual(result["five_grids"]["总格"]["number"], 42)
        self.assertEqual(result["stroke_provenance"]["source"], "user_supplied")
        self.assertFalse(result["stroke_provenance"]["dictionary_verified"])

    def test_download_is_explicit_and_nonempty_unverified_destinations_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "dictionary"
            target.mkdir()
            sentinel = target / "keep.txt"
            sentinel.write_text("keep", encoding="utf-8")
            with patch.object(preparation.urllib.request, "urlopen", side_effect=AssertionError("no automatic network")):
                with self.assertRaisesRegex(ValueError, "explicit --download"):
                    preparation.prepare_dictionary(target)
                with self.assertRaisesRegex(ValueError, "nonempty"):
                    preparation.prepare_dictionary(target, download_data=True)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")


class PreparedOfficialDictionaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = Path(os.environ.get("MINGXUE_TEST_NAME_DICTIONARY") or dictionary.dictionary_directory())
        if dictionary.dictionary_status(cls.directory)["status"] != "ready":
            raise unittest.SkipTest("official external character cache is not prepared; no network is permitted in tests")
        cls.root, cls.records = dictionary.load_dictionary(cls.directory)

    def test_actual_fixed_archive_and_derived_index_checksums(self):
        self.assertEqual(hashlib.sha256((self.root / "Unihan.zip").read_bytes()).hexdigest(), dictionary.ARCHIVE_SHA256)
        self.assertEqual(hashlib.sha256((self.root / "characters.json").read_bytes()).hexdigest(), dictionary.DATA_SHA256)
        self.assertGreater(len(self.records), 100000)
        normalized = dictionary.normalize_archive((self.root / "Unihan.zip").read_bytes())
        self.assertEqual(hashlib.sha256(normalized).hexdigest(), dictionary.DATA_SHA256)

    def test_official_exact_forms_modern_strokes_meaning_and_variants(self):
        result = dictionary.lookup_characters("陈陳单單", self.root)
        self.assertTrue(result["dictionary_verified"])
        entries = {entry["character"]: entry for entry in result["characters"]}
        self.assertEqual([entries[c]["modern_strokes"]["count"] for c in "陈陳单單"], [7, 10, 8, 12])
        self.assertEqual(entries["陳"]["modern_strokes"]["scheme"], "unihan-irG")
        self.assertTrue(entries["陈"]["definition"]["text"])
        self.assertEqual(entries["陈"]["definition"]["language"], "en")
        self.assertIn("陳", [entry["character"] for entry in entries["陈"]["variants"]["kTraditionalVariant"]])
        self.assertEqual(entries["陈"]["character_conversion"], "none")
        self.assertEqual(entries["陈"]["shape_metadata"]["property"], "kRSUnicode")

    def test_real_polyphonic_surname_requires_choice_before_complete_analysis(self):
        result = names.analyze_name("单", "明", dictionary_dir=self.root)
        self.assertEqual(result["status"], "needs_input")
        surname = result["reading_resolution"]["surname"]
        self.assertEqual(set(surname["characters"][0]["choices"]), {"dān", "chán", "shàn"})
        self.assertIsNone(surname["pinyin"])
        self.assertEqual(result["calculation_status"], "calculated")
        completed = names.analyze_name("单", "明", dictionary_dir=self.root, surname_reading="shàn", given_reading="míng")
        self.assertEqual(completed["status"], "calculated")
        self.assertEqual(completed["resolved_pinyin"], "shàn míng")
        self.assertEqual([completed["five_grids"][key]["number"] for key in ("天格", "人格", "地格", "外格", "总格")], [9, 16, 9, 2, 16])

    def test_compound_surname_and_explicit_syllable_positions(self):
        result = names.analyze_name("欧阳", "修", dictionary_dir=self.root, surname_reading="ōu yáng", given_reading="xiū")
        self.assertEqual(result["status"], "calculated")
        self.assertEqual([entry["count"] for entry in result["strokes"]], [8, 6, 9])
        self.assertEqual(result["resolved_pinyin"], "ōu yáng xiū")

    def test_kangxi_request_cannot_silently_use_modern_counts(self):
        result = names.analyze_name("陈", "明", dictionary_dir=self.root, stroke_scheme="kangxi", surname_reading="chén", given_reading="míng")
        self.assertEqual(result["status"], "needs_input")
        self.assertIsNone(result["five_grids"])
        self.assertIn("verified_kangxi", result["pending_inputs"][0]["reason"])
        explicit = names.analyze_name("陈", "明", [16, 8], dictionary_dir=self.root,
            stroke_scheme="kangxi", stroke_standard="用户指定康熙", surname_reading="chén", given_reading="míng")
        self.assertEqual(explicit["five_grids"]["总格"]["number"], 24)
        self.assertEqual(explicit["stroke_provenance"]["source"], "user_supplied")
        self.assertFalse(explicit["stroke_provenance"]["dictionary_verified"])

    def test_user_convention_label_without_counts_cannot_turn_into_modern_dictionary_counts(self):
        result = names.analyze_name("陈", "明", dictionary_dir=self.root, stroke_standard="康熙笔画",
            surname_reading="chén", given_reading="míng", meaning_note="用户文字说明")
        self.assertIsNone(result["five_grids"])
        self.assertEqual(result["pending_inputs"][0]["reason"], "explicit_strokes_required_for_user_convention")
        self.assertEqual(result["sound_form_meaning"]["meaning_note"], "用户文字说明")

    def test_unencoded_or_unlisted_character_returns_pending_without_fabrication(self):
        result = names.analyze_name("李", "\U0002ffff", dictionary_dir=self.root, surname_reading="lǐ")
        self.assertEqual(result["status"], "needs_input")
        self.assertIsNone(result["five_grids"])
        self.assertTrue(any(item.get("reason") == "dictionary_stroke_missing" for item in result["pending_inputs"]))

    def test_batch_comparison_retains_order_and_reports_only_supported_homophones(self):
        result = names.compare_names("王", [{"given": "明", "given_reading": "míng"}, {"given": "铭", "given_reading": "míng"}],
            dictionary_dir=self.root, surname_reading="wáng", homophone_watchlist=[{"text": "用户关注的词", "reading": "wáng míng"}])
        self.assertEqual(result["status"], "compared")
        self.assertEqual([candidate["name"] for candidate in result["candidates"]], ["王明", "王铭"])
        self.assertEqual(result["homophone_reminders"][0]["kind"], "same_pinyin")
        self.assertTrue(any(item["kind"] == "user_watchlist_phonetic_match" for item in result["homophone_reminders"]))
        self.assertTrue(result["same_declared_stroke_convention"])
        self.assertNotIn("dictionary", result["candidates"][0])

    def test_batch_partial_missing_readings_does_not_invent_homophones(self):
        result = names.compare_names("单", [{"given": "明"}, {"given": "铭"}], dictionary_dir=self.root)
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(result["homophone_reminders"], [])
        for candidate in result["candidates"]:
            self.assertIsNone(candidate["resolved_pinyin"])

    def test_batch_mixed_stroke_conventions_are_identified(self):
        result = names.compare_names("王", [{"given": "明", "given_reading": "míng"},
            {"given": "铭", "given_reading": "míng", "strokes": [4, 14], "stroke_standard": "用户口径"}],
            dictionary_dir=self.root, surname_reading="wáng")
        self.assertFalse(result["same_declared_stroke_convention"])
        self.assertEqual(len(result["stroke_conventions"]), 2)

    def test_changed_data_rejected_even_if_local_manifest_is_rewritten(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "dictionary"
            shutil.copytree(self.root, target)
            changed = (target / "characters.json").read_bytes().replace(b'"kTotalStrokes":"7"', b'"kTotalStrokes":"8"', 1)
            (target / "characters.json").write_bytes(changed)
            manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
            manifest["data_sha256"] = hashlib.sha256(changed).hexdigest()
            (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(dictionary.dictionary_status(target)["status"], "invalid_dictionary")
            with self.assertRaises(dictionary.DictionaryError):
                dictionary.lookup_characters("李", target)

    def test_real_lookup_and_probe_remain_offline(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")), \
                patch.object(preparation.urllib.request, "urlopen", side_effect=AssertionError("network forbidden")):
            self.assertEqual(names.probe(self.root)["dictionary"]["status"], "ready")
            self.assertTrue(dictionary.lookup_characters("单", self.root)["dictionary_verified"])

    def test_output_cannot_be_placed_in_custom_dictionary_directory(self):
        result = dictionary.lookup_characters("李", self.root)
        with self.assertRaises(ValueError), redirect_stdout(io.StringIO()):
            names.write_result(result, str(self.root / "user-reading.json"))

    def test_cli_lookup_batch_and_probe_are_json(self):
        def run(script, *args):
            proc = subprocess.run([sys.executable, "-X", "utf8", "-B", str(SKILL / "scripts" / script), *args],
                capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(proc.stderr, "")
            self.assertEqual(proc.returncode, 0, proc.stdout)
            return json.loads(proc.stdout)
        self.assertTrue(run("name_analysis.py", "--lookup", "陈陳", "--dictionary-dir", str(self.root))["dictionary_verified"])
        self.assertEqual(run("prepare_name_dictionary.py", "--probe", "--dictionary-dir", str(self.root))["status"], "ready")
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "candidates.json"
            source.write_text(json.dumps({"surname": "王", "surname_reading": "wáng", "candidates": [
                {"given": "明", "given_reading": "míng"}, {"given": "铭", "given_reading": "míng"}]}), encoding="utf-8")
            result = run("name_analysis.py", "--compare-file", str(source), "--dictionary-dir", str(self.root))
            self.assertEqual(result["homophone_reminders"][0]["kind"], "same_pinyin")


if __name__ == "__main__":
    unittest.main()
