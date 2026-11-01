"""Local runtime discovery and a JSON-preserving tool launcher. No downloads."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
from runtime_paths import engine_home, engine_directory, legacy_engine_directories

SCRIPTS = Path(__file__).resolve().parent
TOOLS = ("doctor", "chart", "fortune", "workflow", "ziwei", "astrology", "name_analysis", "iching", "symbolic",
         "visual_intake", "almanac", "book_search", "case_lookup", "case_audit", "tieban_run", "feedback",
         "prepare_astrology", "prepare_ziwei", "prepare_name_dictionary", "presets", "visual_annotations", "workbench", "extra_methods", "prepare_taiyi", "pair_report", "offline_intake", "agent_intake", "agent_report", "report_pdf")


class RuntimeUnavailable(ValueError):
    def __init__(self, message, **details):
        super().__init__(message)
        self.details = details


def is_windows_app_alias(path):
    value = str(path).replace("\\", "/").lower()
    return bool(re.search(r"/microsoft/windowsapps/(?:pythonw?(?:\d+(?:\.\d+)*)?|pyw?)(?:\.exe)?$", value))


def _unique(values):
    seen = set()
    for raw in values:
        if not raw:
            continue
        try:
            value = Path(raw).expanduser().absolute()
        except (RuntimeError, OSError) as exc:
            raise RuntimeUnavailable("Cannot expand runtime path without a user home; provide an absolute path") from exc
        key = os.path.normcase(str(value))
        if key not in seen:
            seen.add(key)
            yield value


def python_candidates():
    override = os.environ.get("MINGXUE_PYTHON")
    if override:
        return list(_unique([shutil.which(override) or override]))
    values = [sys.executable]
    values.extend(shutil.which(name) for name in ("python3.12", "python3.12.exe", "python.exe", "python3.exe", "python3", "python"))
    roots = [os.environ.get("UV_PYTHON_INSTALL_DIR")]
    try:
        home = Path.home()
    except (RuntimeError, OSError):
        home = None
    if os.name == "nt":
        for variable in ("APPDATA", "LOCALAPPDATA"):
            if os.environ.get(variable):
                roots.append(Path(os.environ[variable]) / "uv/python")
        if home is not None:
            roots.append(home / ".local/share/uv/python")
        local = Path(os.environ["LOCALAPPDATA"]) if os.environ.get("LOCALAPPDATA") else home / "AppData/Local" if home is not None else None
        if local is not None:
            values.append(local / "Programs/Python/Python312/python.exe")
        for variable in ("ProgramFiles", "ProgramFiles(x86)"):
            if os.environ.get(variable):
                values.append(Path(os.environ[variable]) / "Python312/python.exe")
    else:
        data_home = Path(os.environ["XDG_DATA_HOME"]) if os.environ.get("XDG_DATA_HOME") else home / ".local/share" if home is not None else None
        if data_home is not None:
            roots.append(data_home / "uv/python")
    for root in roots:
        if root and Path(root).is_dir():
            for directory in sorted(Path(root).glob("cpython-3.12*"), reverse=True):
                values.extend([directory / "python.exe", directory / "bin/python3.12", directory / "bin/python3"])
    return list(_unique(values))


def inspect_python(path):
    if is_windows_app_alias(path):
        raise RuntimeUnavailable("WindowsApps execution alias is not a Python interpreter")
    try:
        path = Path(path).expanduser()
    except (RuntimeError, OSError) as exc:
        raise RuntimeUnavailable("Cannot expand interpreter path; provide an absolute path") from exc
    if not path.is_file():
        raise RuntimeUnavailable("Interpreter path is missing")
    code = "import sys,json,struct;print(json.dumps({'executable':sys.executable,'version':list(sys.version_info[:3]),'implementation':sys.implementation.name,'bits':struct.calcsize('P')*8}))"
    try:
        process = subprocess.run([str(path), "-I", "-S", "-B", "-X", "utf8", "-c", code],
                                 capture_output=True, text=True, encoding="utf-8", timeout=8, check=False)
        value = json.loads(process.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise RuntimeUnavailable("Interpreter did not return a valid isolated runtime probe") from exc
    if process.returncode or value.get("implementation") != "cpython" or value.get("version", [])[:2] != [3, 12] or value.get("bits") != 64:
        raise RuntimeUnavailable("CPython 3.12 / 64-bit is required for the pinned astrology wheel", observed=value)
    executable = Path(value["executable"]).resolve()
    if is_windows_app_alias(executable) or not executable.is_file():
        raise RuntimeUnavailable("Probe returned an invalid interpreter path")
    return {**value, "available": True, "executable": str(executable), "version_string": ".".join(map(str, value["version"]))}


def find_python(candidates=None):
    rejected = []
    for candidate in python_candidates() if candidates is None else candidates:
        try:
            value = inspect_python(candidate)
            return value["executable"], value
        except (ValueError, OSError) as exc:
            rejected.append({"path": str(candidate), "reason": str(exc)})
    raise RuntimeUnavailable("No existing CPython 3.12 / 64-bit interpreter was found; install it explicitly or set MINGXUE_PYTHON",
                             rejected_candidates=rejected)


def node_candidates():
    override = os.environ.get("MINGXUE_NODE")
    if override:
        return list(_unique([shutil.which(override) or override]))
    values = [shutil.which("node"), shutil.which("node.exe")]
    if os.name == "nt" and os.environ.get("ProgramFiles"):
        values.append(Path(os.environ["ProgramFiles"]) / "nodejs/node.exe")
    return list(_unique(values))


def find_node():
    errors = []
    for candidate in node_candidates():
        try:
            process = subprocess.run([str(candidate), "--version"], capture_output=True, text=True,
                                     encoding="utf-8", timeout=8, check=False)
            match = re.fullmatch(r"v(\d+)\.\d+\.\d+\s*", process.stdout)
            if not process.returncode and match and int(match.group(1)) >= 18:
                return str(candidate.resolve())
            errors.append(str(candidate) + ": Node.js 18+ required")
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(str(candidate) + ": " + str(exc))
    raise RuntimeUnavailable("No healthy existing Node.js 18+ found; no installation was attempted", candidates=errors)


def npm_command(node=None):
    node = node or find_node()
    candidates = [Path(node).with_name("node_modules") / "npm/bin/npm-cli.js"]
    found = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if found:
        npm = Path(found)
        candidates.extend([npm.parent / "node_modules/npm/bin/npm-cli.js", npm.resolve()])
    for candidate in candidates:
        if candidate.is_file() and candidate.suffix == ".js":
            return [node, str(candidate.resolve())]
    if found and os.name != "nt":
        return [str(Path(found).resolve())]
    raise RuntimeUnavailable("Node.js is available but npm CLI was not found; no installation was attempted")


def health_report():
    report = {"schema_version": 1, "status": "needs_runtime_setup", "runtime_ready": False,
              "scope": "runtime_only; resources, dictionaries and engines are checked separately",
              "network_access": False, "installs_performed": False,
              "python": {"available": False}, "node": {"available": False}, "npm": {"available": False},
              "cache": {}, "legacy_caches": {}, "source_root": str(SCRIPTS.parent),
              "tools": {name: str(SCRIPTS / (name + ".py")) for name in TOOLS if (SCRIPTS / (name + ".py")).is_file()}}
    try:
        _, report["python"] = find_python()
    except RuntimeUnavailable as exc:
        report["python"] = {"available": False, "reason": str(exc), **exc.details}
    try:
        node = find_node()
        process = subprocess.run([node, "--version"], capture_output=True, text=True, encoding="utf-8", timeout=8)
        report["node"] = {"available": True, "executable": node, "version": process.stdout.strip()}
        try:
            command = npm_command(node)
            process = subprocess.run(command + ["--version"], capture_output=True, text=True, encoding="utf-8", timeout=15)
            version = process.stdout.strip()
            available = not process.returncode and bool(re.fullmatch(r"\d+\.\d+\.\d+", version))
            report["npm"] = {"available": available, "command": command, "version": version if available else None}
            if not available:
                report["npm"]["reason"] = "npm version probe failed"
        except (RuntimeUnavailable, OSError, subprocess.TimeoutExpired) as exc:
            report["npm"] = {"available": False, "reason": str(exc)}
    except (RuntimeUnavailable, OSError, subprocess.TimeoutExpired) as exc:
        report["node"] = {"available": False, "reason": str(exc)}
    try:
        report["cache"]["engine_home"] = str(engine_home())
        for system, version in (("astrology", "2.10.3.6"), ("ziwei", "2.6.3")):
            report["cache"][system] = str(engine_directory(system, version))
            report["legacy_caches"][system] = [str(path) for path in legacy_engine_directories(system, version)]
        report["cache"]["created_by_probe"] = False
    except ValueError as exc:
        report["cache"]["error"] = str(exc)
    report["runtime_ready"] = report["python"]["available"] and "error" not in report["cache"]
    report["status"] = "runtime_ready" if report["runtime_ready"] else "needs_runtime_setup"
    report["optional_node_tools_ready"] = report["node"]["available"]
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("tool", nargs="?", choices=TOOLS)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.probe or args.tool is None:
        if args.probe and args.tool is not None:
            parser.error("--probe does not accept a tool command")
        result = health_report()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["runtime_ready"] else 3
    try:
        python, _ = find_python()
        source = (SCRIPTS / (args.tool + ".py")).resolve()
        if not source.is_file() or source.parent != SCRIPTS:
            raise RuntimeUnavailable("This package does not contain the requested tool", tool=args.tool)
        arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
        # Inherit stdout verbatim: all JSON-producing tools keep their protocol.
        return subprocess.run([python, "-X", "utf8", "-B", str(source), *arguments], check=False).returncode
    except (RuntimeUnavailable, OSError) as exc:
        print(json.dumps({"status": "needs_setup", "message": str(exc), **getattr(exc, "details", {})}, ensure_ascii=False))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
