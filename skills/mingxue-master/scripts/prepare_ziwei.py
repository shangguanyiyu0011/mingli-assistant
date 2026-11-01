"""Explicit preparation of pinned official archives in an external Ziwei cache."""
from __future__ import annotations
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
import tempfile
import urllib.request

sys.dont_write_bytecode = True
from ziwei import ENGINE_VERSION, ENGINE_ABI, ZiweiError, engine_directory, probe
from bootstrap import find_node
from runtime_paths import validate_external_directory

DEPENDENCY_PINS = {"iztro": ENGINE_VERSION, "dayjs": "1.11.23", "i18next": "23.16.8",
                   "lunar-lite": "0.2.8", "lunar-typescript": "1.8.6", "@babel/runtime": "7.29.10"}
INTEGRITIES = {
    "iztro": "sha512-yFY+ytb1ryOZkL3yx6LKeGQ3ZWo7GOoJIg3lU1yRWxJRKBgVRNNM+Ap1ZfhgWIs3A2WqW7WaSRPjCHi8C60rYg==",
    "dayjs": "sha512-QDTCU0M0MxR3hQfnlDJfwekQiaanm1ubOD231u73WBckQ/fsamwRLiE2GBz6D3a/xF1NgfiDLJjXBa1hYOYTtQ==",
    "i18next": "sha512-06r/TitrM88Mg5FdUXAKL96dJMzgqLE5dv3ryBAra4KCwD9mJ4ndOTS95ZuymIGoE+2hzfdaMak2X11/es7ZWg==",
    "lunar-lite": "sha512-Y4tba4RaIFI0ikImJhgoEsyqtDE64lJIM3yFwRX01dbmagCDq7rNmpDQFrSFFy4WXeuywdRVFpIBoT1GGCEizw==",
    "lunar-typescript": "sha512-5Eo4T/cnuXfrgO4k5LCpOGHIUOuz5hCF/IfNv0T29WY2shR36Hiz+ecN9WjnUuxUKhql9gbOkPaQoqLFKtPRNA==",
    "@babel/runtime": "sha512-NpugTzbKgGrNe45Ui32cN8vCFFMxVtP/9rtfwv0nP5FRDAjvYBxJcLVpYA9mr1jxP6cnIT7x9LUzuDTbWYYNRA==",
}


def archive_filename(name):
    return name.replace("@", "").replace("/", "-") + "-" + DEPENDENCY_PINS[name] + ".tgz"


def archive_url(name):
    return f"https://registry.npmjs.org/{name}/-/{name.split('/')[-1]}-{DEPENDENCY_PINS[name]}.tgz"


def download_archive(name, destination):
    """Patchable I/O boundary. Never called by probe or verification."""
    request = urllib.request.Request(archive_url(name), headers={"User-Agent": "mingxue-engine-preparation/1"})
    with urllib.request.urlopen(request, timeout=60) as response, Path(destination).open("wb") as stream:
        total = 0
        while block := response.read(65536):
            total += len(block)
            if total > 15_000_000:
                raise ZiweiError("setup_failed", "Pinned archive exceeded download size limit")
            stream.write(block)


def archive_files(name, source):
    payload = Path(source).read_bytes()
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(payload).digest()).decode("ascii")
    if integrity != INTEGRITIES[name]:
        raise ZiweiError("engine_integrity_error", f"Fixed archive integrity mismatch: {name}")
    files, names, total = {}, set(), 0
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        for member in archive.getmembers():
            rel = PurePosixPath(member.name)
            if (rel.is_absolute() or not rel.parts or rel.parts[0] != "package"
                    or any(p in ("", ".", "..") for p in rel.parts) or "\\" in member.name or ":" in member.name):
                raise ZiweiError("engine_integrity_error", "Unsafe package archive member")
            if member.isdir():
                continue
            if not member.isfile() or len(rel.parts) < 2:
                raise ZiweiError("engine_integrity_error", "Package links/special members are forbidden")
            total += member.size
            if total > 100_000_000:
                raise ZiweiError("engine_integrity_error", "Package expansion limit exceeded")
            key = PurePosixPath("node_modules", *name.split("/"), *rel.parts[1:]).as_posix()
            if key.casefold() in names:
                raise ZiweiError("engine_integrity_error", "Duplicate package archive member")
            names.add(key.casefold())
            with archive.extractfile(member) as stream:
                files[key] = stream.read()
    return files


def _lock_value():
    return {"name": "mingxue-ziwei-engine", "lockfileVersion": 3, "requires": True,
            "packages": {"": {"dependencies": DEPENDENCY_PINS}, **{
                "node_modules/" + name: {"version": version, "resolved": archive_url(name), "integrity": INTEGRITIES[name]}
                for name, version in DEPENDENCY_PINS.items()}}}


def verify_engine_directory(directory, *, allow_legacy=True):
    """Strict new-cache validation; explicit old caches retain version-only use."""
    directory = validate_external_directory(directory)
    marker = directory / "mingxue-engine.json"
    try:
        manifest = json.loads(marker.read_text(encoding="utf-8")) if marker.is_file() else {}
    except (OSError, ValueError) as exc:
        raise ZiweiError("engine_integrity_error", "Engine manifest is invalid") from exc
    if manifest.get("integrity_schema_version") != 1:
        if allow_legacy:
            try:
                installed = json.loads((directory / "node_modules/iztro/package.json").read_text(encoding="utf-8"))["version"]
            except (OSError, ValueError, KeyError) as exc:
                raise ZiweiError("needs_setup", "Ziwei engine is not prepared; run prepare_ziwei.py explicitly") from exc
            if installed != ENGINE_VERSION:
                raise ZiweiError("needs_setup", "Legacy Ziwei engine version does not match fixed pin")
            return {"status": "legacy_version_only", "version": installed, "network_access": False}
        raise ZiweiError("needs_setup", "Strict integrity metadata is missing; choose a new cache or explicitly repair")
    if (manifest.get("engine") != "iztro" or manifest.get("version") != ENGINE_VERSION
            or manifest.get("adapter_abi") != ENGINE_ABI or manifest.get("dependency_pins") != DEPENDENCY_PINS
            or manifest.get("archive_integrities") != INTEGRITIES):
        raise ZiweiError("engine_integrity_error", "Engine manifest differs from fixed dependency pins")
    try:
        if json.loads((directory / "package-lock.json").read_text(encoding="utf-8")) != _lock_value():
            raise ZiweiError("engine_integrity_error", "Engine lock differs from fixed versions/integrities")
        if json.loads((directory / "package.json").read_text(encoding="utf-8")) != {"private": True, "dependencies": DEPENDENCY_PINS}:
            raise ZiweiError("engine_integrity_error", "Engine dependency declaration differs from fixed pins")
        expected = {}
        for name in DEPENDENCY_PINS:
            expected.update({key: hashlib.sha256(payload).hexdigest()
                             for key, payload in archive_files(name, directory / "archives" / archive_filename(name)).items()})
        if manifest.get("files") != expected:
            raise ZiweiError("engine_integrity_error", "File manifest differs from fixed package archives")
        actual = {}
        modules = directory / "node_modules"
        if modules.is_symlink() or (hasattr(modules, "is_junction") and modules.is_junction()):
            raise ZiweiError("engine_integrity_error", "Engine modules cannot be linked")
        for path in modules.rglob("*"):
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise ZiweiError("engine_integrity_error", "Engine files cannot be linked")
            if path.is_file():
                actual[path.relative_to(directory).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ZiweiError("engine_integrity_error", "Engine extracted file set or content has changed")
    except (OSError, ValueError, tarfile.TarError) as exc:
        if isinstance(exc, ZiweiError):
            raise
        raise ZiweiError("engine_integrity_error", "Prepared engine files are missing or invalid") from exc
    return {"status": "verified", "version": ENGINE_VERSION, "file_count": len(expected), "network_access": False}


def prepare(engine_dir=None, *, repair=False):
    supplied = engine_dir or os.environ.get("MINGXUE_ZIWEI_ENGINE")
    if supplied:
        validate_external_directory(supplied)
    directory = validate_external_directory(engine_directory(engine_dir))
    find_node()
    if directory.exists():
        try:
            verified = verify_engine_directory(directory, allow_legacy=False)
            return {"status": "ready", "engine_dir": str(directory), "preparation": "already_verified",
                    "integrity": verified, "probe": probe(directory)}
        except ZiweiError:
            if not repair:
                raise ZiweiError("needs_setup", "Cache exists without strict integrity. Choose a new directory or pass --repair to retain a backup")
    directory.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".ziwei-prepare-", dir=directory.parent))
    backup = None
    activated = False
    try:
        (stage / "archives").mkdir()
        files = {}
        for name in DEPENDENCY_PINS:
            archive = stage / "archives" / archive_filename(name)
            download_archive(name, archive)
            for key, payload in archive_files(name, archive).items():
                path = stage.joinpath(*PurePosixPath(key).parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
                files[key] = hashlib.sha256(payload).hexdigest()
        (stage / "package.json").write_text(json.dumps({"private": True, "dependencies": DEPENDENCY_PINS}, indent=2) + "\n", encoding="utf-8")
        (stage / "package-lock.json").write_text(json.dumps(_lock_value(), indent=2) + "\n", encoding="utf-8")
        manifest = {"engine": "iztro", "version": ENGINE_VERSION, "adapter_abi": ENGINE_ABI,
                    "integrity_schema_version": 1, "dependency_pins": DEPENDENCY_PINS,
                    "archive_integrities": INTEGRITIES, "files": files, "dependencies_lock": "package-lock.json",
                    "preparation_method": "fixed_integrity_archives_no_install_scripts",
                    "prepared_utc": datetime.now(timezone.utc).isoformat()}
        (stage / "mingxue-engine.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        verify_engine_directory(stage, allow_legacy=False)
        probe(stage)
        if directory.exists():
            if directory.is_symlink() or (hasattr(directory, "is_junction") and directory.is_junction()):
                raise ZiweiError("invalid_input", "Refusing to replace a linked engine cache")
            backup = directory.with_name(directory.name + ".backup-" + datetime.now().strftime("%Y%m%d%H%M%S%f"))
            directory.rename(backup)
        stage.rename(directory)
        activated = True
        result = {"status": "ready", "engine_dir": str(directory), "probe": probe(directory),
                  "preparation": "downloaded_verified_external_archives", "scripts_executed": False,
                  "next_command": [sys.executable, "-X", "utf8", "-B", str(Path(__file__).with_name("ziwei.py")), "--engine-dir", str(directory), "--probe"]}
        if backup:
            result["previous_cache_backup"] = str(backup)
        return result
    except Exception:
        if activated and directory.exists():
            failed = directory.with_name(directory.name + ".failed-" + datetime.now().strftime("%Y%m%d%H%M%S%f"))
            if failed.parent.resolve() != directory.parent.resolve():
                raise ValueError("Failed cache recovery path is outside the engine parent")
            directory.rename(failed)
        if backup is not None and backup.exists() and not directory.exists():
            backup.rename(directory)
        raise
    finally:
        if stage.exists() and stage.parent.resolve() == directory.parent.resolve() and stage.name.startswith(".ziwei-prepare-"):
            shutil.rmtree(stage)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--engine-dir")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--probe", action="store_true", help="local check only; no download")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        supplied = args.engine_dir or os.environ.get("MINGXUE_ZIWEI_ENGINE")
        if supplied:
            validate_external_directory(supplied)
        if args.probe:
            directory = engine_directory(args.engine_dir)
            result = {"status": "ready", "engine_dir": str(directory),
                      "integrity": verify_engine_directory(directory, allow_legacy=bool(args.engine_dir or os.environ.get("MINGXUE_ZIWEI_ENGINE"))),
                      "probe": probe(directory)}
        else:
            result = prepare(args.engine_dir, repair=args.repair)
        code = 0
    except (ZiweiError, ValueError, OSError, tarfile.TarError) as exc:
        result, code = {"status": getattr(exc, "status", "setup_failed"), "message": str(exc), **getattr(exc, "details", {})}, 3
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
