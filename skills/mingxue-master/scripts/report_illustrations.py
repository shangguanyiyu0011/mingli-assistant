"""Bind generated diagrams or explicitly authorized photo vectors to current observations."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import re

from output_paths import guard_output
from photo_uploads import _links
from project_store import read_json
from reader_projection import available
from visual_intake import inspect_image
from visual_annotations import validate_annotations

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 4
FIELDS = {"person", "system", "result_sha256", "image", "sha256", "caption"}
GENERATED_PHOTO_FIELDS = FIELDS | {"photo_id", "photo_sha256", "use_original_photo"}
PHOTO_FIELDS = {"kind", "person", "system", "result_sha256", "photo_id", "photo_sha256", "use_original_photo", "caption", "annotations"}
SHA = re.compile(r"[a-f0-9]{64}")


def _image(value, expected_sha):
    if (not isinstance(value, str) or not value or any(ord(c) < 32 for c in value)
            or value.startswith(("\\\\", "//")) or ":" in value[2:]):
        raise ValueError("示意图须使用本机绝对 PNG/JPEG 路径。")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
        raise ValueError("示意图须使用本机绝对 PNG/JPEG 路径。")
    try:
        _links(path)
        path = guard_output(path)
        if not path.is_file() or not 0 < path.stat().st_size <= MAX_IMAGE_BYTES:
            raise ValueError("示意图不存在或超过每张8 MiB限制。")
        info, notes = inspect_image(path)
        info['_exif_unreadable'] = any('EXIF structure could not be read' in note for note in notes)
        with path.open("rb") as stream:
            raw = stream.read(MAX_IMAGE_BYTES + 1)
    except OSError as exc:
        raise ValueError("无法读取本机示意图，请检查文件与目录。") from exc
    except ValueError as exc:
        raise ValueError("示意图未通过 PNG/JPEG 结构检查。") from exc
    if (len(raw) > MAX_IMAGE_BYTES or len(raw) != info["bytes"]
            or hashlib.sha256(raw).hexdigest() != expected_sha or info["sha256"] != expected_sha):
        raise ValueError("示意图已变化或摘要不一致。")
    mime = "image/png" if info["format"] == "PNG" else "image/jpeg"
    return "data:" + mime + ";base64," + base64.b64encode(raw).decode("ascii"), info


def load_illustrations(filename, records):
    """Return person-bound inline raster/annotation data without private paths."""
    if filename is None:
        return {}
    entries = read_json(filename, max_bytes=32000)
    if not isinstance(entries, list) or len(entries) > MAX_IMAGES:
        raise ValueError("示意图清单须为最多4条的JSON数组。")
    people = {record["role"].upper(): record for record in records}
    photo_hashes = {photo["sha256"] for record in records for photo in record.get("photos", [])}
    result, seen = {}, set()
    for entry in entries:
        original = isinstance(entry, dict) and entry.get("kind") == "photo_annotation"
        generated_original = isinstance(entry, dict) and set(entry) == GENERATED_PHOTO_FIELDS
        if not isinstance(entry, dict) or set(entry) != (PHOTO_FIELDS if original else GENERATED_PHOTO_FIELDS if generated_original else FIELDS):
            raise ValueError("插图条目须完整符合生成图或photo_annotation的字段合同。")
        person, system = entry["person"], entry["system"]
        if not isinstance(person, str) or person not in people or system not in ("palm", "face"):
            raise ValueError("示意图须归属本次A或B的手相或面相。")
        if any(not isinstance(entry[key], str) or not SHA.fullmatch(entry[key]) for key in ("result_sha256", "photo_sha256" if original else "sha256")):
            raise ValueError("示意图与观察结果须提供有效SHA-256摘要。")
        if generated_original and (not isinstance(entry['photo_sha256'],str) or not SHA.fullmatch(entry['photo_sha256'])):
            raise ValueError("原照来源须提供有效SHA-256摘要。")
        caption = entry["caption"]
        if (not isinstance(caption, str) or not 1 <= len(caption.strip()) <= 500
                or any(ord(c) < 32 for c in caption) or re.search(r"[A-Za-z]:[\\/]|\\\\|(?:file|https?)://|/(?:Users|home|tmp)/", caption, re.I)):
            raise ValueError("示意图说明须为最多500字的白话文字，不含本机路径。")
        record = people[person]
        panel = next((p for p in record["report"]["panels"] if p["system"] == system), None)
        payload = record["payloads"].get(system, {})
        features = payload.get("user_reported_observations", {}).get("features")
        refs = payload.get("photo_refs")
        if (panel is None or panel["result_sha256"] != entry["result_sha256"]
                or not available(panel, payload) or payload.get("observation_status") != "agent_observed"
                or not isinstance(features, list) or not features or not isinstance(refs, list) or not refs):
            raise ValueError("示意图须绑定本人当前可阅读、已实际看图并记录特征的结果。")
        photos = {p["id"]: p for p in record.get("photos", [])}
        kinds = ("portrait",) if system == "face" else ("palm_left", "palm_right", "palm_unknown")
        for ref in refs:
            photo = photos.get(ref.get("id")) if isinstance(ref, dict) else None
            if (photo is None or photo.get("person") != person or photo.get("kind") not in kinds
                    or photo["sha256"] != ref.get("sha256")):
                raise ValueError("示意图引用的照片不属于本人当前同类观察。")
        if original or generated_original:
            if entry["use_original_photo"] is not True or not isinstance(entry["photo_id"], str):
                raise ValueError("原图标注须明确授权use_original_photo为布尔true并指定照片。")
            photo = photos.get(entry["photo_id"])
            if (photo is None or photo.get("sha256") != entry["photo_sha256"]
                    or not any(ref.get("id") == photo["id"] and ref.get("sha256") == photo["sha256"] for ref in refs)):
                raise ValueError("原图标注须引用本人本次已观察的同一照片和摘要。")
            src, info = _image(photo.get("file"), entry["photo_sha256"])
        if original:
            if info.get("orientation") not in (None, 1) or info.get('_exif_unreadable'):
                raise ValueError("原图EXIF方向未归一，不能直接使用原像素坐标标注。")
            annotations = validate_annotations(system, entry["annotations"], info["width"], info["height"], labeled=True)
            observed = {f.get("region") for f in features if isinstance(f, dict) and isinstance(f.get("region"), str) and f.get("visibility") != "not_visible"}
            if not annotations or any(a["region"] not in observed for a in annotations):
                raise ValueError("原图标注只能覆盖本次已实际记录的可见部位。")
            binding = (person, system, photo["id"])
            if binding in seen:
                raise ValueError("同一原照片不能在相同分项重复标注。")
            result.setdefault((person, system), []).append({"kind": "photo_annotation", "src": src,
                "caption": caption.strip(), "overlay": {"width": info["width"], "height": info["height"], "annotations": annotations}})
            seen.add(binding)
            continue
        if entry["sha256"] in photo_hashes:
            raise ValueError("分析示意图不能直接使用本次原照片。")
        if entry["sha256"] in seen:
            raise ValueError("同一示意图不能重复或跨人使用。")
        src, _ = _image(entry["image"], entry["sha256"])
        figure = {"src": src, "caption": caption.strip()}
        if generated_original:
            figure.update(kind='generated_photo_annotation',source_photo_id=photo['id'])
        result.setdefault((person, system), []).append(figure)
        seen.add(entry["sha256"])
    return result
