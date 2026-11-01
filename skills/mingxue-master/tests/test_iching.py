"""Independent finite-table, change, method, CLI and output-path checks."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", ROOT))
if not (SKILL / "scripts/iching.py").is_file():
    SKILL = ROOT / "package/mingxue-master"
SCRIPT = SKILL / "scripts/iching.py"
SPEC = importlib.util.spec_from_file_location("iching", SCRIPT)
iching = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(iching)

# King Wen sequence, represented independently as six-line codes (first = bottom).
KING_WEN_CODES = (
    "111111 000000 100010 010001 111010 010111 010000 000010 "
    "111011 110111 111000 000111 101111 111101 001000 000100 "
    "100110 011001 110000 000011 100101 101001 000001 100000 "
    "100111 111001 100001 011110 010010 101101 001110 011100 "
    "001111 111100 000101 101000 101011 110101 001010 010100 "
    "110001 100011 111110 011111 000110 011000 010110 011010 "
    "101110 011101 100100 001001 001011 110100 101100 001101 "
    "011011 110110 010011 110010 110011 001100 101010 010101"
).split()


def static_values(bits):
    return [7 if b == "1" else 8 for b in bits]


class CatalogTests(unittest.TestCase):
    def test_all_64_independent_king_wen_codes(self):
        self.assertEqual(len(set(KING_WEN_CODES)), 64)
        self.assertEqual(len(iching.HEXAGRAMS), 64)
        self.assertEqual(len(iching.PALACES), 64)
        for expected_number, bits in enumerate(KING_WEN_CODES, 1):
            with self.subTest(number=expected_number):
                gua = iching.hexagram(bits)
                self.assertEqual(gua["number"], expected_number)
                self.assertEqual(gua["symbol"], chr(0x4DC0 + expected_number - 1))
                self.assertTrue(gua["cultural_theme"])
                self.assertEqual(gua["bits_bottom_to_top"], bits)

    def test_asymmetric_trigrams_in_both_positions(self):
        # For these four trigrams reversing the line order changes the trigram.
        for bits, name in (("100", "震"), ("001", "艮"), ("011", "巽"), ("110", "兑")):
            with self.subTest(bits=bits):
                self.assertEqual(iching.hexagram(bits + "111")["lower"]["name"], name)
                self.assertEqual(iching.hexagram("111" + bits)["upper"]["name"], name)
        self.assertEqual(iching.hexagram("100010")["full_name"], "水雷屯")
        self.assertEqual(iching.hexagram("010100")["full_name"], "雷水解")

    def test_catalog_mutation_does_not_change_shared_data(self):
        value = iching.hexagram("111111")
        value["upper"]["name"] = "changed"
        self.assertEqual(iching.hexagram("111111")["upper"]["name"], "乾")

    def test_all_eight_symbols_and_numbers(self):
        expected = (("乾", "111", "☰"), ("兑", "110", "☱"), ("离", "101", "☲"), ("震", "100", "☳"),
                    ("巽", "011", "☴"), ("坎", "010", "☵"), ("艮", "001", "☶"), ("坤", "000", "☷"))
        for number, (name, bits, symbol) in enumerate(expected, 1):
            self.assertEqual((iching.TRIGRAMS[bits]["name"], iching.TRIGRAMS[bits]["symbol"],
                              iching.TRIGRAMS[bits]["xiantian_number"]), (name, symbol, number))


class LineTests(unittest.TestCase):
    def test_old_yin_and_old_yang_change_in_opposite_directions(self):
        result = iching.build_result([6, 7, 8, 9, 7, 8])
        self.assertEqual(result["moving_positions"], [1, 4])
        self.assertEqual(result["hexagrams"]["base"]["full_name"], "泽水困")
        self.assertEqual(result["hexagrams"]["changed"]["full_name"], "水泽节")
        self.assertEqual(result["hexagrams"]["changed"]["bits_bottom_to_top"], "110010")
        self.assertEqual(result["hexagrams"]["nuclear"]["full_name"], "风火家人")
        self.assertTrue(result["lines_bottom_to_top"][0]["changed_yang"])
        self.assertFalse(result["lines_bottom_to_top"][3]["changed_yang"])

    def test_all_4096_cast_states_change_only_6_and_9(self):
        # Enumerating the finite six-line input state catches position and flip errors.
        import itertools
        for values in itertools.product((6, 7, 8, 9), repeat=6):
            result = iching.build_result(list(values))
            expected = "".join("1" if v in (6, 7) else "0" for v in values)
            self.assertEqual(result["hexagrams"]["changed"]["bits_bottom_to_top"], expected)

    def test_explicit_top_to_bottom_reverses_once(self):
        expected = iching.build_result([6, 7, 8, 9, 7, 8])
        actual = iching.build_result([8, 7, 9, 8, 7, 6], direction="top-to-bottom")
        self.assertEqual(actual["hexagrams"], expected["hexagrams"])
        self.assertEqual(actual["moving_positions"], [1, 4])
        self.assertEqual(actual["input"]["direction"], "top-to-bottom")

    def test_invalid_values_lengths_types_and_direction(self):
        bad = [None, [], [7] * 5, [7] * 7, [0, 1, 2, 3, 1, 2], [7] * 5 + [10],
               [True, 7, 8, 9, 7, 8], [6.0, 7, 8, 9, 7, 8], ["6", 7, 8, 9, 7, 8]]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                iching.build_result(value)
        with self.assertRaises(ValueError):
            iching.build_result([7] * 6, direction="guess")
        for bits in ("11111", "111112", [True, 1, 1, 1, 1, 1], [1, 0, 0, 1, 1]):
            with self.assertRaises(ValueError):
                iching.hexagram(bits)

    def test_static_and_all_moving_special_text_targets(self):
        for values, expected_kind in (([7] * 6, "卦辞"), ([9] * 6, "用九"), ([6] * 6, "用六")):
            result = iching.build_result(values)
            self.assertEqual(result["reading"]["targets"][0]["kind"], expected_kind)
        result = iching.build_result([9, 9, 7, 7, 7, 7])
        self.assertEqual([t["position"] for t in result["reading"]["targets"] if t["primary"]], [2])
        result = iching.build_result([9, 9, 9, 9, 7, 7])
        self.assertEqual([t["position"] for t in result["reading"]["targets"] if t["primary"]], [5])


class MethodTests(unittest.TestCase):
    def test_coin_seeded_reproducibility_and_auditable_three_coins(self):
        values, record = iching.coin_cast(0)
        self.assertEqual((values, record), iching.coin_cast(0))
        self.assertTrue(record["seed_provided"])
        self.assertEqual(record["seed"], 0)
        self.assertEqual(len(record["coin_values_bottom_to_top"]), 6)
        for value, row in zip(values, record["coin_values_bottom_to_top"]):
            self.assertEqual(len(row), 3)
            self.assertTrue(set(row) <= {2, 3})
            self.assertEqual(value, sum(row))

    def test_coin_no_seed_uses_system_random_and_records_complete_replay(self):
        class FakeSystem:
            def getrandbits(self, width):
                self.assertion = width
                return 1
        with patch.object(iching.random, "SystemRandom", return_value=FakeSystem()) as factory:
            values, record = iching.coin_cast()
        factory.assert_called_once()
        self.assertEqual(values, [9] * 6)
        self.assertIsNone(record["seed"])
        self.assertFalse(record["seed_provided"])
        self.assertEqual(record["rng"], "system_random")
        self.assertEqual(record["coin_values_bottom_to_top"], [[3, 3, 3]] * 6)
        original = iching.build_result(values, method_record=record)
        replay = iching.build_result(record["line_sums_bottom_to_top"])
        self.assertEqual(original["hexagrams"], replay["hexagrams"])

    def test_coin_model_covers_eight_three_coin_combinations(self):
        import itertools
        counts = {6: 0, 7: 0, 8: 0, 9: 0}
        for row in itertools.product((2, 3), repeat=3):
            counts[sum(row)] += 1
        self.assertEqual(counts, {6: 1, 7: 3, 8: 3, 9: 1})

    def test_meihua_two_numbers_and_three_numbers_have_distinct_rules(self):
        values, record = iching.meihua_cast([2, 3])
        result = iching.build_result(values)
        self.assertEqual(result["hexagrams"]["base"]["full_name"], "泽火革")
        self.assertEqual(result["moving_positions"], [5])
        values, record = iching.meihua_cast([2, 3, 1])
        result = iching.build_result(values)
        self.assertEqual(result["hexagrams"]["base"]["full_name"], "泽火革")
        self.assertEqual(result["hexagrams"]["changed"]["full_name"], "泽山咸")
        self.assertEqual(result["moving_positions"], [1])

    def test_meihua_zero_remainders_use_eight_and_six(self):
        for inputs in ([8, 16, 12], [0, 0], [24, 24]):
            values, record = iching.meihua_cast(inputs)
            result = iching.build_result(values)
            self.assertEqual(record["computed"]["upper_number"], 8)
            self.assertEqual(record["computed"]["lower_number"], 8)
            self.assertEqual(result["hexagrams"]["base"]["name"], "坤")
            self.assertEqual(result["moving_positions"], [6])
            self.assertEqual(result["hexagrams"]["changed"]["full_name"], "山地剥")

    def test_meihua_rejects_ambiguous_numbers(self):
        for values in (None, [], [1], [1, 2, 3, 4], [-1, 2], [1.5, 2], [True, 2]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                iching.meihua_cast(values)


class NajiaTests(unittest.TestCase):
    def test_golden_pi_palace_rows_and_relatives(self):
        result = iching.build_result(static_values("000111"), include_najia=True)["najia"]
        self.assertEqual(result["palace"], {"name": "乾", "element": "金", "stage": "三世",
                                            "shi_position": 3, "ying_position": 6})
        rows = result["base_rows_bottom_to_top"]
        self.assertEqual([r["stem_branch"] for r in rows], ["乙未", "乙巳", "乙卯", "壬午", "壬申", "壬戌"])
        self.assertEqual([r["relative"] for r in rows], ["父母", "官鬼", "妻财", "官鬼", "兄弟", "父母"])
        self.assertEqual([r["position"] for r in rows if r["shi"]], [3])
        self.assertEqual([r["position"] for r in rows if r["ying"]], [6])

    def test_golden_returning_soul_does_not_use_upper_trigram_palace(self):
        result = iching.build_result(static_values("111101"), include_najia=True)["najia"]
        self.assertEqual(result["palace"]["name"], "乾")
        self.assertEqual(result["palace"]["stage"], "归魂")
        self.assertEqual(result["palace"]["shi_position"], 3)
        self.assertEqual([r["stem_branch"] for r in result["base_rows_bottom_to_top"]],
                         ["甲子", "甲寅", "甲辰", "己酉", "己未", "己巳"])
        result = iching.build_result(static_values("000101"), include_najia=True)["najia"]
        self.assertEqual(result["palace"]["name"], "乾")
        self.assertEqual(result["palace"]["stage"], "游魂")
        self.assertEqual(result["palace"]["shi_position"], 4)

    def test_changed_relatives_keep_original_palace(self):
        # 乾初、二、四、五爻变为艮；变卦本身属土，但六亲仍按原乾金宫。
        result = iching.build_result([9, 9, 7, 9, 9, 7], include_najia=True)
        self.assertEqual(result["hexagrams"]["changed"]["name"], "艮")
        rows = result["najia"]["changed_rows_bottom_to_top"]
        self.assertEqual((rows[0]["stem_branch"], rows[0]["relative"]), ("丙辰", "父母"))
        self.assertEqual((rows[2]["stem_branch"], rows[2]["relative"]), ("丙申", "兄弟"))
        self.assertEqual([r["position"] for r in rows if r["corresponds_to_moving_line"]], [1, 2, 4, 5])
        self.assertEqual(result["najia"]["status"], "structural_only")
        self.assertIn("六神", result["najia"]["not_calculated"])

    def test_all_palaces_have_eight_unique_stages_and_opposite_positions(self):
        for name in "乾兑离震巽坎艮坤":
            group = [p for p in iching.PALACES.values() if p["name"] == name]
            self.assertEqual(len(group), 8)
            self.assertEqual({p["stage"] for p in group}, set(iching.PALACE_STAGES))
            for entry in group:
                self.assertEqual(abs(entry["shi_position"] - entry["ying_position"]), 3)


class OutputAndCliTests(unittest.TestCase):
    def cli(self, *args, cwd=None):
        result = subprocess.run([sys.executable, "-X", "utf8", "-B", str(SCRIPT), *args],
                                capture_output=True, encoding="utf-8", check=False, cwd=cwd)
        return result

    def test_probe_and_help_work_without_writing(self):
        result = self.cli("--probe")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["hexagrams"], 64)
        result = self.cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("--output", result.stdout)

    def test_explicit_output_must_be_absolute_and_overwrite_requires_path(self):
        for args in (("--lines", "7,7,7,7,7,7", "--overwrite"),
                     ("--lines", "7,7,7,7,7,7", "--output", "relative.json")):
            result = self.cli(*args)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(json.loads(result.stdout)["ok"])
            self.assertEqual(result.stderr, "")

    def test_actual_cast_without_output_returns_complete_json_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as scratch:
            cases = [("--lines", "6,7,8,9,7,8", "--najia"),
                     ("--method", "coins", "--seed", "0"), ("--method", "coins"),
                     ("--method", "meihua", "--numbers", "2", "3", "1")]
            for args in cases:
                with self.subTest(args=args):
                    result = self.cli(*args, cwd=scratch)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    value = json.loads(result.stdout)
                    self.assertTrue(value["ok"])
                    self.assertEqual(len(value["lines_bottom_to_top"]), 6)
                    self.assertEqual(set(value["hexagrams"]), {"base", "changed", "nuclear", "opposite", "reversed"})
                    self.assertNotIn("output_path", value)
                    if value["method"]["method"] == "three_coins":
                        record = value["method"]
                        self.assertEqual(record["line_sums_bottom_to_top"],
                                         [sum(row) for row in record["coin_values_bottom_to_top"]])
                        self.assertEqual(record["seed"], 0 if "--seed" in args else None)
                    self.assertEqual(list(Path(scratch).iterdir()), [])

    def test_protected_output_paths_are_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as scratch:
            paths = [SCRIPT.parent / "secret.json", ROOT / "runtime" / "secret.json",
                     Path(scratch) / "cache" / "secret.json", Path(scratch) / "engine-cache" / "secret.json"]
            for path in paths:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    iching.validate_output_path(path)
            with patch.dict(os.environ, {"MINGXUE_RESOURCE_DIR": scratch}):
                with self.assertRaises(ValueError):
                    iching.validate_output_path(Path(scratch) / "secret.json")

    def test_seeded_cast_stdout_matches_file_and_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch) / "case.json"
            result = self.cli("--method", "coins", "--seed", "0", "--najia", "--output", str(target))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output, json.loads(target.read_text(encoding="utf-8")))
            self.assertEqual(output["method"]["seed"], 0)
            old_content = target.read_bytes()
            result = self.cli("--method", "coins", "--seed", "1", "--output", str(target))
            self.assertEqual(result.returncode, 2)
            self.assertEqual(target.read_bytes(), old_content)
            result = self.cli("--method", "coins", "--seed", "1", "--output", str(target), "--overwrite")
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertNotEqual(target.read_bytes(), old_content)

    def test_cli_manual_space_or_comma_and_catalog(self):
        with tempfile.TemporaryDirectory() as scratch:
            for tokens in (("6,7,8,9,7,8",), ("6", "7", "8", "9", "7", "8")):
                target = Path(scratch) / "manual.json"
                result = self.cli("--lines", *tokens, "--output", str(target), "--overwrite")
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertEqual(json.loads(result.stdout)["moving_positions"], [1, 4])
            result = self.cli("--catalog", "--output", str(Path(scratch) / "catalog.json"))
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual(len(json.loads(result.stdout)["hexagrams"]), 64)
            self.assertEqual(len(json.loads(result.stdout)["trigrams"]), 8)

    def test_cli_conflicting_inputs_and_invalid_values_return_json(self):
        with tempfile.TemporaryDirectory() as scratch:
            cases = [("--method", "coins", "--lines", "7,7,7,7,7,7"),
                     ("--method", "manual", "--seed", "0", "--lines", "7,7,7,7,7,7"),
                     ("--method", "meihua", "--numbers", "2", "3", "--direction", "top-to-bottom"),
                     ("--lines", "6,7,8,9,7,0"), ("--unknown",)]
            for args in cases:
                with self.subTest(args=args):
                    result = self.cli(*args, "--output", str(Path(scratch) / "invalid.json"))
                    self.assertEqual(result.returncode, 2)
                    self.assertFalse(json.loads(result.stdout)["ok"])
                    self.assertFalse((Path(scratch) / "invalid.json").exists())


if __name__ == "__main__":
    unittest.main()
