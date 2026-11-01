"""Persistent external engine paths; importing this module creates nothing."""
from __future__ import annotations

import os
from pathlib import Path
import re
import site
import sys
import tempfile

SKILL_ROOT = Path(__file__).resolve().parents[1]


class CacheHomeUnavailable(ValueError):
    """A default persistent cache root cannot be located without a user home."""


def _default_user_home():
    try:
        return Path.home()
    except (RuntimeError, OSError) as exc:
        raise CacheHomeUnavailable(
            "Default persistent cache home is unavailable; set an absolute MINGXUE_ENGINE_HOME explicitly"
        ) from exc


def protected_directories():
    values = [SKILL_ROOT, Path(sys.prefix), Path(tempfile.gettempdir()) / "mingxue-master-cache"]
    for parent in SKILL_ROOT.parents:
        if (parent / "plugin.json").is_file() or (parent / ".codex-plugin/plugin.json").is_file():
            values.append(parent)
            break
    values.extend(Path(os.environ[name]).expanduser() for name in ("MINGXUE_RESOURCE_DIR", "MINGXUE_CACHE_DIR")
                  if os.environ.get(name))
    try:
        values.extend(Path(value) for value in site.getsitepackages())
        user = site.getusersitepackages()
        values.extend(Path(value) for value in ([user] if isinstance(user, str) else user))
    except (AttributeError, OSError):
        pass
    return tuple(dict.fromkeys(value.resolve() for value in values))


def validate_external_directory(value, *, purpose="engine"):
    """Reject installed skills/resources/runtime trees and their parent roots."""
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        raise ValueError(f"{purpose} directory must be an explicit nonempty path")
    try:
        supplied = Path(value).expanduser()
    except (RuntimeError, OSError) as exc:
        raise ValueError(f"{purpose} directory cannot expand its user-home path; provide an absolute path") from exc
    if not supplied.is_absolute():
        raise ValueError(f"{purpose} directory must be an absolute path")
    path = supplied.resolve()
    if path == Path(path.anchor):
        raise ValueError(f"{purpose} directory cannot be a filesystem root")
    for protected in protected_directories():
        if path.is_relative_to(protected) or protected.is_relative_to(path):
            raise ValueError(f"{purpose} directory must be outside installed skill, resources and Python/site-packages")
    if path.exists() and not path.is_dir():
        raise ValueError(f"{purpose} directory is an existing file")
    return path


def engine_home():
    override = os.environ.get("MINGXUE_ENGINE_HOME")
    if override:
        root = Path(override)
    elif os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or _default_user_home() / "AppData/Local") / "mingxue/engines"
    elif sys.platform == "darwin":
        root = _default_user_home() / "Library/Caches/mingxue/engines"
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME") or _default_user_home() / ".cache") / "mingxue/engines"
    return validate_external_directory(root)


def engine_directory(system, version):
    for name, value in (("system", system), ("version", version)):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", value):
            raise ValueError(f"Invalid engine {name}")
    return validate_external_directory(engine_home() / system / version)


def legacy_engine_directories(system, version):
    """Report existing old temporary locations. Never move or delete them."""
    # Validate tokens with the same rules without touching any directory.
    engine_directory(system, version)
    candidates = [Path(tempfile.gettempdir()) / "mingxue-engines" / system / version]
    current = engine_directory(system, version)
    return [path.resolve() for path in candidates if path.is_dir() and path.resolve() != current]

