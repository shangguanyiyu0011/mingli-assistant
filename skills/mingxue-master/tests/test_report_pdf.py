"""Offline PDF-export boundaries; no actual browser is launched by these tests."""
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT") or
             (HERE / "package/mingxue-master" if (HERE / "package/mingxue-master").is_dir() else HERE))
sys.path.insert(0, str(SKILL / "scripts"))
import report_pdf


# Deliberately a signature/size fixture, not evidence of real browser rendering.
PDF_BYTES = b"%PDF-1.7\n" + b"% offline boundary fixture\n" * 80 + b"%%EOF\n"


class ReportPdfTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="report-pdf-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.originals = self.root / "originals"
        self.originals.mkdir()
        self.source = self.originals / "本人报告 # 甲.html"
        self.source.write_text('<!doctype html><p>PRIVATE_REPORT_TEXT</p>', encoding="utf-8")
        self.target = self.root / "export" / "本人报告.pdf"
        self.browser = self.root / "tools" / "msedge.exe"
        self.browser.parent.mkdir()
        self.browser.write_bytes(b"existing-local-browser-test-double")
        self.browser.chmod(0o700)
        self.commands = []
        self.profiles = []
        self.process = Mock()
        self.process.wait.return_value = 0
        self.process.poll.return_value = None

    def popen(self, command, **kwargs):
        self.commands.append((command, kwargs))
        pdf = Path(next(x.split("=", 1)[1] for x in command if x.startswith("--print-to-pdf=")))
        profile = Path(next(x.split("=", 1)[1] for x in command if x.startswith("--user-data-dir=")))
        self.profiles.append(profile)
        profile.mkdir()
        (profile / "temporary-session").write_text("not a user profile", encoding="utf-8")
        pdf.write_bytes(PDF_BYTES)
        return self.process

    def run_export(self, **kwargs):
        with patch.object(report_pdf, "find_browser", return_value=self.browser), \
                patch.object(report_pdf.subprocess, "Popen", side_effect=self.popen):
            return report_pdf.export_pdf(self.source, self.target, **kwargs)

    def test_exports_only_after_success_and_cleans_private_temporary_profile(self):
        before = self.source.read_bytes()
        result = self.run_export()
        self.assertEqual(result["status"], "exported")
        self.assertEqual(Path(result["path"]), self.target)
        self.assertEqual(result["size_bytes"], len(PDF_BYTES))
        self.assertEqual(result["sha256"], hashlib.sha256(PDF_BYTES).hexdigest())
        self.assertEqual(self.target.read_bytes(), PDF_BYTES)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertTrue(all(not profile.parent.exists() for profile in self.profiles))
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])

    def test_subprocess_uses_list_no_shell_no_logs_and_only_local_page_uri(self):
        self.source.write_text('<script>fetch("https://private.example/payload?secret=abc")</script>', encoding="utf-8")
        with patch.object(report_pdf, "_creation_flags", return_value=0x08000000):
            result = self.run_export(timeout=12)
        self.assertEqual(result["status"], "exported")
        command, options = self.commands[0]
        self.assertIsInstance(command, list)
        self.assertIs(options["shell"], False)
        self.assertEqual(options["creationflags"], 0x08000000)
        for key in ("stdin", "stdout", "stderr"):
            self.assertEqual(options[key], subprocess.DEVNULL)
        self.assertEqual(command[-1], self.source.resolve().as_uri())
        self.assertIn("%23", command[-1])
        self.assertNotIn("https://private.example", " ".join(command))
        self.assertNotIn("PRIVATE_REPORT_TEXT", " ".join(command))
        self.assertIn("--headless", command)
        self.assertIn("--no-pdf-header-footer", command)
        self.assertIn("--disable-background-networking", command)
        self.assertIn("--disable-sync", command)
        self.assertIn("--disable-component-update", command)
        self.assertIn("--virtual-time-budget=3000", command)
        self.assertFalse(any("remote-debugging" in x or "no-sandbox" in x or "disable-web-security" in x for x in command))
        self.assertNotIn(str(self.target), command)
        self.process.wait.assert_called_once_with(timeout=12.0)

    def test_rejects_relative_paths_urls_and_wrong_extensions_before_launch(self):
        values = [
            ("relative.html", self.target),
            (self.source, "relative.pdf"),
            ("https://example.invalid/report.html", self.target),
            (self.source.as_uri(), self.target),
            (str(self.source.with_suffix(".htm")), self.target),
            (self.source, self.target.with_suffix(".html")),
            (r"\\server\share\report.html", self.target),
        ]
        with patch.object(report_pdf.subprocess, "Popen") as start:
            for source, target in values:
                with self.subTest(source=source, target=target):
                    self.assertEqual(report_pdf.export_pdf(source, target)["status"], "error")
            start.assert_not_called()
        self.assertFalse(self.target.parent.exists())

    def test_missing_input_and_directory_input_are_not_launched(self):
        with patch.object(report_pdf.subprocess, "Popen") as start:
            self.assertEqual(report_pdf.export_pdf(self.originals / "missing.html", self.target)["code"], "input_not_found")
            folder = self.originals / "folder.html"
            folder.mkdir()
            self.assertEqual(report_pdf.export_pdf(folder, self.target)["code"], "invalid_input")
            start.assert_not_called()

    def test_existing_output_is_never_touched(self):
        self.target.parent.mkdir()
        self.target.write_bytes(b"user-original-pdf")
        with patch.object(report_pdf.subprocess, "Popen") as start:
            result = report_pdf.export_pdf(self.source, self.target)
        self.assertEqual(result["code"], "output_exists")
        self.assertEqual(self.target.read_bytes(), b"user-original-pdf")
        start.assert_not_called()

    def test_allows_new_pdf_beside_html_or_below_while_preserving_original(self):
        before = self.source.read_bytes()
        for target in (self.originals / "new.pdf", self.originals / "nested" / "new.pdf"):
            self.target = target
            with self.subTest(target=target):
                self.assertEqual(self.run_export()["status"], "exported")
                self.assertEqual(target.read_bytes(), PDF_BYTES)
                self.assertEqual(self.source.read_bytes(), before)

    def test_protects_skill_and_configured_engine_directories(self):
        engine = self.root / "engine"
        with patch.dict(os.environ, {"MINGXUE_ENGINE_HOME": str(engine)}), \
                patch.object(report_pdf.subprocess, "Popen") as start:
            for target in (SKILL / "new-report.pdf", engine / "new-report.pdf"):
                self.assertEqual(report_pdf.export_pdf(self.source, target)["code"], "protected_output")
            start.assert_not_called()
        self.assertFalse(engine.exists())

    def test_missing_browser_does_not_create_profile_or_output_directory(self):
        with patch.object(report_pdf, "find_browser", return_value=None), \
                patch.object(report_pdf.tempfile, "TemporaryDirectory") as temporary, \
                patch.object(report_pdf.subprocess, "Popen") as start:
            result = report_pdf.export_pdf(self.source, self.target)
        self.assertEqual(result["status"], "needs_browser")
        temporary.assert_not_called()
        start.assert_not_called()
        self.assertFalse(self.target.parent.exists())

    def test_browser_detection_only_reads_existing_supported_binaries(self):
        with patch.object(report_pdf, "_known_browser_paths", return_value=iter([self.browser])), \
                patch.object(report_pdf.subprocess, "Popen") as start:
            self.assertEqual(report_pdf.find_browser(), self.browser.resolve())
            self.assertEqual(report_pdf.find_browser(self.browser), self.browser.resolve())
            self.assertIsNone(report_pdf.find_browser("https://example.invalid/chrome.exe"))
            self.assertIsNone(report_pdf.find_browser(self.root / "missing" / "chrome.exe"))
            other = self.root / "other.exe"
            other.write_bytes(b"do not execute")
            self.assertIsNone(report_pdf.find_browser(other))
            start.assert_not_called()

    def test_browser_path_fallback_has_no_process_or_environment_creation(self):
        with patch.object(report_pdf, "_known_browser_paths", return_value=iter([])), \
                patch.object(report_pdf.shutil, "which", return_value=str(self.browser)), \
                patch.object(report_pdf.tempfile, "TemporaryDirectory") as temporary, \
                patch.object(report_pdf.subprocess, "Popen") as start:
            self.assertEqual(report_pdf.find_browser(), self.browser.resolve())
            temporary.assert_not_called()
            start.assert_not_called()

    def test_nonzero_browser_exit_discards_even_pdf_shaped_output(self):
        self.process.wait.return_value = 1
        result = self.run_export()
        self.assertEqual(result["code"], "browser_failed")
        self.assertFalse(self.target.exists())
        self.assertTrue(all(not profile.parent.exists() for profile in self.profiles))

    def test_html_and_truncated_or_tiny_pdfs_are_rejected(self):
        bad = [b"<!doctype html>" + b"error" * 500,
               b"%PDF-1.7\n" + b"x" * 1500,
               b"%PDF-1.7\n%%EOF"]
        for data in bad:
            with self.subTest(data=data[:20]), patch(__name__ + ".PDF_BYTES", data):
                result = self.run_export()
                self.assertEqual(result["code"], "invalid_pdf")
                self.assertFalse(self.target.exists())

    def test_missing_and_oversized_render_are_rejected(self):
        def missing(command, **kwargs):
            return self.process
        with patch.object(report_pdf, "find_browser", return_value=self.browser), \
                patch.object(report_pdf.subprocess, "Popen", side_effect=missing):
            self.assertEqual(report_pdf.export_pdf(self.source, self.target)["code"], "pdf_missing")
        with patch.object(report_pdf, "MAX_PDF_BYTES", 1025):
            self.assertEqual(self.run_export()["code"], "invalid_pdf")
        self.assertFalse(self.target.exists())

    def test_timeout_stops_only_owned_child_and_removes_temporary_files(self):
        self.process.wait.side_effect = [subprocess.TimeoutExpired("private command", 1), 0]
        result = self.run_export(timeout=1)
        self.assertEqual(result["code"], "timeout")
        self.process.terminate.assert_called_once_with()
        self.process.kill.assert_not_called()
        self.assertFalse(self.target.exists())
        self.assertTrue(all(not profile.parent.exists() for profile in self.profiles))
        self.assertNotIn("private command", json.dumps(result))

    def test_timeout_kill_escalation_stays_on_same_child(self):
        expired = subprocess.TimeoutExpired("private command", 1)
        self.process.wait.side_effect = [expired, expired, 0]
        result = self.run_export(timeout=1)
        self.assertEqual(result["code"], "timeout")
        self.process.terminate.assert_called_once_with()
        self.process.kill.assert_called_once_with()
        self.assertFalse(self.target.exists())

    def test_target_created_during_rendering_is_preserved(self):
        def race(command, **kwargs):
            process = self.popen(command, **kwargs)
            self.target.parent.mkdir()
            self.target.write_bytes(b"other-user-file")
            return process
        with patch.object(report_pdf, "find_browser", return_value=self.browser), \
                patch.object(report_pdf.subprocess, "Popen", side_effect=race):
            result = report_pdf.export_pdf(self.source, self.target)
        self.assertEqual(result["code"], "output_exists")
        self.assertEqual(self.target.read_bytes(), b"other-user-file")

    def test_atomic_publication_race_never_overwrites_or_deletes_other_file(self):
        def race(stage, target):
            Path(target).write_bytes(b"raced-original")
            raise FileExistsError("private path")
        with patch.object(report_pdf.os, "link", side_effect=race):
            result = self.run_export()
        self.assertEqual(result["code"], "output_exists")
        self.assertEqual(self.target.read_bytes(), b"raced-original")
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])

    def test_failed_publication_leaves_no_pretend_pdf_or_staging_file(self):
        with patch.object(report_pdf.os, "link", side_effect=PermissionError("private target")):
            result = self.run_export()
        self.assertEqual(result["status"], "error")
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.target.parent.iterdir()), [])
        self.assertNotIn("private target", json.dumps(result))

    def test_invalid_timeout_and_unavailable_browser_errors_are_finite(self):
        for timeout in (0, -1, 301, float("nan"), float("inf"), True, "60"):
            self.assertEqual(report_pdf.export_pdf(self.source, self.target, timeout=timeout)["code"], "invalid_timeout")
        with patch.object(report_pdf, "find_browser", return_value=self.browser), \
                patch.object(report_pdf.subprocess, "Popen", side_effect=OSError("PRIVATE_REPORT_TEXT secret command")):
            result = report_pdf.export_pdf(self.source, self.target)
        self.assertEqual(result["status"], "error")
        self.assertNotIn("PRIVATE_REPORT_TEXT", json.dumps(result))
        self.assertFalse(self.target.exists())

    def test_cli_returns_one_json_object_and_sanitizes_parse_errors(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = report_pdf.main(["--private-unknown=PRIVATE_REPORT_TEXT"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out.getvalue())["code"], "invalid_arguments")
        self.assertNotIn("PRIVATE_REPORT_TEXT", out.getvalue())
        out = io.StringIO()
        expected = {"status": "needs_browser", "code": "browser_not_found", "message": "browser needed"}
        with redirect_stdout(out), patch.object(report_pdf, "export_pdf", return_value=expected) as export:
            code = report_pdf.main(["--input", str(self.source), "--output", str(self.target), "--browser", str(self.browser), "--timeout", "25"])
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out.getvalue()), expected)
        export.assert_called_once_with(str(self.source), str(self.target), str(self.browser), 25.0)


if __name__ == "__main__":
    unittest.main()
