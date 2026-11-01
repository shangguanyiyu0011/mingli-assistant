"""One-use loopback collection entry; no chart calculation or engine preparation."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys

sys.dont_write_bytecode = True


def guard_data_directory(value):
    from output_paths import protected_output_roots
    if not isinstance(value,(str,os.PathLike)) or not Path(value).expanduser().is_absolute():
        raise ValueError("收集目录必须由 Agent 指定为外置绝对路径。")
    root=Path(value).expanduser().resolve()
    if root==Path(root.anchor) or root.exists() and not root.is_dir():
        raise ValueError("收集目录必须为独立文件夹。")
    if any(root.is_relative_to(p) or p.is_relative_to(root) for p in protected_output_roots()):
        raise ValueError("收集目录不能与插件、引擎、资源或 Python 目录重叠。")
    return root


def _write(path,value):
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False).encode("utf-8")+b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def collect_request(data_dir,request, *, photo_session=None, reserved_job=None, reservation_owner=None):
    """Validate, then save native full request and a separate plan. No adapters."""
    from intake_flow import IntakeError, MissingBasics, normalize_request, plan_request
    try:
        root=guard_data_directory(data_dir)
        normalized=normalize_request(request,allow_unresolved_places=True)
        plan=plan_request(normalized)
        from photo_uploads import read_manifest, validate_request_photos
        if photo_session is not None:
            path=Path(photo_session)
            expected=root.parent/".photo-sessions"
            if not path.is_absolute() or not path.resolve().is_relative_to(expected.resolve()) or path.parent.parent.resolve()!=expected.resolve():
                raise ValueError("照片会话不属于本服务资料目录。")
            manifest=read_manifest(path)
            if manifest["manifest_type"]!="photo_session":
                raise ValueError("采集只接受本服务临时照片会话。")
        else:
            manifest=None
        validate_request_photos(normalized,manifest)
    except MissingBasics as exc:
        return {"status":"needs_input","job_id":None,"files":[],"questions":[],"warnings":[str(exc)]}
    except IntakeError as exc:
        return {"status":"invalid_input","job_id":None,"files":[],"questions":[],"warnings":[str(exc)]}
    except (ValueError,TypeError,OSError,RuntimeError):
        return {"status":"invalid_input","job_id":None,"files":[],"questions":[],"warnings":["资料或保存目录校验未通过，请检查日期、参数与本地资料状态。"]}
    job=None
    try:
        root.mkdir(parents=True,exist_ok=True)
        if reserved_job is not None:
            from photo_uploads import _absolute
            candidate=_absolute(reserved_job)
            marker=candidate/"collection-owner.json"
            if candidate.parent!=root or not re.fullmatch(r"[a-f0-9]{32}",candidate.name) or not marker.is_file() or json.loads(marker.read_text(encoding="utf-8"))!={"photo_session":reservation_owner}:
                raise ValueError("采集目录不是本服务的预约目录。")
            job=candidate
            job_id=job.name
        for _ in range(0 if job is not None else 5):
            job_id=secrets.token_hex(16)
            if not re.fullmatch(r"[0-9a-f]{32}",job_id):
                raise ValueError("invalid generated identifier")
            candidate=root/job_id
            try:
                candidate.mkdir()
                job=candidate
                break
            except FileExistsError:
                continue
        if job is None:
            raise ValueError("identifier unavailable")
        from photo_uploads import copy_photos
        photo_manifest=copy_photos(normalized,photo_session,job)
        digests={"original-request.json":_write(job/"original-request.json",copy.deepcopy(request)),
                 "request.json":_write(job/"request.json",normalized),
                 "plan.json":_write(job/"plan.json",plan)}
        if photo_manifest:
            digests["photos.json"]=hashlib.sha256(photo_manifest.read_bytes()).hexdigest()
        _write(job/"metadata.json",{"schema_version":1,"operation":"collect","job_id":job_id,
                                   "created_at":datetime.now(timezone.utc).isoformat(),"mode":normalized["mode"],
                                   "people_count":len(normalized["people"]),"files_sha256":digests,
                                   "calculated":False,"engines_prepared":False,"drawn":False})
        return {"status":"submitted","job_id":job_id,"files":[],"request_file":str(job/"request.json"),"photo_manifest":str(photo_manifest) if photo_manifest else None,
                "questions":plan["questions"],"warnings":plan["warnings"]}
    except (OSError,ValueError,TypeError):
        if job is not None:
            from photo_uploads import discard_private_copy
            try:
                discard_private_copy(job)
            except (OSError,ValueError):
                pass
            for name in ("original-request.json","request.json","plan.json","metadata.json","collection-owner.json"):
                try:
                    (job/name).unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                job.rmdir()
            except OSError:
                pass
        return {"status":"error","job_id":None,"files":[],"questions":[],"warnings":["资料未能完整保存，请重新提交。"]}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument("--data-dir",required=True,help="trusted external absolute collection directory")
    parser.add_argument("--open",action="store_true",help="explicitly open system browser")
    parser.add_argument("--ready-file",help="new external absolute readiness JSON path; no token")
    parser.add_argument("--timeout",type=float,default=900,help="seconds to wait for valid submission")
    args=parser.parse_args(argv)
    from workbench import main as workbench_main
    forwarded=["--agent","--data-dir",args.data_dir,"--timeout",str(args.timeout)]
    if args.open:
        forwarded.append("--open")
    if args.ready_file:
        forwarded.extend(["--ready-file",args.ready_file])
    return workbench_main(forwarded)


if __name__=="__main__":
    raise SystemExit(main())
