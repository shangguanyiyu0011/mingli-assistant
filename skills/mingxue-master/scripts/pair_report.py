"""Export a self-contained comparison of two verified, separately committed projects."""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from output_paths import guard_output
from project_store import contained, load_project, load_revision, read_json, validate_workspace


def load_person(workspace, fallback):
    root = validate_workspace(workspace)
    project = load_project(root, required=True)
    revision = load_revision(root, project)
    source = read_json(contained(root, revision["input_file"]))
    report = read_json(contained(root, f"versions/{revision['id']}/report.json"))
    payloads = {system:read_json(contained(root, meta["file"])) for system,meta in revision["components"].items()}
    report["person"] = source.get("person", {"name": fallback})
    report["birth_input"] = source.get("birth")
    report["location_input"] = source.get("location")
    return {"person": report["person"], "birth": source.get("birth"), "results": payloads}, report, payloads


def export_pair(project_a, project_b, output, relationship="伴侣"):
    target = Path(output).expanduser()
    if not target.is_absolute() or target.suffix.lower() != ".html" or target.exists():
        raise ValueError("请选择新的绝对 .html 输出路径。")
    target = guard_output(target)
    roots = [Path(p).expanduser().resolve() for p in (project_a, project_b)]
    if roots[0] == roots[1] or any(target.is_relative_to(p) for p in roots):
        raise ValueError("双人项目需分别保存，合参输出需位于两个项目外。")
    from pair_analysis import compare_people
    from personal_report import pair_html
    a, ar, ap = load_person(roots[0], "第一人")
    b, br, bp = load_person(roots[1], "第二人")
    comparison = compare_people(a, b, relationship)
    document = pair_html(ar, ap, br, bp, comparison, relationship)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as f:
        f.write(document)
    return {"status": comparison["status"], "report": str(target), "people": comparison["people"], "relationship": relationship}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument("--project-a", required=True)
    p.add_argument("--project-b", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--relationship", default="伴侣")
    a = p.parse_args(argv)
    try:
        print(json.dumps(export_pair(a.project_a,a.project_b,a.output,a.relationship),ensure_ascii=False))
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({"status":"error","message":str(exc)},ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
