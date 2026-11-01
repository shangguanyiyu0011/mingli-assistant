"""Read a pinned external character dataset without any network or installs."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import unicodedata
import zipfile

sys.dont_write_bytecode = True
VERSION = "unihan-17.0.0-v1"
ARCHIVE_URL = "https://www.unicode.org/Public/17.0.0/ucd/Unihan.zip"
ARCHIVE_SHA256 = "f7a48b2b545acfaa77b2d607ae28747404ce02baefee16396c5d2d7a8ef34b5e"
TERMS_URL = "https://www.unicode.org/license.txt"
TERMS_SHA256 = "e7a93b009565cfce55919a381437ac4db883e9da2126fa28b91d12732bc53d96"
DATA_SHA256 = "0e97dee2c4c48794ea8d39be5b7c588e72464daace73881a746d20869dfd124e"
DOCUMENTATION_URL = "https://www.unicode.org/reports/tr38/tr38-39.html"
MEMBERS = ("Unihan_DictionaryLikeData.txt", "Unihan_IRGSources.txt", "Unihan_Readings.txt", "Unihan_Variants.txt")
READING_FIELDS = ("kTGHZ2013", "kXHC1983", "kHanyuPinyin", "kMandarin")
VARIANT_FIELDS = ("kSimplifiedVariant", "kTraditionalVariant", "kSemanticVariant", "kSpecializedSemanticVariant",
                  "kZVariant", "kCompatibilityVariant", "kSpoofingVariant")
FIELDS = frozenset((*READING_FIELDS, *VARIANT_FIELDS, "kTotalStrokes", "kAlternateTotalStrokes", "kDefinition", "kRSUnicode"))
ROOT = Path(__file__).resolve().parents[1]


class DictionaryError(ValueError):
    pass


class DictionaryUnavailable(DictionaryError):
    pass


def canonical_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def normalize_archive(payload):
    """Deterministic indexing; original source archive remains outside skill."""
    if hashlib.sha256(payload).hexdigest() != ARCHIVE_SHA256:
        raise DictionaryError("official character archive checksum does not match the pinned version")
    records = {}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if len(set(archive.namelist())) != len(archive.namelist()):
            raise DictionaryError("duplicate archive members")
        for member in MEMBERS:
            if archive.getinfo(member).file_size > 64 * 1024 * 1024:
                raise DictionaryError("character source member is unexpectedly large")
            for line in archive.read(member).decode("utf-8-sig").splitlines():
                if not line or line.startswith("#"):
                    continue
                code, field, value = line.split("\t", 2)
                if field not in FIELDS:
                    continue
                if not re.fullmatch(r"U\+[0-9A-F]{4,6}", code):
                    raise DictionaryError("invalid character code in official archive")
                character = chr(int(code[2:], 16))
                item = records.setdefault(character, {})
                if field in item:
                    raise DictionaryError("duplicate character property")
                item[field] = value
    return canonical_bytes({"format": 1, "version": VERSION, "records": records})


def dictionary_directory(directory=None):
    from runtime_paths import engine_directory, validate_external_directory
    supplied = directory if directory is not None else os.environ.get("MINGXUE_NAME_DICTIONARY")
    if supplied is None:
        return engine_directory("name-data", VERSION)
    if not isinstance(supplied, (str, os.PathLike)):
        raise DictionaryError("dictionary directory must be an absolute external path")
    candidate = Path(supplied).expanduser()
    if not candidate.is_absolute():
        raise DictionaryError("dictionary directory must be an absolute external path")
    return validate_external_directory(candidate)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DictionaryError("duplicate key in character dataset")
        result[key] = value
    return result


def load_dictionary(directory=None):
    root = dictionary_directory(directory)
    try:
        if (root / "manifest.json").stat().st_size > 64 * 1024:
            raise DictionaryError("external dictionary manifest is unexpectedly large")
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        if (not isinstance(manifest, dict) or manifest.get("format") != 1 or manifest.get("version") != VERSION
                or manifest.get("archive_sha256") != ARCHIVE_SHA256 or manifest.get("data_sha256") != DATA_SHA256
                or manifest.get("terms_sha256") != TERMS_SHA256):
            raise DictionaryError("external dictionary manifest does not match the pinned version")
        # Pin actual bytes, not only a locally editable manifest or ready marker.
        for filename, expected in (("Unihan.zip", ARCHIVE_SHA256), ("terms.txt", TERMS_SHA256), ("characters.json", DATA_SHA256)):
            path = root / filename
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise DictionaryError("external dictionary files cannot be links")
            if path.stat().st_size > (256 * 1024 if filename == "terms.txt" else 20 * 1024 * 1024):
                raise DictionaryError("external dictionary file is unexpectedly large")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected:
                raise DictionaryError(f"external dictionary file checksum mismatch: {filename}")
            if filename == "characters.json":
                data = json.loads(raw, object_pairs_hook=_unique_object)
        if data.get("format") != 1 or data.get("version") != VERSION or not isinstance(data.get("records"), dict):
            raise DictionaryError("invalid external character index")
        return root, data["records"]
    except FileNotFoundError as exc:
        raise DictionaryUnavailable(f"dictionary is not prepared at {root}; run prepare_name_dictionary.py explicitly") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DictionaryError(f"cannot read external character dictionary: {exc}") from exc


def dictionary_status(directory=None):
    try:
        root, records = load_dictionary(directory)
        return {"status": "ready", "directory": str(root), "version": VERSION,
                "characters": len(records), "archive_sha256": ARCHIVE_SHA256, "data_sha256": DATA_SHA256,
                "network": "not_used"}
    except DictionaryUnavailable as exc:
        return {"status": "needs_dictionary", "directory": str(dictionary_directory(directory)),
                "version": VERSION, "reason": str(exc), "network": "not_used"}
    except (DictionaryError, OSError, ValueError) as exc:
        return {"status": "invalid_dictionary", "version": VERSION, "reason": str(exc), "network": "not_used"}


def pinyin_key(text, *, ignore_tone=False):
    if not isinstance(text, str):
        raise ValueError("reading must be text")
    text = unicodedata.normalize("NFC", text.strip().lower())
    if not ignore_tone:
        return text
    # Preserve u-diaeresis as a distinct vowel; remove tone marks only.
    return unicodedata.normalize("NFC", "".join(c for c in unicodedata.normalize("NFD", text)
                                if c not in "\u0300\u0301\u0304\u030c"))


def reading_candidates(properties):
    readings = {}
    for field in READING_FIELDS:
        raw = properties.get(field, "")
        for group in raw.split():
            syllables = group if field == "kMandarin" else group.split(":", 1)[-1]
            for syllable in syllables.split(","):
                normalized = pinyin_key(syllable)
                if normalized:
                    readings.setdefault(normalized, []).append(field)
    return [{"pinyin": value, "properties": list(dict.fromkeys(sources))} for value, sources in readings.items()]


def character_entry(character, records):
    if not isinstance(character, str) or len(character) != 1:
        raise ValueError("character lookup requires one Unicode character")
    fields = records.get(character)
    code = f"U+{ord(character):04X}"
    if fields is None:
        return {"character": character, "code_point": code, "status": "not_found", "pending_inputs": ["verified character data"]}
    raw_strokes = fields.get("kTotalStrokes")
    if raw_strokes is not None and not re.fullmatch(r"[1-9][0-9]{0,2}", raw_strokes):
        raise DictionaryError(f"unexpected pinned-version stroke syntax for {code}")
    readings = reading_candidates(fields)
    missing = []
    if raw_strokes is None:
        missing.append("modern_strokes")
    if not readings:
        missing.append("mandarin_reading")
    if not fields.get("kDefinition"):
        missing.append("definition_en")
    variants = {}
    for field in VARIANT_FIELDS:
        if field in fields:
            variants[field] = [{"character": chr(int(cp, 16)), "code_point": "U+" + cp}
                               for cp in re.findall(r"U\+([0-9A-F]{4,6})", fields[field])]
    return {"character": character, "code_point": code, "status": "found", "dataset": VERSION, "pending_fields": missing,
            "modern_strokes": {"count": int(raw_strokes) if raw_strokes else None, "scheme": "unihan-irG",
                               "property": "kTotalStrokes", "convention": "IRG total-stroke convention; not a Kangxi or naming adjustment",
                               "alternate_source_values": fields.get("kAlternateTotalStrokes")},
            "readings": readings, "multiple_readings": len(readings) > 1,
            "customary_mandarin": fields.get("kMandarin"),
            "definition": {"language": "en", "text": fields.get("kDefinition"), "property": "kDefinition"},
            "variants": variants, "character_conversion": "none",
            "shape_metadata": {"radical_residual_index": fields.get("kRSUnicode"), "property": "kRSUnicode",
                               "scope": "IRG radical-residual index; not a Kangxi or naming total-stroke count"},
            "variant_scope": "informational code-point relations; not automatic context-free substitutions",
            "glyph_scope": "exact code point; rendered font glyph and historical naming stroke adjustments are not verified"}


def lookup_characters(characters, dictionary_dir=None):
    if not isinstance(characters, str) or not 1 <= len(characters) <= 128:
        raise ValueError("lookup accepts 1..128 Unicode characters")
    try:
        root, records = load_dictionary(dictionary_dir)
    except DictionaryUnavailable as exc:
        return {"status": "needs_dictionary", "version": VERSION, "dictionary_dir": str(dictionary_directory(dictionary_dir)),
                "pending_inputs": [str(exc)], "characters": [], "network": "not_used"}
    entries = [character_entry(c, records) for c in dict.fromkeys(characters)]
    return {"status": "ready" if all(x["status"] == "found" and not x["pending_fields"] for x in entries) else "needs_input",
            "version": VERSION, "dictionary_dir": str(root), "dictionary_verified": True,
            "archive_sha256": ARCHIVE_SHA256, "data_sha256": DATA_SHA256,
            "documentation": DOCUMENTATION_URL, "characters": entries, "network": "not_used"}


def resolve_readings(text, entries, selected=None, *, part="name"):
    if selected is not None:
        if not isinstance(selected, str) or len(selected.split()) != len(text):
            raise ValueError(f"{part} reading must provide one space-separated dictionary pinyin syllable per character")
        choices = [pinyin_key(s) for s in selected.split()]
    else:
        choices = [None] * len(text)
    resolved, pending = [], []
    for i, (character, choice) in enumerate(zip(text, choices)):
        entry = entries.get(character, {})
        options = [x["pinyin"] for x in entry.get("readings", [])]
        item = {"character": character, "index": i + 1, "part": part, "choices": options, "selected": None}
        if choice is not None:
            if choice not in options:
                item["reason"] = "chosen_reading_not_in_dictionary; provide a separate verified reading reference"
                pending.append(item.copy())
            else:
                item.update(selected=choice, source="user_choice_from_dictionary_candidates")
        elif len(options) == 1:
            item.update(selected=options[0], source="single_dictionary_candidate")
        else:
            item["reason"] = "explicit_reading_choice_required" if options else "dictionary_reading_missing"
            pending.append(item.copy())
        resolved.append(item)
    return {"characters": resolved, "pending_inputs": pending,
            "pinyin": " ".join(item["selected"] for item in resolved) if not pending else None,
            "surname_scope": "character readings do not certify surname-specific usage; family pronunciation is user-confirmed" if part == "surname" else None}
