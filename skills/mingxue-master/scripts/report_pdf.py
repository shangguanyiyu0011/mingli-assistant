"""Print an existing offline HTML report to a new PDF with a local browser."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
from output_paths import guard_output


MIN_PDF_BYTES = 1024
MAX_PDF_BYTES = 128 * 1024 * 1024
DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 300
VIRTUAL_TIME_MS = 3000
_BROWSER_NAMES = frozenset({
    "msedge.exe", "chrome.exe", "chromium.exe", "chromium-browser.exe",
    "microsoft-edge", "microsoft-edge-stable", "google-chrome",
    "google-chrome-stable", "chromium", "chromium-browser", "chrome",
})


class PdfExportError(ValueError):
    """A fixed, non-sensitive public error rather than raw browser output."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _fail(code, message):
    raise PdfExportError(code, message)


def _absolute_local_path(value, kind):
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        _fail("invalid_path", "请输入本地绝对文件路径。")
    path = Path(value)
    # Reject URLs, UNC shares and Windows device paths before touching a file.
    # A mapped network drive cannot be detected portably; callers must choose
    # files on local storage, as documented.
    if not path.is_absolute() or str(path).startswith(("\\\\", "//")):
        _fail("invalid_path", "请输入本地绝对文件路径，不接受网址或网络共享。")
    suffix = ".html" if kind == "input" else ".pdf"
    if path.suffix.lower() != suffix:
        _fail("invalid_extension", "来源须为 .html，目标须为新的 .pdf 文件。")
    return path


def _paths(input_path, output_path):
    supplied_source = _absolute_local_path(input_path, "input")
    supplied_target = _absolute_local_path(output_path, "output")
    try:
        source = supplied_source.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        _fail("input_not_found", "找不到可读取的本地 HTML 报告。")
    if str(source).startswith(("\\\\", "//")):
        _fail("invalid_path", "来源须保存在本机磁盘，不能指向网络共享。")
    if source.suffix.lower() != ".html" or not source.is_file():
        _fail("invalid_input", "来源须为现有本地 HTML 文件。")
    if supplied_target.exists() or supplied_target.is_symlink():
        _fail("output_exists", "目标已存在，请选择新的 PDF 文件名。")
    # Preserve the original file itself, while allowing a new sibling PDF.
    protected = (source, supplied_source.absolute())
    try:
        target = guard_output(supplied_target, extra_protected=protected)
    except (ValueError, OSError, RuntimeError):
        _fail("protected_output", "请在插件、技能、资源及引擎目录之外选择新的 PDF 文件。")
    if str(target).startswith(("\\\\", "//")):
        _fail("invalid_path", "目标须保存在本机磁盘，不能指向网络共享。")
    return source, target, protected


def _known_browser_paths():
    """Read known executable locations only; no profile reads or probes."""
    if sys.platform == "win32":
        for key in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
            folder = os.environ.get(key)
            if not folder:
                continue
            base = Path(folder)
            for relative in (
                "Microsoft/Edge/Application/msedge.exe",
                "Google/Chrome/Application/chrome.exe",
                "Chromium/Application/chrome.exe",
            ):
                yield base / relative
    elif sys.platform == "darwin":
        for app, executable in (
            ("Google Chrome", "Google Chrome"),
            ("Microsoft Edge", "Microsoft Edge"),
            ("Chromium", "Chromium"),
        ):
            yield Path("/Applications") / (app + ".app") / "Contents/MacOS" / executable


def _browser_file(path, *, explicit=False):
    try:
        supplied = Path(path)
        # macOS app executable names are accepted only from known app paths.
        known_mac = not explicit and supplied.name in {"Google Chrome", "Microsoft Edge", "Chromium"}
        if not supplied.is_absolute() or str(supplied).startswith(("\\\\", "//")):
            return None
        if not known_mac and supplied.name.casefold() not in _BROWSER_NAMES:
            return None
        resolved = supplied.resolve(strict=True)
        if str(resolved).startswith(("\\\\", "//")):
            return None
        if not resolved.is_file():
            return None
        if sys.platform != "win32" and not os.access(resolved, os.X_OK):
            return None
        return resolved
    except (OSError, RuntimeError, ValueError):
        return None


def find_browser(browser=None):
    """Return an already-installed supported browser, without launching it."""
    if browser is not None:
        if not isinstance(browser, (str, os.PathLike)):
            return None
        return _browser_file(browser, explicit=True)
    for candidate in _known_browser_paths():
        found = _browser_file(candidate)
        if found is not None:
            return found
    for name in ("msedge", "chrome", "chromium", "chromium-browser",
                 "google-chrome", "google-chrome-stable", "microsoft-edge",
                 "microsoft-edge-stable"):
        found_path = shutil.which(name)
        if found_path:
            found = _browser_file(found_path)
            if found is not None:
                return found
    return None


def _creation_flags():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _command(browser, source, profile, pdf):
    # Only an encoded local file URI is a page argument. No payload content,
    # remote URL, default profile, shell command or debugging port is accepted.
    return [
        str(browser), "--headless", "--no-first-run", "--no-default-browser-check",
        "--disable-background-networking", "--disable-component-update",
        "--disable-sync", "--disable-default-apps", "--disable-extensions",
        "--disable-domain-reliability", "--no-pings", "--metrics-recording-only",
        "--safebrowsing-disable-auto-update", "--disable-breakpad",
        "--disable-crash-reporter", "--disable-session-crashed-bubble",
        "--no-pdf-header-footer", "--run-all-compositor-stages-before-draw",
        f"--virtual-time-budget={VIRTUAL_TIME_MS}",
        f"--user-data-dir={profile}", f"--print-to-pdf={pdf}", source.as_uri(),
    ]


def _stop_child(process):
    """Stop only this invocation's Popen child, never a named browser fleet."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def _render(browser, source, timeout):
    # The profile and intermediate PDF are removed before publishing a target.
    with tempfile.TemporaryDirectory(prefix="mingxue-pdf-") as directory:
        temporary = Path(directory)
        profile = temporary / "profile"
        pdf = temporary / "rendered.pdf"
        command = _command(browser, source, profile, pdf)
        process = subprocess.Popen(
            command, shell=False, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=_creation_flags(), cwd=str(temporary),
        )
        try:
            exit_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                _stop_child(process)
            except (OSError, subprocess.SubprocessError):
                _fail("browser_stop_failed", "本次导出进程未能正常结束，未生成目标 PDF。")
            _fail("timeout", "本次 PDF 导出超时，未生成目标文件。")
        except BaseException:
            _stop_child(process)
            raise
        if exit_code != 0:
            _fail("browser_failed", "浏览器未完成 PDF 导出，未生成目标文件。")
        if not pdf.is_file() or pdf.is_symlink():
            _fail("pdf_missing", "浏览器未产生可用的 PDF 文件。")
        size = pdf.stat().st_size
        if not MIN_PDF_BYTES <= size <= MAX_PDF_BYTES:
            _fail("invalid_pdf", "生成文件未通过 PDF 完整性检查。")
        with pdf.open("rb") as stream:
            data = stream.read(MAX_PDF_BYTES + 1)
        if (len(data) != size or not data.startswith(b"%PDF-")
                or b"%%EOF" not in data[-2048:]):
            _fail("invalid_pdf", "生成文件未通过 PDF 完整性检查。")
    return data


def _publish(data, target, protected):
    """Atomic no-replace publication from an exclusively-created local stage."""
    # Recheck after rendering: a target may have appeared while Chrome ran.
    if target.exists() or target.is_symlink():
        _fail("output_exists", "目标已存在，请选择新的 PDF 文件名。")
    if guard_output(target, extra_protected=protected) != target:
        _fail("protected_output", "导出目录已变化，请重新选择本地目标。")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, stage_name = tempfile.mkstemp(prefix=".mingxue-pdf-", suffix=".tmp", dir=target.parent)
    stage = Path(stage_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # Both paths are on the target volume. Unlike replace()/rename() on
        # POSIX, link() fails if the destination exists, including a race.
        os.link(stage, target)
    except FileExistsError:
        _fail("output_exists", "目标已存在，请选择新的 PDF 文件名。")
    finally:
        # The stage belongs exclusively to this invocation; never unlink target.
        try:
            stage.unlink()
        except OSError:
            pass


def export_pdf(input, output, browser=None, timeout=DEFAULT_TIMEOUT):
    """Return exported/needs_browser/error; never expose HTML or browser logs."""
    try:
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or not 1 <= timeout <= MAX_TIMEOUT):
            _fail("invalid_timeout", "超时秒数须在1至300之间。")
        source, target, protected = _paths(input, output)
        executable = find_browser(browser)
        if executable is None:
            return {"status": "needs_browser", "code": "browser_not_found",
                    "message": "未找到现有 Edge、Chrome 或 Chromium。可打开报告，点击“导出PDF”后另存。"}
        data = _render(executable, source, float(timeout))
        digest = hashlib.sha256(data).hexdigest()
        _publish(data, target, protected)
        return {"status": "exported", "path": str(target), "sha256": digest, "size_bytes": len(data)}
    except PdfExportError as exc:
        return {"status": "error", "code": exc.code, "message": exc.message}
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        return {"status": "error", "code": "export_failed",
                "message": "未能完成 PDF 导出，请检查文件能否读写，或换一个保存位置后再试。"}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        _fail("invalid_arguments", "请提供 --input、--output，以及可选的 --browser、--timeout。")


def main(argv=None):
    parser = _Parser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--browser")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    try:
        args = parser.parse_args(argv)
        result = export_pdf(args.input, args.output, args.browser, args.timeout)
    except PdfExportError as exc:
        result = {"status": "error", "code": exc.code, "message": exc.message}
    print(json.dumps(result, ensure_ascii=False))
    return {"exported": 0, "needs_browser": 3}.get(result["status"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
