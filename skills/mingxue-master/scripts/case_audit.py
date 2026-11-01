"""Recompute conservative library quality flags without rewriting any case."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

sys.dont_write_bytecode = True

SCHEMA_VERSION = 1
PILLARS = ("year", "month", "day", "hour")
# Exclude only identifiers, source lists and editorial audit fields. All case
# content, including name, pillars, narrative and uncertainty, must still agree.
IDENTIFIER_FIELDS = frozenset(("id", "evidence_id", "record_fingerprint", "sources",
                               "verification_status", "confidence_note"))
NARRATIVE_FIELDS = ("summary", "birth_text", "reasoning", "conclusion")
UNKNOWN_NAMES = re.compile(r"^(?:无名|無名|佚名|匿名|未知|不详|不詳|某(?:人|男|女|氏)?|命例|示例|示意命例|[?？-]+)$")
HOUR_DOUBT = re.compile(
    r"(?:时辰|時辰|出生时间|出生時間|出生时刻|出生時刻|生时|生時).{0,18}"
    r"(?:未知|不详|不詳|不明|存疑|有争议|有爭議|异说|異說|推定|推算|待考|不可考|可靠度[：:\s「]*低)"
    r"|(?:时柱|時柱).{0,12}(?:占位|存疑|推定|异说|異說)"
)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_library(path):
    """Read every nonblank JSONL row; report invalid rows instead of repairing."""
    path = Path(path)
    raw = path.read_bytes()
    rows, issues = [], []
    for number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line, object_pairs_hook=_unique_object)
            if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not record["id"]:
                raise ValueError("record requires a nonempty string id")
            if not isinstance(record.get("pillars"), dict):
                raise ValueError("record requires a pillars object")
            if set(record["pillars"]) != set(PILLARS):
                raise ValueError("pillars must contain exactly year/month/day/hour")
            if any(v is not None and not isinstance(v, str) for v in record["pillars"].values()):
                raise ValueError("pillar values must be text or null")
            rows.append((number, record))
        except (ValueError, TypeError) as exc:
            issues.append({"row": number, "reason": str(exc)})
    return rows, issues, hashlib.sha256(raw).hexdigest()


def content_fingerprint(record):
    """A content equality key, never an identity or truth assessment."""
    return _digest({k: v for k, v in record.items() if k not in IDENTIFIER_FIELDS})


def _usable_name(value):
    if not isinstance(value, str):
        return None
    value = "".join(unicodedata.normalize("NFKC", value).casefold().split())
    if not value or UNKNOWN_NAMES.fullmatch(value) or "示意命例" in value:
        return None
    return value


def _pillar_key(record):
    return tuple(record.get("pillars", {}).get(k) for k in PILLARS)


def _incompatible(a, b):
    """Missing data alone is not a contradictory pillar."""
    return any(a.get(k) is not None and b.get(k) is not None and a[k] != b[k] for k in PILLARS)


def audit_records(records, *, source_sha256=None, row_numbers=None, input_issues=None):
    """Return candidate duplicate/conflict groups; no records are merged/deleted.

    Same-name checks use explicit name only, not aliases or names guessed from
    narrative. Unnamed equal-pillar cases with differing narrative stay separate.
    A null pillar and a supplied pillar are incomplete data, not a contradiction.
    """
    records = list(records)
    row_numbers = list(range(1, len(records) + 1)) if row_numbers is None else list(row_numbers)
    if len(row_numbers) != len(records):
        raise ValueError("row_numbers and records must have equal length")
    issues = list(input_issues or [])
    quality, duplicate_candidates, name_candidates = [], defaultdict(list), defaultdict(list)
    stored_fingerprints = defaultdict(list)
    id_rows = defaultdict(list)
    for position, (row, record) in enumerate(zip(row_numbers, records)):
        case_id = record.get("id")
        id_rows[case_id].append(row)
        flags = []
        missing = [k for k in PILLARS if record.get("pillars", {}).get(k) is None]
        if missing:
            flags.append("incomplete_pillars")
        if "hour" in missing:
            flags.append("missing_hour")
        basis = record.get("hour_basis")
        if basis in ("占位", "推定"):
            flags.append("uncertain_hour")
        hour_fields = [k for k in ("birth_text", "caution")
                       if isinstance(record.get(k), str) and HOUR_DOUBT.search(record[k])]
        if hour_fields and "uncertain_hour" not in flags:
            flags.append("uncertain_hour")
        if record.get("pillars", {}).get("hour") is not None and not basis:
            flags.append("hour_basis_unspecified")
        if basis == "缺失" and record.get("pillars", {}).get("hour") is not None:
            flags.append("hour_metadata_mismatch")
        variants = record.get("variants") or []
        variant_rows = []
        if not isinstance(variants, list):
            issues.append({"row": row, "reason": "variants is not a list"})
            variants = []
        for variant_number, variant in enumerate(variants, 1):
            vp = variant.get("pillars") if isinstance(variant, dict) else None
            if isinstance(vp, dict) and _incompatible(record.get("pillars", {}), vp):
                variant_rows.append(variant_number)
        if variant_rows:
            flags.append("conflicting_variant_pillars")
        item = {"id": case_id, "evidence_id": record.get("evidence_id"), "row": row,
                "flags": flags, "missing_pillars": missing,
                "hour_caution_fields": hour_fields,
                "conflicting_variant_numbers": variant_rows,
                "duplicate_group_ids": [], "same_name_group_ids": [],
                "birth_verification_status": "unverified_historical_record"}
        quality.append(item)
        if isinstance(record.get("record_fingerprint"), str) and record["record_fingerprint"]:
            stored_fingerprints[record["record_fingerprint"]].append(position)
        # Equal blank templates do not establish duplicated source content.
        if any(isinstance(record.get(k), str) and record[k].strip() for k in NARRATIVE_FIELDS):
            duplicate_candidates[content_fingerprint(record)].append(position)
        name = _usable_name(record.get("name"))
        if name:
            name_candidates[name].append(position)
    groups = {"exact_content_duplicates": [], "same_name_different_pillars": [],
              "legacy_fingerprint_collisions": []}
    for digest, positions in sorted(duplicate_candidates.items()):
        if len(positions) < 2:
            continue
        group_id = "CQ-DUP-" + digest[:16]
        members = [{"id": quality[p]["id"], "row": quality[p]["row"]} for p in positions]
        groups["exact_content_duplicates"].append({"group_id": group_id, "content_sha256": digest,
                                                   "members": members, "action": "retain_all"})
        for p in positions:
            quality[p]["flags"].append("exact_content_duplicate")
            quality[p]["duplicate_group_ids"].append(group_id)
    for name, positions in sorted(name_candidates.items()):
        if not any(_incompatible(records[a]["pillars"], records[b]["pillars"])
                   for a in positions for b in positions if a < b):
            continue
        group_id = "CQ-NAME-" + _digest(name)[:16]
        members = [{"id": quality[p]["id"], "row": quality[p]["row"],
                    "pillars": dict(records[p]["pillars"])} for p in positions]
        groups["same_name_different_pillars"].append({"group_id": group_id, "normalized_name": name,
                                                     "members": members, "action": "retain_all_and_review_identity"})
        for p in positions:
            quality[p]["flags"].append("same_name_different_pillars")
            quality[p]["same_name_group_ids"].append(group_id)
    for stored, positions in sorted(stored_fingerprints.items()):
        distinct_content = {content_fingerprint(records[p]) for p in positions}
        if len(positions) > 1 and len(distinct_content) > 1:
            group_id = "CQ-FP-" + _digest(stored)[:16]
            groups["legacy_fingerprint_collisions"].append({
                "group_id": group_id, "members": [{"id": quality[p]["id"], "row": quality[p]["row"]} for p in positions],
                "distinct_content_count": len(distinct_content),
                "action": "retain_all; stored fingerprint does not prove duplicate content"})
            for p in positions:
                quality[p]["flags"].append("legacy_fingerprint_collision")
    for case_id, rows in id_rows.items():
        if len(rows) > 1:
            issues.append({"reason": "duplicate record id", "id": case_id, "rows": rows})
    counts = Counter(flag for item in quality for flag in item["flags"])
    return {"schema_version": SCHEMA_VERSION, "audit_version": "1.0.0",
            "source": {"logical_name": "命例库.jsonl", "sha256": source_sha256,
                       "parsed_records": len(records)},
            "semantics": {"duplicate": "all content fields equal except ids, source lists and editorial audit metadata; requires narrative",
                          "identity": "explicit normalized name only; aliases and unnamed same-pillar records are not identities",
                          "verification": "structural/text quality only; no birth data or prediction was verified",
                          "missing_hour": "structured hour pillar is null; a birth_text may still contain an unconverted time",
                          "action": "retain every source record; group membership never proves truth or falsity"},
            "summary": {"records": len(records), "flag_counts": dict(sorted(counts.items())),
                        "exact_duplicate_groups": len(groups["exact_content_duplicates"]),
                        "exact_duplicate_excess_records": sum(len(g["members"]) - 1 for g in groups["exact_content_duplicates"]),
                        "same_name_different_pillar_groups": len(groups["same_name_different_pillars"]),
                        "legacy_fingerprint_collision_groups": len(groups["legacy_fingerprint_collisions"]),
                        "issues": len(issues)},
            "issues": issues, "groups": groups, "records": quality}


def audit_library(path):
    rows, issues, sha256 = read_library(path)
    return audit_records([r for _, r in rows], source_sha256=sha256,
                         row_numbers=[n for n, _ in rows], input_issues=issues)


def load_quality_index(index_path, database_path):
    """Refuse stale quality metadata before a caller attaches it to results."""
    value = json.loads(Path(index_path).read_text(encoding="utf-8-sig"))
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported case quality schema")
    actual = hashlib.sha256(Path(database_path).read_bytes()).hexdigest()
    if value.get("source", {}).get("sha256") != actual:
        raise ValueError("case quality index is stale; rerun case_audit.py")
    if value.get("issues"):
        raise ValueError("case quality index has unresolved input issues")
    items = value.get("records", [])
    if len(items) != value.get("source", {}).get("parsed_records"):
        raise ValueError("case quality index has inconsistent record count")
    by_id = {item["id"]: item for item in items}
    if len(by_id) != len(items):
        raise ValueError("case quality index has duplicate record ids")
    return value, by_id


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--database", required=True, help="input JSONL; never modified")
    parser.add_argument("--output", help="new quality JSON path, distinct from database")
    parser.add_argument("--json", action="store_true", help="JSON is also the default")
    args = parser.parse_args(argv)
    try:
        database = Path(args.database).resolve()
        if args.output and Path(args.output).resolve() == database:
            raise ValueError("output must differ from the source database")
        value = audit_library(database)
        text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            dest = Path(args.output)
            from output_paths import guard_output
            guard_output(dest)
            if dest.exists():
                raise ValueError("quality output already exists; use a new path")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("x", encoding="utf-8") as stream:
                stream.write(text)
        else:
            print(text, end="")
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
