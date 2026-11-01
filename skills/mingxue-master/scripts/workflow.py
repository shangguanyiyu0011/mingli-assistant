"""Run selected traditions once, keep immutable revisions, and recalculate corrections."""
from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
from chart import build_chart, validate_shichen
from fortune import ROOT, dispatch, find_system
import presets
from project_store import (ProjectError, canonical, commit_revision, contained, digest, file_digest,
    load_project, load_revision, merge_patch, project_lock, read_json, reserve_revision, utc_now,
    validate_workspace, write_atomic, write_new_json)
from reporting import build_report, index_html, report_html
from resources import ResourceError
from workbench_catalog import EXTRA_MODULES

VERSION = "5.2.0"
BIRTH_SYSTEMS = {"bazi", "ziwei", "astrology", "vedic"}
RETRY_STATUSES = {"needs_setup", "engine_unavailable", "needs_input", "ambiguous_input", "error",
                  "invalid_input", "unsupported_range", "unsupported_date", "unsupported_boundary", "engine_integrity_error", "engine_error", "calculation_unavailable", "needs_dictionary"}
ROOT_KEYS = {"schema_version", "birth", "location", "name", "topic", "question", "systems",
             "profile", "settings", "options", "compare_profiles", "readings", "person", "questionnaire", "report_depth", "deferred"}
BIRTH_KEYS = {"date", "time", "shichen", "calendar", "leap", "sect", "timezone", "time_basis", "gender",
              "yun_sect", "longitude", "true_solar", "fold"}
NAME_KEYS = {"surname", "given", "strokes", "stroke_standard", "stroke_reference", "pronunciation",
             "meaning_note", "dictionary_dir", "stroke_scheme", "surname_reading", "given_reading", "candidates", "homophone_watchlist",
             "mode", "full_name", "latin_name"}
OPTION_KEYS = {
    "bazi": set(), "names": set(), "ziwei": {"scope", "target_date", "target_time", "target_time_index", "horoscope_divide", "engine_dir"},
    "astrology": {"engine_dir"}, "vedic": {"engine_dir", "ayanamsa", "house_system"},
    "iching": {"lines", "method", "numbers", "direction", "najia", "seed", "question", "cast_date", "cast_time",
               "cast_timezone", "cast_sect", "cast_fold", "cast_chart", "cast_time_basis", "cast_longitude", "cast_true_solar"},
    "tarot": {"spread", "seed", "cards", "question", "upright_only"},
    "numerology": {"date", "year", "masters", "method", "latin_name"},
    "electional": {"date", "days", "time", "topic"},
    "palm": {"image", "observations", "annotations"}, "face": {"image", "observations", "annotations"},
    "fengshui": set(), "qimen": set(), "liuren": set(), "human_design": set(),
}
OPTION_KEYS.update({system: {"params"} for system in EXTRA_MODULES})
FILE_OPTIONS = {"palm": ("image", "observations", "annotations"),
                "face": ("image", "observations", "annotations"), "iching": ("cast_chart",)}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ProjectError(message)


def _object(value, keys, label):
    if not isinstance(value, dict) or set(value) - keys:
        raise ProjectError(label + " has unknown fields or is not an object")
    return copy.deepcopy(value)


def normalize_input(value):
    result = _object(value, ROOT_KEYS, "input")
    if type(result.get("schema_version", 1)) is not int or result.get("schema_version", 1) != 1:
        raise ProjectError("workflow input requires schema_version 1")
    result["schema_version"] = 1
    if "person" in result:
        person = _object(result["person"], {"name", "notes"}, "person")
        if not isinstance(person.get("name"), str) or not 1 <= len(person["name"].strip()) <= 120:
            raise ProjectError("person.name requires a nonempty label of at most 120 characters")
        if "notes" in person and (not isinstance(person["notes"], str) or len(person["notes"]) > 4000):
            raise ProjectError("invalid person.notes")
        result["person"] = person
    if result.get("report_depth", "detailed") not in ("brief", "detailed"):
        raise ProjectError("report_depth must be brief or detailed")
    if "questionnaire" in result:
        answers = result["questionnaire"]
        if not isinstance(answers, dict) or len(answers) > 50 + sum(key in answers for key in ("_relationship_context","_photo_context","_report_language")):
            raise ProjectError("questionnaire must be a bounded object")
        for key, answer in answers.items():
            if not isinstance(key, str) or not 1 <= len(key) <= 120:
                raise ProjectError("invalid questionnaire key")
            values = answer if isinstance(answer, list) else [answer]
            if len(values) > 30 or any(not isinstance(v, str) or len(v) > 2000 for v in values):
                raise ProjectError("questionnaire answers must be text or bounded text lists")
        if "_report_language" in answers and answers["_report_language"] not in ("zh-CN","en","ja","ko"):
            raise ProjectError("invalid report language")
    deferred = result.get("deferred", {})
    if not isinstance(deferred, dict) or len(deferred) > 25:
        raise ProjectError("invalid deferred systems")
    for name, entry in deferred.items():
        find_system(name)
        entry = _object(entry, {"reason", "required_inputs"}, "deferred entry")
        if not isinstance(entry.get("reason"), str) or not 1 <= len(entry["reason"]) <= 2000:
            raise ProjectError("deferred reason is required")
        if not isinstance(entry.get("required_inputs", []), list) or len(entry.get("required_inputs", [])) > 20 or any(not isinstance(x, str) or len(x) > 500 for x in entry.get("required_inputs", [])):
            raise ProjectError("deferred inputs must be text labels")
    for field, default, maximum in (("topic", "综合分析", 200), ("question", "", 4000)):
        result.setdefault(field, default)
        if not isinstance(result[field], str) or len(result[field]) > maximum or (field == "topic" and not result[field].strip()):
            raise ProjectError("invalid " + field)
    birth = result.get("birth")
    if birth is not None:
        result["birth"] = _object(birth, BIRTH_KEYS, "birth")
        try:
            validate_shichen(birth.get("shichen"), birth.get("time"))
        except ValueError as exc:
            raise ProjectError(str(exc)) from exc
        if not isinstance(birth.get("date"), str):
            raise ProjectError("birth.date is required when a birth object is supplied")
        for field in ("time", "timezone", "time_basis", "calendar", "gender"):
            if field in birth and birth[field] is not None and not isinstance(birth[field], str):
                raise ProjectError("invalid birth." + field)
        for field in ("leap", "true_solar"):
            if field in birth and type(birth[field]) is not bool:
                raise ProjectError("invalid birth." + field)
        for field in ("sect", "yun_sect"):
            if field in birth and (type(birth[field]) is not int or birth[field] not in (1, 2)):
                raise ProjectError("invalid birth." + field)
        if birth.get("fold") is not None and (type(birth["fold"]) is not int or birth["fold"] not in (0, 1)):
            raise ProjectError("invalid birth.fold")
    name = result.get("name")
    if name is not None:
        result["name"] = _object(name, NAME_KEYS, "name")
        if name.get("mode") == "international":
            if set(name) - {"mode", "full_name", "latin_name", "pronunciation"}:
                raise ProjectError("international names cannot use Chinese stroke or dictionary fields")
            from name_analysis import validate_international_name
            validate_international_name(name.get("full_name"), name.get("latin_name"), name.get("pronunciation"))
        elif "mode" in name or "full_name" in name or "latin_name" in name:
            raise ProjectError("unsupported name mode")
        elif not isinstance(name.get("surname"), str) or not name["surname"]:
            raise ProjectError("name requires an explicit surname")
        elif "candidates" in name:
            allowed = {"surname", "candidates", "surname_reading", "stroke_scheme", "homophone_watchlist", "dictionary_dir"}
            if set(name) - allowed or not isinstance(name["candidates"], list) or not 1 <= len(name["candidates"]) <= 50:
                raise ProjectError("name candidate comparison requires a bounded candidate list and comparison fields")
        elif not isinstance(name.get("given"), str) or not name["given"]:
            raise ProjectError("individual name analysis requires an explicit given name")
    if result.get("location") is None:
        result["location"] = {}
    location = result.setdefault("location", {})
    result["location"] = _object(location, {"latitude", "longitude"}, "location")
    for field, bound in (("latitude", 90), ("longitude", 180)):
        if field in location and (type(location[field]) not in (int, float) or not math.isfinite(location[field]) or abs(location[field]) > bound):
            raise ProjectError("invalid location." + field)
    if birth and birth.get("longitude") is not None and location.get("longitude") is not None:
        if type(birth["longitude"]) not in (int, float) or abs(birth["longitude"] - location["longitude"]) > 1e-9:
            raise ProjectError("birth.longitude and location.longitude disagree")
    result.setdefault("profile", "baseline")
    if result.get("settings") is None:
        result["settings"] = {}
    result.setdefault("settings", {})
    presets.resolve_profile(result["profile"], result["settings"])
    if result.get("options") is None:
        result["options"] = {}
    options = result.setdefault("options", {})
    if not isinstance(options, dict):
        raise ProjectError("options must be an object")
    normalized = {}
    for name, item in options.items():
        if item is None:
            continue
        system = find_system(name)["id"]
        if system in normalized:
            raise ProjectError("duplicate options for the same system")
        normalized[system] = _object(item, OPTION_KEYS[system], "options." + system)
    result["options"] = normalized
    if result.get("readings") is None:
        result["readings"] = {}
    readings = result.setdefault("readings", {})
    if not isinstance(readings, dict) or len(readings) > 25:
        raise ProjectError("readings must be an object keyed by system ID")
    normalized_readings = {}
    for name, reading in readings.items():
        if reading is None:
            continue
        system = find_system(name)["id"]
        if system in normalized_readings:
            raise ProjectError("duplicate reading for the same system")
        reading = _object(reading, {"text", "result_sha256", "question_hash", "basis"}, "reading")
        if not isinstance(reading.get("text"), str) or not 1 <= len(reading["text"]) <= 12000:
            raise ProjectError("reading.text must contain 1..12000 characters")
        for key in ("result_sha256", "question_hash"):
            if not isinstance(reading.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", reading[key]):
                raise ProjectError("reading requires valid result and question hashes")
        basis = reading.get("basis")
        if not isinstance(basis, list) or not 1 <= len(basis) <= 20:
            raise ProjectError("reading requires 1..20 explicit calculation/reference bases")
        for item in basis:
            item = _object(item, {"kind", "pointer", "file", "label", "section"}, "reading basis")
            if item.get("kind") == "calculation":
                if not isinstance(item.get("pointer"), str) or not item["pointer"].startswith("/"):
                    raise ProjectError("calculation basis requires a JSON pointer")
            elif item.get("kind") in ("reference", "resource"):
                filename = item.get("file")
                if (not isinstance(filename, str) or not filename.startswith("references/") or "\\" in filename
                        or ".." in Path(filename).parts or not isinstance(item.get("label"), str) or not item["label"]):
                    raise ProjectError("reference basis requires a contained reference path and a label")
            else:
                raise ProjectError("unsupported reading basis")
            for field in ("label", "section"):
                if field in item and (not isinstance(item[field], str) or len(item[field]) > 500):
                    raise ProjectError("invalid reading basis label or section")
        normalized_readings[system] = reading
    result["readings"] = normalized_readings
    if result.get("compare_profiles") is None:
        result["compare_profiles"] = []
    comparisons = result.setdefault("compare_profiles", [])
    if not isinstance(comparisons, list) or len(comparisons) > 4 or any(not isinstance(item, str) for item in comparisons):
        raise ProjectError("compare_profiles must contain at most four preset IDs")
    if len(set(comparisons)) != len(comparisons):
        raise ProjectError("duplicate comparison profile")
    for profile in comparisons:
        presets.resolve_profile(profile)
    requested = result.setdefault("systems", "auto")
    if requested != "auto":
        if not isinstance(requested, list) or not 1 <= len(requested) <= 25:
            raise ProjectError("systems must be auto or an explicit nonempty list")
        selected = [find_system(item)["id"] for item in requested]
        if len(set(selected)) != len(selected):
            raise ProjectError("duplicate selected system")
        result["systems"] = selected
    canonical(result)
    return result


def select_systems(source):
    if source["systems"] != "auto":
        return list(source["systems"])
    selected = []
    name_topic = any(word in source["topic"] for word in ("姓名", "取名", "名字"))
    if source.get("birth"):
        selected.append("bazi")
        if not name_topic:
            if source["birth"].get("time") or source["birth"].get("shichen"):
                selected.append("ziwei")
            selected.append("astrology")
    if source.get("name"):
        selected.append("names")
    for system in ("iching", "tarot", "numerology", "electional", "palm", "face"):
        if source["options"].get(system):
            selected.append(system)
    if not selected:
        raise ProjectError("no applicable inputs: provide birth, name, an explicit system or its independent inputs")
    return selected


def _implementation_fingerprint():
    files = [*sorted((ROOT / "scripts").glob("*.py")), *sorted((ROOT / "scripts").glob("*.cjs")),
             ROOT / "assets/resources-manifest.json", ROOT / "references/presets.json"]
    return digest({str(path.relative_to(ROOT)): file_digest(path) for path in files})


def _external_roots(source):
    paths = [item["engine_dir"] for item in source["options"].values() if item.get("engine_dir")]
    if (source.get("name") or {}).get("dictionary_dir"):
        paths.append(source["name"]["dictionary_dir"])
    for path in paths:
        if not isinstance(path, str) or not Path(path).expanduser().is_absolute():
            raise ProjectError("external engine paths must be absolute")
    return paths


def _snapshot_files(root, revision, source):
    copied = copy.deepcopy(source)
    snapshots = {}
    for system, fields in FILE_OPTIONS.items():
        options = copied["options"].get(system, {})
        for field in fields:
            if not options.get(field):
                continue
            if not isinstance(options[field], str):
                raise ProjectError("input file paths must be strings")
            original = Path(options[field]).expanduser()
            if not original.is_absolute():
                raise ProjectError("input file paths must be absolute")
            expected = file_digest(original)
            suffix = original.suffix.lower()
            if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
                suffix = ".bin"
            relative = f"versions/{revision}/external/{system}-{field}{suffix}"
            target = contained(root, relative)
            target.parent.mkdir(exist_ok=True)
            with original.open("rb") as stream:
                payload = stream.read(50_000_001)
            if len(payload) > 50_000_000:
                raise ProjectError("input file grew past its size limit while being snapshotted")
            import hashlib
            if hashlib.sha256(payload).hexdigest() != expected:
                raise ProjectError("input file changed while it was being snapshotted")
            with target.open("xb") as stream:
                stream.write(payload)
            options[field] = str(target)
            snapshots[f"{system}.{field}"] = {"original": str(original), "file": relative, "sha256": expected}
    return copied, snapshots


def _effective_birth(source, profile):
    if not source.get("birth"):
        return None
    options = dict(profile["settings"]["bazi"])
    options.update(source["birth"])
    if "longitude" not in options and source["location"].get("longitude") is not None:
        options["longitude"] = source["location"]["longitude"]
    date = options.pop("date")
    time = options.pop("time", None)
    return build_chart(date, time, **options)


def _append(args, key, value):
    if value is None:
        return
    option = "--" + key.replace("_", "-")
    if isinstance(value, bool):
        if value:
            args.append(option)
    elif isinstance(value, (list, tuple)):
        if key == "numbers":
            args += [option, *[str(item) for item in value]]
        else:
            args += [option, ",".join(str(item) for item in value)]
    else:
        args += [option, str(value)]


def _arguments(system, source, profile, birth_file, work_dir=None):
    options = dict(source["options"].get(system, {}))
    args = []
    if system in EXTRA_MODULES:
        parameters = options.get("params", {})
        if not isinstance(parameters, dict):
            raise ProjectError("extra-method params must be an object")
        return ["--params", json.dumps(parameters, ensure_ascii=False, allow_nan=False)], None
    if system in BIRTH_SYSTEMS:
        if birth_file is None:
            return None, "this system requires birth input"
        args += ["--chart", str(birth_file)]
        if system == "ziwei":
            settings = profile["settings"]["ziwei"]
            for key in ("algorithm", "year_divide", "day_divide"):
                _append(args, key, settings[key])
            args.append("--fix-leap" if settings["fix_leap"] else "--no-fix-leap")
            options.setdefault("horoscope_divide", settings.get("horoscope_divide", "normal"))
        elif system in ("astrology", "vedic"):
            settings = dict(profile["settings"]["astrology"])
            if system == "vedic":
                settings["zodiac"] = "sidereal"
                settings.setdefault("ayanamsa", "lahiri")
            for key, value in settings.items():
                _append(args, key, value)
            for key, value in source["location"].items():
                _append(args, key, value)
    elif system == "names":
        if not source.get("name"):
            return None, "this system requires an explicit surname and given name"
        if "candidates" in source["name"]:
            if work_dir is None:
                raise ProjectError("name comparison requires a revision directory")
            comparison = {key: value for key, value in source["name"].items() if key != "dictionary_dir"}
            comparison_file = work_dir / "name-candidates.json"
            write_new_json(comparison_file, comparison)
            args = ["--compare-file", str(comparison_file)]
            if source["name"].get("dictionary_dir"):
                args += ["--dictionary-dir", source["name"]["dictionary_dir"]]
            return args, None
        options.update(source["name"])
    elif system == "numerology":
        if "date" not in options and source.get("birth"):
            if source["birth"].get("calendar", "solar") != "solar":
                return None, "numerology needs an explicit Gregorian date; a lunar label is not reused as Gregorian"
            options["date"] = source["birth"]["date"]
    elif system == "iching" and not any(key in options for key in ("lines", "method")):
        return None, "supply actual lines or an explicit virtual casting method"
    elif system == "tarot" and not options:
        return None, "request a spread or provide cards explicitly before sampling"
    elif system == "electional" and not options.get("date"):
        return None, "supply an explicit event/calendar date"
    options.pop("annotations", None)
    for key, value in options.items():
        _append(args, key, value)
    return args, None


def _engine_probe(system, source):
    if system == "names" and (source.get("name") or {}).get("mode") == "international":
        return None
    if system in {"qizheng", "horary", "taiyi"}:
        from astrology import probe as astro_probe
        from taiyi import probe as taiyi_probe
        directory = source["options"].get(system, {}).get("params", {}).get("engine_dir")
        payload = taiyi_probe(directory) if system == "taiyi" else astro_probe(directory)
        return {"exit": 0 if payload.get("available") else 3, "payload": payload}
    if system not in {"ziwei", "astrology", "vedic", "names"}:
        return None
    args = ["--probe"]
    directory = source["options"].get(system, {}).get("engine_dir")
    if directory:
        args += ["--engine-dir", directory]
    if system == "names" and (source.get("name") or {}).get("dictionary_dir"):
        args += ["--dictionary-dir", source["name"]["dictionary_dir"]]
    result, code = dispatch(find_system(system), args)
    return {"exit": code, "payload": result.get("payload", result)}


def _dependency(system, source, profile, birth, implementation, readiness):
    options = copy.deepcopy(source["options"].get(system, {}))
    for field in FILE_OPTIONS.get(system, ()):
        if options.get(field):
            options[field] = {"sha256": file_digest(options[field])}
    dependency = {"implementation": implementation, "options": options, "engine": readiness}
    if system in source.get("deferred", {}):
        dependency["deferred"] = source["deferred"][system]
    if system in BIRTH_SYSTEMS:
        dependency["birth_input"] = birth["input"] if birth else None
        # All canonical fields take part, including gender/sect/yun convention,
        # so reused source_chart links cannot silently belong to an old revision.
        if system == "ziwei":
            dependency["settings"] = profile["settings"]["ziwei"]
        elif system in ("astrology", "vedic"):
            dependency["settings"] = profile["settings"]["astrology"]
            dependency["location"] = source["location"]
    elif system == "names":
        dependency["name"] = source.get("name")
    elif system == "numerology" and "date" not in options:
        dependency["birth_date"] = {key: (source.get("birth") or {}).get(key) for key in ("date", "calendar", "leap")}
    return digest(dependency)


def _state(payload, code):
    native = payload.get("status")
    if native == "reference_only":
        return "reference_only"
    if native == "intake_only":
        return "intake_only"
    if native == "partial":
        return "partial"
    if native == "needs_input" and (payload.get("five_grids") or any(item.get("five_grids") for item in payload.get("candidates", []) if isinstance(item, dict))):
        return "partial"
    if code or native in RETRY_STATUSES:
        return native if isinstance(native, str) else "error"
    return "ready"


def _execute(system, source, profile, birth, birth_file, work_dir=None):
    if system in source.get("deferred", {}):
        entry = source["deferred"][system]
        return {"system": system, "status": "needs_input", "message": entry["reason"], "required_inputs": entry.get("required_inputs", [])}, "needs_input", False
    if system == "bazi":
        if birth is None:
            return {"system": "bazi", "status": "needs_input", "message": "birth data is required"}, "needs_input", False
        return birth, "ready", True
    if system in ("palm","face") and source["options"].get(system,{}).get("observations"):
        options=source["options"][system]
        observed=read_json(options["observations"],max_bytes=1_000_000)
        if isinstance(observed,dict) and observed.get("schema_version")==2:
            from visual_intake import intake
            if set(observed)-{"schema_version","source","photo_refs","observations","note"} or observed.get("source") not in ("agent_viewed","user_reported"):
                raise ProjectError("invalid visual observation wrapper")
            refs=observed.get("photo_refs",[])
            if not isinstance(refs,list) or len(refs)>12 or any(not isinstance(ref,dict) or set(ref)!={"id","sha256"}
                or not isinstance(ref["id"],str) or not re.fullmatch(r"[a-f0-9]{32}",ref["id"])
                or not isinstance(ref["sha256"],str) or not re.fullmatch(r"[a-f0-9]{64}",ref["sha256"]) for ref in refs):
                raise ProjectError("invalid photo observation references")
            note=observed.get("note","")
            if not isinstance(note,str) or len(note)>4000:raise ProjectError("invalid photo observation note")
            value=intake(system,Path(options["image"]) if options.get("image") else None,observed.get("observations"))
            value.update(observation_source=observed["source"],photo_refs=copy.deepcopy(refs),observation_note=note)
            image=value.get("image") or {}
            clear=any(f.get("visibility")=="clear" for f in value["user_reported_observations"]["features"])
            matched=any(ref["sha256"]==image.get("sha256") for ref in refs)
            if observed["source"]=="agent_viewed" and clear and matched:
                value["observation_status"]="agent_observed"
                value["agent_visual_review_declared"]=True
            elif observed["source"]=="user_reported":
                value["observation_status"]="user_reported"
            return value,"intake_only",False
    args, missing = _arguments(system, source, profile, birth_file, work_dir)
    if missing:
        return {"system": system, "status": "needs_input", "message": missing}, "needs_input", False
    wrapped, code = dispatch(find_system(system), args)
    value = wrapped.get("payload", wrapped)
    if not isinstance(value, dict):
        raise ProjectError("adapter returned an invalid result")
    state = _state(value, code)
    if system in BIRTH_SYSTEMS and state in ("ready", "partial"):
        link = value.get("source_chart")
        if not isinstance(link, dict) or link.get("input_hash") != digest(birth["input"]):
            raise ProjectError("adapter shared birth-input link does not match this revision")
    cacheable = state in ("ready", "partial", "reference_only") and value.get("status") not in RETRY_STATUSES
    return value, state, cacheable


def _prepare(selected, source):
    prepared = []
    seen = set()
    for system in selected:
        if system == "names" and (source.get("name") or {}).get("mode") == "international":
            continue
        family = "astrology" if system in ("vedic", "qizheng", "horary") else system
        spec = find_system(family)
        if not spec.get("prepare") or family in seen:
            continue
        seen.add(family)
        args = ["--download"] if family == "names" else []
        directory = source["options"].get(system, {}).get("engine_dir")
        if system in EXTRA_MODULES:
            directory = source["options"].get(system, {}).get("params", {}).get("engine_dir")
        if family == "names":
            directory = (source.get("name") or {}).get("dictionary_dir")
            if directory:
                args += ["--dictionary-dir", directory]
        elif directory:
            args += ["--engine-dir", directory]
        result, code = dispatch(spec, args, prepare=True)
        prepared.append({"system": family, "exit": code, "result": result.get("payload", result)})
    return prepared


def _comparisons(root, directory, source, profile, selected, payloads):
    comparisons = []
    for other_id in source["compare_profiles"]:
        alternate = presets.resolve_profile(other_id)
        alternate_source = copy.deepcopy(source)
        alternate_source["profile"], alternate_source["settings"] = other_id, {}
        alternate_birth = _effective_birth(alternate_source, alternate)
        prefix = directory / "comparisons" / other_id
        prefix.mkdir(parents=True)
        alternate_file = prefix / "birth.json" if alternate_birth else None
        if alternate_birth:
            write_new_json(alternate_file, alternate_birth)
        for system in selected:
            if system not in BIRTH_SYSTEMS:
                continue
            original = payloads[system]
            relevant = "bazi" if system == "bazi" else "ziwei" if system == "ziwei" else "astrology"
            if profile["settings"][relevant] == alternate["settings"][relevant] and system != "bazi":
                continue
            value, state, _ = _execute(system, alternate_source, alternate, alternate_birth, alternate_file)
            write_new_json(prefix / (system + ".json"), value)
            try:
                difference = presets.compare_results(original, value)
            except ValueError as exc:
                difference = {"status": "comparison_unavailable", "reason": str(exc)}
            item = {"system": system, "base_profile": profile["id"], "other_profile": other_id,
                    "other_state": state, "result_file": str((prefix / (system + ".json")).relative_to(root).as_posix()),
                    "difference": difference}
            comparisons.append(item)
    return comparisons


def _annotation(system, source, directory, value, state):
    options = source["options"].get(system, {})
    if system not in ("palm", "face") or not options.get("annotations"):
        return value, state
    annotation = read_json(options["annotations"], max_bytes=1_000_000)
    if not isinstance(annotation, dict) or annotation.get("system") != system or not options.get("image"):
        return {**value, "annotation": {"status": "not_generated", "reason": "annotation system and explicit image must match the selected route"}}, "partial"
    target = directory / "observations" / (system + ".html")
    target.parent.mkdir(exist_ok=True)
    process = subprocess.run([sys.executable, "-X", "utf8", "-B", str(ROOT / "scripts/visual_annotations.py"),
        "--image", options["image"], "--annotations", options["annotations"], "--output", str(target)],
        capture_output=True, text=True, encoding="utf-8", timeout=60)
    result = json.loads(process.stdout)
    result["status"] = "created" if process.returncode == 0 else "not_generated"
    if process.returncode == 0:
        result["file"] = f"observations/{system}.html"
        result["sha256"] = file_digest(target, max_bytes=100_000_000)
    return {**value, "annotation": result}, state if process.returncode == 0 else "partial"


def run_project(workspace, incoming=None, *, patch=None, prepare_engines=False):
    # Validation before any project writes. For updates, the read/merge occurs
    # under the same lock as cache decisions and the active-pointer commit.
    preliminary = normalize_input(incoming) if incoming is not None else None
    root = validate_workspace(workspace, extra_protected=_external_roots(preliminary) if preliminary else ())
    with project_lock(root):
        project = load_project(root, required=patch is not None)
        previous = load_revision(root, project) if project else None
        if patch is not None:
            if incoming is not None or not isinstance(patch, dict):
                raise ProjectError("update requires one object patch and an existing project")
            old_input = read_json(contained(root, previous["input_file"]))
            source = normalize_input(merge_patch(old_input, patch))
        else:
            if preliminary is None:
                raise ProjectError("run requires input")
            source = preliminary
        validate_workspace(root, extra_protected=_external_roots(source))
        profile = presets.resolve_profile(source["profile"], source["settings"])
        selected = select_systems(source)
        preparation = _prepare(selected, source) if prepare_engines else []
        implementation = _implementation_fingerprint()
        revision, directory = reserve_revision(root)
        source, snapshots = _snapshot_files(root, revision, source)
        input_file = directory / "input.json"
        write_new_json(input_file, source)
        birth = _effective_birth(source, profile) if any(system in BIRTH_SYSTEMS and system not in source.get("deferred", {}) for system in selected) else None
        birth_file = directory / "birth.json" if birth else None
        if birth:
            write_new_json(birth_file, birth)
        payloads, components = {}, {}
        for system in selected:
            readiness = _engine_probe(system, source)
            key = _dependency(system, source, profile, birth, implementation, readiness)
            old = previous["components"].get(system) if previous else None
            reused = bool(old and old.get("dependency_hash") == key and old.get("cacheable") is True)
            # Visual inputs are snapshotted and rechecked every revision.
            reused = reused and system not in ("palm", "face")
            if reused:
                value = read_json(contained(root, old["file"]), max_bytes=10_000_000)
                state, cacheable = old["state"], old["cacheable"]
            else:
                value, state, cacheable = _execute(system, source, profile, birth, birth_file, directory)
            value, state = _annotation(system, source, directory, value, state)
            target = directory / "results" / (system + ".json")
            write_new_json(target, value)
            relative = target.relative_to(root).as_posix()
            components[system] = {"state": state, "file": relative, "sha256": file_digest(target),
                "dependency_hash": key, "cacheable": cacheable,
                "reused_from": previous["id"] if reused else None,
                "supersedes_result": old["file"] if old and not reused else None}
            payloads[system] = value
        comparisons = _comparisons(root, directory, source, profile, selected, payloads)
        report = build_report(revision, source, profile, components, payloads, comparisons)
        write_new_json(directory / "report.json", report)
        with (directory / "report.html").open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(report_html(report, payloads))
        incomplete = any(item["state"] not in ("ready", "reference_only") for item in components.values())
        state = "partial" if incomplete else "ready"
        artifacts = {path.relative_to(root).as_posix(): file_digest(path, max_bytes=100_000_000)
                     for path in directory.rglob("*") if path.is_file()}
        manifest = {"schema_version": 1, "id": revision, "created": utc_now(), "software_version": VERSION,
                    "status": state, "input_file": input_file.relative_to(root).as_posix(),
                    "input_hash": digest(source), "implementation": implementation,
                    "components": components, "artifacts": artifacts, "snapshots": snapshots,
                    "preparation": preparation, "report": f"versions/{revision}/report.html",
                    "supersedes": previous["id"] if previous else None}
        updated = commit_revision(root, project, manifest)
        warning = None
        try:
            write_atomic(root / "index.html", index_html(updated))
        except OSError as exc:
            warning = "active project committed, but index refresh failed: " + str(exc)
        return {"schema_version": 1, "status": state, "workspace": str(root), "revision": revision,
                "report": str(directory / "report.html"), "report_json": str(directory / "report.json"),
                "index": str(root / "index.html"), "selected_systems": selected,
                "recomputed": [name for name, item in components.items() if not item["reused_from"]],
                "reused": [name for name, item in components.items() if item["reused_from"]],
                "states": {name: item["state"] for name, item in components.items()},
                "question_hash": report["question_hash"],
                "interpretation_needed": [panel["system"] for panel in report["panels"] if panel["reading_status"] != "applied"],
                "warning": warning}


def project_status(workspace):
    root = validate_workspace(workspace)
    project = load_project(root, required=True)
    active = load_revision(root, project)
    return {"schema_version": 1, "status": active["status"], "workspace": str(root),
            "active_revision": active["id"], "components": active["components"],
            "report": str(contained(root, active["report"])),
            "history": [{**item, "validity": "active" if item["id"] == active["id"] else "superseded"}
                        for item in project["revisions"]]}


def main(argv=None):
    parser = Parser(description=__doc__, allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    for name in ("run", "update", "status"):
        child = sub.add_parser(name, allow_abbrev=False)
        child.add_argument("--workspace", required=True)
        if name != "status":
            child.add_argument("--input" if name == "run" else "--patch", required=True)
            child.add_argument("--prepare-engines", action="store_true", help="explicitly prepare the selected fixed external dependencies")
    try:
        args = parser.parse_args(argv)
        if args.command == "status":
            result = project_status(args.workspace)
        elif args.command == "run":
            result = run_project(args.workspace, read_json(args.input), prepare_engines=args.prepare_engines)
        else:
            result = run_project(args.workspace, patch=read_json(args.patch), prepare_engines=args.prepare_engines)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, TypeError, KeyError, OSError, ResourceError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"schema_version": 1, "status": "error", "error": {"code": "project_request", "message": str(exc)}}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
