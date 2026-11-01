"""Runtime launch, persistent cache and isolated preparation regressions."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", ROOT)).resolve()
if not (SKILL / "scripts/bootstrap.py").is_file():
    SKILL = ROOT / "package/mingxue-master"
sys.path.insert(0, str(SKILL / "scripts"))
import bootstrap
import runtime_paths as paths
import prepare_ziwei as pz
import prepare_astrology as pa


class RuntimePathsTests(unittest.TestCase):
    def test_entire_portable_or_compatibility_plugin_is_protected_from_engine_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            for index, manifest_name in enumerate(("plugin.json", ".codex-plugin/plugin.json")):
                plugin = Path(temp) / ("plugin-" + str(index))
                skill = plugin / "skills/example"
                skill.mkdir(parents=True)
                manifest = plugin / manifest_name
                manifest.parent.mkdir(parents=True, exist_ok=True)
                manifest.write_text(json.dumps({"name": "example", "version": "1.0.0"}), encoding="utf-8")
                target = plugin / "assets/cache"
                with patch.object(paths, "SKILL_ROOT", skill):
                    self.assertIn(plugin.resolve(), paths.protected_directories())
                    with self.assertRaises(ValueError):
                        paths.validate_external_directory(target)
                    sibling = Path(temp) / ("external-cache-" + str(index))
                    self.assertEqual(paths.validate_external_directory(sibling), sibling.resolve())
                self.assertFalse(target.exists())

    @unittest.skipUnless(os.name == "nt", "Windows home resolution under a genuinely empty environment")
    def test_empty_windows_environment_has_typed_cache_failure_and_runtime_report(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(paths.CacheHomeUnavailable):
                paths.engine_home()
            executable, _ = bootstrap.find_python()
            self.assertTrue(Path(executable).is_absolute())
            report = bootstrap.health_report()
            self.assertEqual(report["status"], "needs_runtime_setup")
            self.assertFalse(report["runtime_ready"])
            self.assertIn("cache home is unavailable", report["cache"]["error"])
            self.assertEqual(dict(os.environ), {})

    def test_missing_home_does_not_break_python_or_mask_invalid_explicit_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            explicit = Path(temp) / "explicit-cache"
            with patch.dict(os.environ, {}, clear=True), patch("pathlib.Path.home", side_effect=RuntimeError("home unavailable")):
                with self.assertRaises(paths.CacheHomeUnavailable):
                    paths.engine_home()
                executable, _ = bootstrap.find_python()
                self.assertTrue(Path(executable).is_absolute())
                with patch.dict(os.environ, {"MINGXUE_ENGINE_HOME": str(explicit)}):
                    self.assertEqual(paths.engine_home(), explicit)
                    self.assertFalse(explicit.exists())
                with patch.dict(os.environ, {"MINGXUE_ENGINE_HOME": "relative-cache"}):
                    with self.assertRaises(ValueError) as captured:
                        paths.engine_home()
                    self.assertNotIsInstance(captured.exception, paths.CacheHomeUnavailable)

    def test_persistent_default_and_override_are_read_only(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MINGXUE_ENGINE_HOME", None)
            default = paths.engine_home()
            self.assertIn("mingxue", default.parts)
            self.assertNotIn("mingxue-engines", default.parts)
            self.assertEqual(default.name, "engines")
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "persistent-cache"
            with patch.dict(os.environ, {"MINGXUE_ENGINE_HOME": str(home)}):
                self.assertEqual(paths.engine_directory("ziwei", "2.6.3"), home / "ziwei/2.6.3")
                self.assertEqual(paths.engine_home(), home)
                self.assertFalse(home.exists())

    def test_cache_rejects_skill_resources_global_python_and_ancestors(self):
        with self.assertRaisesRegex(ValueError, "absolute"):
            paths.validate_external_directory("relative-cache")
        for candidate in (SKILL, SKILL / "new-cache", SKILL.parent, Path(sys.prefix) / "Lib/site-packages/new-cache"):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                paths.validate_external_directory(candidate)
        with tempfile.TemporaryDirectory() as temp:
            resource = Path(temp) / "resources"
            with patch.dict(os.environ, {"MINGXUE_RESOURCE_DIR": str(resource)}):
                with self.assertRaises(ValueError):
                    paths.validate_external_directory(resource / "engines")
        for token in ("../astrology", "a/b", "", "a\\b"):
            with self.subTest(token=token), self.assertRaises(ValueError):
                paths.engine_directory(token, "1")

    def test_legacy_reporting_never_moves_or_creates(self):
        with tempfile.TemporaryDirectory() as temp:
            old = Path(temp) / "mingxue-engines/ziwei/2.6.3"
            old.mkdir(parents=True)
            keep = old / "keep.txt"
            keep.write_text("original", encoding="utf-8")
            with patch("runtime_paths.tempfile.gettempdir", return_value=temp), patch.dict(os.environ, {"MINGXUE_ENGINE_HOME": str(Path(temp) / "new")}):
                self.assertEqual(paths.legacy_engine_directories("ziwei", "2.6.3"), [old])
                self.assertEqual(keep.read_text(encoding="utf-8"), "original")
                self.assertFalse((Path(temp) / "new").exists())


class RuntimeDiscoveryTests(unittest.TestCase):
    def test_offline_intake_entry_is_launched_with_its_real_output_option(self):
        process=subprocess.run([sys.executable,'-X','utf8','-B',str(SKILL/'scripts/bootstrap.py'),'offline_intake','--help'],capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertIn('--output',process.stdout)
        self.assertIn('offline_intake',process.stdout)

    def test_windowsapps_alias_is_never_executed(self):
        with patch("bootstrap.subprocess.run", side_effect=AssertionError("alias must never run")):
            for name in ("python.exe", "python3.12.exe", "pythonw.exe", "pyw.exe"):
                alias = Path("C:/Users/example/AppData/Local/Microsoft/WindowsApps") / name
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, "WindowsApps"):
                    bootstrap.inspect_python(alias)

    def test_missing_python_and_explicit_bad_override_do_not_download(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("no download")):
            with self.assertRaises(ValueError):
                bootstrap.find_python([Path(tempfile.gettempdir()) / "nonexistent-runtime.exe"])
            with patch.dict(os.environ, {"MINGXUE_PYTHON": "missing-interpreter"}), patch("bootstrap.shutil.which", return_value=None):
                candidates = bootstrap.python_candidates()
                self.assertEqual(len(candidates), 1)
                self.assertEqual(candidates[0].name, "missing-interpreter")

    def test_existing_interpreter_after_alias_is_usable(self):
        executable, report = bootstrap.find_python([Path("C:/Users/example/AppData/Local/Microsoft/WindowsApps/python.exe"), Path(sys.executable)])
        self.assertEqual(report["version"][:2], [3, 12])
        self.assertTrue(Path(executable).is_absolute())
        self.assertFalse(bootstrap.is_windows_app_alias(executable))

    def test_node_and_npm_missing_are_clear(self):
        with patch("bootstrap.node_candidates", return_value=[]):
            with self.assertRaisesRegex(ValueError, "Node.js"):
                bootstrap.find_node()
        with patch("bootstrap.shutil.which", return_value=None):
            with self.assertRaisesRegex(ValueError, "npm"):
                bootstrap.npm_command(str(Path(tempfile.gettempdir()) / "missing-node/node.exe"))

    def test_health_probe_has_no_network_cache_creation_or_path_changes(self):
        previous_path = os.environ.get("PATH")
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "not-created"
            with patch.dict(os.environ, {"MINGXUE_ENGINE_HOME": str(home)}), patch("urllib.request.urlopen", side_effect=AssertionError("offline probe")):
                report = bootstrap.health_report()
            self.assertTrue(report["python"]["available"])
            self.assertFalse(report["network_access"])
            self.assertFalse(home.exists())
            self.assertEqual(previous_path, os.environ.get("PATH"))
            self.assertTrue(Path(report["source_root"]).is_absolute())


class RuntimeLaunchTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows launchers")
    def test_actual_cmd_launcher_finds_python_and_preserves_json(self):
        run = subprocess.run([str(SKILL / "launch.cmd"), "--probe", "--json"], cwd=tempfile.gettempdir(),
                             capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        report = json.loads(run.stdout)
        self.assertEqual(report["status"], "runtime_ready")
        self.assertIn("runtime_only", report["scope"])
        self.assertEqual(Path(report["source_root"]), SKILL)
        self.assertEqual(report["python"]["version"][:2], [3, 12])

    @unittest.skipUnless(os.name == "nt", "Windows launchers")
    def test_actual_launcher_routes_tool_without_wrapping_stdout(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "engine-cache/astrology"
            run = subprocess.run([str(SKILL / "launch.cmd"), "astrology", "--probe", "--engine-dir", str(missing)],
                                 capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(run.returncode, 3, run.stderr)
            report = json.loads(run.stdout)
            self.assertFalse(report["available"])
            self.assertFalse(missing.exists())


class PreparationTests(unittest.TestCase):
    def test_preparation_probes_are_offline_and_do_not_create_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "engine-cache/astrology"
            with patch("urllib.request.urlopen", side_effect=AssertionError("offline")):
                report = pa.probe(directory)
            self.assertFalse(report["available"])
            self.assertFalse(directory.exists())
            with patch("prepare_ziwei.download_archive", side_effect=AssertionError("offline")):
                with self.assertRaises(pz.ZiweiError):
                    pz.verify_engine_directory(Path(temp) / "empty")

    def test_failed_repair_keeps_original_before_staging_commit(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "engine-cache/ziwei"
            target.mkdir(parents=True)
            keep = target / "original.txt"
            keep.write_text("keep", encoding="utf-8")
            with patch("prepare_ziwei.find_node", return_value="existing-node"), patch("prepare_ziwei.download_archive", side_effect=OSError("download interrupted")):
                with self.assertRaises(OSError):
                    pz.prepare(target, repair=True)
            self.assertEqual(keep.read_text(encoding="utf-8"), "keep")
            self.assertEqual(list(target.parent.glob(".ziwei-prepare-*")), [])

    def test_failed_activation_restores_original_directory(self):
        source = paths.engine_directory("ziwei", pz.ENGINE_VERSION)
        if not (source / "archives").is_dir():
            self.skipTest("Explicit strict Ziwei preparation required")
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "engine-cache/ziwei"
            target.mkdir(parents=True)
            (target / "original.txt").write_text("original", encoding="utf-8")
            def copy_archive(name, destination):
                shutil.copyfile(source / "archives" / pz.archive_filename(name), destination)
            with patch("prepare_ziwei.download_archive", side_effect=copy_archive), patch("prepare_ziwei.probe", side_effect=[{"status": "available"}, pz.ZiweiError("engine_error", "activation failed")]):
                with self.assertRaises(pz.ZiweiError):
                    pz.prepare(target, repair=True)
            self.assertEqual((target / "original.txt").read_text(encoding="utf-8"), "original")
            self.assertEqual(len(list(target.parent.glob("ziwei.failed-*"))), 1)

    def test_astrology_failed_activation_restores_original_directory(self):
        source = paths.engine_directory("astrology", pa.ENGINE_VERSION) / pa.WHEEL_FILENAME
        if not source.is_file():
            self.skipTest("Explicit persistent astrology preparation required")
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "engine-cache/astrology"
            target.mkdir(parents=True)
            (target / "original.txt").write_text("original", encoding="utf-8")
            with patch("prepare_astrology.urllib.request.urlopen", return_value=io.BytesIO(source.read_bytes())), patch("prepare_astrology.probe", side_effect=pa.EngineError("activation failed")):
                with self.assertRaises(pa.EngineError):
                    pa.prepare(target, repair=True)
            self.assertEqual((target / "original.txt").read_text(encoding="utf-8"), "original")
            self.assertEqual(len(list(target.parent.glob("astrology.failed-*"))), 1)

    def test_existing_persistent_strict_cache_and_offline_repair_backup(self):
        source = paths.engine_directory("ziwei", pz.ENGINE_VERSION)
        if not (source / "archives").is_dir():
            self.skipTest("Explicit strict Ziwei preparation required for real archive regression")
        self.assertEqual(pz.verify_engine_directory(source, allow_legacy=False)["status"], "verified")
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "engine-cache/ziwei"
            target.mkdir(parents=True)
            (target / "old.txt").write_text("retained", encoding="utf-8")
            def copy_archive(name, destination):
                shutil.copyfile(source / "archives" / pz.archive_filename(name), destination)
            with patch("prepare_ziwei.download_archive", side_effect=copy_archive), patch("urllib.request.urlopen", side_effect=AssertionError("offline repair")):
                result = pz.prepare(target, repair=True)
            backup = Path(result["previous_cache_backup"])
            self.assertEqual((backup / "old.txt").read_text(encoding="utf-8"), "retained")
            self.assertEqual(pz.verify_engine_directory(target, allow_legacy=False)["status"], "verified")
            self.assertFalse(result["scripts_executed"])
            # Tamper with an executable file and its editable manifest together.
            js = next((target / "node_modules/iztro").rglob("*.js"))
            js.write_bytes(js.read_bytes() + b"\n// changed\n")
            marker = target / "mingxue-engine.json"
            value = json.loads(marker.read_text(encoding="utf-8"))
            value["files"][js.relative_to(target).as_posix()] = hashlib.sha256(js.read_bytes()).hexdigest()
            marker.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(pz.ZiweiError):
                pz.verify_engine_directory(target, allow_legacy=False)


if __name__ == "__main__":
    unittest.main()
