#!/usr/bin/env python3
"""Local image metadata and explicit user-observation intake; no image recognition."""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

MAX_BYTES = 30 * 1024 * 1024
MAX_PIXELS = 100_000_000
QUALITY_VALUES = {
    "clarity": {"clear", "blurry", "unknown"},
    "lighting": {"even", "uneven", "unknown"},
    "shadow": {"none", "present", "unknown"},
    "perspective": {"frontal", "angled", "unknown"},
    "cropping": {"complete", "partial", "unknown"},
    "occlusion": {"none", "present", "unknown"},
    "mirrored": {"yes", "no", "unknown"},
    "filters": {"yes", "no", "unknown"},
}
REGIONS = {
    "palm": {"palm_outline", "thumb_arc", "middle_transverse", "upper_transverse",
             "central_vertical", "ring_finger_vertical", "finger_outline", "palm_pad"},
    "face": {"face_outline", "forehead", "eyebrow_outline", "eye_outline", "nose_outline",
             "mouth_outline", "ear_outline", "chin_outline", "visible_line"},
}
SHAPES = {"straight", "curved", "branched", "interrupted", "parallel", "round", "angular",
          "long", "short", "wide", "narrow", "unresolved"}


class IntakeError(ValueError):
    pass


def exif_summary(raw: bytes) -> tuple[dict, list[str]]:
    """Read only orientation; never return location, device or identity metadata."""
    out = {"exif_present": True, "orientation": None}
    try:
        if raw.startswith(b"Exif\x00\x00"):
            raw = raw[6:]
        if len(raw) < 8 or raw[:2] not in (b"II", b"MM"):
            raise ValueError
        endian = "<" if raw[:2] == b"II" else ">"
        if struct.unpack_from(endian + "H", raw, 2)[0] != 42:
            raise ValueError
        offset = struct.unpack_from(endian + "I", raw, 4)[0]
        count = struct.unpack_from(endian + "H", raw, offset)[0]
        if count > 4096 or offset + 2 + count * 12 + 4 > len(raw):
            raise ValueError
        for i in range(count):
            pos = offset + 2 + i * 12
            tag, field_type, size = struct.unpack_from(endian + "HHI", raw, pos)
            if tag == 0x0112 and field_type == 3 and size == 1:
                value = struct.unpack_from(endian + "H", raw, pos + 8)[0]
                if 1 <= value <= 8:
                    out["orientation"] = value
        return out, []
    except (ValueError, struct.error):
        return out, ["EXIF structure could not be read; embedded values were not interpreted."]


def png_metadata(data: bytes) -> tuple[dict, list[str]]:
    pos, first, idat, ended = 8, True, False, False
    out = {"format": "PNG", "exif_present": False, "orientation": None,
           "text_metadata_present": False, "icc_profile_present": False}
    warnings = []
    while pos < len(data):
        if pos + 12 > len(data):
            raise IntakeError("Truncated PNG chunk.")
        length = struct.unpack_from(">I", data, pos)[0]
        kind = data[pos + 4:pos + 8]
        end = pos + 12 + length
        if end > len(data):
            raise IntakeError("PNG chunk exceeds the file length.")
        value = data[pos + 8:pos + 8 + length]
        crc = struct.unpack_from(">I", data, pos + 8 + length)[0]
        if zlib.crc32(kind + value) & 0xFFFFFFFF != crc:
            raise IntakeError("PNG checksum mismatch.")
        if first:
            if kind != b"IHDR" or length != 13:
                raise IntakeError("PNG must begin with a valid IHDR.")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", value)
            valid_depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
            if depth not in valid_depths.get(color, set()) or compression or filtering or interlace not in (0, 1):
                raise IntakeError("Unsupported or invalid PNG header.")
            out.update(width=width, height=height, bit_depth=depth, color_type=color)
        elif kind == b"IHDR":
            raise IntakeError("Duplicate PNG header.")
        if kind == b"IDAT":
            idat = idat or bool(length)
        if kind == b"eXIf":
            meta, notes = exif_summary(value)
            out.update(meta)
            warnings.extend(notes)
        if kind in (b"tEXt", b"iTXt", b"zTXt"):
            out["text_metadata_present"] = True
        if kind == b"iCCP":
            out["icc_profile_present"] = True
        if kind == b"pHYs" and length == 9:
            x, y, unit = struct.unpack(">IIB", value)
            out["pixel_density"] = {"x": x, "y": y, "unit": "pixels_per_meter" if unit == 1 else "unspecified"}
        pos, first = end, False
        if kind == b"IEND":
            if length or pos != len(data):
                raise IntakeError("Invalid PNG end marker or trailing data.")
            ended = True
            break
    if not ended or not idat:
        raise IntakeError("PNG is missing image data or the end marker.")
    return out, warnings


def jpeg_metadata(data: bytes) -> tuple[dict, list[str]]:
    pos, scan, ended = 2, False, False
    out = {"format": "JPEG", "exif_present": False, "orientation": None,
           "text_metadata_present": False, "icc_profile_present": False}
    warnings = []
    frame_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while pos < len(data):
        if data[pos] != 0xFF:
            raise IntakeError("Invalid JPEG marker boundary.")
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        if pos >= len(data):
            raise IntakeError("Truncated JPEG marker.")
        marker = data[pos]
        pos += 1
        if marker == 0xD9:
            ended = True
            if pos != len(data):
                warnings.append("JPEG has bytes after the end marker; they were not interpreted.")
            break
        if marker in {0x00, 0xD8} or 0xD0 <= marker <= 0xD7:
            raise IntakeError("Unexpected JPEG marker.")
        if marker == 0x01:
            continue
        if pos + 2 > len(data):
            raise IntakeError("Truncated JPEG segment.")
        length = struct.unpack_from(">H", data, pos)[0]
        if length < 2 or pos + length > len(data):
            raise IntakeError("JPEG segment exceeds the file length.")
        value = data[pos + 2:pos + length]
        pos += length
        if marker in frame_markers:
            if len(value) < 6:
                raise IntakeError("Invalid JPEG frame.")
            depth, height, width, components = struct.unpack_from(">BHHB", value)
            if len(value) != 6 + components * 3 or components not in (1, 3, 4):
                raise IntakeError("Invalid JPEG frame component table.")
            out.update(width=width, height=height, bit_depth=depth, components=components)
        if marker == 0xE1 and value.startswith(b"Exif\x00\x00"):
            meta, notes = exif_summary(value)
            out.update(meta)
            warnings.extend(notes)
        if marker == 0xE2 and value.startswith(b"ICC_PROFILE\x00"):
            out["icc_profile_present"] = True
        if marker == 0xFE:
            out["text_metadata_present"] = True
        if marker == 0xE0 and value.startswith(b"JFIF\x00") and len(value) >= 12:
            unit, x, y = struct.unpack_from(">BHH", value, 7)
            out["pixel_density"] = {"x": x, "y": y, "unit": {1: "pixels_per_inch", 2: "pixels_per_cm"}.get(unit, "unspecified")}
        if marker == 0xDA:
            scan = True
            # Skip entropy-coded bytes, byte stuffing and restart markers; do not decode pixels.
            while True:
                boundary = data.find(b"\xff", pos)
                if boundary < 0:
                    raise IntakeError("JPEG scan is missing its end marker.")
                probe = boundary + 1
                while probe < len(data) and data[probe] == 0xFF:
                    probe += 1
                if probe >= len(data):
                    raise IntakeError("Truncated JPEG scan marker.")
                if data[probe] == 0x00 or 0xD0 <= data[probe] <= 0xD7:
                    pos = probe + 1
                    continue
                pos = boundary
                break
    if not ended or not scan or "width" not in out:
        raise IntakeError("JPEG is missing a frame, scan or end marker.")
    return out, warnings


def inspect_image(path: Path) -> tuple[dict, list[str]]:
    if not path.is_file():
        raise IntakeError("Image must be an existing local file.")
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise IntakeError("Image exceeds the 30 MiB intake limit.")
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise IntakeError("Image exceeds the 30 MiB intake limit.")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        info, notes = png_metadata(data)
        extensions = {".png"}
    elif data.startswith(b"\xff\xd8"):
        info, notes = jpeg_metadata(data)
        extensions = {".jpg", ".jpeg", ".jpe"}
    else:
        raise IntakeError("Only actual PNG and JPEG file structures are supported.")
    if not 0 < info["width"] * info["height"] <= MAX_PIXELS or not info["width"] or not info["height"]:
        raise IntakeError("Invalid dimensions or image exceeds the 100 megapixel intake limit.")
    if path.suffix.lower() not in extensions:
        notes.append("Filename extension differs from the detected image format.")
    rotated = info.get("orientation") in {5, 6, 7, 8}
    info.update(file_name=path.name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                display_width=info["height"] if rotated else info["width"],
                display_height=info["width"] if rotated else info["height"],
                validation="container_structure_only", pixel_decode_performed=False)
    if min(info["width"], info["height"]) < 600:
        notes.append("Short edge is below 600 px; fine line visibility requires direct visual checking.")
    return info, notes


def validate_observations(system: str, raw: object) -> dict:
    if not isinstance(raw, dict) or set(raw) - {"hand", "dominant_hand", "quality", "features"}:
        raise IntakeError("Observations must contain only hand, dominant_hand, quality and features.")
    out = {"quality": {key: "unknown" for key in QUALITY_VALUES}, "features": []}
    if system == "palm":
        out.update(hand="unknown", dominant_hand="unknown")
    for key in ("hand", "dominant_hand"):
        if key in raw:
            allowed = {"left", "right", "both", "unknown"} if key == "hand" else {"left", "right", "ambidextrous", "unknown"}
            if system != "palm" or not isinstance(raw[key], str) or raw[key] not in allowed:
                raise IntakeError("Invalid hand metadata for this system.")
            out[key] = raw[key]
    quality = raw.get("quality", {})
    if not isinstance(quality, dict) or set(quality) - set(QUALITY_VALUES):
        raise IntakeError("Unknown quality field.")
    for key, value in quality.items():
        if not isinstance(value, str) or value not in QUALITY_VALUES[key]:
            raise IntakeError("Invalid quality value.")
        out["quality"][key] = value
    features = raw.get("features", [])
    if not isinstance(features, list) or len(features) > 100:
        raise IntakeError("Features must be a list of at most 100 entries.")
    for feature in features:
        if not isinstance(feature, dict) or set(feature) != {"region", "shape", "visibility"}:
            raise IntakeError("Each feature must have exactly region, shape and visibility.")
        if not all(isinstance(value, str) for value in feature.values()):
            raise IntakeError("Feature values must be strings.")
        if feature["region"] not in REGIONS[system] or feature["shape"] not in SHAPES or feature["visibility"] not in {"clear", "unclear", "not_visible"}:
            raise IntakeError("Unsupported visible-feature descriptor.")
        out["features"].append(dict(feature))
    return out


def intake(system: str, image: Path | None = None, observations: dict | None = None) -> dict:
    if system not in REGIONS:
        raise IntakeError("Unsupported system.")
    report = validate_observations(system, {} if observations is None else observations)
    info, notes = inspect_image(image) if image else (None, [])
    notes.append("Clarity, crop, lighting, occlusion and side are user-reported or unknown; this tool does not inspect image content.")
    return {"ok": True, "system": system, "status": "intake_only", "image": info,
            "observation_status": "image_available_not_interpreted" if image else "not_observed",
            "image_content_analysis": False, "uploaded": False,
            "user_reported_observations": report, "warnings": notes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system", choices=sorted(REGIONS), required=True)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--observations", type=Path, help="UTF-8 JSON of explicit user-reported shapes and quality")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        raw = json.loads(args.observations.read_text(encoding="utf-8-sig")) if args.observations else {}
        result = intake(args.system, args.image, raw)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            from fortune import validate_save_path
            from chart import write_json
            from contextlib import redirect_stdout
            import io
            target = validate_save_path(args.output)
            with redirect_stdout(io.StringIO()):
                write_json(result, str(target))
        print(text)
        return 0
    except (OSError, IntakeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": {"code": "invalid_visual_input", "message": str(exc)}}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())

