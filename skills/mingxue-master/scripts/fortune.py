"""One local dispatcher and explicit input-chain bundle for separate traditions."""
import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
from chart import write_json

ROOT = Path(__file__).resolve().parents[1]


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def registry():
    value = json.loads((ROOT / "references/systems.json").read_text(encoding="utf-8"))
    return value["systems"]


def find_system(name):
    for item in registry():
        if name == item["id"] or name in item.get("aliases", []):
            return item
    raise ValueError(f"Unknown system: {name}; use --list")


def _input_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def compatible_system(declared, wanted):
    if declared == wanted:
        return True
    if wanted == "names" and declared in ("name_five_grids", "name_candidate_comparison", "name_character_lookup"):
        return True
    if wanted == "vedic" and declared == "astrology":
        return True
    try:
        return find_system(declared)["id"] == wanted
    except (ValueError, TypeError):
        return False


def validate_result_type(value, spec):
    declared = value.get("system")
    if declared is not None and not compatible_system(declared, spec["id"]):
        raise ValueError("JSON declares a different system than its selected bundle route")
    if declared is None:
        bazi_shape = (spec["id"] == "bazi" and value.get("schema_version") == 3
            and isinstance(value.get("input"), dict) and isinstance(value.get("pillars"), dict)
            and isinstance(value.get("candidates"), list) and isinstance(value.get("time_context"), dict))
        if not bazi_shape and spec["level"] != "reference_only":
            raise ValueError("calculated result has no compatible system type")
    if spec["id"] == "vedic" and (not isinstance(value.get("zodiac"), dict) or value["zodiac"].get("type") != "sidereal"):
        raise ValueError("vedic bundle data must explicitly use the sidereal zodiac")


def validate_save_path(save_path, extra_protected=()):
    path = Path(save_path).expanduser()
    if not path.is_absolute() or path.exists():
        raise ValueError("--save requires a new absolute output path; use a new version filename")
    resolved = path.resolve()
    from output_paths import guard_output
    guard_output(path, extra_protected)
    protected = [ROOT.resolve(), (ROOT.parents[1] / "runtime").resolve(),
        (Path(tempfile.gettempdir()) / "mingxue-master-cache").resolve(),
        (Path(tempfile.gettempdir()) / "mingxue-engines").resolve()]
    protected += [Path(os.environ[key]).expanduser().resolve() for key in
        ("MINGXUE_CACHE_DIR", "MINGXUE_RESOURCE_DIR", "MINGXUE_ZIWEI_ENGINE", "MINGXUE_ASTRO_ENGINE") if os.environ.get(key)]
    protected += [Path(value).expanduser().resolve() for value in extra_protected]
    if any(resolved.is_relative_to(root) for root in protected):
        raise ValueError("user results must be outside skill, resources and engine caches")
    if any(parent.name.casefold() in ("engine-cache", "mingxue-engines") for parent in (resolved, *resolved.parents)):
        raise ValueError("user results must be outside engine caches")
    return path


def emit(value, save_path=None):
    if save_path is not None:
        path = validate_save_path(save_path)
        payload = value.get("payload", value) if isinstance(value, dict) else value
        with redirect_stdout(io.StringIO()):
            write_json(payload, str(path))
    print(json.dumps(value, ensure_ascii=False, indent=2))


def bundle(items, *, topic=None, allow_different_inputs=False):
    if not isinstance(items, list) or not 1 <= len(items) <= 50:
        raise ValueError("provide 1..50 explicit system=absolute_JSON_path items")
    panels, hashes, seen = [], {}, set()
    for entry in items:
        if not isinstance(entry, str) or "=" not in entry:
            raise ValueError("each item must be system=absolute_JSON_path")
        label, filename = entry.split("=", 1)
        system_name, separator, tag = label.partition("@")
        if separator and (not tag or len(tag) > 64 or any(c in tag for c in "=/@\r\n")):
            raise ValueError("invalid explicit panel label")
        spec = find_system(system_name)
        panel_id = spec["id"] + ("@" + tag if separator else "")
        if panel_id in seen:
            raise ValueError("duplicate system/panel in bundle; use explicit SYSTEM@LABEL for separate panels")
        seen.add(panel_id)
        path = Path(filename).expanduser()
        if not path.is_absolute() or not path.is_file() or path.stat().st_size > 10_000_000:
            raise ValueError("bundle requires existing absolute JSON files of at most 10 MB")
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("each result must be a JSON object")
        if "payload" in value:
            if not compatible_system(value.get("system"), spec["id"]):
                raise ValueError("wrapper declares a different system than its bundle route")
            value = value["payload"]
        if not isinstance(value, dict):
            raise ValueError("result payload must be a JSON object")
        validate_result_type(value, spec)
        link = value.get("source_chart")
        if spec["id"] == "bazi" and value.get("schema_version") == 3 and isinstance(value.get("input"), dict):
            link = {"schema_version": 3, "input_hash": _input_hash(value["input"])}
        if link is not None:
            if (not isinstance(link, dict) or link.get("schema_version") != 3
                    or not isinstance(link.get("input_hash"), str)
                    or len(link["input_hash"]) != 64
                    or any(c not in "0123456789abcdef" for c in link["input_hash"])):
                raise ValueError("invalid declared shared-input link")
            hashes[panel_id] = link["input_hash"]
        panels.append({"panel_id": panel_id, "system": spec["id"], "name": spec["name"], "capability": spec["level"],
            "source_file": str(path.resolve()), "source_file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "input_link": link, "result": value})
    distinct = set(hashes.values())
    if len(distinct) > 1 and not allow_different_inputs:
        raise ValueError("shared birth-input links differ; regenerate affected results. "
                         "Use --allow-different-inputs only for an intentional comparison of separate inputs.")
    status = ("different_declared_inputs" if len(distinct) > 1 else
              "same_declared_input" if len(hashes) >= 2 else "insufficient_shared_links")
    return {"schema_version": 1, "system": "multi_system", "status": "collected", "topic": topic,
        "panels": panels, "input_chain": {"status": status, "linked_systems": list(hashes),
            "unlinked_systems": [p["panel_id"] for p in panels if p["panel_id"] not in hashes],
            "verification": "declared input-chain comparison only; calculations were not reexecuted"},
        "cross_system_conclusion": {"status": "not_automatically_inferred",
            "method": "present each tradition and its assumptions separately; explain overlap and disagreement in prose",
            "probability": None,
            "limitations": "Agreement is not independent validation; no voting, combined fate score or certainty multiplier."}}


def dispatch(spec, args, *, prepare=False):
    script = spec.get("prepare") if prepare else spec.get("script")
    if not script:
        if prepare:
            if args:
                raise ValueError("this system has no external engine preparation command")
            return {"system": spec["id"], "status": "not_required", "capability": spec["level"]}, 0
        if args and args != ["--probe"]:
            raise ValueError("This system has reference guidance only; it does not provide an automated chart engine")
        return {"system": spec["id"], "status": "reference_only", "capability": spec["level"],
                "reference": spec["reference"], "required_inputs": spec["inputs"]}, 0
    path = ROOT / "scripts" / script
    if not path.is_file():
        raise ValueError("Declared tool is not packaged")
    tail = list(args)
    def values(option):
        found = [a.split("=", 1)[1] for a in tail if a.startswith(option + "=")]
        for i, value in enumerate(tail):
            if value == option:
                if i + 1 >= len(tail):
                    raise ValueError(option + " requires a value")
                found.append(tail[i + 1])
        return found
    if spec["id"] in ("palm", "face"):
        if any(value != spec["id"] for value in values("--system")):
            raise ValueError("visual route and --system must agree")
        if tail == ["--probe"]:
            tail = []
    if spec["id"] == "bazi" and tail == ["--probe"]:
        path, tail = ROOT / "scripts/doctor.py", ["--json"]
    if spec["id"] == "vedic" and not prepare:
        if values("--zodiac"):
            if any(value != "sidereal" for value in values("--zodiac")):
                raise ValueError("vedic route requires sidereal zodiac")
        else:
            tail += ["--zodiac", "sidereal"]
        if not values("--ayanamsa"):
            tail += ["--ayanamsa", "lahiri"]
        if tail == ["--probe", "--zodiac", "sidereal", "--ayanamsa", "lahiri"]:
            tail = ["--probe"]
    if spec.get("prefix") and not prepare and not (spec["script"] == "symbolic.py" and tail == ["--probe"]):
        tail = list(spec["prefix"]) + tail
    result = subprocess.run([sys.executable, "-X", "utf8", "-B", str(path), *tail],
        capture_output=True, text=True, encoding="utf-8", timeout=180)
    try:
        payload = json.loads(result.stdout) if result.stdout.strip() else None
    except ValueError:
        payload = None
    if payload is None:
        if result.returncode == 0 and any(arg in ("--help", "-h") for arg in tail):
            return {"system": spec["id"], "status": "help", "help": result.stdout}, 0
        return {"system": spec["id"], "status": "error",
                "error": {"code": "tool_output", "message": result.stderr.strip() or "Tool returned no JSON"}}, result.returncode or 2
    return {"schema_version": 1, "system": spec["id"],
            "status": "ok" if result.returncode == 0 else "error",
            "capability": spec["level"], "payload": payload}, result.returncode


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        args = [part for arg in args for part in (["--save", arg.split("=", 1)[1]] if arg.startswith("--save=") else [arg])]
        explicit_engines = [arg.split("=", 1)[1] for arg in args if arg.startswith("--engine-dir=")]
        explicit_engines += [args[i + 1] for i, arg in enumerate(args[:-1]) if arg == "--engine-dir"]
        save_path = None
        if "--save" in args:
            if args.count("--save") != 1 or any(arg == "--output" or arg.startswith("--output=") for arg in args):
                raise ValueError("use one --save or the native --output option, not both")
            i = args.index("--save")
            if i + 1 >= len(args):
                raise ValueError("--save requires an absolute path")
            save_path = args[i + 1]
            del args[i:i + 2]
            validate_save_path(save_path, explicit_engines)
        if not args or args == ["--list"]:
            value, code = {"schema_version": 1, "systems": registry(),
                "readiness_note": "Capability levels are explicit; external engines require preparation and probe."}, 0
        elif args and args[0] in ("web", "visual", "workbench"):
            if save_path is not None:
                raise ValueError("workbench does not accept --save")
            from workbench import main as workbench_main
            return workbench_main(args[1:])
        elif args and args[0] in ("workflow", "project"):
            if save_path is not None:
                raise ValueError("workflow saves a revision in --workspace; do not combine it with --save")
            from workflow import main as workflow_main
            return workflow_main(args[1:])
        elif args and args[0] == "presets":
            if save_path is not None:
                raise ValueError("use the preset tool's explicit output options")
            from presets import main as presets_main
            return presets_main(args[1:])
        elif args == ["--probe"]:
            from doctor import diagnose
            value = diagnose()
            code = 0 if value["ok"] else 1
        elif args[0] in ("--help", "-h") or (args[0] == "bundle" and any(x in ("--help", "-h") for x in args)):
            value, code = {"usage": ["fortune.py --list", "fortune.py describe SYSTEM",
                "fortune.py SYSTEM <system tool arguments> [--save NEW_ABSOLUTE_JSON_PATH]", "fortune.py prepare SYSTEM <engine directory arguments>",
                "fortune.py bundle --item SYSTEM=ABSOLUTE_JSON_PATH [--item ...] [--output ABSOLUTE_JSON_PATH]"],
                "note": "Separate methods and inputs are retained. Reference-only routes do not invent charts."}, 0
        elif args[0] == "describe":
            if len(args) != 2:
                raise ValueError("describe requires one system id")
            value, code = find_system(args[1]), 0
        elif args[0] == "bundle":
            parser = Parser(prog="fortune.py bundle", allow_abbrev=False)
            parser.add_argument("--item", action="append", required=True)
            parser.add_argument("--topic")
            parser.add_argument("--allow-different-inputs", action="store_true")
            parser.add_argument("--output")
            parsed = parser.parse_args(args[1:])
            if parsed.output:
                output_path = Path(parsed.output).expanduser().resolve()
                for entry in parsed.item:
                    if "=" not in entry:
                        continue
                    source_path = Path(entry.split("=", 1)[1]).expanduser()
                    if output_path == source_path.resolve() or (output_path.exists() and source_path.exists() and output_path.samefile(source_path)):
                        raise ValueError("bundle output must not overwrite an input result")
            value = bundle(parsed.item, topic=parsed.topic, allow_different_inputs=parsed.allow_different_inputs)
            if save_path is not None:
                emit(value, save_path)
            else:
                write_json(value, parsed.output)
            return 0
        else:
            prepare = args[0] == "prepare"
            if prepare:
                if len(args) < 2:
                    raise ValueError("prepare requires a system id")
                spec, tail = find_system(args[1]), args[2:]
            else:
                spec, tail = find_system(args[0]), args[1:]
            if not prepare and spec["id"] == "bazi" and "--bazi" in tail:
                parser = Parser(prog="fortune.py bazi --bazi", allow_abbrev=False)
                parser.add_argument("--bazi", nargs="+", required=True)
                parser.add_argument("--output")
                given = parser.parse_args(tail)
                from case_lookup import parse_bazi
                from pillar_details import build_details
                pillars = parse_bazi(given.bazi)
                payload = {"schema_version": 1, "system": "bazi", "status": "provided_pillars",
                           "pillars": pillars, "details": build_details(pillars), "source_chart": None,
                           "basis": "user supplied pillars; birth calendar and clock were not recalculated"}
                value = {"schema_version": 1, "system": "bazi", "status": "ok",
                         "capability": "calculation", "payload": payload}
                if given.output:
                    with redirect_stdout(io.StringIO()):
                        write_json(payload, given.output)
                emit(value, save_path)
                return 0
            value, code = dispatch(spec, tail, prepare=prepare)
        emit(value, save_path)
        return code
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "error", "error": {"code": "invalid_request", "message": str(exc)}}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
