"""Fixed oracle fixtures, input boundaries and vector layout contracts."""
import hashlib
import io
import itertools
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
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", HERE))
if not (SKILL / "scripts/oracles.py").is_file():
    SKILL = HERE / "package/mingxue-master"
sys.path.insert(0, str(SKILL / "scripts"))
import oracles


class LenormandTests(unittest.TestCase):
    def test_complete_numbered_catalog_and_chinese_keywords(self):
        self.assertEqual(len(oracles.LENORMAND_CARDS), 36)
        self.assertEqual([c["number"] for c in oracles.LENORMAND_CARDS], list(range(1, 37)))
        self.assertEqual(len({c["id"] for c in oracles.LENORMAND_CARDS}), 36)
        self.assertEqual(oracles.LENORMAND_CARDS[0]["name"], "骑士")
        self.assertEqual(oracles.LENORMAND_CARDS[35]["name"], "十字架")
        self.assertTrue(all(c["name"] and len(c["keywords"]) == 3 for c in oracles.LENORMAND_CARDS))

    def test_manual_pair_order_and_no_invented_randomness(self):
        with patch.object(oracles.secrets, "randbits", side_effect=AssertionError("manual cards must not draw")):
            result = oracles.calculate("lenormand", {"spread": "pair", "cards": [1, 27]})
        self.assertEqual([c["number"] for c in result["cards"]], [1, 27])
        self.assertEqual([c["label"] for c in result["cards"]], ["左位", "右位"])
        self.assertEqual(result["randomness"], {"source": "user_supplied_cards", "seed": None, "algorithm": None})
        self.assertFalse(result["rules"]["reversals"])

    def test_every_spread_has_unique_cards_and_explicit_positions(self):
        for spread, count in (("pair", 2), ("three", 3), ("nine", 9), ("grand", 36)):
            with self.subTest(spread=spread):
                result = oracles.calculate("lenormand", {"spread": spread, "seed": 42})
                self.assertEqual(len(result["cards"]), count)
                self.assertEqual(len({c["number"] for c in result["cards"]}), count)
                self.assertEqual([c["index"] for c in result["cards"]], list(range(1, count + 1)))
                self.assertEqual(len({(c["row"], c["column"]) for c in result["cards"]}), count)
                self.assertTrue(all(c["card_id"].startswith("lenormand-") and c["position_id"].startswith("p") for c in result["cards"]))

    def test_nine_grid_groups_and_selected_center(self):
        result = oracles.calculate("lenormand", {"spread": "nine", "cards": list(range(1, 10)), "significator": 5})
        self.assertEqual(result["groups"]["rows"], [[1, 2, 3], [4, 5, 6], [7, 8, 9]])
        self.assertEqual(result["groups"]["columns"], [[1, 4, 7], [2, 5, 8], [3, 6, 9]])
        self.assertEqual(result["groups"]["diagonals"], [[1, 5, 9], [3, 5, 7]])
        self.assertEqual(result["significator"]["position_index"], 5)
        self.assertEqual(len(result["significator"]["neighbors"]), 8)

    def test_significator_is_not_forced_into_a_small_draw(self):
        result = oracles.calculate("lenormand", {"spread": "pair", "cards": [1, 2], "significator": 28})
        self.assertEqual(result["significator"], {"card_number": 28, "status": "not_in_spread"})
        self.assertEqual([c["number"] for c in result["cards"]], [1, 2])

    def test_grand_layouts_and_houses_are_position_numbers_not_drawn_numbers(self):
        manual = list(range(36, 0, -1))
        nine = oracles.calculate("lenormand", {"spread": "grand", "cards": manual, "layout": "9x4"})
        eight = oracles.calculate("lenormand", {"spread": "grand", "cards": manual, "layout": "8x4+4"})
        self.assertEqual((nine["spread"]["rows"], nine["spread"]["columns"]), (4, 9))
        self.assertEqual((eight["spread"]["rows"], eight["spread"]["columns"]), (5, 8))
        self.assertEqual([(c["row"], c["column"]) for c in eight["cards"][-4:]], [(5, 3), (5, 4), (5, 5), (5, 6)])
        self.assertEqual(nine["cards"][0]["house_number"], 1)
        self.assertEqual(nine["cards"][0]["house_name"], "骑士")
        self.assertEqual(nine["cards"][0]["number"], 36)

    def test_seed_fixed_fixture_and_replay(self):
        result = oracles.calculate("lenormand", {"spread": "nine", "seed": 42})
        self.assertEqual([c["number"] for c in result["cards"]], [32, 29, 22, 18, 21, 33, 23, 7, 3])
        self.assertEqual(result["randomness"]["seed"], "42")
        self.assertEqual(result["randomness"]["counter_blocks_used"], 9)
        self.assertEqual(result["cards"], oracles.calculate("lenormand", result["input"])["cards"])

    def test_invalid_manual_values_and_combined_seed_are_rejected(self):
        for cards in ([], [1], [1, 1], [0, 2], [1, 37], [True, 2], [1.0, 2], ["1", 2], "1,2"):
            with self.subTest(cards=cards), self.assertRaises(ValueError):
                oracles.calculate("lenormand", {"spread": "pair", "cards": cards})
        with self.assertRaises(ValueError):
            oracles.calculate("lenormand", {"spread": "pair", "cards": [1, 2], "seed": 42})

    def test_invalid_spread_layout_question_and_significator(self):
        for extra in ({"spread": "single"}, {"layout": "9x4"}, {"layout": False}, {"layout": []},
                      {"significator": 0}, {"significator": 37}, {"significator": True}, {"question": 1}, {"question": "a" * 2001}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                oracles.calculate("lenormand", {"spread": "pair", "cards": [1, 2], **extra})

    def test_result_mutations_do_not_change_the_catalog_or_visual_copy(self):
        first = oracles.calculate("lenormand", {"spread": "pair", "cards": [1, 2]})
        first["cards"][0]["keywords"].append("changed")
        self.assertNotIn("changed", first["visual"]["cells"][0]["keywords"])
        second = oracles.calculate("lenormand", {"spread": "pair", "cards": [1, 2]})
        self.assertNotIn("changed", second["cards"][0]["keywords"])


class GeomancyTests(unittest.TestCase):
    def test_all_16_figures_cover_the_four_line_binary_space(self):
        expected = {"".join(bits) for bits in itertools.product("12", repeat=4)}
        self.assertEqual(set(oracles.FIGURE_CATALOG), expected)
        self.assertEqual(oracles.FIGURE_CATALOG["1121"]["latin_name"], "Puer")
        self.assertEqual(oracles.FIGURE_CATALOG["1211"]["latin_name"], "Puella")

    def test_nontrivial_fixed_shield_fixture(self):
        result = oracles.calculate("geomancy", {"mothers": ["1112", "1211", "2122", "2211"]})
        actual = {f["id"]: f["code"] for f in result["shield"]["figures"]}
        self.assertEqual(actual, {"M1": "1112", "M2": "1211", "M3": "2122", "M4": "2211",
            "D1": "1122", "D2": "1212", "D3": "1121", "D4": "2121", "N1": "2121", "N2": "2111",
            "N3": "2112", "N4": "1222", "WR": "2212", "WL": "1112", "J": "1122", "R": "2212"})
        self.assertEqual(result["randomness"]["source"], "user_supplied_mothers")
        self.assertIsNone(result["randomness"]["seed"])

    def test_daughter_transposition_and_top_down_element_order(self):
        result = oracles.calculate("geomancy", {"mothers": ["1111", "2222", "1212", "2121"]})
        figures = {f["id"]: f for f in result["shield"]["figures"]}
        self.assertEqual([figures[k]["code"] for k in ("D1", "D2", "D3", "D4")], ["1212", "1221", "1212", "1221"])
        self.assertEqual([line["element"] for line in figures["M1"]["lines"]], ["火", "风", "水", "土"])
        self.assertEqual(figures["D2"]["derivation"], {"operation": "transpose", "parents": ["M1", "M2", "M3", "M4"], "source_line": 2})

    def test_parity_addition_truth_table_identity_and_commutativity(self):
        self.assertEqual(oracles.add_figures("1111", "1111"), "2222")
        self.assertEqual(oracles.add_figures("1111", "2222"), "1111")
        for first, second in itertools.product(oracles.FIGURE_CATALOG, repeat=2):
            self.assertEqual(oracles.add_figures(first, second), oracles.add_figures(second, first))
            self.assertEqual(oracles.add_figures(first, "2222"), first)
            self.assertEqual(oracles.add_figures(first, first), "2222")

    def test_judge_even_point_invariant_across_a_broad_fixed_matrix(self):
        for first, second in itertools.product(oracles.FIGURE_CATALOG, repeat=2):
            figures = oracles.derive_shield([first, second, first[::-1], second[::-1]])
            self.assertEqual(sum(map(int, figures["J"])) % 2, 0)
            self.assertEqual(figures["R"], oracles.add_figures(first, figures["J"]))

    def test_15_and_16_figure_variants_are_kept_distinct(self):
        mothers = ["1111", "2222", "1212", "2121"]
        short = oracles.calculate("geomancy", {"mothers": mothers, "shield_size": 15})
        full = oracles.calculate("geomancy", {"mothers": mothers, "shield_size": 16})
        self.assertEqual(len(short["shield"]["figures"]), 15)
        self.assertEqual(len(full["shield"]["figures"]), 16)
        self.assertIsNone(short["shield"]["reconciler_id"])
        self.assertNotIn("R", [f["id"] for f in short["shield"]["figures"]])
        self.assertNotIn("R", short["house_chart"]["court_ids"])
        self.assertEqual(full["shield"]["reconciler_id"], "R")

    def test_real_point_counts_preserved_and_parity_used_without_entropy(self):
        counts = [[7, 8, 9, 10], [11, 12, 13, 14], [15, 16, 17, 18], [19, 20, 21, 22]]
        with patch.object(oracles.secrets, "randbits", side_effect=AssertionError("manual counts must not draw")):
            result = oracles.calculate("geomancy", {"point_counts": counts})
        self.assertEqual(result["initial_mothers"], ["1212"] * 4)
        self.assertEqual(result["input"]["point_counts"], counts)
        self.assertIsNone(result["input"]["mothers"])
        self.assertEqual(result["randomness"]["source"], "user_supplied_point_counts")
        self.assertEqual(oracles.calculate("geomancy", result["input"])["initial_mothers"], ["1212"] * 4)

    def test_seeded_mother_fixture_and_input_replay(self):
        result = oracles.calculate("geomancy", {"seed": 42})
        self.assertEqual(result["initial_mothers"], ["2212", "1221", "2112", "1212"])
        self.assertIsNone(result["input"]["mothers"])
        self.assertEqual(result["randomness"]["seed"], "42")
        self.assertEqual(result["randomness"]["counter_blocks_used"], 16)
        replay = oracles.calculate("geomancy", result["input"])
        self.assertEqual(result["shield"], replay["shield"])

    def test_house_maps_are_explicit_and_do_not_recalculate_the_shield(self):
        regular = oracles.calculate("geomancy", {"seed": 42, "house_mode": "sequential"})
        angular = oracles.calculate("geomancy", {"seed": 42, "house_mode": "agrippa"})
        self.assertEqual(regular["shield"], angular["shield"])
        self.assertEqual([h["source_figure"] for h in regular["house_chart"]["houses"]], list(oracles.ROLE_IDS[:12]))
        self.assertEqual([h["source_figure"] for h in angular["house_chart"]["houses"]],
                         ["M1", "D1", "N1", "M4", "D4", "N4", "M3", "D3", "N3", "M2", "D2", "N2"])
        houses = regular["house_chart"]["houses"]
        self.assertLess(houses[0]["x"], 310)
        self.assertGreater(houses[3]["y"], 310)
        self.assertLess(houses[9]["y"], 310)

    def test_invalid_mothers_counts_variants_and_mixed_inputs(self):
        bad = ({"mothers": []}, {"mothers": ["1111"] * 3}, {"mothers": ["1111", "2222", "1212", "0000"]},
               {"mothers": "1111,2222,1212,2121"}, {"point_counts": []}, {"point_counts": [[1, 2, 3, 0]] * 4},
               {"point_counts": [[1, 2, 3, True]] * 4}, {"point_counts": [[1, 2, 3, 1000001]] * 4},
               {"point_counts": [[1, 2, 3, 4.0]] * 4}, {"shield_size": True}, {"shield_size": 15.0},
               {"shield_size": 14}, {"house_mode": "unspecified"}, {"mothers": ["1111"] * 4, "seed": 42},
               {"mothers": ["1111"] * 4, "point_counts": [[1, 2, 3, 4]] * 4})
        for params in bad:
            with self.subTest(params=params), self.assertRaises(ValueError):
                oracles.calculate("geomancy", params)


class SharedOracleTests(unittest.TestCase):
    def test_required_schema_and_offline_probe(self):
        with patch.object(socket, "socket", side_effect=AssertionError("no network")), \
                patch.object(oracles.secrets, "randbits", side_effect=AssertionError("probe does not draw")):
            ready = oracles.probe()
        self.assertEqual(ready["network"], "not_used")
        for system in ("lenormand", "geomancy"):
            result = oracles.calculate(system, {"seed": 42})
            self.assertTrue({"system", "status", "input", "rules", "limitations", "randomness", "visual"} <= set(result))

    def test_generated_seed_is_recorded_and_replays_each_system(self):
        for system in ("lenormand", "geomancy"):
            with self.subTest(system=system), patch.object(oracles.secrets, "randbits", return_value=123456789) as entropy:
                first = oracles.calculate(system, {})
            entropy.assert_called_once_with(128)
            second = oracles.calculate(system, first["input"])
            field = "cards" if system == "lenormand" else "shield"
            self.assertEqual(first[field], second[field])
            self.assertEqual(first["randomness"]["seed"], "123456789")

    def test_seed_boundaries_and_decimal_strings(self):
        for system in ("lenormand", "geomancy"):
            for seed in (0, 2**256 - 1, "42"):
                self.assertEqual(oracles.calculate(system, {"seed": seed})["randomness"]["seed"], str(seed))
            for seed in (-1, 2**256, True, 1.5, "0042", "-1", "x"):
                with self.subTest(system=system, seed=seed), self.assertRaises(ValueError):
                    oracles.calculate(system, {"seed": seed})

    def test_rejection_sampling_does_not_reduce_the_biased_hash_tail(self):
        fake = [SimpleNamespace(digest=lambda: b"\xff" * 32), SimpleNamespace(digest=lambda: b"\x00" * 32)]
        with patch.object(oracles.hashlib, "sha256", side_effect=fake) as hashes:
            sampler = oracles._Sampler("lenormand", 0)
            self.assertEqual(sampler.below(36), 0)
        self.assertEqual(hashes.call_count, 2)

    def test_svg_xml_and_layout_bounds_for_every_layout(self):
        params = [{"spread": "pair"}, {"spread": "three"}, {"spread": "nine"},
                  {"spread": "grand", "layout": "9x4"}, {"spread": "grand", "layout": "8x4+4"}]
        for entry in params:
            result = oracles.calculate("lenormand", {**entry, "seed": 42, "question": "<script>bad</script>"})
            visual = result["visual"]
            xml = ET.fromstring(visual["svg"])
            self.assertEqual(len(xml.findall("{http://www.w3.org/2000/svg}g")), len(result["cards"]))
            self.assertNotIn("<script", visual["svg"])
            self.assertNotIn("bad", visual["svg"])
            for card in visual["cells"]:
                self.assertTrue(0 <= card["x"] < visual["width"])
                self.assertTrue(0 <= card["y"] < visual["height"])
                self.assertLessEqual(card["x"] + card["width"], visual["width"])
                self.assertLessEqual(card["y"] + card["height"], visual["height"])
        for size, mode in itertools.product((15, 16), ("sequential", "agrippa")):
            result = oracles.calculate("geomancy", {"seed": 42, "shield_size": size, "house_mode": mode})
            for kind in ("shield", "house"):
                ET.fromstring(result["visual"][kind]["svg"])
            for node in result["visual"]["shield"]["nodes"]:
                self.assertTrue(node["width"] / 2 <= node["x"] <= 960 - node["width"] / 2)
                self.assertLessEqual(node["y"] + node["height"], result["visual"]["shield"]["height"])
                self.assertEqual([len(row) for row in node["dot_rows"]], node["points"])

    def test_question_does_not_change_a_seeded_result(self):
        for system in ("lenormand", "geomancy"):
            a = oracles.calculate(system, {"seed": 42, "question": "a"})
            b = oracles.calculate(system, {"seed": 42, "question": "b"})
            field = "cards" if system == "lenormand" else "shield"
            self.assertEqual(a[field], b[field])

    def test_unknown_fields_and_nonobject_params_fail(self):
        for system in ("lenormand", "geomancy"):
            for params in (None, [], "seed=42", {"unknown": 1}, {1: "value"}):
                with self.subTest(system=system, params=params), self.assertRaises(ValueError):
                    oracles.calculate(system, params)

    def test_cli_json_probe_error_duplicate_keys_and_help(self):
        def run(*args):
            proc = subprocess.run([sys.executable, "-X", "utf8", "-B", str(SKILL / "scripts/oracles.py"), *args],
                capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(proc.stderr, "")
            result = json.loads(proc.stdout)
            self.assertTrue({"system", "status", "input", "rules", "limitations"} <= set(result))
            return proc, result
        for args in (("--probe",), ("--help",), ("lenormand", "--params", '{"spread":"pair","cards":[1,27]}')):
            proc, result = run(*args)
            self.assertEqual(proc.returncode, 0)
        for args in (("geomancy", "--params", "[]"), ("lenormand", "--params", '{"seed":1,"seed":2}'), ("--unknown",)):
            proc, result = run(*args)
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(result["status"], "error")

    def test_explicit_output_new_path_guard_and_no_overwrite(self):
        result = oracles.calculate("lenormand", {"spread": "pair", "cards": [1, 2]})
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "reading.json"
            with patch("sys.stdout", new_callable=io.StringIO) as output:
                oracles._write_result(result, str(target))
            self.assertEqual(json.loads(output.getvalue()), json.loads(target.read_text(encoding="utf-8")))
            self.assertTrue(Path(json.loads(output.getvalue())["output_path"]).is_absolute())
            before = target.read_bytes()
            with self.assertRaises(ValueError):
                oracles._write_result(result, str(target))
            self.assertEqual(target.read_bytes(), before)
        for path in ("relative.json", SKILL / "forbidden.json"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                oracles._write_result(result, str(path))


if __name__ == "__main__":
    unittest.main()
