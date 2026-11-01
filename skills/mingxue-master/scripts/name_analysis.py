"""Offline name arithmetic, pinned character lookup and candidate comparison."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unicodedata

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
ELEMENTS = ("木", "火", "土", "金", "水")


class JsonParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)

    def print_help(self, file=None):
        print(json.dumps({"help": self.format_help()}, ensure_ascii=False), file=file)


def write_result(value, output=None):
    """Only an explicit absolute, new user path may receive a file."""
    target = None
    if output is not None:
        supplied = Path(output).expanduser()
        if not supplied.is_absolute():
            raise ValueError("--output must be an absolute path")
        target = supplied.resolve()
        protected = [ROOT, ROOT.parent.parent / "runtime", ROOT.parent.parent / "engine-cache",
                     Path(tempfile.gettempdir()).resolve() / "mingxue-master-cache"]
        protected.extend(Path(os.environ[key]).expanduser().resolve() for key in
                         ("MINGXUE_RESOURCE_DIR", "MINGXUE_CACHE_DIR", "MINGXUE_NAME_DICTIONARY", "MINGXUE_ENGINE_HOME") if os.environ.get(key))
        from runtime_paths import engine_home
        protected.append(engine_home())
        for record in (value, value.get("dictionary", {})):
            for key in ("dictionary_dir", "directory"):
                if isinstance(record, dict) and record.get(key):
                    protected.append(Path(record[key]).expanduser().resolve())
        from output_paths import guard_output
        guard_output(target, extra_protected=protected)
        if (any(target.is_relative_to(p.resolve()) for p in protected)
                or any(p.name.casefold() in {"runtime", "cache", "engine-cache", "__pycache__", "mingxue-master-cache"}
                       for p in (target, *target.parents))):
            raise ValueError("output must be outside the skill, runtime and cache directories")
        if target.exists():
            raise ValueError("output already exists; choose a new path to preserve the original")
        value = {**value, "output_path": str(target)}
    rendered = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(rendered)
    print(rendered, end="")


def _han(character):
    n = ord(character)
    return (0x3400 <= n <= 0x4DBF or 0x4E00 <= n <= 0x9FFF
            or 0xF900 <= n <= 0xFAFF or 0x20000 <= n <= 0x33479)


def validate_name(part, label):
    if not isinstance(part, str) or len(part) not in (1, 2) or not all(_han(c) for c in part):
        raise ValueError(f"{label} must contain exactly one or two Han characters; provide surname/given separately")
    return part


def validate_international_name(full_name, latin_name=None, pronunciation=None):
    for label, value, limit in (("full_name", full_name, 160), ("latin_name", latin_name, 160), ("pronunciation", pronunciation, 240)):
        if value is None and label != "full_name":
            continue
        if (not isinstance(value, str) or not 1 <= len(value) <= limit or not value.strip()
                or any(unicodedata.category(c).startswith("C") for c in value)):
            raise ValueError(label + " must be bounded nonempty text without control characters")
    if not any(c.isalpha() for c in full_name):
        raise ValueError("full_name must contain the original written name")
    if latin_name is not None:
        from symbolic import name_expression
        name_expression(latin_name)


def analyze_international_name(full_name, *, latin_name=None, pronunciation=None):
    validate_international_name(full_name, latin_name, pronunciation)
    from symbolic import name_expression
    scripts = Counter()
    for c in full_name:
        if not c.isalpha():
            continue
        script = next((s for s in ("Latin", "Hiragana", "Katakana", "Hangul") if s.upper() in unicodedata.name(c, "")), None)
        scripts[script or ("Han" if _han(c) else "Other")] += 1
    spelling = latin_name
    if spelling is None and re.fullmatch(r"[A-Za-z '\-]+", full_name) and re.search(r"[A-Za-z]", full_name):
        spelling = full_name
    return {"schema_version": 1, "system": "name_five_grids", "mode": "international",
            "status": "calculated", "calculation_status": "calculated", "name": full_name, "full_name": full_name,
            "writing": {"scripts": dict(scripts), "letter_count": sum(scripts.values()), "word_parts": full_name.split()},
            "pronunciation": pronunciation, "pronunciation_source": "user_supplied" if pronunciation else "not_provided",
            "latin_numerology": name_expression(spelling) if spelling else None,
            "latin_name_source": "user_supplied" if latin_name else "original_ascii_name" if spelling else "not_provided",
            "five_grids": None, "three_talents": None,
            "interpretation_scope": "Written form and supplied pronunciation only; Latin expression arithmetic uses explicit ASCII spelling. No automatic transliteration, nationality, personality or fate inference."}


def parse_strokes(value):
    if value is None:
        raise ValueError("missing strokes: supply --strokes in surname-then-given character order; no dictionary is bundled")
    if isinstance(value, str):
        if not re.fullmatch(r"[0-9]+(?:,[0-9]+)*", value):
            raise ValueError("--strokes must be comma-separated positive integers")
        value = [int(n) for n in value.split(",")]
    if not isinstance(value, (list, tuple)) or any(type(n) is not int or not 1 <= n <= 100 for n in value):
        raise ValueError("each supplied stroke count must be an integer in 1..100 (input guard, not a dictionary claim)")
    return list(value)


def number_symbol(number):
    return {"number": number, "last_digit": number % 10,
            "element": ELEMENTS[((number - 1) % 10) // 2],
            "yin_yang": "阳" if number % 2 else "阴"}


def element_relation(first, second):
    delta = (ELEMENTS.index(second) - ELEMENTS.index(first)) % 5
    return ("同类", "前生后", "前克后", "后克前", "后生前")[delta]


def _arithmetic(surname, given, strokes, *, stroke_standard="unspecified", stroke_reference=None,
                 pronunciation=None, meaning_note=None):
    validate_name(surname, "surname")
    validate_name(given, "given")
    values = parse_strokes(strokes)
    full = surname + given
    if len(values) != len(full):
        raise ValueError(f"expected {len(full)} stroke counts, got {len(values)}; one count for each character occurrence")
    if not isinstance(stroke_standard, str) or not stroke_standard.strip():
        raise ValueError("stroke_standard must be a nonempty user-specified label")
    for label, value in (("stroke_reference", stroke_reference), ("pronunciation", pronunciation), ("meaning_note", meaning_note)):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"{label} must be nonempty text when supplied")
    # A repeated written character cannot silently acquire different counts in
    # the same declared dictionary convention.
    seen = {}
    for character, number in zip(full, values):
        if character in seen and seen[character] != number:
            raise ValueError(f"conflicting stroke counts for repeated character {character}")
        seen[character] = number
    s, g = values[:len(surname)], values[len(surname):]
    sky = sum(s) + (len(s) == 1)
    person = s[-1] + g[0]
    ground = sum(g) + (len(g) == 1)
    grids = {key: number_symbol(number) for key, number in
             (("天格", sky), ("人格", person), ("地格", ground),
              ("外格", sky + ground - person), ("总格", sum(values)))}
    three = [grids[key]["element"] for key in ("天格", "人格", "地格")]
    return {
        "schema_version": 1, "system": "name_five_grids", "status": "calculated",
        "name": full, "surname": surname, "given": given,
        "name_structure": {"surname_characters": len(s), "given_characters": len(g)},
        "stroke_provenance": {"source": "user_supplied", "standard_label": stroke_standard,
                              "reference_label": stroke_reference, "dictionary_verified": False,
                              "character_conversion": "none; exact supplied written forms retained"},
        "strokes": [{"index": i + 1, "character": character, "count": number,
                     "part": "surname" if i < len(s) else "given"}
                    for i, (character, number) in enumerate(zip(full, values))],
        "rule_id": "five-grid-virtual-one-v1",
        "formula": {"天格": "sum(surname) + 1 only for a one-character surname",
                    "人格": "last surname character + first given character",
                    "地格": "sum(given) + 1 only for a one-character given name",
                    "外格": "天格 + 地格 - 人格", "总格": "sum(actual character strokes), no virtual ones"},
        "five_grids": grids,
        "three_talents": {"order": ["天格", "人格", "地格"], "elements": three,
                          "label": "".join(three),
                          "mapping": "1/2木,3/4火,5/6土,7/8金,9/0水; use unreduced grid last digit",
                          "adjacent_relations": [
                              {"from": a, "to": b, "relation": element_relation(grids[a]["element"], grids[b]["element"])}
                              for a, b in (("天格", "人格"), ("人格", "地格"))]},
        "sound_form_meaning": {"scope": "textual_analysis_only", "pronunciation": pronunciation,
                               "pronunciation_source": "user_supplied" if pronunciation else "not_provided",
                               "meaning_note": meaning_note,
                               "meaning_source": "user_supplied" if meaning_note else "not_provided",
                               "repeated_characters": [c for c, n in Counter(full).items() if n > 1]},
        "interpretation_scope": "Cultural arithmetic and text discussion; no identity, ethnicity, personality or fate is inferred.",
    }


def _with_dictionary(surname, given, strokes, *, lookup, stroke_standard, stroke_reference,
                     pronunciation, meaning_note, stroke_scheme, surname_reading, given_reading):
    import name_dictionary as dictionary
    full = surname + given
    entries = {item["character"]: item for item in lookup.get("characters", [])}
    pending = []
    if strokes is None:
        if stroke_standard != "__dictionary_derived__":
            pending.append({"reason": "explicit_strokes_required_for_user_convention", "requested_standard": stroke_standard,
                            "required": "explicit per-character counts; user convention labels do not select dictionary counts"})
        elif stroke_scheme != "unihan-irG":
            pending.append({"reason": "verified_kangxi_or_naming_adjusted_counts_not_available", "required": "explicit per-character strokes and convention"})
        elif lookup.get("dictionary_verified"):
            strokes = [entries.get(c, {}).get("modern_strokes", {}).get("count") for c in full]
            if any(value is None for value in strokes):
                pending.extend({"character": c, "reason": "dictionary_stroke_missing"} for c, n in zip(full, strokes) if n is None)
                strokes = None
        else:
            pending.append({"reason": "dictionary_not_prepared", "required": "explicit preparation or supplied strokes"})
    derived = strokes is not None and stroke_standard == "__dictionary_derived__"
    # The wrapper passes an internal marker only when no counts were supplied.
    if strokes is not None:
        result = _arithmetic(surname, given, strokes, stroke_standard="Unihan 17.0.0 IRG kTotalStrokes" if derived else stroke_standard,
                             stroke_reference=stroke_reference, pronunciation=pronunciation, meaning_note=meaning_note)
        result["calculation_status"] = "calculated"
        if derived:
            result["stroke_provenance"] = {"source": "verified_external_dictionary", "standard_label": "Unihan 17.0.0 IRG kTotalStrokes",
                                           "dictionary_verified": True, "dictionary_version": dictionary.VERSION,
                                           "archive_sha256": lookup["archive_sha256"], "data_sha256": lookup["data_sha256"],
                                           "property": "kTotalStrokes", "character_conversion": "none; exact supplied written forms retained",
                                           "not_kangxi_or_naming_adjustment": True}
    else:
        result = {"schema_version": 1, "system": "name_five_grids", "name": full, "surname": surname, "given": given,
                  "calculation_status": "not_calculated", "five_grids": None, "three_talents": None,
                  "stroke_provenance": {"source": "not_available", "requested_scheme": stroke_scheme,
                                        "requested_standard": None if stroke_standard == "__dictionary_derived__" else stroke_standard},
                  "sound_form_meaning": {"scope": "textual_analysis_only", "pronunciation": pronunciation,
                                         "pronunciation_source": "user_supplied" if pronunciation else "not_provided",
                                         "meaning_note": meaning_note, "meaning_source": "user_supplied" if meaning_note else "not_provided"}}
    result["dictionary"] = lookup
    if lookup.get("dictionary_verified"):
        surname_result = dictionary.resolve_readings(surname, entries, surname_reading, part="surname")
        given_result = dictionary.resolve_readings(given, entries, given_reading, part="given")
        result["reading_resolution"] = {"surname": surname_result, "given": given_result}
        pending.extend(surname_result["pending_inputs"])
        pending.extend(given_result["pending_inputs"])
        for character in dict.fromkeys(full):
            item = entries.get(character, {})
            if not item.get("definition", {}).get("text"):
                pending.append({"character": character, "reason": "dictionary_definition_missing"})
        if surname_result["pinyin"] is not None and given_result["pinyin"] is not None:
            result["resolved_pinyin"] = surname_result["pinyin"] + " " + given_result["pinyin"]
        else:
            result["resolved_pinyin"] = None
    else:
        result["reading_resolution"] = None
        result["resolved_pinyin"] = None
        if not pending:
            pending.append({"reason": "dictionary_not_prepared", "required": "explicit preparation for reading/meaning lookup"})
    result["pending_inputs"] = pending
    result["status"] = "needs_input" if pending else "calculated"
    result["interpretation_scope"] = "Character data and cultural arithmetic; user confirms surname-specific readings. No identity, ethnicity or fate is inferred."
    return result


def analyze_name(surname, given, strokes=None, *, stroke_standard="unspecified", stroke_reference=None,
                 pronunciation=None, meaning_note=None, dictionary_dir=None, stroke_scheme="unihan-irG",
                 surname_reading=None, given_reading=None):
    validate_name(surname, "surname")
    validate_name(given, "given")
    if stroke_scheme not in ("unihan-irG", "kangxi"):
        raise ValueError("stroke_scheme must be unihan-irG or kangxi")
    if stroke_standard == "__dictionary_derived__":
        raise ValueError("reserved stroke convention label")
    # Existing explicit-stroke calls retain their original output and do not
    # acquire a dependency on an external dictionary.
    if strokes is not None and dictionary_dir is None and surname_reading is None and given_reading is None:
        return _arithmetic(surname, given, strokes, stroke_standard=stroke_standard, stroke_reference=stroke_reference,
                           pronunciation=pronunciation, meaning_note=meaning_note)
    import name_dictionary as dictionary
    lookup = dictionary.lookup_characters(surname + given, dictionary_dir)
    return _with_dictionary(surname, given, strokes, lookup=lookup,
        stroke_standard="__dictionary_derived__" if strokes is None and stroke_standard == "unspecified" and stroke_reference is None else stroke_standard,
        stroke_reference=stroke_reference, pronunciation=pronunciation, meaning_note=meaning_note,
        stroke_scheme=stroke_scheme, surname_reading=surname_reading, given_reading=given_reading)


def compare_names(surname, candidates, *, dictionary_dir=None, stroke_scheme="unihan-irG", surname_reading=None,
                  homophone_watchlist=None):
    import name_dictionary as dictionary
    validate_name(surname, "surname")
    if stroke_scheme not in ("unihan-irG", "kangxi"):
        raise ValueError("stroke_scheme must be unihan-irG or kangxi")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 50:
        raise ValueError("provide 1..50 candidate objects")
    allowed = {"given", "given_reading", "strokes", "stroke_standard", "stroke_reference", "meaning_note"}
    for candidate in candidates:
        if not isinstance(candidate, dict) or set(candidate) - allowed or "given" not in candidate:
            raise ValueError("candidate must contain given and only supported reading/stroke/meaning fields")
        validate_name(candidate["given"], "candidate given")
        if candidate.get("stroke_standard") == "__dictionary_derived__":
            raise ValueError("reserved stroke convention label")
    if homophone_watchlist is not None:
        if not isinstance(homophone_watchlist, list) or len(homophone_watchlist) > 100:
            raise ValueError("homophone_watchlist must be a list of at most 100 explicit entries")
        for item in homophone_watchlist:
            if (not isinstance(item, dict) or set(item) != {"text", "reading"}
                    or any(not isinstance(item[k], str) or not item[k].strip() for k in item)):
                raise ValueError("each watchlist entry must contain nonempty text and reading strings")
    lookup = dictionary.lookup_characters(surname + "".join(c["given"] for c in candidates), dictionary_dir)
    results = []
    for candidate in candidates:
        original = candidate.get("strokes")
        # Each candidate receives the same verified snapshot, without re-reading
        # or silently changing dictionary versions midway through the batch.
        result = _with_dictionary(surname, candidate["given"], original, lookup=lookup,
            stroke_standard="__dictionary_derived__" if original is None and candidate.get("stroke_standard", "unspecified") == "unspecified" and candidate.get("stroke_reference") is None else candidate.get("stroke_standard", "unspecified"),
            stroke_reference=candidate.get("stroke_reference"), pronunciation=None, meaning_note=candidate.get("meaning_note"),
            stroke_scheme=stroke_scheme, surname_reading=surname_reading, given_reading=candidate.get("given_reading"))
        # Keep the common dictionary snapshot once at the batch level.
        result.pop("dictionary", None)
        results.append(result)
    reminders = []
    for i, first in enumerate(results):
        if not first.get("resolved_pinyin"):
            continue
        for second in results[i + 1:]:
            if not second.get("resolved_pinyin"):
                continue
            exact = dictionary.pinyin_key(first["resolved_pinyin"]) == dictionary.pinyin_key(second["resolved_pinyin"])
            toneless = dictionary.pinyin_key(first["resolved_pinyin"], ignore_tone=True) == dictionary.pinyin_key(second["resolved_pinyin"], ignore_tone=True)
            if toneless:
                reminders.append({"kind": "same_pinyin" if exact else "same_pinyin_without_tone",
                                  "names": [first["name"], second["name"]], "reading": first["resolved_pinyin"],
                                  "scope": "pronunciation comparison only; no negative meaning is inferred"})
        for item in homophone_watchlist or []:
            if dictionary.pinyin_key(first["resolved_pinyin"], ignore_tone=True) == dictionary.pinyin_key(" ".join(item["reading"].split()), ignore_tone=True):
                reminders.append({"kind": "user_watchlist_phonetic_match", "name": first["name"],
                                  "watchlist_text": item["text"], "watchlist_reading": item["reading"],
                                  "source": "user_supplied_watchlist", "requires_context_review": True})
    conventions = list(dict.fromkeys(r["stroke_provenance"].get("standard_label", "not_available") for r in results))
    return {"schema_version": 1, "system": "name_candidate_comparison", "status": "needs_input" if any(r["pending_inputs"] for r in results) else "compared",
            "surname": surname, "dictionary": lookup, "candidates": results, "homophone_reminders": reminders,
            "stroke_conventions": conventions, "same_declared_stroke_convention": len(conventions) == 1 and conventions[0] not in ("unspecified", "not_available"),
            "comparison_order": "input order; no invented auspiciousness or destiny ranking",
            "homophone_scope": "Only resolved readings, other supplied candidates and an optional explicit user watchlist; no comprehensive language or dialect screening."}


def probe(dictionary_dir=None):
    import name_dictionary as dictionary
    sample = analyze_name("欧阳", "修", [15, 17, 10])
    return {"status": "ready", "network": "not_used", "dependencies": "python_standard_library",
            "capabilities": ["one_or_two_character_surname_and_given", "five_grids", "three_talents"],
            "stroke_dictionary": "external_pinned_unihan_irG; explicit strokes remain supported",
            "dictionary": dictionary.dictionary_status(dictionary_dir),
            "self_check": sample["five_grids"]["外格"]["number"] == 16}


def main(argv=None):
    parser = JsonParser(description=__doc__, allow_abbrev=False)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--probe", action="store_true")
    modes.add_argument("--lookup", help="look up exact characters, readings, English meanings and variant relations")
    modes.add_argument("--compare-file", help="absolute JSON path containing surname, candidates and optional reading settings")
    parser.add_argument("--surname")
    parser.add_argument("--given")
    parser.add_argument("--mode", choices=("chinese", "international"), default="chinese")
    parser.add_argument("--full-name")
    parser.add_argument("--latin-name")
    parser.add_argument("--strokes", help="e.g. 11,3; surname then given, one count per occurrence")
    parser.add_argument("--stroke-standard", default="unspecified", help="user label only; never treated as dictionary verification")
    parser.add_argument("--stroke-reference", help="user supplied dictionary/page reference label")
    parser.add_argument("--pronunciation", help="user supplied reading; no automatic pinyin guess")
    parser.add_argument("--meaning-note", help="user supplied textual meaning note")
    parser.add_argument("--dictionary-dir", help="absolute external dictionary directory; no automatic preparation/download")
    parser.add_argument("--stroke-scheme", choices=("unihan-irG", "kangxi"), default="unihan-irG")
    parser.add_argument("--surname-reading", help="explicit dictionary pinyin syllable per surname character, space separated")
    parser.add_argument("--given-reading", help="explicit dictionary pinyin syllable per given character, space separated")
    parser.add_argument("--output", help="new absolute JSON path outside skill/runtime/cache")
    try:
        args = parser.parse_args(argv)
        if args.mode == "international":
            if (args.probe or args.lookup or args.compare_file or args.surname or args.given or args.strokes
                    or args.dictionary_dir or args.surname_reading or args.given_reading or args.meaning_note
                    or args.stroke_standard != "unspecified" or args.stroke_reference or args.stroke_scheme != "unihan-irG"):
                raise ValueError("international names cannot use Chinese stroke/dictionary inputs or other modes")
            write_result(analyze_international_name(args.full_name, latin_name=args.latin_name, pronunciation=args.pronunciation), args.output)
            return 0
        if args.full_name is not None or args.latin_name is not None:
            raise ValueError("full-name and latin-name require international mode")
        if args.probe:
            value = probe(args.dictionary_dir)
        elif args.lookup:
            import name_dictionary
            if args.surname or args.given or args.strokes or args.surname_reading or args.given_reading:
                raise ValueError("--lookup cannot be combined with individual name analysis inputs")
            value = {"schema_version": 1, "system": "name_character_lookup",
                     **name_dictionary.lookup_characters(args.lookup, args.dictionary_dir)}
        elif args.compare_file:
            if args.surname or args.given or args.strokes or args.given_reading or args.pronunciation or args.meaning_note:
                raise ValueError("--compare-file cannot be combined with individual name analysis inputs")
            source = Path(args.compare_file).expanduser()
            if not source.is_absolute() or source.stat().st_size > 2 * 1024 * 1024:
                raise ValueError("compare-file must be an absolute JSON path no larger than 2 MiB")
            import name_dictionary
            data = json.loads(source.read_text(encoding="utf-8-sig"), object_pairs_hook=name_dictionary._unique_object)
            if not isinstance(data, dict) or set(data) - {"surname", "candidates", "surname_reading", "stroke_scheme", "homophone_watchlist"}:
                raise ValueError("unsupported comparison-file fields")
            value = compare_names(data.get("surname"), data.get("candidates"), dictionary_dir=args.dictionary_dir,
                stroke_scheme=data.get("stroke_scheme", args.stroke_scheme), surname_reading=data.get("surname_reading", args.surname_reading),
                homophone_watchlist=data.get("homophone_watchlist"))
        else:
            value = analyze_name(args.surname, args.given, args.strokes,
                stroke_standard=args.stroke_standard, stroke_reference=args.stroke_reference,
                pronunciation=args.pronunciation, meaning_note=args.meaning_note, dictionary_dir=args.dictionary_dir,
                stroke_scheme=args.stroke_scheme, surname_reading=args.surname_reading, given_reading=args.given_reading)
        write_result(value, args.output)
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
