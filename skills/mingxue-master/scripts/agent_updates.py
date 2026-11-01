"""Replan a native collected request and revise its existing person projects."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import secrets

from agent_intake import guard_data_directory
from intake_flow import normalize_request, plan_request, _json_budget
from project_store import contained, merge_patch, project_lock, read_json, write_atomic, write_new_json
import workflow


def _linked(path):
    return path.is_symlink() or bool(getattr(path,"is_junction",lambda:False)())


def _no_links(path):
    for node in (path,*path.parents):
        if _linked(node):
            raise ValueError("Agent 更正不接受符号链接或目录联接。")


def _private(job,name):
    path=job/name
    _no_links(path)
    if not path.resolve().is_relative_to(job):
        raise ValueError("私有资料路径不能离开本次任务。")
    return path


def _job(value):
    if not isinstance(value,(str,os.PathLike)) or not Path(value).expanduser().is_absolute():
        raise ValueError("更正任务必须使用外置绝对目录。")
    path=Path(value).expanduser()
    _no_links(path)
    job=guard_data_directory(path)
    if not job.is_dir() or not re.fullmatch(r"[a-f0-9]{32}",job.name):
        raise ValueError("更正目标不是有效任务目录。")
    submitted=_private(job,"submitted-input.json")
    if not submitted.is_file():
        raise ValueError("更正任务缺少原始提交。")
    return job


def _diff(old,new):
    """Diagnostic recursive merge diff; null marks removals, never applied as config."""
    if not isinstance(old,dict) or not isinstance(new,dict):
        return copy.deepcopy(new)
    result={key:None for key in old.keys()-new.keys()}
    for key,value in new.items():
        if key not in old:
            result[key]=copy.deepcopy(value)
        elif old[key]!=value:
            result[key]=_diff(old[key],value) if isinstance(old[key],dict) and isinstance(value,dict) else copy.deepcopy(value)
    return result


def _current(project):
    _no_links(project)
    state=workflow.project_status(project)
    directory=Path(state["report"]).parent
    source=directory/"input.json"
    _no_links(source)
    if not source.resolve().is_relative_to(project):
        raise ValueError("当前个人输入离开了其项目。")
    return state,read_json(source,max_bytes=2000000)


def update_job(job_dir,patch:dict,person=None):
    """Update A/B native person or full request; no mutation of original submit.

    Invalid input raises before any person revision. A runtime failure can leave
    earlier person commits; it returns partial/request_committed:false and never
    publishes current-request.json as if both had completed.
    """
    job=_job(job_dir)
    if not isinstance(patch,dict) or person not in (None,"A","B"):
        raise ValueError("patch须为对象，person仅接受A、B或null。")
    _json_budget(patch)
    if person is not None and set(patch)-{"person","birth","location","name","photos","observations","dream"}:
        raise ValueError("指定人物时仅能更正本人基础资料、照片引用与独立观察。")
    with project_lock(job):
        current_file=_private(job,"current-request.json")
        original=normalize_request(read_json(current_file if current_file.exists() else _private(job,"submitted-input.json"),max_bytes=2000000),allow_agent_observations=True)
        if person is None:
            requested=merge_patch(original,patch)
            answer_patch=patch.get('preferences',{}).get('answers') if isinstance(patch.get('preferences'),dict) else None
            if isinstance(answer_patch,dict):
                # Null deletes an optional answer, while birth.time:null still
                # means an explicitly unknown clock and must remain intact.
                for key,value in answer_patch.items():
                    if value is None:requested['preferences']['answers'].pop(key,None)
        else:
            index=0 if person=="A" else 1
            if index>=len(original["people"]):
                raise ValueError("本次单人任务没有B。")
            requested=copy.deepcopy(original)
            requested["people"][index]=merge_patch(requested["people"][index],patch)
        native=normalize_request(requested,allow_agent_observations=True)
        from photo_uploads import read_manifest, validate_request_photos, observation_image
        manifest=_private(job,"photos.json")
        validate_request_photos(native,read_manifest(manifest) if manifest.exists() else None)
        if native["mode"]!=original["mode"] or len(native["people"])!=len(original["people"]):
            raise ValueError("更正不更换single/pair人数；请为新人数创建新任务。")
        plan=plan_request(native,allow_agent_observations=True)
        preparations=[]
        observation_writes=[]
        for index,person_plan in enumerate(plan["people"]):
            role="A" if index==0 else "B"
            project=_private(job,"project-"+role.lower())
            state,old=_current(project)
            target=copy.deepcopy(person_plan["workflow_input"])
            # Readings carry their old binding; the workflow alone decides stale/applied.
            target["readings"]=copy.deepcopy(old.get("readings",{}))
            for system,observations in person_plan["inline_observations"].items():
                old_file=old.get("options",{}).get(system,{}).get("observations")
                reusable=False
                if old_file:
                    candidate=Path(old_file)
                    _no_links(candidate)
                    if not candidate.is_absolute() or not candidate.resolve().is_relative_to(job):
                        raise ValueError("已有观察文件不能逃离本次任务。")
                    reusable=read_json(candidate)==observations
                if reusable:
                    filename=candidate
                else:
                    filename=_private(job,"private-update-"+role.lower()+"-"+system+"-"+secrets.token_hex(16)+".json")
                    if filename.exists():
                        raise ValueError("新的观察记录文件已存在。")
                    observation_writes.append((filename,observations))
                target["options"].setdefault(system,{})["observations"]=str(filename)
                image=observation_image(manifest if manifest.exists() else None,native,index,system)
                if image:
                    target["options"][system]["image"]=image
            target=workflow.normalize_input(target)
            difference=_diff(old,target)
            preparations.append((role,project,state,target,difference))
        # Every native person and complete target has now passed validation.
        revisions={}
        warnings=list(plan["warnings"])
        complete=False
        try:
            for filename,observations in observation_writes:
                write_new_json(filename,observations)
            for role,project,state,target,difference in preparations:
                if not difference:
                    revisions[role]={"revision":state["active_revision"],"status":state["status"],"changed":False,
                                     "recomputed":[],"reused":list(state["components"])}
                    continue
                # Complete incoming config removes obsolete nested keys. The
                # shared merge_patch intentionally retains null for unknown time.
                response=workflow.run_project(project,target,prepare_engines=native["preferences"]["prepare_engines"])
                revisions[role]={"revision":response["revision"],"status":response["status"],"changed":True,
                                 "recomputed":response["recomputed"],"reused":response["reused"]}
            # The caller's original submitted-input.json is never replaced.
            write_atomic(current_file,json.dumps(native,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
            complete=True
        except Exception:
            warnings.append("本次更正尚未全部完成；current-request未更新。已提交的个人版本保留，必须核对双方快照，不能把混合版本导出为完成报告。")
        if complete:
            for item in plan["questions"]:
                warnings.append(item["person_name"]+" · "+item["system"]+"："+item["question"])
        return {"status":"updated" if complete and all(item["status"]=="ready" for item in revisions.values()) else "partial",
                "request_committed":complete,"job_id":job.name,"job_dir":str(job),"revisions":revisions,
                "questions":plan["questions"],"warnings":warnings}
