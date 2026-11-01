"""Read-only local readiness report. No network calls, installs or user-data writes."""
import argparse
import importlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True


def diagnose():
    checks = []
    def check(name, action):
        try:
            detail = action()
            checks.append({"name": name, "ok": True, "detail": detail})
            return detail
        except Exception as exc:
            checks.append({"name": name, "ok": False, "error": str(exc)})
            return None
    check("python", lambda: {"version": sys.version.split()[0], "supported": sys.version_info >= (3, 10)}
          if sys.version_info >= (3, 10) else (_ for _ in ()).throw(RuntimeError("Python 3.10+ required")))
    for module in ("resources", "time_conversion", "pillar_details", "chart", "case_lookup", "case_audit", "book_search", "tieban_run", "feedback",
                   "fortune", "iching", "ziwei", "astrology", "name_analysis", "name_dictionary", "symbolic", "visual_intake", "almanac",
                   "runtime_paths", "bootstrap", "output_paths", "presets", "project_store", "reporting", "workflow", "visual_annotations"):
        check("import:" + module, lambda name=module: str(importlib.import_module(name).__file__))
    root = check("resources", lambda: str(importlib.import_module("resources").get_resources()))
    if root:
        check("calendar_library", lambda: str(importlib.import_module("chart").calendar_library().__file__))
        check("timezone_database", lambda: importlib.import_module("time_conversion").timezone_metadata(Path(root)))
        def timezone_probe():
            from datetime import datetime
            zone = importlib.import_module("time_conversion").load_zone("America/New_York", Path(root))
            first = datetime(2024, 11, 3, 1, 30, tzinfo=zone, fold=0).utcoffset().total_seconds()
            second = datetime(2024, 11, 3, 1, 30, tzinfo=zone, fold=1).utcoffset().total_seconds()
            if (first, second) != (-14400, -18000):
                raise RuntimeError("Bundled timezone fold probe failed")
            return {"zone": zone.key, "fold_offsets_seconds": [first, second]}
        check("timezone_resolution", timezone_probe)
        def details_probe():
            value = importlib.import_module("pillar_details").build_details(
                {"year": "癸巳", "month": "甲子", "day": "丁酉", "hour": "甲辰"})
            return {"day_master": value["day_master"], "complete": value["complete"]}
        check("pillar_details", details_probe)
        def counts():
            records, invalid = importlib.import_module("case_lookup").load_cases(root)
            return {"case_records_valid": len(records), "case_records_invalid": len(invalid),
                    "invalid_records": invalid,
                    "complete_four_pillars": sum(all(r["pillars"].values()) for r in records),
                    "resource_files": sum(p.is_file() for p in Path(root).rglob("*"))}
        check("data_counts", counts)
        def quality_audit():
            audit, _ = importlib.import_module("case_audit").load_quality_index(
                Path(root) / "references/case-quality.json",
                Path(root) / "references/upstream/tongren-mingdian-skillpack/data/命例库.jsonl")
            return audit["summary"]
        check("case_quality", quality_audit)
        def evidence_cards():
            path = Path(__file__).resolve().parents[1] / "references/classics/index.json"
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            return {"path": str(path), "available": isinstance(value, (dict, list))}
        check("classic_evidence", evidence_cards)
    def system_files():
        systems = importlib.import_module("fortune").registry()
        missing = [item["reference"] for item in systems if not (Path(__file__).resolve().parents[1] / item["reference"]).is_file()]
        if missing:
            raise RuntimeError("Missing system references: " + ", ".join(missing))
        return {"systems": len(systems), "levels": {item["id"]: item["level"] for item in systems}}
    check("system_interfaces", system_files)
    optional = {}
    for name in ("ziwei", "astrology"):
        try:
            optional[name] = importlib.import_module(name).probe()
        except Exception as exc:
            optional[name] = {"status": "needs_setup", "message": str(exc)}
    try:
        optional["name_dictionary"] = importlib.import_module("name_dictionary").dictionary_status()
    except Exception as exc:
        optional["name_dictionary"] = {"status": "needs_setup", "message": str(exc)}
    return {"schema_version": 2, "ok": all(item["ok"] for item in checks), "checks": checks,
            "optional_engines": optional,
            "scope": "native resources and interfaces checked locally; external engine readiness is reported separately; no prediction validity assessment"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--json", action="store_true", help="JSON is also the default")
    parser.parse_args(argv)
    result = diagnose()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
