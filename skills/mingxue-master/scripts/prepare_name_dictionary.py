"""Explicitly prepare a pinned external character dictionary, never on lookup."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import urllib.request

sys.dont_write_bytecode = True
import name_dictionary as dictionary


class JsonParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)

    def print_help(self, file=None):
        print(json.dumps({"help": self.format_help()}, ensure_ascii=False), file=file)


def download(url, max_bytes):
    request = urllib.request.Request(url, headers={"User-Agent": "name-dictionary-preparer/1"})
    with urllib.request.urlopen(request, timeout=45) as response:
        if not response.geturl().startswith("https://www.unicode.org/"):
            raise ValueError("character data download redirected outside its official HTTPS host")
        payload = response.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ValueError("official download exceeds the expected size limit")
    return payload


def prepare_dictionary(directory=None, *, download_data=False, archive=None, terms=None):
    """Keep all upstream bytes and their accompanying terms in external storage."""
    root = dictionary.dictionary_directory(directory)
    if download_data and (archive is not None or terms is not None):
        raise ValueError("choose --download or local --archive/--terms inputs")
    if not download_data and (archive is None or terms is None):
        raise ValueError("preparation requires explicit --download, or both --archive and --terms")
    if root.exists():
        if not root.is_dir():
            raise ValueError("dictionary destination is not a directory")
        if any(root.iterdir()):
            # Readiness is checked against pinned actual bytes before reuse.
            state = dictionary.dictionary_status(root)
            if state["status"] == "ready":
                return {**state, "preparation": "verified_existing", "network": "not_used"}
            raise ValueError("destination is nonempty and not a verified dictionary; choose a new external directory")
    if download_data:
        source = download(dictionary.ARCHIVE_URL, 20 * 1024 * 1024)
        accompanying = download(dictionary.TERMS_URL, 256 * 1024)
    else:
        for value in (archive, terms):
            if not Path(value).expanduser().is_absolute():
                raise ValueError("local archive/terms inputs must use absolute paths")
        if Path(archive).expanduser().stat().st_size > 20 * 1024 * 1024 or Path(terms).expanduser().stat().st_size > 256 * 1024:
            raise ValueError("local source files exceed the pinned preparation size limits")
        source = Path(archive).expanduser().read_bytes()
        accompanying = Path(terms).expanduser().read_bytes()
    if hashlib.sha256(source).hexdigest() != dictionary.ARCHIVE_SHA256:
        raise ValueError("source archive checksum does not match the pinned official version")
    if hashlib.sha256(accompanying).hexdigest() != dictionary.TERMS_SHA256:
        raise ValueError("accompanying terms checksum changed; source review is required before preparing this version")
    indexed = dictionary.normalize_archive(source)
    if hashlib.sha256(indexed).hexdigest() != dictionary.DATA_SHA256:
        raise ValueError("derived character index differs from the pinned normalizer output")
    manifest = {"format": 1, "version": dictionary.VERSION, "archive_url": dictionary.ARCHIVE_URL,
                "archive_sha256": dictionary.ARCHIVE_SHA256, "data_sha256": dictionary.DATA_SHA256,
                "terms_url": dictionary.TERMS_URL, "terms_sha256": dictionary.TERMS_SHA256,
                "documentation": dictionary.DOCUMENTATION_URL,
                "character_count": len(json.loads(indexed)["records"]),
                "scope": "IRG total strokes, character readings, English glosses and variant relations; no Kangxi/name-adjusted stroke table"}
    root.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".name-data-", dir=root.parent))
    try:
        (stage / "Unihan.zip").write_bytes(source)
        (stage / "terms.txt").write_bytes(accompanying)
        (stage / "characters.json").write_bytes(indexed)
        (stage / "manifest.json").write_bytes(dictionary.canonical_bytes(manifest))
        dictionary.load_dictionary(stage)
        if root.exists():
            root.rmdir()  # Existing empty destination only; never recursive.
        os.rename(stage, root)
    finally:
        if stage.exists():
            # Only the freshly created staging directory within validated root.parent.
            if stage.resolve().parent != root.parent.resolve() or not stage.name.startswith(".name-data-"):
                raise ValueError("invalid preparation staging cleanup target")
            shutil.rmtree(stage)
    return {**dictionary.dictionary_status(root), "preparation": "downloaded_official" if download_data else "imported_verified_archive",
            "network": "official_https_download" if download_data else "not_used"}


def main(argv=None):
    parser = JsonParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--dictionary-dir", help="absolute external dictionary directory")
    parser.add_argument("--download", action="store_true", help="explicitly download the pinned official archive and accompanying terms")
    parser.add_argument("--archive", help="absolute path to the pinned original archive")
    parser.add_argument("--terms", help="absolute path to its retained accompanying terms")
    try:
        args = parser.parse_args(argv)
        if args.probe:
            if args.download or args.archive or args.terms:
                raise ValueError("--probe cannot be combined with preparation inputs")
            result = dictionary.dictionary_status(args.dictionary_dir)
        else:
            result = prepare_dictionary(args.dictionary_dir, download_data=args.download, archive=args.archive, terms=args.terms)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, ImportError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
