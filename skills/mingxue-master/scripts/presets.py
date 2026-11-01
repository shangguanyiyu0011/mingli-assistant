"""Explicit supported-rule presets and bounded same-input calculation diffs.

This module never computes charts, installs engines or treats presets as complete schools.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path, PureWindowsPath
import re
import sys

PROFILE_FILE = Path(__file__).resolve().parents[1] / "references" / "presets.json"
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_NODES = 60_000
MAX_DEPTH = 48
MAX_CHANGES = 100  # Per category, with exact total and omitted counts.
MAX_VALUE_CHARS = 512
RULES = {
    "bazi": {"sect": (int, {1, 2}), "true_solar": (bool, {True, False}), "yun_sect": (int, {1, 2})},
    "ziwei": {"algorithm": (str, {"default", "zhongzhou"}), "year_divide": (str, {"normal", "exact"}),
              "day_divide": (str, {"forward", "current"}), "fix_leap": (bool, {True, False}),
              "horoscope_divide": (str, {"normal", "exact"})},
    "astrology": {"zodiac": (str, {"tropical", "sidereal"}), "house_system": (str, {"P", "K", "O", "R", "C", "E", "W"}),
                  "ayanamsa": ((str, type(None)), {None, "lahiri", "fagan-bradley", "raman"})},
}
REQUIRED = {"bazi": {"sect", "true_solar"},
            "ziwei": {"algorithm", "year_divide", "day_divide", "fix_leap"},
            "astrology": {"zodiac", "house_system"}}
_MISSING = object()


class PresetError(ValueError):
    pass


class _JSONArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise PresetError(message)


def _load_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise PresetError("Duplicate JSON key: " + key)
            result[key] = value
        return result

    def invalid_constant(value):
        raise PresetError("Invalid non-finite JSON constant: " + value)

    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant)


def _settings(value, *, partial=False):
    if not isinstance(value, dict) or set(value) - set(RULES):
        raise PresetError("settings/overrides must use only bazi, ziwei and astrology objects")
    if not partial and set(value) != set(RULES):
        raise PresetError("A profile must explicitly declare all three supported systems")
    for system, options in value.items():
        if not isinstance(options, dict) or set(options) - set(RULES[system]):
            raise PresetError("Unknown parameter or non-object settings for " + system)
        if not partial and not REQUIRED[system].issubset(options):
            raise PresetError("Incomplete settings for " + system)
        for key, item in options.items():
            expected, choices = RULES[system][key]
            types = expected if isinstance(expected, tuple) else (expected,)
            if type(item) not in types or item not in choices:
                raise PresetError("Invalid value or type for " + system + "." + key)
    if not partial:
        astro = value["astrology"]
        if astro["zodiac"] == "sidereal" and astro.get("ayanamsa") is None:
            raise PresetError("sidereal requires an explicit supported ayanamsa")
        if astro["zodiac"] == "tropical" and astro.get("ayanamsa") is not None:
            raise PresetError("ayanamsa cannot be applied to tropical settings")


def load_profiles():
    """Return a fresh list of validated {id,label,settings,limits} objects."""
    try:
        if PROFILE_FILE.stat().st_size > MAX_INPUT_BYTES:
            raise PresetError("Profile registry is too large")
        data = _load_json(PROFILE_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PresetError("Cannot read the local profile registry: " + str(exc)) from exc
    if not isinstance(data, dict) or set(data) != {"schema_version", "profiles"} or type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise PresetError("Unsupported profile registry schema")
    profiles = data["profiles"]
    if not isinstance(profiles, list) or not 1 <= len(profiles) <= 64:
        raise PresetError("Profile registry must contain 1..64 entries")
    seen = set()
    for profile in profiles:
        if not isinstance(profile, dict) or set(profile) != {"id", "label", "settings", "limits"}:
            raise PresetError("Invalid profile fields")
        ident = profile["id"]
        if not isinstance(ident, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", ident) or ident in seen:
            raise PresetError("Invalid or duplicate profile id")
        if not isinstance(profile["label"], str) or not 1 <= len(profile["label"]) <= 160:
            raise PresetError("Invalid profile label")
        if not isinstance(profile["limits"], list) or not profile["limits"] or not all(isinstance(x, str) and 0 < len(x) <= 2000 for x in profile["limits"]):
            raise PresetError("Every profile needs explicit limits")
        _settings(profile["settings"])
        seen.add(ident)
    if "baseline" not in seen:
        raise PresetError("Profile registry must contain baseline")
    return copy.deepcopy(profiles)


def resolve_profile(name, overrides=None):
    """Resolve one exact id; apply strictly validated, nested partial overrides."""
    if not isinstance(name, str):
        raise PresetError("Profile id must be a string")
    profile = next((item for item in load_profiles() if item["id"] == name), None)
    if profile is None:
        raise PresetError("Unknown profile id: " + name)
    if overrides is not None:
        _settings(overrides, partial=True)
        for system, options in overrides.items():
            profile["settings"][system].update(copy.deepcopy(options))
        _settings(profile["settings"])
        if any(overrides.values()):
            profile["label"] += "（含显式覆写）"
            profile["limits"].append("显式覆写参数：" + json.dumps(overrides, ensure_ascii=False, sort_keys=True))
    return profile


def _validate_json(value):
    nodes, weight, active = 0, 0, set()

    def walk(item, depth=0):
        nonlocal nodes, weight
        nodes += 1
        weight += 16
        if nodes > MAX_NODES or depth > MAX_DEPTH or weight > MAX_INPUT_BYTES:
            raise PresetError("Comparison object exceeds the structural size/depth budget")
        kind = type(item)
        if kind in (dict, list):
            if id(item) in active:
                raise PresetError("Comparison input must not contain cycles")
            if len(item) > 4096:
                raise PresetError("Comparison container is too large")
            active.add(id(item))
            if kind is dict:
                for key, val in item.items():
                    if not isinstance(key, str) or len(key) > 128:
                        raise PresetError("Comparison object keys must be strings of at most 128 characters")
                    weight += len(key.encode("utf-8"))
                    walk(val, depth + 1)
            else:
                for val in item:
                    walk(val, depth + 1)
            active.remove(id(item))
        elif kind is str:
            weight += len(item.encode("utf-8"))
        elif kind is float and not math.isfinite(item):
            raise PresetError("NaN and Infinity are not valid calculation values")
        elif kind not in (str, int, float, bool, type(None)):
            raise PresetError("Comparison accepts JSON values only")
        if weight > MAX_INPUT_BYTES:
            raise PresetError("Comparison object is too large")

    walk(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise PresetError("Invalid comparison JSON: " + str(exc)) from exc
    if len(encoded.encode("utf-8")) > MAX_INPUT_BYTES:
        raise PresetError("Comparison JSON exceeds 2 MiB")


def _system(value):
    if not isinstance(value, dict) or not isinstance(value.get("input"), dict):
        raise PresetError("Compare complete result objects, not arrays, profiles or chart fragments")
    system = value.get("system")
    if type(value.get("schema_version")) is not int:
        raise PresetError("Result schema_version must be an integer")
    if value.get("schema_version") == 3 and system in (None, "bazi"):
        candidates = value.get("candidates")
        if (not isinstance(value.get("input", {}).get("date"), str) or not isinstance(value.get("convention"), dict)
                or not isinstance(value.get("pillars"), dict) or not isinstance(candidates, list) or not candidates
                or any(not isinstance(x, dict) or not isinstance(x.get("pillars"), dict) for x in candidates)):
            raise PresetError("Incomplete shared schema-3 Bazi result")
        return "bazi"
    if value.get("schema_version") != 1:
        raise PresetError("Unsupported calculation result schema")
    if system == "ziwei":
        palaces = value.get("chart", {}).get("palaces") if isinstance(value.get("chart"), dict) else None
        if value.get("status") not in {"ok", "partial"} or not isinstance(value.get("convention"), dict) or not isinstance(palaces, list) or len(palaces) != 12:
            raise PresetError("Ziwei comparison requires a real twelve-palace calculation result")
        if not isinstance(value["input"].get("solar_date"), str) or type(value["input"].get("time_index")) is not int:
            raise PresetError("Ziwei result has no adopted birth date/time")
        return system
    if system == "astrology":
        actual = (value.get("status") == "calculated" and isinstance(value.get("candidates"), list) and value["candidates"]
                  and all(isinstance(x, dict) and isinstance(x.get("planets"), list) and x["planets"] for x in value["candidates"]))
        partial = value.get("status") == "partial" and isinstance(value.get("sun_ranges"), list) and bool(value["sun_ranges"])
        if not (actual or partial) or not isinstance(value.get("zodiac"), dict) or not isinstance(value.get("house_system"), dict) or not isinstance(value["input"].get("date"), str):
            raise PresetError("Astrology comparison requires calculated candidates or actual unknown-time Sun ranges")
        return system
    raise PresetError("Only shared Bazi, Ziwei and astrology calculation results can be compared")


def _identity(left, right, system):
    for container in (left, right):
        other = right if container is left else left
        for key in ("subject_id", "person_id", "case_id"):
            if (key in container or key in other) and container.get(key) != other.get(key):
                raise PresetError("Different subject/case identifiers cannot be compared as a rule change")
    if system == "ziwei":
        a, b = left.get("source_chart"), right.get("source_chart")
        if bool(a) != bool(b) or (a and a != b):
            raise PresetError("Ziwei source birth input hashes differ or are missing on one side; same original input cannot be established")
        if left["input"] != right["input"]:
            raise PresetError("Ziwei adopted birth inputs differ; cannot treat this as only a school-option change")
        for key in ("scope", "target"):
            default = "origin" if key == "scope" else None
            if left.get(key, default) != right.get(key, default):
                raise PresetError("Ziwei scope/target periods must be identical")
        for result in (left, right):
            scope = result.get("scope", "origin")
            target = result.get("target")
            if scope not in {"origin", "yearly", "monthly", "daily"}:
                raise PresetError("Unknown Ziwei comparison scope")
            if scope == "origin":
                if target is not None:
                    raise PresetError("Origin Ziwei result must not contain a target period")
            else:
                flow = result.get("horoscope")
                if (not isinstance(target, dict) or not isinstance(target.get("date"), str)
                        or type(target.get("time_index")) is not int or not isinstance(flow, dict)
                        or flow.get("scope") != scope or flow.get("target") != target
                        or not isinstance(flow.get("layers"), dict) or not isinstance(flow["layers"].get(scope), dict)):
                    raise PresetError("Ziwei flow comparison needs matching top-level and horoscope scope/target with real layers")
        return "matching adopted birth inputs, source identity (if present), scope and target"
    ignored_input_rules = {"sect", "true_solar", "yun_sect"}
    a = {k: v for k, v in left["input"].items() if k not in ignored_input_rules}
    b = {k: v for k, v in right["input"].items() if k not in ignored_input_rules}
    if a != b:
        raise PresetError("Birth facts (date/time/calendar/timezone/coordinates/gender/fold) differ; not a same-input rule comparison")
    # Source hashes include rule settings, so Bazi/astrology use inspectable birth facts above.
    for key in ("scope", "target", "target_date", "target_time"):
        if left.get(key) != right.get(key):
            raise PresetError("Target periods differ")
    return "matching explicit birth input after excluding only sect/true_solar/yun_sect rule switches"


def _pointer(parts):
    return "/" + "/".join(str(x).replace("~", "~0").replace("/", "~1") for x in parts)


def _path_noise(parts, a, b):
    if not parts:
        return False
    key = parts[-1]
    known = ((parts[0] == "engine" and key in {"engine_dir", "path", "directory", "root", "module_path", "library_path", "python_path", "manifest_path"})
             or (len(parts) == 1 and key in {"output_path", "file_path", "artifact_path", "report_path"}))
    values = [x for x in (a, b) if x is not _MISSING]
    return known and bool(values) and all(isinstance(x, str) and (Path(x).is_absolute() or PureWindowsPath(x).is_absolute()) for x in values)


def _category(parts, system):
    top = parts[0] if parts else ""
    if top in {"convention", "zodiac", "house_system", "aspect_policy", "frame"}:
        return "convention_changes"
    if top == "input" and len(parts) > 1 and parts[1] in {"sect", "true_solar", "yun_sect"}:
        return "convention_changes"
    if top == "time_context" and len(parts) > 1 and parts[1] in {"chart_time_basis", "solar_model"}:
        return "convention_changes"
    if top == "corrections" and len(parts) > 1 and parts[1] == "true_solar_time":
        return "convention_changes"
    if top == "horoscope" and len(parts) > 1 and parts[1] == "convention":
        return "convention_changes"
    if system == "bazi":
        if parts and parts[-1] in {"sect", "chart_time_basis"} and top in {"candidates", "convention_alternatives"}:
            return "convention_changes"
        chart_keys = {"pillars", "details", "candidates", "convention_alternatives", "solar", "solar_candidates",
                      "solar_year", "chinese_calendar_solar_date", "lunar", "lunar_candidates", "solar_terms_on_date", "yun"}
    elif system == "ziwei":
        chart_keys = {"chart", "soul_palace", "body_palace", "natal_mutagens", "horoscope", "gender_dependent_omitted"}
    else:
        chart_keys = {"candidates", "sun_ranges", "sun_sign"}
    return "chart_changes" if top in chart_keys else "metadata_changes"


def _view(value):
    if value is _MISSING:
        return {"missing": True}
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(text) <= MAX_VALUE_CHARS:
        return copy.deepcopy(value)
    return {"truncated_value": True, "type": type(value).__name__, "json_characters": len(text),
            "preview": text[:MAX_VALUE_CHARS], "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def compare_results(left, right):
    """Diff two existing same-system, same-input calculations; never recompute or vote."""
    _validate_json(left)
    _validate_json(right)
    system = _system(left)
    if _system(right) != system:
        raise PresetError("Cannot compare different systems")
    identity = _identity(left, right, system)
    buckets = {key: [] for key in ("convention_changes", "chart_changes", "metadata_changes")}
    counts = {key: 0 for key in buckets}
    ignored = []
    ignored_count = 0

    def walk(a, b, parts=()):
        nonlocal ignored_count
        if type(a) is type(b) and not isinstance(a, (dict, list)) and a == b:
            return
        if _path_noise(parts, a, b):
            ignored_count += 1
            if len(ignored) < 20:
                ignored.append(_pointer(parts))
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                walk(a.get(key, _MISSING), b.get(key, _MISSING), parts + (key,))
            return
        if isinstance(a, list) and isinstance(b, list):
            for index in range(max(len(a), len(b))):
                walk(a[index] if index < len(a) else _MISSING,
                     b[index] if index < len(b) else _MISSING, parts + (index,))
            return
        category = _category(parts, system)
        counts[category] += 1
        if len(buckets[category]) < MAX_CHANGES:
            buckets[category].append({"path": _pointer(parts),
                                      "kind": "added" if a is _MISSING else "removed" if b is _MISSING else "changed",
                                      "left": _view(a), "right": _view(b)})

    walk(left, right)
    omitted = {key: counts[key] - len(buckets[key]) for key in buckets}
    return {"schema_version": 1, "status": "compared", "system": system, "identity_check": identity,
            "equal_chart": counts["chart_changes"] == 0, "equal_result": not any(counts.values()),
            **buckets, "counts": counts, "omitted_counts": omitted, "truncated": any(omitted.values()),
            "ignored_path_changes": {"count": ignored_count, "sample_paths": ignored},
            "limits": ["Structural differences in existing calculations only; no chart is recomputed by this function.",
                       "No floating-point rounding, scoring, voting or predictive accuracy inference is applied.",
                       "Array order is preserved. equal_chart does not mean all conventions or metadata are identical.",
                       "At most 100 differences per category are shown; all difference counts are retained. Long values have previews and SHA-256 digests."]}


def _read_absolute(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise PresetError("CLI JSON input paths must be absolute")
    if not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
        raise PresetError("Input JSON must be an existing file no larger than 2 MiB")
    try:
        return _load_json(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise PresetError("Cannot read input JSON: " + str(exc)) from exc


def main(argv=None):
    parser = _JSONArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--list", action="store_true")
    modes.add_argument("resolve", nargs="?", metavar="COMMAND", choices=("resolve", "compare"))
    parser.add_argument("name", nargs="?", help="exact preset id for resolve")
    parser.add_argument("--overrides", help="absolute path to nested settings JSON")
    parser.add_argument("--left", help="absolute result JSON path")
    parser.add_argument("--right", help="absolute result JSON path")
    try:
        args = parser.parse_args(argv)
        if args.list:
            if args.name or args.overrides or args.left or args.right:
                raise PresetError("--list accepts no resolve/compare arguments")
            result = load_profiles()
        elif args.resolve == "resolve":
            if not args.name or args.left or args.right:
                raise PresetError("Use resolve PROFILE_ID [--overrides ABS_JSON]")
            result = resolve_profile(args.name, _read_absolute(args.overrides) if args.overrides else None)
        else:
            if args.name or args.overrides or not args.left or not args.right:
                raise PresetError("Use compare --left ABS_JSON --right ABS_JSON")
            result = compare_results(_read_absolute(args.left), _read_absolute(args.right))
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (PresetError, OSError, UnicodeError, RecursionError) as exc:
        print(json.dumps({"ok": False, "error": {"code": "invalid_preset_or_comparison", "message": str(exc)}}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
