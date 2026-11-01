"""Explicitly prepare a fixed Taiyi engine, private runtime and wheels outside the skill."""
from __future__ import annotations
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

sys.dont_write_bytecode = True
from taiyi import (ARTIFACTS, ENGINE_VERSION, ENGINE_COMMIT, ENGINE_ABI, TaiyiError,
                   engine_directory, archive_files, verify_engine, probe)

def download_artifact(name, destination):
    request = urllib.request.Request(ARTIFACTS[name]["url"], headers={"User-Agent": "mingxue-engine-preparation/1"})
    with urllib.request.urlopen(request, timeout=60) as response, Path(destination).open("wb") as stream:
        total = 0
        while block := response.read(65536):
            total += len(block)
            if total > 40_000_000:
                raise TaiyiError("setup_failed", "下载归档超过上限。")
            stream.write(block)

def prepare(engine_dir=None, *, repair=False):
    directory = engine_directory(engine_dir)
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise TaiyiError("unsupported_runtime", "当前固定太乙引擎运行组合只验收Windows x86-64；不会下载不兼容依赖。")
    if directory.exists():
        try:
            verify_engine(directory)
            value = probe(directory)
            if not value["available"]:
                raise TaiyiError("engine_error", value.get("message", "探针失败"))
            return {"system": "taiyi", "status": "ready", "engine_dir": str(directory), "preparation": "already_verified", "probe": value}
        except TaiyiError:
            if not repair:
                raise TaiyiError("needs_setup", "目录已存在但尚未通过验收；可选新目录或显式 --repair 保留旧缓存后修复。")
    directory.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".taiyi-prepare-", dir=directory.parent))
    backup = None
    activated = False
    try:
        (stage / "archives").mkdir()
        files, seen = {}, set()
        for name, artifact in ARTIFACTS.items():
            archive = stage / "archives" / artifact["filename"]
            download_artifact(name, archive)
            for key, payload in archive_files(name, archive).items():
                if key.casefold() in seen:
                    raise TaiyiError("engine_integrity_error", "依赖文件路径冲突。")
                seen.add(key.casefold())
                dest = stage.joinpath(*PurePosixPath(key).parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(payload)
                files[key] = hashlib.sha256(payload).hexdigest()
        manifest = {"system": "taiyi", "version": ENGINE_VERSION, "commit": ENGINE_COMMIT, "adapter_abi": ENGINE_ABI,
                    "files": files, "archives": ARTIFACTS, "prepared_utc": datetime.now(timezone.utc).isoformat(),
                    "install_scripts_executed": False}
        (stage / "engine.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        verify_engine(stage)
        value = probe(stage)
        if not value["available"]:
            raise TaiyiError("engine_error", value.get("message", "隔离引擎验收失败。"))
        if directory.exists():
            if directory.is_symlink() or (hasattr(directory, "is_junction") and directory.is_junction()):
                raise TaiyiError("invalid_input", "拒绝替换链接缓存。")
            backup = directory.with_name(directory.name + ".backup-" + datetime.now().strftime("%Y%m%d%H%M%S%f"))
            directory.rename(backup)
        stage.rename(directory)
        activated = True
        value = probe(directory)
        if not value["available"]:
            raise TaiyiError("engine_error", value.get("message", "激活后探针失败。"))
        result = {"system": "taiyi", "status": "ready", "engine_dir": str(directory), "probe": value,
                  "scripts_executed": False, "preparation": "fixed_archives_private_runtime", "preparation_network_access": True}
        if backup:
            result["previous_cache_backup"] = str(backup)
        return result
    except Exception:
        if activated and directory.exists():
            failed = directory.with_name(directory.name + ".failed-" + datetime.now().strftime("%Y%m%d%H%M%S%f"))
            directory.rename(failed)
        if backup and backup.exists() and not directory.exists():
            backup.rename(directory)
        raise
    finally:
        if stage.exists() and stage.parent.resolve() == directory.parent.resolve() and stage.name.startswith(".taiyi-prepare-"):
            shutil.rmtree(stage)

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--engine-dir")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        value = probe(args.engine_dir) if args.probe else prepare(args.engine_dir, repair=args.repair)
    except (TaiyiError, ValueError, OSError) as exc:
        value = {"system": "taiyi", "status": getattr(exc, "status", "setup_failed"), "message": str(exc), **getattr(exc, "details", {})}
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0 if value["status"] in ("ready", "available") else 2

if __name__ == "__main__":
    raise SystemExit(main())

