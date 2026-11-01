"""Session-scoped PNG/JPEG intake and private, hash-bound photo handoff.

Container checks are not image viewing. No network, image recognition or chart work.
"""
from __future__ import annotations
import base64
import binascii
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import threading

MAX_PHOTO_BYTES = 6 * 1024 * 1024
MAX_TOTAL_BYTES = 30 * 1024 * 1024
MAX_PHOTOS = 12
MAX_UPLOAD_BODY = 4 * ((MAX_PHOTO_BYTES + 2) // 3) + 8192
KINDS = {"palm_left", "palm_right", "palm_unknown", "portrait", "room", "floorplan", "chart", "other"}
ID = re.compile(r"[a-f0-9]{32}")
SHA = re.compile(r"[a-f0-9]{64}")
MIMES = {"image/png": ".png", "image/jpeg": ".jpg"}
ENTRY_KEYS = {"id", "person", "kind", "name", "mime", "sha256", "bytes", "width", "height", "display_width", "display_height", "include_in_report", "relative_path", "viewed", "validation", "pixel_decode_performed"}

class PhotoError(ValueError):
    pass


def _choice(value, choices):
    return isinstance(value,str) and value in choices


def _links(path):
    for node in (path, *path.parents):
        if node.is_symlink() or bool(getattr(node, "is_junction", lambda: False)()):
            raise PhotoError("照片资料不接受符号链接或目录联接。")


def _absolute(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise PhotoError("可信照片资料必须使用绝对路径。")
    _links(path)
    return path.resolve()


def _write_new(path, value):
    raw = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8") + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _image(path):
    from visual_intake import inspect_image
    info, _ = inspect_image(path)
    mime = "image/png" if path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    return {k: info[k] for k in ("sha256", "bytes", "width", "height", "display_width", "display_height")}, mime


def normalize_refs(value, person):
    if not isinstance(value, list) or len(value) > MAX_PHOTOS:
        raise PhotoError("每次最多保留12张照片引用。")
    result, seen = [], set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != {"id", "kind", "sha256", "include_in_report"}:
            raise PhotoError("照片引用只能含id、kind、sha256和include_in_report。")
        if not isinstance(raw["id"], str) or not ID.fullmatch(raw["id"]) or raw["id"] in seen:
            raise PhotoError("照片标识无效或重复。")
        if not isinstance(raw["sha256"], str) or not SHA.fullmatch(raw["sha256"]) or not _choice(raw["kind"],KINDS) or type(raw["include_in_report"]) is not bool:
            raise PhotoError("照片类型、摘要或展示选择无效。")
        seen.add(raw["id"])
        result.append(copy.deepcopy(raw))
    return result


def normalize_observations(value, photos, *, allow_agent_observations=False):
    from visual_intake import validate_observations
    if not isinstance(value, dict) or set(value) - {"palm", "face"}:
        raise PhotoError("本人观察只支持手掌与人像。")
    by_id = {p["id"]: p for p in photos}
    output = {}
    for system, raw in value.items():
        allowed = {"schema_version", "source", "photo_refs", "observations", "note"}
        if not isinstance(raw, dict) or set(raw) - allowed or not {"schema_version", "source", "photo_refs", "observations"} <= set(raw):
            raise PhotoError("观察须含版本、来源、照片引用和具体观察。")
        if type(raw["schema_version"]) is not int or raw["schema_version"] != 2 or not _choice(raw["source"],{"agent_viewed", "user_reported"}):
            raise PhotoError("不支持的观察版本或来源。")
        if raw["source"] == "agent_viewed" and not allow_agent_observations:
            raise PhotoError("初次采集不能声称Agent已看图；须实际查看后由可信更正补充。")
        refs = raw["photo_refs"]
        if not isinstance(refs, list) or len(refs) > MAX_PHOTOS or raw["source"] == "agent_viewed" and not refs:
            raise PhotoError("已看图观察必须引用当前本人照片。")
        seen = set()
        allowed_kinds = {"palm_left", "palm_right", "palm_unknown"} if system == "palm" else {"portrait"}
        for ref in refs:
            if not isinstance(ref, dict) or set(ref) != {"id", "sha256"} or not isinstance(ref["id"], str) or ref["id"] in seen:
                raise PhotoError("观察照片引用无效或重复。")
            real = by_id.get(ref["id"])
            if real is None or ref["sha256"] != real["sha256"] or real["kind"] not in allowed_kinds:
                raise PhotoError("观察须引用本人当前同类照片及真实摘要。")
            seen.add(ref["id"])
        note = raw.get("note", "")
        if not isinstance(note, str) or len(note) > 2000 or "\x00" in note:
            raise PhotoError("观察说明须为最多2000字的文字。")
        output[system] = {"schema_version": 2, "source": raw["source"], "photo_refs": copy.deepcopy(refs),
                          "observations": validate_observations(system, raw["observations"]), "note": note}
    return output


def validate_request_photos(request, manifest=None):
    entries = {p["id"]: p for p in manifest["photos"]} if manifest else {}
    used = set()
    selected = []
    for index, person in enumerate(request["people"]):
        role = "A" if index == 0 else "B"
        refs = normalize_refs(person.get("photos", []), role)
        for ref in refs:
            if ref["id"] in used:
                raise PhotoError("同一照片不能重复或跨人引用。")
            item = entries.get(ref["id"])
            if item is None or item["person"] != role or item["sha256"] != ref["sha256"] or item["kind"] != ref["kind"]:
                raise PhotoError("照片已撤回、会话已失效，或照片不属于当前本人。")
            used.add(ref["id"])
            selected.append((item, ref))
        normalize_observations(person.get("observations", {}), refs, allow_agent_observations=True)
    if len(selected) > MAX_PHOTOS or sum(item["bytes"] for item, _ in selected) > MAX_TOTAL_BYTES:
        raise PhotoError("照片总数或总字节超过本次限制。")
    return selected


def read_manifest(value, request=None):
    path = _absolute(value)
    if not path.is_file() or path.stat().st_size > 128000:
        raise PhotoError("照片清单不存在或大小无效。")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise PhotoError("照片清单不是有效JSON。") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "manifest_type", "owner_id", "photos"} or type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise PhotoError("照片清单版本或字段无效。")
    if not _choice(raw["manifest_type"],{"photo_session", "private_photos"}) or not isinstance(raw["owner_id"], str) or not ID.fullmatch(raw["owner_id"]):
        raise PhotoError("照片清单归宿无效。")
    if raw["owner_id"] != path.parent.name:
        raise PhotoError("照片清单不属于所在资料目录。")
    if raw["manifest_type"] == "private_photos" and path.name != "photos.json":
        raise PhotoError("持久照片清单须为本任务photos.json。")
    if not isinstance(raw["photos"], list) or len(raw["photos"]) > MAX_PHOTOS:
        raise PhotoError("照片清单数量无效。")
    seen, hashes, total = set(), set(), 0
    for item in raw["photos"]:
        if not isinstance(item, dict) or set(item) != ENTRY_KEYS:
            raise PhotoError("照片清单条目字段无效。")
        if not isinstance(item["id"], str) or not ID.fullmatch(item["id"]) or item["id"] in seen or not isinstance(item["sha256"], str) or not SHA.fullmatch(item["sha256"]) or item["sha256"] in hashes:
            raise PhotoError("照片清单标识或摘要重复/无效。")
        if not _choice(item["person"],{"A", "B"}) or not _choice(item["kind"],KINDS) or not _choice(item["mime"],MIMES) or type(item["include_in_report"]) is not bool:
            raise PhotoError("照片清单归属或类型无效。")
        if item["viewed"] is not False or item["validation"] != "container_structure_only" or item["pixel_decode_performed"] is not False:
            raise PhotoError("上传清单不能伪称已看图。")
        prefix = "files" if raw["manifest_type"] == "photo_session" else "private-photos"
        expected = prefix + "/" + item["id"] + MIMES[item["mime"]]
        if item["relative_path"] != expected:
            raise PhotoError("照片清单路径不在服务端固定格式内。")
        filename = path.parent / expected
        _links(filename)
        if not filename.is_file() or not filename.resolve().is_relative_to(path.parent) or filename.stat().st_size > MAX_PHOTO_BYTES:
            raise PhotoError("照片文件缺失或离开本任务目录。")
        info, mime = _image(filename)
        if mime != item["mime"] or any(type(item[k]) is not type(v) or item[k] != v for k, v in info.items()):
            raise PhotoError("照片文件与清单摘要、字节或尺寸不一致。")
        if not isinstance(item["name"], str) or not 0 < len(item["name"]) <= 120 or any(c in item["name"] for c in ('/', '\\', '\x00')):
            raise PhotoError("照片原始文件名无效。")
        seen.add(item["id"]); hashes.add(item["sha256"]); total += item["bytes"]
    if total > MAX_TOTAL_BYTES:
        raise PhotoError("照片总字节超过限制。")
    if request is not None:
        validate_request_photos(request, raw)
    return raw


def photo_handoff(path, request=None):
    path = _absolute(path)
    raw = read_manifest(path, request)
    selected=validate_request_photos(request,raw) if request is not None else [(p,p) for p in raw["photos"]]
    return {"schema_version": 1, "photo_manifest": str(path),
            "photos": [{**item,"include_in_report":ref["include_in_report"], "file": str(path.parent / item["relative_path"])} for item,ref in selected]}


def observation_image(manifest_path,request,person_index,system):
    """Resolve the first verified photo for a person's explicit observation only."""
    wrapper=request["people"][person_index].get("observations",{}).get(system)
    if not wrapper or not wrapper.get("photo_refs"):
        return None
    if manifest_path is None:
        raise PhotoError("照片观察缺少可信清单。")
    handoff=photo_handoff(manifest_path,request)
    role="A" if person_index==0 else "B"
    entries={p["id"]:p for p in handoff["photos"]}
    for ref in wrapper["photo_refs"]:
        photo=entries.get(ref["id"])
        if photo is None or photo["person"]!=role or photo["sha256"]!=ref["sha256"]:
            raise PhotoError("观察照片归属或摘要变化。")
    return entries[wrapper["photo_refs"][0]["id"]]["file"]


def copy_photos(request, photo_manifest, target_job):
    has_refs = any(p.get("photos") for p in request["people"])
    if photo_manifest is None:
        if has_refs:
            raise PhotoError("照片引用缺少可信私有清单。")
        validate_request_photos(request)
        return None
    source = _absolute(photo_manifest)
    manifest = read_manifest(source, request)
    selected = validate_request_photos(request, manifest)
    if not selected:
        return None
    target = _absolute(target_job)
    if not ID.fullmatch(target.name) or not target.is_dir():
        raise PhotoError("照片归宿必须为本次服务端任务。")
    directory = target / "private-photos"
    directory.mkdir()
    written, photos = [], []
    try:
        for item, ref in selected:
            filename = item["id"] + MIMES[item["mime"]]
            src = source.parent / item["relative_path"]
            data = src.read_bytes()
            if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise PhotoError("照片复制前校验失败。")
            destination = directory / filename
            with destination.open("xb") as stream:
                stream.write(data)
            written.append(destination)
            photos.append({**item, "relative_path": "private-photos/" + filename, "include_in_report": ref["include_in_report"]})
        result = target / "photos.json"
        _write_new(result, {"schema_version": 1, "manifest_type": "private_photos", "owner_id": target.name, "photos": photos})
        written.append(result)
        read_manifest(result, request)
        return result
    except Exception:
        for file in reversed(written):
            file.unlink(missing_ok=True)
        directory.rmdir()
        raise


def discard_private_copy(target_job):
    """Rollback only a just-created private photo copy, never caller files."""
    target=_absolute(target_job)
    manifest=target/"photos.json"
    if not manifest.exists():
        return
    raw=read_manifest(manifest)
    for item in raw["photos"]:
        file=target/item["relative_path"]
        _links(file)
        file.unlink()
    manifest.unlink()
    (target/"private-photos").rmdir()


def reserve_collection(data_dir,owner):
    from agent_intake import guard_data_directory
    root=guard_data_directory(data_dir)
    _links(root)
    if not isinstance(owner,str) or not ID.fullmatch(owner):
        raise PhotoError("无效的采集归属。")
    root.mkdir(parents=True,exist_ok=True)
    for _ in range(5):
        job=root/secrets.token_hex(16)
        try:
            job.mkdir()
            _write_new(job/"collection-owner.json",{"photo_session":owner})
            return job
        except FileExistsError:
            continue
    raise PhotoError("无法创建本次资料目录。")


def discard_reserved(job_dir,owner):
    job=_absolute(job_dir)
    marker=job/"collection-owner.json"
    if not job.exists():
        return
    if not ID.fullmatch(job.name) or not marker.is_file() or json.loads(marker.read_text(encoding="utf-8"))!={"photo_session":owner}:
        raise PhotoError("收集目录归属变化，停止清理。")
    directory=job/"private-photos"
    if directory.exists():
        _links(directory)
        for file in directory.iterdir():
            if re.fullmatch(r"[a-f0-9]{32}\.(?:jpg|png)",file.name):
                _links(file)
                file.unlink()
        directory.rmdir()
    for name in ("photos.json","original-request.json","request.json","plan.json","metadata.json"):
        file=job/name
        _links(file)
        file.unlink(missing_ok=True)
    marker.unlink()
    job.rmdir()


class PhotoSession:
    def __init__(self, parent):
        from agent_intake import guard_data_directory
        self.parent = guard_data_directory(parent)
        _links(self.parent)
        self.id = secrets.token_hex(16)
        self.root = self.parent / self.id
        self.entries = {}
        self.lock = threading.RLock()
        self.closed = False
        self.created = False
        self.snapshots = set()

    def _ensure(self):
        if self.closed:
            raise PhotoError("照片会话已经结束。")
        _links(self.root)
        if not self.created:
            self.parent.mkdir(parents=True, exist_ok=True)
            self.root.mkdir()
            (self.root / "files").mkdir()
            _write_new(self.root / "owner.json", {"session_id": self.id})
            self.created = True

    @staticmethod
    def ref(item):
        return {k: item[k] for k in ("id", "kind", "sha256", "include_in_report")}

    @classmethod
    def public(cls, item):
        return {**{k: v for k, v in item.items() if k != "relative_path"}, "preview_url": "/api/photos/" + item["id"]}

    def upload(self, request):
        with self.lock:
            allowed = {"person", "kind", "name", "mime", "data_base64", "include_in_report"}
            if not isinstance(request, dict) or set(request) - allowed or not {"person", "kind", "name", "mime", "data_base64"} <= set(request):
                raise PhotoError("上传参数无效，不接受路径或额外字段。")
            if not _choice(request["person"],{"A", "B"}) or not _choice(request["kind"],KINDS) or not _choice(request["mime"],MIMES) or type(request.get("include_in_report", False)) is not bool:
                raise PhotoError("照片人物、类型或展示选择无效。")
            name = request["name"]
            if not isinstance(name, str) or not 0 < len(name) <= 120 or any(ord(c) < 32 or c in '/\\:' for c in name) or Path(name).suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                raise PhotoError("仅接受有效JPG/PNG文件名。")
            try:
                name.encode("utf-8")
            except UnicodeError as exc:
                raise PhotoError("照片文件名编码无效。") from exc
            encoded = request["data_base64"]
            if not isinstance(encoded, str) or not encoded or len(encoded) > 4 * ((MAX_PHOTO_BYTES + 2) // 3):
                raise PhotoError("每张照片上限6MiB。")
            try:
                data = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise PhotoError("照片编码无效。") from exc
            if not 0 < len(data) <= MAX_PHOTO_BYTES:
                raise PhotoError("每张照片上限6MiB。")
            if len(self.entries) >= MAX_PHOTOS or sum(p["bytes"] for p in self.entries.values()) + len(data) > MAX_TOTAL_BYTES:
                raise PhotoError("本次最多12张、合计30MiB。")
            digest = hashlib.sha256(data).hexdigest()
            if any(p["sha256"] == digest for p in self.entries.values()):
                raise PhotoError("同一照片不能重复上传或跨人复用。")
            self._ensure()
            id_ = secrets.token_hex(16)
            destination = self.root / "files" / (id_ + MIMES[request["mime"]])
            try:
                with destination.open("xb") as stream:
                    stream.write(data)
                info, mime = _image(destination)
                if mime != request["mime"]:
                    raise PhotoError("声明类型与实际PNG/JPEG容器不一致。")
                item = {**info, "id": id_, "person": request["person"], "kind": request["kind"], "name": name,
                        "mime": mime, "include_in_report": request.get("include_in_report", False), "relative_path": "files/" + destination.name,
                        "viewed": False, "validation": "container_structure_only", "pixel_decode_performed": False}
                self.entries[id_] = item
                return {"schema_version": 1, "photo": self.public(item), "ref": self.ref(item)}
            except Exception:
                destination.unlink(missing_ok=True)
                raise

    def list(self):
        with self.lock:
            if self.closed:
                raise PhotoError("照片会话已经结束。")
            return {"schema_version": 1, "photos": [self.public(p) for p in self.entries.values()],
                    "total_bytes": sum(p["bytes"] for p in self.entries.values()), "limits": {"per_photo_bytes": MAX_PHOTO_BYTES, "total_bytes": MAX_TOTAL_BYTES, "count": MAX_PHOTOS}}

    def preview(self, id_):
        with self.lock:
            if self.closed or not ID.fullmatch(id_) or id_ not in self.entries:
                raise PhotoError("照片不存在或已撤回。")
            item = self.entries[id_]
            file = self.root / item["relative_path"]
            _links(file)
            data = file.read_bytes()
            if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise PhotoError("照片已变化，预览被拒绝。")
            return data, item["mime"]

    def remove(self, id_):
        with self.lock:
            if self.closed or not isinstance(id_, str) or not ID.fullmatch(id_) or id_ not in self.entries:
                raise PhotoError("照片不存在或已撤回。")
            item = self.entries[id_]
            file = self.root / item["relative_path"]
            _links(file)
            file.unlink()
            del self.entries[id_]
            return {"status": "removed", "id": id_}

    def prune_snapshots(self):
        with self.lock:
            for name in self.snapshots:
                file=self.root/name
                _links(file)
                file.unlink(missing_ok=True)
            self.snapshots.clear()

    def snapshot(self, request):
        with self.lock:
            if self.closed:
                raise PhotoError("照片会话已经结束。")
            manifest = {"schema_version": 1, "manifest_type": "photo_session", "owner_id": self.id, "photos": list(self.entries.values())}
            validate_request_photos(request, manifest)
            if not any(p.get("photos") for p in request["people"]):
                return None
            self._ensure()
            self.prune_snapshots()
            file = self.root / ("snapshot-" + secrets.token_hex(16) + ".json")
            _write_new(file, manifest)
            self.snapshots.add(file.name)
            return file

    def cleanup(self):
        with self.lock:
            self.closed = True
            if not self.created:
                return
            _links(self.root)
            marker = self.root / "owner.json"
            if not marker.is_file() or json.loads(marker.read_text(encoding="utf-8")) != {"session_id": self.id}:
                raise PhotoError("会话目录归属变化，停止清理。")
            for item in self.entries.values():
                file = self.root / item["relative_path"]
                _links(file)
                file.unlink(missing_ok=True)
            for name in self.snapshots:
                file = self.root / name
                _links(file)
                file.unlink(missing_ok=True)
            marker.unlink()
            (self.root / "files").rmdir()
            self.root.rmdir()
            self.entries.clear()
