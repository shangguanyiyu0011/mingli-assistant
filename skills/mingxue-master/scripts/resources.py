"""Verified offline resources. Never write caches into the installed skill.

Manifest v1: {"schema_version":1,"archive_sha256":"<64 hex>",
"files":{"relative/posix/path":{"sha256":"<64 hex>","size":123}}}.
Every archive file must be listed. Parts start at 000 or 001, contiguously.
"""
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SHA_RE = re.compile(r"[0-9a-f]{64}")


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ResourceError(f"Duplicate manifest key: {key}")
        value[key] = item
    return value


def _is_link(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


class ResourceError(RuntimeError):
    """A local bundle, override or cache could not be verified."""


def _safe_name(name):
    if not isinstance(name, str) or not name or any(c in name for c in '\\:*?"<>|'):
        raise ResourceError(f"Invalid resource path: {name!r}")
    rel = PurePosixPath(name)
    if rel.is_absolute() or any(p in ("", ".", "..") for p in name.split("/")):
        raise ResourceError(f"Invalid resource path: {name!r}")
    if any(ord(c) < 32 for c in name) or any(p.endswith((" ", ".")) for p in rel.parts):
        raise ResourceError(f"Invalid resource path: {name!r}")
    for part in rel.parts:
        stem = part.split(".")[0].upper()
        if stem in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                    *(f"LPT{i}" for i in range(1, 10))}:
            raise ResourceError(f"Non-portable resource path: {name!r}")
    return rel


def read_manifest(assets_dir=None):
    assets = Path(assets_dir) if assets_dir else ROOT / "assets"
    try:
        manifest = json.loads((assets / "resources-manifest.json").read_text(encoding="utf-8-sig"),
                              object_pairs_hook=_unique_object)
        if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1 or not SHA_RE.fullmatch(manifest.get("archive_sha256", "")):
            raise ResourceError("resources-manifest.json: invalid schema_version/archive_sha256")
        files = manifest.get("files")
        if not isinstance(files, dict) or not files:
            raise ResourceError("resources-manifest.json: files must be a nonempty object")
        seen = set()
        for name, item in files.items():
            _safe_name(name)
            if name.casefold() in seen:
                raise ResourceError(f"Duplicate or case-colliding resource path: {name}")
            seen.add(name.casefold())
            if (not isinstance(item, dict) or not SHA_RE.fullmatch(item.get("sha256", ""))
                    or type(item.get("size")) is not int or item["size"] < 0):
                raise ResourceError(f"Invalid manifest hash/size: {name}")
        for name in files:
            if any(str(parent) in files for parent in PurePosixPath(name).parents if str(parent) != "."):
                raise ResourceError(f"Resource path is both file and directory: {name}")
        checksum = (assets / "sources.sha256").read_text(encoding="ascii").strip().split()
        if not checksum or checksum[0] != manifest["archive_sha256"]:
            raise ResourceError("sources.sha256 does not agree with resources-manifest.json")
        return manifest
    except ResourceError:
        raise
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise ResourceError(f"Cannot read resource manifest in {assets}: {exc}") from exc


def verify_tree(root, manifest):
    """Verify the complete file set, sizes and SHA-256; no marker shortcuts."""
    root = Path(root)
    if _is_link(root) or not root.is_dir():
        raise ResourceError(f"Resource directory missing or is a symlink: {root}")
    actual = {}
    for path in root.rglob("*"):
        if _is_link(path):
            raise ResourceError(f"Resource symlink is not allowed: {path}")
        if path.is_file():
            actual[path.relative_to(root).as_posix()] = path
        elif not path.is_dir():
            raise ResourceError(f"Non-regular resource: {path}")
    expected = manifest["files"]
    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))[:3]
        extra = sorted(set(actual) - set(expected))[:3]
        raise ResourceError(f"Resource file set differs (missing={missing}, extra={extra})")
    for name, path in actual.items():
        item = expected[name]
        if path.stat().st_size != item["size"] or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ResourceError(f"Resource content failed SHA-256/size check: {name}")
    return root


@contextmanager
def _lock(path, timeout=60):
    """Process lock released on process death, on Windows/POSIX."""
    handle = path.open("a+b")
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    deadline = time.monotonic() + timeout
    locked = False
    try:
        while not locked:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise ResourceError(f"Timed out waiting for local resource cache lock: {path}")
                time.sleep(0.05)
        yield
    finally:
        if locked:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _payload(assets, expected):
    numbered = []
    for path in assets.glob("sources.zip.part*"):
        match = re.fullmatch(r"sources\.zip\.part(\d{3})", path.name)
        if not match:
            raise ResourceError(f"Unexpected archive part name: {path.name}")
        numbered.append((int(match[1]), path))
    numbered.sort()
    numbers = [n for n, _ in numbered]
    if not numbers or numbers[0] not in (0, 1) or numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        raise ResourceError("Missing/non-contiguous sources.zip.partNNN files (start at 000 or 001)")
    payload = b"".join(path.read_bytes() for _, path in numbered)
    if hashlib.sha256(payload).hexdigest() != expected:
        raise ResourceError("Bundled sources.zip SHA-256 check failed; restore the complete package")
    return payload


def _extract(payload, dest, manifest):
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        seen = set()
        for member in archive.infolist():
            name = member.filename[:-1] if member.is_dir() else member.filename
            rel = _safe_name(name)
            if name.casefold() in seen:
                raise ResourceError(f"Duplicate archive path: {name}")
            seen.add(name.casefold())
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))):
                raise ResourceError(f"Non-regular archive member: {name}")
            target = dest.joinpath(*rel.parts)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            expected = manifest["files"].get(name)
            if expected is None or member.file_size != expected["size"]:
                raise ResourceError(f"Archive member missing from manifest or wrong size: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, target.open("xb") as out:
                shutil.copyfileobj(src, out)
    verify_tree(dest, manifest)


def get_resources(*, assets_dir=None, cache_dir=None, resource_dir=None):
    """Return a verified root containing references/upstream; rebuild corrupt caches."""
    assets = Path(assets_dir) if assets_dir else ROOT / "assets"
    manifest = read_manifest(assets)
    override = resource_dir if resource_dir is not None else os.environ.get("MINGXUE_RESOURCE_DIR")
    try:
        if override:
            return verify_tree(Path(override).absolute(), manifest)
        base = Path(cache_dir or os.environ.get("MINGXUE_CACHE_DIR") or
                    (Path(tempfile.gettempdir()) / "mingxue-master-cache")).resolve()
        if base.is_relative_to(ROOT.resolve()):
            raise ResourceError("Resource cache must be outside the installed skill directory")
        base.mkdir(parents=True, exist_ok=True)
        key = manifest["archive_sha256"]
        dest = base / key
        # Verify the distribution too, even when a previously verified cache exists.
        payload = _payload(assets, key)
        with _lock(base / (key + ".lock")):
            if dest.exists() or _is_link(dest):
                try:
                    return verify_tree(dest, manifest)
                except ResourceError:
                    if dest.is_symlink() or dest.is_file():
                        dest.unlink()
                    elif _is_link(dest):
                        dest.rmdir()
                    else:
                        shutil.rmtree(dest)
            staging = Path(tempfile.mkdtemp(prefix=key + ".staging-", dir=base))
            try:
                _extract(payload, staging, manifest)
                os.replace(staging, dest)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
            return dest
    except ResourceError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ResourceError(f"Cannot prepare verified offline resources: {exc}") from exc


if __name__ == "__main__":
    try:
        print(get_resources())
    except ResourceError as error:
        raise SystemExit(f"Resource error: {error}")
