"""Offline case lookup. Matches describe text/database resemblance, not validation."""
import argparse
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
from chart import (PILLAR_KEYS, TIME_BASES, build_chart, is_valid_pillar,
                   validate_pillars, write_json)
from resources import get_resources, ResourceError
from case_audit import load_quality_index

TIERS = ("four_pillars", "three_pillars", "similar", "same_day")


def parse_bazi(value):
    if isinstance(value, (list, tuple)) and not all(isinstance(item, str) for item in value):
        raise ValueError("bazi entries must be strings")
    text = " ".join(value) if isinstance(value, (list, tuple)) else value
    if not isinstance(text, str):
        raise ValueError("bazi must contain three or four sixty-cycle pillars")
    parts = text.split()
    if len(parts) == 1 and len(parts[0]) in (6, 8):
        parts = [parts[0][i:i + 2] for i in range(0, len(parts[0]), 2)]
    if len(parts) not in (3, 4) or not all(is_valid_pillar(p) for p in parts):
        raise ValueError("bazi must contain exactly three or four legal sixty-cycle pillars; no extra text")
    return dict(zip(PILLAR_KEYS, parts + ([None] if len(parts) == 3 else [])))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load_chart(path):
    """Accept only a canonical v3 output, recomputed through the same API."""
    path = Path(path)
    if path.stat().st_size > 2_000_000:
        raise ValueError("Chart JSON is unexpectedly large")
    saved = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_object)
    expected_keys = {"date", "time", "calendar", "leap", "sect", "timezone", "time_basis", "gender", "yun_sect",
                     "longitude", "true_solar", "fold"}
    if isinstance(saved, dict) and saved.get("schema_version") == 2:
        raise ValueError("schema_version=2 stored clocks without real timezone conversion; verify the original timezone/time basis and regenerate v3. No silent migration is permitted.")
    if not isinstance(saved, dict) or type(saved.get("schema_version")) is not int or saved.get("schema_version") != 3:
        raise ValueError("--chart requires canonical chart.py JSON schema_version=3")
    source = saved.get("input")
    if not isinstance(source, dict) or set(source) not in (expected_keys, expected_keys | {"shichen"}):
        raise ValueError("Chart input fields are missing or contain extra fields")
    canonical = build_chart(source["date"], source["time"], calendar=source["calendar"], leap=source["leap"],
                            sect=source["sect"], timezone=source["timezone"], time_basis=source["time_basis"],
                            gender=source["gender"], yun_sect=source["yun_sect"], longitude=source["longitude"],
                            true_solar=source["true_solar"], fold=source["fold"], shichen=source.get("shichen"))
    if saved != canonical:
        raise ValueError("Chart JSON is not canonical or has been modified; regenerate it using chart.py")
    return canonical


def load_cases(resource_root=None):
    root = Path(resource_root) if resource_root is not None else get_resources()
    path = root / "references/upstream/tongren-mingdian-skillpack/data/命例库.jsonl"
    records, issues = [], []
    with path.open(encoding="utf-8-sig") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line, object_pairs_hook=_unique_object)
                if not isinstance(record, dict) or not isinstance(record.get("id"), str):
                    raise ValueError("record must have a string id")
                validate_pillars(record.get("pillars"), allow_unknown=True)
                if not isinstance(record.get("sources", []), list):
                    raise ValueError("record sources must be a list")
                records.append(record)
            except (ValueError, TypeError) as exc:
                issues.append({"line": number, "reason": str(exc)})
    return records, issues


def _tier(query, case):
    matched = [key for key in PILLAR_KEYS if query[key] is not None and query[key] == case[key]]
    if len(matched) == 4:
        return "four_pillars", matched
    if len(matched) == 3:
        return "three_pillars", matched
    if len(matched) == 2:
        return "similar", matched
    if "day" in matched:
        return "same_day", matched
    return None, matched


def lookup_cases(queries, records, *, limit=10):
    """Classify each record once by its best match across possible input charts."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer from 1 to 100 per tier")
    if isinstance(queries, dict):
        queries = [queries]
    if not isinstance(queries, list) or not queries:
        raise ValueError("at least one query pillar set is required")
    for query in queries:
        validate_pillars(query, allow_unknown=True)
        if not any(query.values()):
            raise ValueError("query cannot have all pillars unknown")
    groups = {tier: [] for tier in TIERS}
    seen_ids = set()
    for record in records:
        validate_pillars(record.get("pillars"), allow_unknown=True)
        if record.get("id") in seen_ids:
            continue
        seen_ids.add(record.get("id"))
        best, matching = None, []
        for index, query in enumerate(queries):
            tier, fields = _tier(query, record["pillars"])
            if tier is None:
                continue
            rank = TIERS.index(tier)
            if best is None or rank < best:
                best, matching = rank, []
            if rank == best:
                matching.append({"candidate_index": index, "matched_fields": fields})
        if best is not None:
            tier = TIERS[best]
            # Retain library fields, including provenance and contrary/alternative records.
            found = dict(record)
            found.update({"match_tier": tier, "candidate_matches": matching,
                          "sources": record.get("sources", []),
                          "confidence": record.get("confidence"), "caution": record.get("caution"),
                          "variants": record.get("variants", [])})
            groups[tier].append(found)
    counts = {tier: len(items) for tier, items in groups.items()}
    for tier, items in groups.items():
        items.sort(key=lambda item: item.get("id", ""))
        groups[tier] = items[:limit]
    return {"groups": groups, "counts": counts, "limit_per_tier": limit,
            "match_semantics": {"four_pillars": "four supplied pillars equal",
                "three_pillars": "exactly three supplied pillars equal; unknown or differing fourth is retained",
                "similar": "exactly two supplied pillars equal", "same_day": "only the day pillar equals"},
            "caution": "Counts and tiers express database resemblance, not predictive validity or statistical confidence. "
                       "Record confidence is copied from the library, not computed from match counts."}


def query_chart(chart):
    queries = []
    for candidate in chart["candidates"]:
        p = dict(candidate["pillars"])
        if not chart["time_known"]:
            p["hour"] = None
        if p not in queries:
            queries.append(p)
    return queries


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--bazi", nargs="+", help="exactly three/four pillars, quoted or space-separated")
    source.add_argument("--chart", help="canonical chart.py JSON file")
    source.add_argument("--birth", help="birth date; always calls chart.build_chart")
    parser.add_argument("--time")
    parser.add_argument("--shichen", choices=tuple("子丑寅卯辰巳午未申酉戌亥"))
    parser.add_argument("--calendar", choices=("solar", "lunar"))
    parser.add_argument("--leap", action="store_true", default=None)
    parser.add_argument("--sect", type=int, choices=(1, 2))
    parser.add_argument("--timezone")
    parser.add_argument("--time-basis", choices=TIME_BASES)
    parser.add_argument("--longitude", type=float)
    parser.add_argument("--true-solar", action="store_true", default=None)
    parser.add_argument("--fold", type=int, choices=(0, 1))
    parser.add_argument("--gender", choices=("male", "female"))
    parser.add_argument("--yun-sect", type=int, choices=(1, 2))
    parser.add_argument("--limit", type=int, default=10, help="maximum returned per tier, 1..100")
    parser.add_argument("--json", action="store_true", help="JSON is also the default")
    parser.add_argument("--output", help="explicit JSON result path outside the skill")
    args = parser.parse_args(argv)
    try:
        birth_names = ("time", "shichen", "calendar", "leap", "sect", "timezone", "time_basis", "gender", "yun_sect",
                       "longitude", "true_solar", "fold")
        if args.birth is None and any(getattr(args, name) is not None for name in birth_names):
            raise ValueError("Birth options are permitted only with --birth; --chart preserves its own input")
        chart = None
        if args.bazi is not None:
            queries = [parse_bazi(args.bazi)]
        else:
            chart = load_chart(args.chart) if args.chart is not None else build_chart(
                args.birth, args.time, calendar=args.calendar or "solar", leap=bool(args.leap),
                sect=2 if args.sect is None else args.sect, timezone=args.timezone,
                time_basis=args.time_basis or "local-clock", gender=args.gender,
                yun_sect=1 if args.yun_sect is None else args.yun_sect,
                longitude=args.longitude, true_solar=bool(args.true_solar), fold=args.fold, shichen=args.shichen)
            queries = query_chart(chart)
        resource_root = get_resources()
        records, issues = load_cases(resource_root)
        result = lookup_cases(queries, records, limit=args.limit)
        database_path = resource_root / "references/upstream/tongren-mingdian-skillpack/data/命例库.jsonl"
        audit, by_id = load_quality_index(resource_root / "references/case-quality.json", database_path)
        for items in result["groups"].values():
            for record in items:
                record["quality"] = by_id[record["id"]]
        result.update({"schema_version": 1, "query_pillars": queries,
                       "database": {"valid_records": len(records), "excluded_invalid_records": issues,
                                    "quality_audit": audit["summary"],
                                    "quality_source_sha256": audit["source"]["sha256"],
                                    "quality_semantics": audit["semantics"]}})
        if chart is not None:
            result["chart"] = chart
        write_json(result, args.output)
    except (ValueError, OSError, ResourceError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
