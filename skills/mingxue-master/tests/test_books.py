"""Offline tests: every HTTP response is an in-memory fixture; no external requests."""

from __future__ import annotations

import contextlib
from email.message import Message
import errno
import hashlib
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys

sys.dont_write_bytecode = True

import tempfile
import unittest
from unittest import mock
import urllib.error
import urllib.parse
import urllib.request
import zipfile


BASE = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", BASE / "package" / "mingxue-master"))
if not (ROOT / "scripts" / "book_search.py").is_file():
    ROOT = BASE
SCRIPT = ROOT / "scripts" / "book_search.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("book_search_under_test", SCRIPT)
book = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(book)

MD5 = "a" * 32
MD5_TWO = "b" * 32
PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def epub_bytes():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", b"application/epub+zip")
        archive.writestr("META-INF/container.xml", b"<?xml version='1.0'?><container/>")
    return buffer.getvalue()


def search_page(md5=MD5, title="测试图书", extension="pdf"):
    cells = [f'<a href="edition.php?id=1">{title}</a><a href="ads.php?md5={md5}">GET</a>',
             "示例作者", "示例出版社", "2020", "Chinese", "100", "1 MiB", extension, ""]
    return ("<html><table><tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr></table></html>").encode()


ARCHIVE_ID = "public-sample-1910"


def archive_payload(files=None, **metadata):
    return {
        "metadata": {"identifier": ARCHIVE_ID, "title": "Public Test Book", "creator": ["Test Author"],
                     "date": "1910", "edition": "1910 annotated edition", "language": "eng",
                     "licenseurl": "https://creativecommons.org/publicdomain/mark/1.0/", **metadata},
        "files": files if files is not None else [{
            "name": "book.pdf", "format": "Text PDF", "size": str(len(PDF)),
            "md5": hashlib.md5(PDF, usedforsecurity=False).hexdigest(),
        }],
    }


class Response(io.BytesIO):
    def __init__(self, data, headers=None, url="https://libgen.li/fixture", *, fault=None):
        super().__init__(data)
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = str(value)
        self.url = url
        self.fault = fault
        self.reads = 0

    def geturl(self):
        return self.url

    def read(self, size=-1):
        self.reads += 1
        if self.fault and self.reads > 1:
            raise self.fault
        return super().read(size)


class FixtureOpener:
    def __init__(self, router):
        self.router = router
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        value = self.router(request, len(self.calls))
        if isinstance(value, BaseException):
            raise value
        return value


class BookTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="book-search-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.store = book.SessionStore(self.base / "workspace")
        self.output = self.base / "output"
        self.sleeps = []

    def client(self, router, retries=0, *, agent_model="fixture-model"):
        opener = FixtureOpener(router)
        client = book.HttpClient(timeout=5, retries=retries, opener=opener, sleep=self.sleeps.append, agent_model=agent_model)
        client.fixture_opener = opener
        return client

    def session(self, *, extension="pdf", title="测试图书"):
        return self.store.save({"query": title, "results": [{
            "source": "libgen", "md5": MD5, "index": 1, "title": title, "extension": extension,
        }]})

    def download_client(self, data=PDF, *, headers=None, fault=None, retries=0):
        download_headers = {"Content-Type": "application/octet-stream", "Content-Length": len(data)}
        download_headers.update(headers or {})

        def router(req, count):
            if "/ads.php?" in req.full_url:
                return Response(f'<a href="get.php?md5={MD5}&amp;key=EXAMPLE">GET</a>'.encode())
            if "/get.php?" in req.full_url:
                return Response(data, download_headers, fault=fault)
            raise AssertionError(f"Unexpected fixture URL: {req.full_url}")

        return self.client(router, retries)

    def run_main(self, argv, client=None):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            if client is None:
                code = book.main(argv)
            else:
                with mock.patch.object(book, "HttpClient", return_value=client):
                    code = book.main(argv)
        return code, json.loads(output.getvalue())

    def test_multi_source_merge_has_one_global_index_and_limit(self):
        def router(req, count):
            if "libgen.li" in req.full_url:
                return Response(search_page() + search_page(MD5_TWO, "第二本"))
            return Response(json.dumps({"success": 1, "books": [
                {"id": "99", "hash": "exampleHash", "title": "认证源图书", "extension": "epub"},
                {"id": "100", "hash": "otherHash", "title": "第四本", "extension": "pdf"},
            ]}).encode())

        with mock.patch.dict(os.environ, {"Z_LIBRARY_ID": "test-user", "Z_LIBRARY_KEY": "test-key"}):
            result = book.search("关键词", ["libgen", "zlib"], 3, self.client(router), self.store)
        self.assertEqual(result["status"], "ok")
        self.assertEqual([row["index"] for row in result["results"]], [1, 2, 3])
        self.assertEqual([row["source"] for row in result["results"]], ["libgen", "zlib", "libgen"])
        self.assertEqual(len({row["result_id"] for row in result["results"]}), 3)
        cached = self.store.load(result["session_id"])
        self.assertEqual(cached["results"], result["results"])
        cache_text = (self.store.sessions / f"{result['session_id']}.json").read_text(encoding="utf-8")
        self.assertNotIn("test-key", cache_text)
        self.assertNotIn("test-user", cache_text)

    def test_same_source_duplicate_removed(self):
        groups = [[{"source": "libgen", "md5": MD5}, {"source": "libgen", "md5": MD5}],
                  [{"source": "libgen", "md5": MD5_TWO}]]
        merged = book._merge_results(groups, 10)
        self.assertEqual([row["index"] for row in merged], [1, 2])

    def archive_client(self, payload=None, *, data=PDF, search_payload=None, retries=0):
        metadata = archive_payload() if payload is None else payload
        search_data = search_payload if search_payload is not None else {"response": {
            "numFound": 1, "docs": [{"identifier": ARCHIVE_ID, "title": "Public Test Book"}],
        }}

        def router(req, count):
            if "/advancedsearch.php?" in req.full_url:
                return Response(json.dumps(search_data).encode())
            if "/metadata/" in req.full_url:
                return Response(json.dumps(metadata).encode())
            if "/download/" in req.full_url:
                return Response(data, {"Content-Length": len(data)})
            self.fail(f"Unexpected offline archive fixture: {req.full_url}")

        return self.client(router, retries)

    def test_default_archive_cli_metadata_version_and_source_status(self):
        client = self.archive_client()
        code, result = self.run_main(["search", "Public Test Book", "--work-dir", str(self.store.root)], client)
        self.assertEqual(code, 0)
        self.assertEqual(result["sources"][0]["source"], "archive")
        self.assertTrue(result["sources"][0]["network_checked"])
        self.assertIn("checked_at", result["sources"][0])
        entry = result["results"][0]
        self.assertEqual(entry["version_id"], ARCHIVE_ID)
        self.assertEqual(entry["edition_status"], "source_stated")
        self.assertEqual(entry["edition"], "1910 annotated edition")
        self.assertEqual(entry["available_formats"], ["pdf"])
        self.assertEqual(entry["acquisition_status"], "public_file_listed_not_downloaded")
        self.assertEqual(entry["rights_metadata"]["verification"], "source_metadata_only_not_independent_authorization_check")
        self.assertTrue(all("fixture-model" in req.get_header("User-agent") for req, _ in client.fixture_opener.calls))

    def test_archive_format_choice_and_source_checksum_are_verified(self):
        text_data = "Public test book 文本\n".encode()
        files = archive_payload()["files"] + [{
            "name": "book.txt", "format": "Text", "size": str(len(text_data)),
            "md5": hashlib.md5(text_data, usedforsecurity=False).hexdigest(),
        }]
        metadata = archive_payload(files)
        record = book.search("Public", ["archive"], 1, self.archive_client(metadata), self.store)
        self.assertEqual(record["results"][0]["extension"], "pdf")
        client = self.archive_client(metadata, data=text_data)
        result = book.download(record["session_id"], 1, self.output, client, self.store, format_="txt")
        self.assertEqual(result["extension"], "txt")
        self.assertEqual(result["source_checksum_status"], "matched")
        self.assertEqual(result["source_md5"], hashlib.md5(text_data, usedforsecurity=False).hexdigest())
        self.assertEqual(Path(result["path"]).read_bytes(), text_data)
        self.assertTrue(any("/download/" + ARCHIVE_ID + "/book.txt" in req.full_url for req, _ in client.fixture_opener.calls))
        self.assertEqual(list(self.store.partials.iterdir()), [])

    def test_archive_changed_file_requires_new_search(self):
        record = book.search("Public", ["archive"], 1, self.archive_client(), self.store)
        changed = archive_payload()
        changed["files"][0]["md5"] = "b" * 32
        client = self.archive_client(changed)
        with self.assertRaises(book.BookError) as error:
            book.download(record["session_id"], 1, self.output, client, self.store)
        self.assertEqual(error.exception.code, "version_changed")
        self.assertFalse(any("/download/" in req.full_url for req, _ in client.fixture_opener.calls))

    def test_archive_wrong_file_checksum_not_saved(self):
        record = book.search("Public", ["archive"], 1, self.archive_client(), self.store)
        wrong_pdf = PDF.replace(b"1.4", b"1.5")
        with self.assertRaises(book.BookError) as error:
            book.download(record["session_id"], 1, self.output, self.archive_client(data=wrong_pdf), self.store)
        self.assertEqual(error.exception.code, "checksum_mismatch")
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(list(self.store.partials.iterdir()), [])

    def test_archive_private_restricted_and_path_traversal_files_not_offered(self):
        for restriction in ("access-restricted-item", "is_dark", "is_lendable"):
            payload = archive_payload()
            if restriction == "access-restricted-item":
                payload["metadata"][restriction] = "true"
            else:
                payload[restriction] = True
            with self.subTest(restriction=restriction):
                record = book.search("Public", ["archive"], 1, self.archive_client(payload), self.store)
                entry = record["results"][0]
                self.assertFalse(entry["download"]["supported"])
                self.assertEqual(entry["acquisition_status"], "restricted")
        files = archive_payload()["files"]
        files += [{"name": "../escape.pdf", "size": 10}, {"name": "/absolute.pdf", "size": 10},
                  {"name": r"C:\private.pdf", "size": 10}, {"name": "private.pdf", "size": 10, "private": "true"}]
        offered = book._archive_files(archive_payload(files))
        self.assertEqual([entry["name"] for entry in offered], ["book.pdf"])

    def test_archive_new_restriction_blocks_cached_download(self):
        record = book.search("Public", ["archive"], 1, self.archive_client(), self.store)
        restricted = archive_payload(**{"access-restricted-item": True})
        client = self.archive_client(restricted)
        with self.assertRaises(book.BookError) as error:
            book.download(record["session_id"], 1, self.output, client, self.store)
        self.assertEqual(error.exception.code, "download_unavailable")
        self.assertFalse(any("/download/" in req.full_url for req, _ in client.fixture_opener.calls))

    def test_archive_metadata_failure_is_partial_not_empty_result(self):
        record = book.search("Public", ["archive"], 1, self.archive_client({"error": "Item unavailable"}), self.store)
        self.assertEqual(record["status"], "partial")
        self.assertEqual(record["sources"][0]["status"], "partial")
        self.assertEqual(record["results"][0]["acquisition_status"], "metadata_error")
        self.assertFalse(record["results"][0]["download"]["supported"])

    def test_archive_empty_and_malformed_api_responses_are_distinct(self):
        empty = book.search("Public", ["archive"], 1, self.archive_client(search_payload={"response": {"numFound": 0, "docs": []}}), self.store)
        self.assertEqual(empty["status"], "no_results")
        for payload in ({"error": "bad query"}, {"response": {"numFound": 10, "docs": []}}, {"response": {"docs": "bad"}}):
            with self.subTest(payload=payload):
                record = book.search("Public", ["archive"], 1, self.archive_client(search_payload=payload), self.store)
                self.assertEqual(record["status"], "error")
                self.assertEqual(record["sources"][0]["error"]["code"], "invalid_response")
                self.assertNotEqual(record["session_id"], empty["session_id"])

    def test_archive_collection_and_phrase_are_preserved_in_api_query(self):
        client = self.archive_client()
        book.search('A "quoted" title', ["archive"], 1, client, self.store, archive_collection="gutenberg")
        request = client.fixture_opener.calls[0][0]
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)["q"][0]
        self.assertIn(r'title:"A \"quoted\" title"', query)
        self.assertIn("collection:gutenberg", query)
        self.assertIn("-access-restricted-item:true", query)

    def test_archive_unavailable_format_rejected_without_request(self):
        record = book.search("Public", ["archive"], 1, self.archive_client(), self.store)
        with self.assertRaises(book.BookError) as error:
            book.download(record["session_id"], 1, self.output,
                          self.client(lambda r, c: self.fail("No download expected")), self.store, format_="epub")
        self.assertEqual(error.exception.code, "format_unavailable")

    def test_retry_after_is_honored_and_long_rate_limit_stops(self):
        self.assertIsNone(book._retry_after("nan"))
        self.assertIsNone(book._retry_after("inf"))
        def transient(req, count):
            if count == 1:
                return urllib.error.HTTPError(req.full_url, 429, "Rate limited", {"Retry-After": "2"}, None)
            return Response(b"ok")

        client = self.client(transient, retries=1)
        self.assertEqual(client.read_bytes("https://archive.org/example"), b"ok")
        self.assertEqual(self.sleeps, [2.0])
        self.sleeps.clear()
        client = self.client(lambda req, count: urllib.error.HTTPError(req.full_url, 429, "Rate limited", {"Retry-After": "300"}, None), retries=3)
        with self.assertRaises(book.BookError) as error:
            client.read_bytes("https://archive.org/example")
        self.assertEqual(error.exception.code, "rate_limited")
        self.assertEqual(error.exception.as_dict()["retry_after_seconds"], 300)
        self.assertEqual(len(client.fixture_opener.calls), 1)
        self.assertEqual(self.sleeps, [])

    def test_agent_model_can_be_overridden_and_header_injection_rejected(self):
        with mock.patch.dict(os.environ, {"BOOK_SEARCH_AGENT_MODEL": "gpt-example"}):
            client = self.client(lambda r, c: Response(b"ok"), agent_model=None)
            client.read_bytes("https://archive.org/metadata/example")
        self.assertIn("gpt-example", client.fixture_opener.calls[0][0].get_header("User-agent"))
        with self.assertRaises(book.BookError):
            book.HttpClient(agent_model="model\r\nBad: injected")

    def test_model_default_is_unspecified_and_archive_is_blocked_before_request(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            client = self.client(lambda r, c: Response(b"ok"), agent_model=None)
        self.assertIsNone(client.agent_model)
        self.assertIn("model unspecified", client.user_agent)
        with self.assertRaises(book.BookError) as error:
            client.read_bytes("https://archive.org/metadata/example")
        self.assertEqual(error.exception.code, "model_id_required")
        self.assertEqual(client.fixture_opener.calls, [])
        self.assertEqual(client.read_bytes("https://libgen.li/example"), b"ok")
        self.assertIn("model unspecified", client.fixture_opener.calls[0][0].get_header("User-agent"))
        request = urllib.request.Request("https://libgen.li/example")
        with self.assertRaises(book.BookError) as error:
            book.SafeRedirectHandler().redirect_request(request, None, 302, "", {}, "https://archive.org/metadata/example")
        self.assertEqual(error.exception.code, "model_id_required")

    def test_cli_missing_model_returns_model_id_required_without_network(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(urllib.request.OpenerDirector, "open", side_effect=AssertionError("No request without model identity")):
            code, result = self.run_main(["search", "Public Test Book", "--work-dir", str(self.store.root)])
        self.assertNotEqual(code, 0)
        self.assertEqual(result["error"]["code"], "model_id_required")

    def test_cli_explicit_model_overrides_environment_and_env_is_used_when_not_supplied(self):
        for explicit in (None, "explicit-model"):
            fixture = self.archive_client().fixture_opener
            argv = ["search", "Public Test Book", "--work-dir", str(self.store.root)]
            if explicit:
                argv += ["--agent-model", explicit]
            with self.subTest(explicit=explicit), \
                 mock.patch.dict(os.environ, {"BOOK_SEARCH_AGENT_MODEL": "environment-model"}), \
                 mock.patch.object(urllib.request, "build_opener", return_value=fixture):
                code, result = self.run_main(argv)
            self.assertEqual(code, 0)
            self.assertEqual(result["sources"][0]["source"], "archive")
            expected = explicit or "environment-model"
            self.assertTrue(fixture.calls)
            self.assertTrue(all(expected in req.get_header("User-agent") for req, _ in fixture.calls))

    def test_cached_archive_download_requires_current_explicit_model(self):
        record = book.search("Public", ["archive"], 1, self.archive_client(), self.store)
        with mock.patch.dict(os.environ, {}, clear=True):
            client = self.client(lambda r, c: self.fail("No archive request without model identity"), agent_model=None)
        with self.assertRaises(book.BookError) as error:
            book.download(record["session_id"], 1, self.output, client, self.store)
        self.assertEqual(error.exception.code, "model_id_required")
        self.assertEqual(client.fixture_opener.calls, [])
        self.assertEqual(list(self.store.partials.iterdir()), [])

    def test_global_index_download_dispatches_correct_source_without_auth_leak(self):
        def router(req, count):
            if "/eapi/book/99/exampleHash/file" in req.full_url:
                self.assertIn("remix_userkey=test-key", req.get_header("Cookie"))
                return Response(json.dumps({"success": 1, "file": {
                    "allowDownload": True, "downloadLink": "https://cdn.example.invalid/book.pdf",
                }}).encode())
            if "cdn.example.invalid" in req.full_url:
                self.assertIsNone(req.get_header("Cookie"))
                self.assertIsNone(req.get_header("Remix-userkey"))
                return Response(PDF, {"Content-Length": len(PDF)})
            self.fail(f"Wrong source or record requested: {req.full_url}")

        record = self.store.save({"query": "多源", "results": [
            {"source": "libgen", "md5": MD5, "index": 1, "title": "第一本", "extension": "pdf"},
            {"source": "zlib", "id": "99", "hash": "exampleHash", "host": book.ZLIB_HOSTS[0],
             "index": 2, "title": "第二本", "extension": "pdf"},
        ]})
        with mock.patch.dict(os.environ, {"Z_LIBRARY_ID": "test-user", "Z_LIBRARY_KEY": "test-key"}):
            result = book.download(record["session_id"], 2, self.output, self.client(router), self.store)
        self.assertEqual(result["source"], "zlib")
        self.assertEqual(result["index"], 2)
        self.assertEqual(Path(result["path"]).read_bytes(), PDF)

    def test_workspaces_are_isolated(self):
        record = self.session()
        other = book.SessionStore(self.base / "other-workspace")
        with self.assertRaises(book.BookError) as error:
            other.load(record["session_id"])
        self.assertEqual(error.exception.code, "session_not_found")
        self.assertFalse((SCRIPT.parent / ".last_results.json").exists())

    def test_default_workspace_is_temporary_and_env_overrides(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(book.tempfile, "gettempdir", return_value=str(self.base)):
            default = book.SessionStore()
        self.assertEqual(default.root, (self.base / "mingxue-book-search").resolve())
        with mock.patch.dict(os.environ, {"BOOK_SEARCH_WORK_DIR": str(self.base / "from-env")}):
            self.assertEqual(book.SessionStore().root, (self.base / "from-env").resolve())
            self.assertEqual(book.SessionStore(self.base / "explicit").root, (self.base / "explicit").resolve())

    def test_work_dir_inside_skill_rejected_before_mkdir_or_http(self):
        target = ROOT / "private-work-regression-do-not-create"
        self.assertFalse(target.exists())
        with mock.patch.object(Path, "mkdir", side_effect=AssertionError("Must reject before mkdir")), \
             mock.patch.object(book, "HttpClient", side_effect=AssertionError("Must reject before HTTP setup")):
            code, result = self.run_main(["search", "任意", "--sources", "annas", "--work-dir", str(target)])
        self.assertNotEqual(code, 0)
        self.assertEqual(result["error"]["code"], "protected_path")
        self.assertFalse(target.exists())

    def test_output_inside_skill_rejected_before_workspace_creation_or_http(self):
        target = ROOT / "private-download-regression-do-not-create"
        unused_work = self.base / "unused-work"
        with mock.patch.object(Path, "mkdir", side_effect=AssertionError("Must reject before mkdir")), \
             mock.patch.object(book, "HttpClient", side_effect=AssertionError("Must reject before HTTP setup")):
            code, result = self.run_main([
                "download", "1", "--session", "f" * 32, "--output", str(target), "--work-dir", str(unused_work),
            ])
        self.assertNotEqual(code, 0)
        self.assertEqual(result["error"]["code"], "protected_path")
        self.assertFalse(target.exists())
        self.assertFalse(unused_work.exists())

    def test_default_and_configured_resource_roots_protect_work_and_output(self):
        defaults = self.base / "mingxue-master-cache"
        cache = self.base / "configured-cache"
        resources = self.base / "configured-resources"
        env = {"MINGXUE_CACHE_DIR": str(cache), "MINGXUE_RESOURCE_DIR": str(resources)}
        with mock.patch.dict(os.environ, env), mock.patch.object(book.tempfile, "gettempdir", return_value=str(self.base)):
            for root in (defaults, cache, resources):
                for target in (root, root / "nested" / "private"):
                    with self.subTest(target=target):
                        with self.assertRaises(book.BookError) as error:
                            book.SessionStore(target)
                        self.assertEqual(error.exception.code, "protected_path")
                        with self.assertRaises(book.BookError) as error:
                            book.download("f" * 32, 1, target,
                                          self.client(lambda r, c: self.fail("No request expected")), self.store)
                        self.assertEqual(error.exception.code, "protected_path")
                        self.assertFalse(target.exists())

    def test_known_resource_cache_names_are_protected(self):
        for dirname in ("mingxue-master-cache", "mingxue-resources-legacy"):
            target = self.base / "old-install" / dirname / "private"
            with self.subTest(dirname=dirname), self.assertRaises(book.BookError) as error:
                book.SessionStore(target)
            self.assertEqual(error.exception.code, "protected_path")
            self.assertFalse(target.exists())

    def test_resolved_aliases_into_protected_roots_and_out_of_skill_are_rejected(self):
        outside_alias = self.base / "alias-to-skill"
        inside_alias = ROOT / "alias-to-outside"
        real_resolve = Path.resolve

        def alias_resolve(path, *args, **kwargs):
            if path.is_relative_to(outside_alias):
                return ROOT / path.relative_to(outside_alias)
            if path.is_relative_to(inside_alias):
                return self.base / "outside" / path.relative_to(inside_alias)
            return real_resolve(path, *args, **kwargs)

        with mock.patch.object(Path, "resolve", alias_resolve):
            for target in (outside_alias / "private", inside_alias / "private"):
                with self.subTest(target=target), self.assertRaises(book.BookError) as error:
                    book.SessionStore(target)
                self.assertEqual(error.exception.code, "protected_path")

    def test_existing_workspace_child_alias_cannot_write_into_skill_or_escape(self):
        real_resolve = Path.resolve
        work = self.base / "fresh-work"
        for redirect, expected in ((ROOT / "private", "protected_path"),
                                   (self.base / "different-work", "unsafe_work_dir")):
            def alias_resolve(path, *args, **kwargs):
                if path == work / "sessions":
                    return redirect
                return real_resolve(path, *args, **kwargs)

            with self.subTest(redirect=redirect), mock.patch.object(Path, "resolve", alias_resolve):
                with self.assertRaises(book.BookError) as error:
                    book.SessionStore(work)
                self.assertEqual(error.exception.code, expected)
                self.assertFalse(work.exists())

    def test_windows_junction_into_skill_is_rejected(self):
        if os.name != "nt":
            self.skipTest("Windows junction test")
        try:
            import _winapi
        except ImportError:
            self.skipTest("Windows junction API is unavailable")
        alias = self.base / "junction-to-skill"
        try:
            _winapi.CreateJunction(str(ROOT.resolve()), str(alias))
        except (AttributeError, OSError):
            self.skipTest("Junction creation is unavailable on this host")
        try:
            with self.assertRaises(book.BookError) as error:
                book.SessionStore(alias / "private-work-regression-do-not-create")
            self.assertEqual(error.exception.code, "protected_path")
            with self.assertRaises(book.BookError) as error:
                book.download("f" * 32, 1, alias / "private-download-regression-do-not-create",
                              self.client(lambda r, c: self.fail("No request expected")), self.store)
            self.assertEqual(error.exception.code, "protected_path")
        finally:
            # rmdir 仅移除已确认的 junction 自身，不遍历其指向的技能目录。
            self.assertTrue(alias.is_junction())
            alias.rmdir()

    def test_local_imports_do_not_write_bytecode(self):
        self.assertTrue(book.sys.dont_write_bytecode)

    def test_empty_search_creates_new_empty_session(self):
        first = book.search("有结果", ["libgen"], 15, self.client(lambda r, c: Response(search_page())), self.store)
        empty = book.search("没有", ["libgen"], 15, self.client(lambda r, c: Response(b"<html>No books found</html>")), self.store)
        self.assertNotEqual(first["session_id"], empty["session_id"])
        self.assertEqual(empty["status"], "no_results")
        self.assertEqual(self.store.load(empty["session_id"])["results"], [])
        with self.assertRaises(book.BookError) as error:
            book.download(empty["session_id"], 1, self.output, self.client(lambda r, c: self.fail("No request expected")), self.store)
        self.assertEqual(error.exception.code, "invalid_index")

    def test_source_error_distinct_from_no_results(self):
        client = self.client(lambda r, c: urllib.error.HTTPError(r.full_url, 503, "unavailable", {}, None))
        result = book.search("关键词", ["libgen"], 10, client, self.store)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["sources"][0]["error"]["code"], "http_error")
        self.assertEqual(result["results"], [])

    def test_block_page_and_unknown_layout_are_errors(self):
        for page, code in [(b"<html><title>Just a moment...</title>cf-chl-123</html>", "source_blocked"),
                           (b"<html><table><td>Unrecognized server message</td></table></html>", "unrecognized_page")]:
            with self.subTest(page=page):
                result = book.search("关键词", ["libgen"], 10, self.client(lambda r, c: Response(page)), self.store)
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["sources"][0]["error"]["code"], code)

    def test_manual_source_truthfully_returns_link_without_http(self):
        result = book.search("书名 with spaces", ["annas"], 10, self.client(lambda r, c: self.fail("No HTTP expected")), self.store)
        self.assertEqual(result["status"], "manual")
        self.assertEqual(result["results"], [])
        self.assertEqual(result["sources"][0]["status"], "manual")
        self.assertIn("q=", result["sources"][0]["search_url"])

    def test_optional_credentials_are_not_automatically_enabled(self):
        client = self.client(lambda r, c: Response(search_page()))
        with mock.patch.dict(os.environ, {"Z_LIBRARY_ID": "test-user", "Z_LIBRARY_KEY": "test-key"}):
            code, result = self.run_main(["search", "测试", "--sources", "libgen", "--work-dir", str(self.store.root)], client)
        self.assertEqual(code, 0)
        self.assertEqual([item["source"] for item in result["sources"]], ["libgen"])
        self.assertTrue(all("libgen.li" in request.full_url for request, _ in client.fixture_opener.calls))

    def test_explicit_auth_source_reports_missing_credentials(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            result = book.search("测试", ["zlib"], 10, self.client(lambda r, c: self.fail("No HTTP expected")), self.store)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["sources"][0]["error"]["code"], "credentials_missing")

    def test_windows_filename_and_server_path_sanitized(self):
        for filename in ["../../CON.pdf", r"C:\secret\report.pdf", "bad<>:\"|?*.pdf", "../图书.pdf"]:
            with self.subTest(filename=filename):
                record = self.session()
                value = book.download(record["session_id"], 1, self.output, self.download_client(headers={
                    "Content-Disposition": f"attachment; filename*=UTF-8''{urllib.parse.quote(filename, safe='')}"
                }), self.store)
                target = Path(value["path"])
                self.assertEqual(target.parent, self.output.resolve())
                self.assertFalse(any(char in target.name for char in '<>:"/\\|?*'))
                self.assertNotEqual(target.name.upper(), "CON.PDF")
                self.assertEqual(target.read_bytes(), PDF)

    def test_session_id_path_traversal_rejected(self):
        for session_id in ["../other", "a" * 32 + "/../other", r"C:\secret\file"]:
            with self.subTest(session_id=session_id), self.assertRaises(book.BookError) as error:
                self.store.load(session_id)
            self.assertEqual(error.exception.code, "invalid_session")

    def test_target_resolve_outside_output_is_rejected_without_symlink_privilege(self):
        self.output.mkdir()
        real_resolve = Path.resolve
        candidate = self.output / "escape.pdf"

        def fixture_resolve(path, *args, **kwargs):
            if path == candidate:
                return self.base / "outside" / "escape.pdf"
            return real_resolve(path, *args, **kwargs)

        with mock.patch.object(Path, "resolve", fixture_resolve):
            with self.assertRaises(book.BookError) as error:
                book._target_path(self.output, "escape.pdf")
        self.assertEqual(error.exception.code, "unsafe_output_path")

    def test_html_and_json_error_pages_are_rejected(self):
        cases = [(b"<!DOCTYPE html><html>Download denied</html>", "application/octet-stream"),
                 (PDF, "text/html"), (b'{"error":"rate limited"}', "application/json"),
                 (b"Access Denied", "application/octet-stream")]
        for data, content_type in cases:
            with self.subTest(data=data):
                record = self.session()
                with self.assertRaises(book.BookError) as error:
                    book.download(record["session_id"], 1, self.output,
                                  self.download_client(data, headers={"Content-Type": content_type}), self.store)
                self.assertEqual(error.exception.code, "not_a_book")
                self.assertEqual(list(self.store.partials.iterdir()), [])
                self.assertEqual(list(self.output.iterdir()), [])

    def test_magic_and_extension_mismatch_rejected(self):
        for data, headers, extension in [(b"not really a pdf", {}, "pdf"),
                                         (PDF, {"Content-Disposition": 'attachment; filename="book.epub"'}, "pdf"),
                                         (PDF, {}, "epub"), (b"%PDF-1.4\ntruncated", {}, "pdf")]:
            with self.subTest(extension=extension, headers=headers):
                record = self.session(extension=extension)
                with self.assertRaises(book.BookError) as error:
                    book.download(record["session_id"], 1, self.output, self.download_client(data, headers=headers), self.store)
                self.assertEqual(error.exception.code, "format_mismatch")
                self.assertEqual(list(self.store.partials.iterdir()), [])
                self.assertEqual(list(self.output.iterdir()), [])

    def test_stream_interruption_retries_bounded_and_cleans_files(self):
        record = self.session()
        client = self.download_client(fault=http.client.IncompleteRead(b"", 20), retries=2)
        with self.assertRaises(book.BookError) as error:
            book.download(record["session_id"], 1, self.output, client, self.store)
        self.assertEqual(error.exception.code, "interrupted_download")
        self.assertEqual(len([req for req, _ in client.fixture_opener.calls if "/get.php" in req.full_url]), 3)
        self.assertEqual(len(self.sleeps), 2)
        self.assertEqual(list(self.store.partials.iterdir()), [])
        self.assertEqual(list(self.output.iterdir()), [])

    def test_silent_truncation_content_length_detected(self):
        record = self.session()
        with self.assertRaises(book.BookError) as error:
            book.download(record["session_id"], 1, self.output,
                          self.download_client(headers={"Content-Length": len(PDF) + 1}), self.store)
        self.assertEqual(error.exception.code, "incomplete_download")
        self.assertEqual(list(self.store.partials.iterdir()), [])
        self.assertEqual(list(self.output.iterdir()), [])

    def test_valid_pdf_and_epub_are_saved_with_hash(self):
        for extension, data in [("pdf", PDF), ("epub", epub_bytes())]:
            with self.subTest(extension=extension):
                record = self.session(extension=extension)
                result = book.download(record["session_id"], 1, self.output, self.download_client(data), self.store)
                self.assertEqual(result["status"], "ok")
                self.assertEqual(Path(result["path"]).read_bytes(), data)
                self.assertEqual(result["sha256"], hashlib.sha256(data).hexdigest())
                self.assertEqual(Path(result["path"]).suffix, "." + extension)
                self.assertEqual(list(self.store.partials.iterdir()), [])

    def test_text_multibyte_boundary_is_valid_and_utf16_html_is_rejected(self):
        record = self.session(extension="txt")
        text_data = ("中" * 4000).encode("utf-8")
        result = book.download(record["session_id"], 1, self.output, self.download_client(text_data), self.store)
        self.assertEqual(Path(result["path"]).read_bytes(), text_data)
        invalid = "<html><body>Access denied</body></html>".encode("utf-16")
        with self.assertRaises(book.BookError):
            book.download(record["session_id"], 1, self.output, self.download_client(invalid), self.store)
        self.assertEqual(len(list(self.output.iterdir())), 1)
        self.assertEqual(list(self.store.partials.iterdir()), [])

    def test_existing_file_preserved_and_deduplicated(self):
        self.output.mkdir()
        existing = self.output / "book.pdf"
        existing.write_bytes(b"original")
        record = self.session()
        result = book.download(record["session_id"], 1, self.output,
                               self.download_client(headers={"Content-Disposition": 'attachment; filename="book.pdf"'}), self.store)
        self.assertEqual(existing.read_bytes(), b"original")
        self.assertEqual(Path(result["path"]).name, "book (1).pdf")

    def test_concurrent_target_creation_is_not_overwritten_or_deleted(self):
        self.output.mkdir()
        part = self.store.partials / "concurrent.part"
        part.write_bytes(PDF)
        target = self.output / "concurrent.pdf"

        def competing_link(source, destination):
            Path(destination).write_bytes(b"someone else's file")
            raise FileExistsError(errno.EEXIST, "fixture target created concurrently")

        with mock.patch.object(book.os, "link", side_effect=competing_link):
            with self.assertRaises(FileExistsError):
                book._commit_file(part, self.output, target.name)
        self.assertEqual(target.read_bytes(), b"someone else's file")
        self.assertEqual(part.read_bytes(), PDF)

    def test_symlink_target_cannot_escape_or_overwrite(self):
        self.output.mkdir()
        outside = self.base / "outside.pdf"
        outside.write_bytes(b"outside original")
        try:
            (self.output / "book.pdf").symlink_to(outside)
        except OSError:
            self.skipTest("Symlink creation is unavailable on this host")
        result = book.download(self.session()["session_id"], 1, self.output,
                               self.download_client(headers={"Content-Disposition": 'attachment; filename="book.pdf"'}), self.store)
        self.assertEqual(outside.read_bytes(), b"outside original")
        self.assertEqual(Path(result["path"]).name, "book (1).pdf")

    def test_atomic_commit_never_exposes_empty_final_file(self):
        self.output.mkdir()
        part = self.store.partials / "atomic.part"
        part.write_bytes(PDF)
        original_link = os.link

        def inspect_link(source, target):
            self.assertFalse(Path(target).exists())
            self.assertEqual(Path(source).read_bytes(), PDF)
            original_link(source, target)
            self.assertEqual(Path(target).read_bytes(), PDF)

        with mock.patch.object(book.os, "link", side_effect=inspect_link):
            target = book._commit_file(part, self.output, "atomic.pdf")
        self.assertEqual(target.read_bytes(), PDF)
        self.assertFalse(part.exists())

    def test_cross_volume_commit_uses_validated_staging_then_atomic_publish(self):
        self.output.mkdir()
        part = self.store.partials / "cross-volume.part"
        part.write_bytes(PDF)
        original_link = os.link
        calls = []

        def link(source, target):
            calls.append((Path(source), Path(target)))
            if Path(source).parent == self.store.partials:
                raise OSError(errno.EXDEV, "fixture different device")
            self.assertEqual(Path(source).read_bytes(), PDF)
            return original_link(source, target)

        with mock.patch.object(book.os, "link", side_effect=link):
            target = book._commit_file(part, self.output, "cross-volume.pdf")
        self.assertEqual(target.read_bytes(), PDF)
        self.assertEqual(len(calls), 2)
        self.assertEqual(list(self.output.iterdir()), [target])
        self.assertFalse(part.exists())

    def test_size_limit_is_enforced_and_partials_removed(self):
        with self.assertRaises(book.BookError) as error:
            book.download(self.session()["session_id"], 1, self.output, self.download_client(), self.store, max_bytes=1)
        self.assertEqual(error.exception.code, "download_too_large")
        self.assertEqual(list(self.store.partials.iterdir()), [])
        self.assertEqual(list(self.output.iterdir()), [])

    def test_tls_enabled_and_timeout_passed(self):
        client = self.client(lambda r, c: Response(b"ok"))
        self.assertEqual(client.ssl_context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(client.ssl_context.check_hostname)
        self.assertEqual(client.read_bytes("https://libgen.li/example"), b"ok")
        self.assertEqual(client.fixture_opener.calls[0][1], 5)
        with self.assertRaises(book.BookError) as error:
            client.read_bytes("http://libgen.li/insecure")
        self.assertEqual(error.exception.code, "unsafe_url")

    def test_unused_network_client_does_not_initialize_tls(self):
        with mock.patch.dict(os.environ, {"BOOK_SEARCH_AGENT_MODEL": ""}), mock.patch.object(book.ssl, "create_default_context", side_effect=ssl.SSLError("unavailable local TLS")):
            client = book.HttpClient(agent_model=None)
            with self.assertRaises(book.BookError) as error:
                client.read_bytes("https://archive.org/metadata/example")
            self.assertEqual(error.exception.code, "model_id_required")
            with self.assertRaises(book.BookError) as error:
                client.read_bytes("https://libgen.li/example")
            self.assertEqual(error.exception.code, "tls_setup_error")

    def test_injected_offline_opener_does_not_require_system_tls(self):
        with mock.patch.object(book.ssl, "create_default_context", side_effect=ssl.SSLError("unavailable local TLS")):
            client = self.client(lambda r, c: Response(b"offline response"))
            self.assertEqual(client.read_bytes("https://libgen.li/example"), b"offline response")

    def test_tls_failure_does_not_retry(self):
        failure = urllib.error.URLError(ssl.SSLCertVerificationError("fixture certificate failure"))
        client = self.client(lambda r, c: failure, retries=3)
        with self.assertRaises(book.BookError) as error:
            client.read_bytes("https://libgen.li/example")
        self.assertEqual(error.exception.code, "tls_error")
        self.assertEqual(len(client.fixture_opener.calls), 1)
        self.assertEqual(self.sleeps, [])

    def test_transient_network_retries_are_bounded(self):
        client = self.client(lambda r, c: urllib.error.URLError(socket.timeout()), retries=3)
        with self.assertRaises(book.BookError):
            client.read_bytes("https://libgen.li/example")
        self.assertEqual(len(client.fixture_opener.calls), 4)
        self.assertEqual(self.sleeps, [0.25, 0.5, 1.0])

    def test_auth_redirect_and_https_downgrade_are_blocked(self):
        handler = book.SafeRedirectHandler()
        request = urllib.request.Request("https://z-library.sk/eapi/book/search", headers={"remix-userkey": "test-secret"})
        with self.assertRaises(book.BookError) as error:
            handler.redirect_request(request, None, 302, "", {}, "https://elsewhere.invalid/file")
        self.assertEqual(error.exception.code, "auth_redirect")
        with self.assertRaises(book.BookError) as error:
            handler.redirect_request(request, None, 302, "", {}, "http://z-library.sk/file")
        self.assertEqual(error.exception.code, "unsafe_url")

    def test_cli_search_error_and_download_error_exit_nonzero_json(self):
        code, result = self.run_main(["search", "关键词", "--work-dir", str(self.store.root)],
                                     self.client(lambda r, c: urllib.error.URLError("fixture unavailable")))
        self.assertEqual(code, 3)
        self.assertEqual(result["status"], "error")
        code, result = self.run_main(["download", "1", "--session", "f" * 32,
                                     "--output", str(self.output), "--work-dir", str(self.store.root)])
        self.assertNotEqual(code, 0)
        self.assertEqual(result["error"]["code"], "session_not_found")

    def test_cli_download_html_failure_nonzero_and_no_final_file(self):
        record = self.session()
        code, result = self.run_main(["download", "1", "--session", record["session_id"],
                                     "--output", str(self.output), "--work-dir", str(self.store.root)],
                                    self.download_client(b"<html>error</html>"))
        self.assertNotEqual(code, 0)
        self.assertEqual(result["error"]["code"], "not_a_book")
        self.assertEqual(list(self.output.iterdir()), [])

    def test_cli_rejects_invalid_arguments_as_json(self):
        for argv in [["search", "q", "--limit", "0"], ["search", "q", "--retries", "4"],
                     ["search", "q", "--timeout", "0"], ["download", "1"],
                     ["search", "q", "--sources", "unknown"]]:
            with self.subTest(argv=argv):
                code, result = self.run_main(argv)
                self.assertEqual(code, 2)
                self.assertEqual(result["error"]["code"], "invalid_arguments")

    def test_process_exit_status_is_nonzero_for_download_failure(self):
        completed = subprocess.run([
            sys.executable, str(SCRIPT), "download", "1", "--session", "f" * 32,
            "--output", str(self.output), "--work-dir", str(self.store.root),
        ], capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(json.loads(completed.stdout)["error"]["code"], "session_not_found")
        self.assertEqual(completed.stderr, "")


if __name__ == "__main__":
    unittest.main()
