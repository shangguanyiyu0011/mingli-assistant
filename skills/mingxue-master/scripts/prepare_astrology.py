"""Explicitly download and verify the pinned external astrology engine wheel.

Only this preparation command accesses a network. No global package install.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import sys
import tempfile
import urllib.request
import zipfile

sys.dont_write_bytecode = True
from astrology import (ENGINE_PACKAGE, ENGINE_VERSION, WHEEL_FILENAME, WHEEL_SHA256, WHEEL_URL,
                       engine_directory, validate_engine_directory, probe, _verify_engine, EngineError)
from runtime_paths import validate_external_directory


def prepare(engine_dir=None, *, repair=False):
    supplied = engine_dir or os.environ.get("MINGXUE_ASTRO_ENGINE")
    if supplied:
        validate_external_directory(supplied)
    target = validate_external_directory(validate_engine_directory(engine_directory(engine_dir)))
    if sys.version_info[:2] != (3, 12) or sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise EngineError("This preparation pin requires CPython 3.12 / Windows x86-64; no download was attempted")
    if target.exists():
        try:
            _verify_engine(target)
            result = probe(target)
            result["preparation"] = "already_verified"
            return result
        except EngineError:
            if not repair:
                raise ValueError("Engine directory exists but is not verified; choose an empty cache or explicitly pass --repair")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".astrology-prepare-", dir=target.parent))
    backup = None
    activated = False
    try:
        wheel = stage / WHEEL_FILENAME
        request = urllib.request.Request(WHEEL_URL, headers={"User-Agent": "mingxue-engine-preparation/1"})
        with urllib.request.urlopen(request, timeout=60) as response, wheel.open("wb") as stream:
            total = 0
            while chunk := response.read(65536):
                total += len(chunk)
                if total > 5_000_000:
                    raise ValueError("Pinned wheel exceeds its expected maximum download size")
                stream.write(chunk)
        if hashlib.sha256(wheel.read_bytes()).hexdigest() != WHEEL_SHA256:
            raise ValueError("Downloaded wheel SHA-256 does not match the fixed pin")
        python_dir = stage / "python"
        python_dir.mkdir()
        with zipfile.ZipFile(wheel) as archive:
            names = set()
            for item in archive.infolist():
                rel = PurePosixPath(item.filename)
                if (rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts)
                        or "\\" in item.filename or ":" in item.filename
                        or (item.external_attr >> 16) & 0o170000 == 0o120000
                        or item.filename.casefold() in names):
                    raise ValueError("Unsafe or duplicate wheel member")
                names.add(item.filename.casefold())
                dest = python_dir.joinpath(*rel.parts)
                if item.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(archive.read(item))
        files = {p.relative_to(python_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in python_dir.rglob("*") if p.is_file()}
        manifest = {"schema_version": 1, "package": ENGINE_PACKAGE, "version": ENGINE_VERSION,
                    "wheel_filename": WHEEL_FILENAME, "wheel_sha256": WHEEL_SHA256,
                    "prepared_utc": datetime.now(timezone.utc).isoformat(), "files": files}
        (stage / "engine.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        _verify_engine(stage)
        if target.exists():
            if target.is_symlink() or (hasattr(target, "is_junction") and target.is_junction()):
                raise ValueError("Refusing to replace a linked engine cache")
            backup = target.with_name(target.name + ".backup-" + datetime.now().strftime("%Y%m%d%H%M%S%f"))
            target.rename(backup)
        stage.rename(target)
        activated = True
        result = probe(target)
        if not result["available"]:
            raise EngineError(result["reason"])
        result["preparation"] = "downloaded_verified_external_wheel"
        result["preparation_network_access"] = True
        result["next_command"] = [sys.executable, "-X", "utf8", "-B", str(Path(__file__).with_name("astrology.py")),
                                  "--engine-dir", str(target), "--probe"]
        if backup is not None:
            result["previous_cache_backup"] = str(backup)
        return result
    except Exception:
        if activated and target.exists():
            failed = target.with_name(target.name + ".failed-" + datetime.now().strftime("%Y%m%d%H%M%S%f"))
            if failed.parent.resolve() != target.parent.resolve():
                raise ValueError("Failed cache recovery path is outside the engine parent")
            target.rename(failed)
        if backup is not None and backup.exists() and not target.exists():
            backup.rename(target)
        raise
    finally:
        # Only a locally generated staging child is removed; never the target.
        if stage.exists() and stage.parent.resolve() == target.parent.resolve() and stage.name.startswith(".astrology-prepare-"):
            shutil.rmtree(stage)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--engine-dir")
    parser.add_argument("--repair", action="store_true", help="replace an invalid cache, retaining its backup")
    parser.add_argument("--probe", action="store_true", help="check only; never download")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        supplied = args.engine_dir or os.environ.get("MINGXUE_ASTRO_ENGINE")
        if supplied:
            validate_external_directory(supplied)
        result = probe(args.engine_dir) if args.probe else prepare(args.engine_dir, repair=args.repair)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["available"] else 3
    except (ValueError, OSError, EngineError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "setup_failed", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 3


if __name__ == "__main__":
    sys.exit(main())
