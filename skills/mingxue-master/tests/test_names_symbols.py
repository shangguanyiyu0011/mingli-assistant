"""Independent arithmetic examples, date conventions and reproducible draws."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", HERE))
if not (SKILL / "scripts/name_analysis.py").is_file():
    SKILL = HERE / "package/mingxue-master"
sys.path.insert(0, str(SKILL / "scripts"))
import name_analysis as names
import symbolic


class NameArithmeticTests(unittest.TestCase):
    def test_all_four_surname_given_structures(self):
        # Expected values calculated independently, ordered 天/人/地/外/总.
        examples = (("李", "明", [7, 8], [8, 15, 9, 2, 15]),
                    ("李", "明华", [7, 8, 14], [8, 15, 22, 15, 29]),
                    ("欧阳", "修", [15, 17, 10], [32, 27, 11, 16, 42]),
                    ("欧阳", "明华", [15, 17, 8, 14], [32, 25, 22, 29, 54]))
        for surname, given, strokes, expected in examples:
            with self.subTest(surname=surname, given=given):
                result = names.analyze_name(surname, given, strokes)
                actual = [result["five_grids"][k]["number"] for k in ("天格", "人格", "地格", "外格", "总格")]
                self.assertEqual(actual, expected)
                self.assertEqual(result["strokes"][len(surname)]["part"], "given")

    def test_three_talents_uses_tails_with_zero_as_water(self):
        self.assertEqual([names.number_symbol(n)["element"] for n in range(1, 11)],
                         ["木", "木", "火", "火", "土", "土", "金", "金", "水", "水"])
        self.assertEqual(names.number_symbol(100)["element"], "水")
        self.assertEqual(names.number_symbol(11)["element"], "木")
        result = names.analyze_name("李", "明华", [7, 8, 14])
        self.assertEqual(result["three_talents"]["label"], "金土木")
        self.assertEqual(result["three_talents"]["adjacent_relations"],
                         [{"from": "天格", "to": "人格", "relation": "后生前"},
                          {"from": "人格", "to": "地格", "relation": "后克前"}])

    def test_explicit_strokes_remain_user_supplied_and_kangxi_is_not_guessed(self):
        unresolved = names.analyze_name("李", "明", None, stroke_scheme="kangxi")
        self.assertEqual(unresolved["status"], "needs_input")
        self.assertIsNone(unresolved.get("five_grids"))
        result = names.analyze_name("陈", "明", [16, 8], stroke_standard="康熙（用户指定）", stroke_reference="用户字典第42页")
        self.assertEqual(result["stroke_provenance"]["source"], "user_supplied")
        self.assertFalse(result["stroke_provenance"]["dictionary_verified"])
        self.assertEqual(result["stroke_provenance"]["standard_label"], "康熙（用户指定）")
        self.assertEqual(result["name"], "陈明")  # No silent traditional conversion.

    def test_name_structure_and_non_han_boundaries(self):
        for surname, given in (("", "明"), ("李王张", "明"), ("李", "明华华"), ("Li", "明"), ("李", "-"), (None, "明")):
            with self.subTest(surname=surname, given=given), self.assertRaises(ValueError):
                names.analyze_name(surname, given, [1, 2])
        self.assertEqual(names.analyze_name("𠀀", "一", [1, 1])["five_grids"]["总格"]["number"], 2)

    def test_counts_match_each_occurrence_and_have_real_boundaries(self):
        for values in ([1], [1, 2, 3], [0, 8], [-1, 8], [101, 8], [True, 8], [1.5, 8], "7,,8", "７,8", "7.0,8", "7, 8", {}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                names.analyze_name("李", "明", values)
        result = names.analyze_name("一", "龘", [1, 100])
        self.assertEqual(result["five_grids"]["总格"]["number"], 101)  # No silent 81-cycle wrap.
        with self.assertRaisesRegex(ValueError, "conflicting"):
            names.analyze_name("李", "李", [7, 8])
        self.assertEqual(names.analyze_name("李", "李", [7, 7])["sound_form_meaning"]["repeated_characters"], ["李"])

    def test_sound_and_meaning_stay_user_supplied(self):
        result = names.analyze_name("单", "明", [12, 8], pronunciation="shàn míng", meaning_note="明：明亮")
        self.assertEqual(result["sound_form_meaning"]["pronunciation_source"], "user_supplied")
        self.assertEqual(result["sound_form_meaning"]["scope"], "textual_analysis_only")
        self.assertEqual(result["sound_form_meaning"]["pronunciation"], "shàn míng")


class NumerologyTests(unittest.TestCase):
    def test_master_reduction_and_trace(self):
        self.assertEqual(symbolic.reduce_number(29), {"number": 11, "trace": [29, 11], "is_master": True})
        self.assertEqual(symbolic.reduce_number(38, ()), {"number": 2, "trace": [38, 11, 2], "is_master": False})
        self.assertEqual(symbolic.reduce_number(33)["number"], 33)
        self.assertEqual(symbolic.reduce_number(33, (11, 22))["number"], 6)
        for bad in (True, -1, 2.0, "11"):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                symbolic.reduce_number(bad)

    def test_date_fixed_examples_and_personal_year(self):
        result = symbolic.numerology("1990-06-15", year=2026)
        self.assertEqual(result["life_path"]["reduction"]["trace"], [31, 4])
        self.assertEqual(result["personal_year"]["reduction"]["trace"], [22])
        self.assertEqual(symbolic.numerology("2000-01-08")["life_path"]["reduction"]["number"], 11)
        self.assertEqual(symbolic.numerology("2000-09-29")["life_path"]["reduction"]["number"], 22)
        self.assertEqual(symbolic.numerology("1999-01-04")["life_path"]["reduction"]["number"], 33)

    def test_methods_are_explicit_and_can_differ(self):
        all_digits = symbolic.numerology("1999-01-04")
        component = symbolic.numerology("1999-01-04", method="component")
        self.assertEqual(all_digits["life_path"]["reduction"]["number"], 33)
        self.assertEqual(component["life_path"]["reduction"]["number"], 6)
        self.assertEqual(component["life_path"]["components"]["year"]["trace"], [1999, 28, 10, 1])
        self.assertEqual(component["convention"]["method"], "component")

    def test_actual_dates_leap_days_and_target_year_bounds(self):
        for value in ("2023-02-29", "1900-02-29", "0000-01-01", "2024-13-01", "2024-1-1", "20240101", "２０２４-01-01", None):
            with self.subTest(date=value), self.assertRaises(ValueError):
                symbolic.numerology(value)
        self.assertEqual(symbolic.numerology("2000-02-29", year=2023)["personal_year"]["year"], 2023)
        for year in (0, 10000, True, 2026.0):
            with self.subTest(year=year), self.assertRaises(ValueError):
                symbolic.numerology("2000-02-29", year=year)

    def test_pythagorean_mapping_is_explicit_ascii_and_no_pinyin_guess(self):
        result = symbolic.numerology("1990-06-15", latin_name="Jane Doe")["name_expression"]
        self.assertEqual(result["values"], [1, 1, 5, 5, 4, 6, 5])
        self.assertEqual(result["sum"], 27)
        self.assertEqual(result["reduction"]["number"], 9)
        self.assertEqual(result["mapping"]["Z"], 8)
        for value in ("张明", "José", "A1", "-", "", "İ"):
            with self.subTest(name=value), self.assertRaises(ValueError):
                symbolic.numerology("1990-06-15", latin_name=value)


class TarotTests(unittest.TestCase):
    def test_all_78_cards_are_unique_complete_and_named(self):
        self.assertEqual(len(symbolic.DECK), 78)
        self.assertEqual(len(symbolic.CARD_INDEX), 78)
        self.assertEqual(len({c["name"] for c in symbolic.DECK}), 78)
        self.assertEqual(sum(c["arcana"] == "major" for c in symbolic.DECK), 22)
        for suit in symbolic.SUITS:
            self.assertEqual(sum(c.get("suit") == suit for c in symbolic.DECK), 14)
        self.assertEqual(symbolic.CARD_INDEX["major-08"]["name"], "力量")
        self.assertEqual(symbolic.CARD_INDEX["major-11"]["name"], "正义")

    def test_seed_replays_and_positions_match_every_spread(self):
        for spread, (_, positions) in symbolic.SPREADS.items():
            with self.subTest(spread=spread):
                first = symbolic.tarot(spread, seed=42)
                second = symbolic.tarot(spread, seed=42)
                self.assertEqual(first, second)
                self.assertEqual(first["randomness"]["seed"], "42")
                self.assertEqual(first["randomness"]["algorithm"], "sha256-counter-rejection-v1")
                self.assertEqual(first["positions"], list(positions))
                self.assertEqual([c["position"] for c in first["cards"]], list(positions))
                self.assertEqual([c["position_index"] for c in first["cards"]], list(range(1, len(positions) + 1)))
                self.assertEqual(len({c["id"] for c in first["cards"]}), len(positions))

    def test_versioned_draw_has_a_fixed_reproduction_vector(self):
        result = symbolic.tarot("three", seed=42)
        self.assertEqual([(card["id"], card["orientation"]) for card in result["cards"]],
                         [("major-10", "upright"), ("cups-knight", "upright"), ("wands-queen", "upright")])
        self.assertEqual(result["randomness"]["counter_blocks_used"], 6)

    def test_integer_sampler_rejects_out_of_range_tail_before_modulo(self):
        # 2^256 is not divisible by 78: the all-FF hash lies in the rejected
        # tail, so reducing it modulo 78 directly would introduce bias.
        fake_hashes = [SimpleNamespace(digest=lambda: b"\xff" * 32), SimpleNamespace(digest=lambda: b"\x00" * 32)]
        with patch.object(symbolic.hashlib, "sha256", side_effect=fake_hashes) as hasher:
            rng = symbolic.CounterRandom(0)
            self.assertEqual(rng.randbelow(78), 0)
        self.assertEqual(hasher.call_count, 2)
        self.assertEqual(rng.counter, 2)

    def test_generated_seed_is_recorded_and_can_replay_cards(self):
        with patch.object(symbolic.secrets, "randbits", return_value=123456789) as entropy:
            first = symbolic.tarot("celtic")
        entropy.assert_called_once_with(128)
        replay = symbolic.tarot("celtic", seed=int(first["randomness"]["seed"]))
        self.assertEqual(first["cards"], replay["cards"])
        self.assertEqual(first["randomness"]["source"], "virtual_draw")
        self.assertEqual(first["randomness"]["seed_origin"], "generated_by_secrets")

    def test_manual_cards_have_no_invented_random_draw(self):
        with patch.object(symbolic.secrets, "randbits", side_effect=AssertionError("must not draw")):
            result = symbolic.tarot("three", cards="major-00:upright,cups-02:reversed,swords-ace:upright")
        self.assertEqual(result["randomness"], {"source": "user_supplied_cards", "seed": None, "algorithm": None})
        self.assertEqual(result["cards"][1]["orientation_label"], "逆位")
        self.assertIn("受阻", result["cards"][1]["symbolic_lens"])

    def test_manual_card_count_ids_duplicates_and_input_conflicts(self):
        for text in ("major-00:upright", "major-00:upright,major-00:reversed,cups-02:upright",
                     "major-99:upright,cups-02:upright,swords-ace:upright", "major-00:up,cups-02:upright,swords-ace:upright", ""):
            with self.subTest(cards=text), self.assertRaises(ValueError):
                symbolic.tarot("three", cards=text)
        for kwargs in ({"seed": 1}, {"upright_only": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                symbolic.tarot("single", cards="major-00:upright", **kwargs)

    def test_orientation_option_and_seed_boundaries(self):
        for seed in (0, 2**256 - 1):
            result = symbolic.tarot("celtic", seed=seed, upright_only=True)
            self.assertTrue(all(c["orientation"] == "upright" for c in result["cards"]))
        for seed in (-1, 2**256, True, 1.2, "42"):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                symbolic.tarot(seed=seed)
        orientations = {c["orientation"] for seed in range(10) for c in symbolic.tarot("celtic", seed=seed)["cards"]}
        self.assertEqual(orientations, {"upright", "reversed"})


class CliAndOutputTests(unittest.TestCase):
    def run_cli(self, script, *arguments):
        run = subprocess.run([sys.executable, "-X", "utf8", "-B", str(SKILL / "scripts" / script), *arguments],
                             capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(run.stderr, "", run.stderr)
        return run, json.loads(run.stdout)

    def test_probe_has_no_network_or_entropy_dependency(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")), \
                patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden")), \
                patch.object(symbolic.secrets, "randbits", side_effect=AssertionError("probe must not draw")):
            self.assertTrue(names.probe()["self_check"])
            self.assertEqual(symbolic.probe()["tarot"]["unique_ids"], 78)
        for script in ("name_analysis.py", "symbolic.py"):
            run, result = self.run_cli(script, "--probe")
            self.assertEqual(run.returncode, 0)
            self.assertEqual(result["network"], "not_used")

    def test_success_and_errors_are_json_stdout(self):
        run, result = self.run_cli("name_analysis.py", "--surname", "李", "--given", "明", "--strokes", "7,8")
        self.assertEqual(run.returncode, 0)
        self.assertEqual(result["five_grids"]["外格"]["number"], 2)
        for script, args in (("name_analysis.py", ["--surname", "李"]),
                             ("symbolic.py", ["numerology", "--date", "2023-02-29"]),
                             ("symbolic.py", ["tarot", "--seed", "oops"]), ("symbolic.py", ["--unknown"]),
                             ("symbolic.py", [])):
            with self.subTest(script=script, args=args):
                run, result = self.run_cli(script, *args)
                self.assertEqual(run.returncode, 2)
                self.assertEqual(result["status"], "error")
        run, result = self.run_cli("symbolic.py", "--help")
        self.assertEqual(run.returncode, 0)
        self.assertIn("help", result)

    def test_saved_path_is_absolute_explicit_and_stdout_matches_file(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "reading.json"
            run, result = self.run_cli("symbolic.py", "tarot", "--spread", "single", "--seed", "42", "--output", str(destination))
            self.assertEqual(run.returncode, 0)
            self.assertTrue(Path(result["output_path"]).is_absolute())
            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), result)
            original = destination.read_bytes()
            run, result = self.run_cli("name_analysis.py", "--probe", "--output", str(destination))
            self.assertEqual(run.returncode, 2)
            self.assertEqual(destination.read_bytes(), original)

    def test_protected_output_paths_and_relative_paths_are_rejected(self):
        for module in (names, symbolic):
            for target in ("relative.json", str(SKILL / "forbidden.json"), str(HERE / "runtime" / "forbidden.json"),
                           str(HERE / "engine-cache" / "forbidden.json")):
                with self.subTest(module=module.__name__, target=target), self.assertRaises(ValueError):
                    with redirect_stdout(io.StringIO()):
                        module.write_result({"value": 1}, target)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"MINGXUE_RESOURCE_DIR": directory}):
            for module in (names, symbolic):
                with self.subTest(module=module.__name__), self.assertRaises(ValueError):
                    module.write_result({"value": 1}, str(Path(directory) / "forbidden.json"))


if __name__ == "__main__":
    unittest.main()
