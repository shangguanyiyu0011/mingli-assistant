"""Build the same intake UI as a self-contained file; no network or private data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
from output_paths import guard_output
from reader_art import art_bundle
from workbench_catalog import VERSION

ROOT = Path(__file__).resolve().parents[1]


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")


def _script(value):
    return "<script>" + re.sub(r"</script", r"<\\/script", value, flags=re.I) + "</script>"


def inline_locales(page):
    marker='<script id="intake-locales" type="application/json">{}</script>'
    if page.count(marker)!=1:
        raise ValueError("The intake language dictionary marker changed.")
    locales=json.loads((ROOT/"ui/intake-locales.json").read_text(encoding="utf-8-sig"))
    return page.replace(marker,'<script id="intake-locales" type="application/json">'+_json(locales)+'</script>')


def build_page():
    ui = ROOT / "ui"
    page = inline_locales((ui / "intake.html").read_text(encoding="utf-8-sig"))
    for filename in ("intake.css", "intake-draws.css"):
        tag = f'<link rel="stylesheet" href="{filename}">'
        if page.count(tag) != 1:
            raise ValueError("The intake stylesheet reference changed; review the standalone export.")
        page = page.replace(tag, "<style>" + (ui / filename).read_text(encoding="utf-8-sig") + "</style>")
    for filename in ("i18n.js", "art-assets.js", "intake-draws.js", "intake.js"):
        tag = f'<script defer src="{filename}"></script>'
        if page.count(tag) != 1:
            raise ValueError("The intake script reference changed; review the standalone export.")
        page = page.replace(tag, "")
    registry = json.loads((ROOT / "references/systems.json").read_text(encoding="utf-8-sig"))
    systems = registry["systems"] if isinstance(registry, dict) else registry
    catalog = {"version": VERSION, "systems": [
        {key: row[key] for key in ("id", "name", "category", "summary") if key in row} for row in systems]}
    setup = "window.MINGXUE_OFFLINE=true;window.OFFLINE_CATALOG=" + _json(catalog) + ";window.MingxueArt=" + _json(art_bundle()) + ";"
    scripts = [setup] + [(ui / name).read_text(encoding="utf-8-sig") for name in ("i18n.js", "offline-intake.js", "intake-draws.js", "intake.js")]
    page = page.replace("<head>", '<head><meta name="mingli-intake-mode" content="agent">', 1)
    page = page.replace("</body>", "".join(_script(value) for value in scripts) + "</body>", 1)
    if re.search(r'<script[^>]+src=|<link[^>]+stylesheet', page, flags=re.I):
        raise ValueError("Standalone export still contains external UI files.")
    return page


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--output", required=True, help="new absolute HTML file outside the plugin")
    args = parser.parse_args(argv)
    if not Path(args.output).expanduser().is_absolute():
        parser.error("--output must be an absolute path")
    output = guard_output(args.output)
    if output.suffix.lower() != ".html":
        parser.error("--output must be an HTML file")
    page = build_page()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(page)
    print(json.dumps({"status": "ready", "file": str(output), "bytes": output.stat().st_size}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
