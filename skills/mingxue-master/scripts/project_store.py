"""Local, revisioned project storage with an atomic active-revision pointer."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

SCHEMA = 1
MAX_JSON = 2_000_000
REVISION = re.compile(r"v[0-9]{6}")


class ProjectError(ValueError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ProjectError("duplicate JSON key: " + key)
        value[key] = item
    return value


def read_json(path, *, max_bytes=MAX_JSON):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > max_bytes:
        raise ProjectError("JSON file is missing or exceeds its size limit")
    value = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_pairs,
                       parse_constant=lambda value: (_ for _ in ()).throw(ProjectError("nonfinite JSON number")))
    canonical(value)
    return value


def file_digest(path, *, max_bytes=50_000_000):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > max_bytes:
        raise ProjectError("file is missing or exceeds its size limit")
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            result.update(chunk)
    return result.hexdigest()


def validate_workspace(workspace, *, extra_protected=()):
    from fortune import ROOT, validate_save_path
    from output_paths import protected_output_roots
    if not isinstance(workspace, (str, os.PathLike)):
        raise ProjectError("workspace must be an absolute path")
    path = Path(workspace).expanduser()
    if not path.is_absolute():
        raise ProjectError("workspace must be an absolute path")
    path = path.resolve()
    if path.exists() and not path.is_dir():
        raise ProjectError("workspace must be a directory")
    protected = [*protected_output_roots(extra_protected), ROOT.resolve(),
                 (ROOT.parents[1] / "runtime").resolve(),
                 (Path(tempfile.gettempdir()) / "mingxue-master-cache").resolve(),
                 (Path(tempfile.gettempdir()) / "mingxue-engines").resolve()]
    protected += [Path(os.environ[key]).expanduser().resolve() for key in
                  ("MINGXUE_RESOURCE_DIR", "MINGXUE_CACHE_DIR", "MINGXUE_ZIWEI_ENGINE",
                   "MINGXUE_ASTRO_ENGINE", "MINGXUE_NAME_DICTIONARY") if os.environ.get(key)]
    protected += [Path(item).expanduser().resolve() for item in extra_protected]
    if any(path.is_relative_to(root) or root.is_relative_to(path) for root in protected):
        raise ProjectError("workspace must not overlap skill, resources or engine caches")
    validate_save_path(path / (".path-check-" + uuid.uuid4().hex), extra_protected)
    return path


def contained(root, relative):
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ProjectError("invalid relative artifact path")
    rel = Path(relative)
    if rel.is_absolute() or any(part in ("..", ".") for part in rel.parts):
        raise ProjectError("artifact path escapes the project")
    target = root.joinpath(rel).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ProjectError("artifact link escapes the project")
    return target


def write_new_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def write_atomic(path, text):
    path = Path(path)
    handle, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def project_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".project.lock"
    token = uuid.uuid4().hex
    try:
        with lock.open("x", encoding="utf-8") as stream:
            json.dump({"token": token, "pid": os.getpid(), "created": utc_now()}, stream)
    except FileExistsError as exc:
        raise ProjectError("project is busy or has an interrupted lock; inspect .project.lock before recovery") from exc
    try:
        yield
    finally:
        try:
            if read_json(lock).get("token") == token:
                lock.unlink()
        except (OSError, ValueError):
            pass


def load_project(root, *, required=False):
    path = contained(root, "project.json")
    if not path.exists():
        if required:
            raise ProjectError("no project exists in this workspace")
        return None
    value = read_json(path)
    if (not isinstance(value, dict) or type(value.get("schema_version")) is not int or value.get("schema_version") != SCHEMA
            or not isinstance(value.get("project_id"), str)
            or not re.fullmatch(r"[0-9a-f]{32}", value["project_id"])
            or not isinstance(value.get("revisions"), list)):
        raise ProjectError("invalid project manifest")
    ids = [item.get("id") for item in value["revisions"] if isinstance(item, dict)]
    if (len(ids) != len(value["revisions"]) or len(ids) != len(set(ids))
            or any(not isinstance(item, str) or not REVISION.fullmatch(item) for item in ids)
            or value.get("active_revision") not in ids):
        raise ProjectError("invalid active revision or history")
    for item in value["revisions"]:
        if item.get("manifest") != f"versions/{item['id']}/manifest.json":
            raise ProjectError("invalid revision manifest path")
        if (not isinstance(item.get("created"), str) or not item["created"]
                or item.get("status") not in ("ready", "partial")
                or not isinstance(item.get("manifest_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", item["manifest_sha256"])):
            raise ProjectError("invalid revision history metadata")
        contained(root, item["manifest"])
    return value


def load_revision(root, project, revision=None):
    revision = revision or project["active_revision"]
    entry = next((item for item in project["revisions"] if item["id"] == revision), None)
    if entry is None:
        raise ProjectError("unknown committed revision")
    path = contained(root, entry["manifest"])
    if file_digest(path) != entry.get("manifest_sha256"):
        raise ProjectError("revision manifest checksum mismatch")
    value = read_json(path)
    if (not isinstance(value, dict) or value.get("id") != revision or type(value.get("schema_version")) is not int or value.get("schema_version") != SCHEMA
            or not isinstance(value.get("artifacts"), dict) or not isinstance(value.get("components"), dict)):
        raise ProjectError("invalid revision manifest")
    for relative, expected in value["artifacts"].items():
        if not relative.startswith(f"versions/{revision}/"):
            raise ProjectError("revision artifact belongs to a different revision")
        if file_digest(contained(root, relative), max_bytes=100_000_000) != expected:
            raise ProjectError("revision artifact checksum mismatch: " + relative)
    if value.get("input_file") != f"versions/{revision}/input.json" or value.get("report") != f"versions/{revision}/report.html":
        raise ProjectError("revision input or report path is invalid")
    for system, component in value["components"].items():
        if not isinstance(component, dict) or not re.fullmatch(r"[a-z][a-z_]*", system):
            raise ProjectError("invalid component entry")
        filename = f"versions/{revision}/results/{system}.json"
        if component.get("file") != filename or value["artifacts"].get(filename) != component.get("sha256"):
            raise ProjectError("component result is missing from the revision artifacts")
    for filename in (value["input_file"], value["report"], f"versions/{revision}/report.json"):
        if filename not in value["artifacts"]:
            raise ProjectError("required revision artifact is missing")
    if digest(read_json(contained(root, value["input_file"]))) != value.get("input_hash"):
        raise ProjectError("revision input hash does not match the saved input")
    return value


def reserve_revision(root):
    versions = root / "versions"
    if versions.exists() and not versions.resolve().is_relative_to(root.resolve()):
        raise ProjectError("versions directory escapes the workspace")
    versions.mkdir(exist_ok=True)
    numbers = [int(path.name[1:]) for path in versions.iterdir() if REVISION.fullmatch(path.name)]
    number = max(numbers, default=0) + 1
    if number > 999999:
        raise ProjectError("revision number limit reached")
    revision = f"v{number:06d}"
    directory = versions / revision
    directory.mkdir()
    return revision, directory


def commit_revision(root, project, revision_manifest):
    revision = revision_manifest["id"]
    relative = f"versions/{revision}/manifest.json"
    path = contained(root, relative)
    write_new_json(path, revision_manifest)
    entry = {"id": revision, "manifest": relative, "manifest_sha256": file_digest(path),
             "created": revision_manifest["created"], "status": revision_manifest["status"]}
    updated = {"schema_version": SCHEMA, "project_id": project["project_id"] if project else uuid.uuid4().hex,
               "active_revision": revision, "updated": utc_now(),
               "revisions": ([*project["revisions"]] if project else []) + [entry]}
    # The only authoritative publication step. Uncommitted directories remain
    # unreferenced and their revision numbers are never reused.
    write_atomic(root / "project.json", json.dumps(updated, ensure_ascii=False, indent=2) + "\n")
    return updated


def merge_patch(original, patch):
    """Object merge with explicit null retained (e.g. correction to unknown time)."""
    if not isinstance(patch, dict):
        return patch
    result = dict(original) if isinstance(original, dict) else {}
    for key, value in patch.items():
        result[key] = merge_patch(result.get(key), value) if isinstance(value, dict) else value
    return result
