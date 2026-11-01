"""Shared user-output boundaries for standalone skills and plugin packages."""
import os
from pathlib import Path
import tempfile


def protected_output_roots(extra_protected=()):
    from runtime_paths import CacheHomeUnavailable, engine_home, protected_directories
    skill = Path(__file__).resolve().parents[1]
    roots = [*protected_directories(), skill.parents[1] / "runtime",
             Path(tempfile.gettempdir()) / "mingxue-engines"]
    try:
        roots.append(engine_home())
    except CacheHomeUnavailable:
        # Native read-only/explicit-output tools remain usable in minimal
        # service environments. Explicit cache roots are still guarded below.
        pass
    for parent in skill.parents:
        if (parent / "plugin.json").is_file() or (parent / ".codex-plugin/plugin.json").is_file():
            roots.append(parent)
            break
    roots.extend(Path(os.environ[key]).expanduser() for key in
                 ("MINGXUE_ENGINE_HOME", "MINGXUE_ZIWEI_ENGINE", "MINGXUE_ASTRO_ENGINE", "MINGXUE_NAME_DICTIONARY")
                 if os.environ.get(key))
    roots.extend(Path(path).expanduser() for path in extra_protected)
    return tuple(dict.fromkeys(root.resolve() for root in roots))


def guard_output(path, extra_protected=()):
    target = Path(path).expanduser().resolve()
    if any(target.is_relative_to(root) for root in protected_output_roots(extra_protected)):
        raise ValueError("user output must be outside plugin, skill, resources, engine caches and Python directories")
    return target
