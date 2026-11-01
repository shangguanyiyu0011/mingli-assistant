"""Agent-facing calculation, evidence handoff and immutable HTML/PDF delivery."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
from intake_flow import _offline_html, _reports_root, normalize_request, plan_request, submit
from output_paths import guard_output
from pair_report import load_person
from project_store import contained, read_json, write_new_json, file_digest


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")).hexdigest()


def job_directory(value):
    supplied=Path(value).expanduser()
    if not supplied.is_absolute() or supplied.is_symlink():
        raise ValueError("Agent任务必须使用实际的绝对目录。")
    root=supplied.resolve()
    if not re.fullmatch(r"[a-f0-9]{32}",root.name) or not (root/"submitted-input.json").is_file():
        raise ValueError("这不是一次已提交的命理任务。")
    _reports_root(root.parent)
    return root


def snapshot(job):
    job=job_directory(job)
    request_file="current-request.json" if (job/"current-request.json").exists() else "submitted-input.json"
    request=normalize_request(read_json(contained(job,request_file),max_bytes=256000),allow_agent_observations=True)
    plans=plan_request(request,allow_agent_observations=True)["people"]
    photos=[]
    if (job/"photos.json").is_file():
        from photo_uploads import photo_handoff
        photos=photo_handoff(job/"photos.json",request)["photos"]
    elif any(p.get("photos") for p in request["people"]):
        raise ValueError("照片记录不完整，请先核对本次上传资料。")
    records=[]
    for index in range(len(request["people"])):
        role="a" if index==0 else "b"
        packed,report,payloads=load_person(job/("project-"+role),"第一人" if index==0 else "第二人")
        from workflow import normalize_input
        expected=normalize_input(plans[index]["workflow_input"])
        source=read_json(contained(job/("project-"+role),f"versions/{report['revision']}/input.json"),max_bytes=2000000)
        # Readings may be updated directly. Facts and derived inputs go through
        # the request planner together, so a corrected birthday cannot keep an
        # old numerology date or old lunar mansion behind an apparently valid label.
        for key in ("person","birth","location","name","topic","question","questionnaire","report_depth","profile","settings","systems","deferred"):
            if expected.get(key)!=source.get(key):
                raise ValueError("Agent采集资料与当前个人项目不一致；请用 agent_report update 更正事实或问题后再导出。")
        for system in set(expected["options"])|set(source["options"]):
            if system not in ("palm","face") and expected["options"].get(system)!=source["options"].get(system):
                raise ValueError("本人派生日期或方法输入与采集资料不一致；请用 agent_report update 重规划。")
        for system in ("palm","face"):
            planned=plans[index]["inline_observations"].get(system)
            options=source["options"].get(system,{})
            actual=read_json(options["observations"],max_bytes=1_000_000) if options.get("observations") else None
            if actual!=planned:
                raise ValueError("照片观察与本人这次资料不一致，请通过Agent更新本人记录。")
            if isinstance(planned,dict) and planned.get("schema_version")==2:
                from photo_uploads import observation_image
                trusted=observation_image(job/"photos.json",request,index,system)
                image=options.get("image")
                if bool(trusted)!=bool(image) or trusted and file_digest(Path(image),max_bytes=6*1024*1024)!=file_digest(Path(trusted),max_bytes=6*1024*1024):
                    raise ValueError("观察照片不属于本人的这次选择。")
                value=payloads.get(system,{})
                if value.get("photo_refs")!=planned.get("photo_refs",[]) or value.get("observation_source")!=planned.get("source"):
                    raise ValueError("观察内容与本人的照片依据不一致。")
            elif options.get("image"):
                raise ValueError("照片必须先和本人的上传资料绑定。")
        records.append({"role":role,"packed":packed,"report":report,"payloads":payloads,"workspace":job/("project-"+role),
                        "relationship":request["preferences"]["relationship"],
                        "photos":[p for p in photos if p.get("person")==role.upper()],
                        "observations":request["people"][index].get("observations",{})})
    return job,request,records


def describe(job):
    root,request,records=snapshot(job)
    return describe_snapshot(root,request,records)


def describe_snapshot(root,request,records):
    from report_synthesis import synthesis_context
    comprehensive=len({panel["system"] for record in records for panel in record["report"]["panels"] if panel["state"] in ("ready","partial")})>1
    people=[]
    for record in records:
        report=record["report"]
        needs=[]
        for panel in report["panels"]:
            photo_ready=panel["system"] in ("palm","face") and record["payloads"][panel["system"]].get("observation_status")=="agent_observed"
            if (panel["state"] in ("ready","partial") or photo_ready) and panel.get("reading_status")!="applied":
                needs.append({"system":panel["system"],"result_sha256":panel["result_sha256"],"question_hash":report["question_hash"],
                    "result_file":str(record["workspace"]/panel["result_file"]),"required":"绑定本次结果及问题的文字解读与依据"})
        people.append({"role":record["role"],"name":record["packed"]["person"]["name"],"workspace":str(record["workspace"]),
            "revision":report["revision"],"report_json":str(record["workspace"]/"versions"/report["revision"]/"report.json"),"needs_readings":needs,
            "synthesis_required":comprehensive,"synthesis_context":synthesis_context(records,record["role"].upper()),
            "photos":record.get("photos",[])})
    value={"job_dir":str(root),"job_id":root.name,"mode":request["mode"],"people":people,
        "status":"needs_interpretation" if any(p["needs_readings"] for p in people) or request["mode"]=="pair" else "ready_to_export"}
    value["synthesis_required"]=comprehensive
    pending_photos=[]
    for record in records:
        reviewed={ref["id"] for obs in record.get("observations",{}).values() if obs.get("source")=="agent_viewed" for ref in obs.get("photo_refs",[])}
        for photo in record.get("photos",[]):
            if photo.get("kind") in ("portrait","palm_left","palm_right","palm_unknown") and photo["id"] not in reviewed:
                pending_photos.append({"person":record["role"].upper(),"id":photo["id"],"kind":photo["kind"],"file":photo["file"],"sha256":photo["sha256"]})
    value["pending_photo_review"]=pending_photos
    if pending_photos:value["status"]="needs_photo_review"
    value["synthesis_scopes"]=[p["role"].upper() for p in people]+(["pair"] if request["mode"]=="pair" else [])
    if comprehensive:
        value["synthesis_schema"]={"context_sha256":"对应synthesis_context的哈希","summary":"本人的综合结论",
            "themes":[{"title":"关注主题","text":"结合所有已算方法的具体解释","basis":[{"person":"A","system":"bazi","pointer":"/pillars","label":"本次四柱"}]}],
            "agreements":[],"differences":[],"actions":[{"title":"可实践的建议","text":"可核实的行动","basis":[]}],"limitations":[]}
        if not any(p["needs_readings"] for p in people) and not pending_photos:
            value["status"]="needs_synthesis"
    if request["mode"]=="pair":
        from pair_analysis import compare_people
        comp=compare_people(records[0]["packed"],records[1]["packed"],request["preferences"]["relationship"])
        comp["reading_context"]={"A":records[0]["report"]["question_hash"],"B":records[1]["report"]["question_hash"]}
        value["pair_comparison_sha256"]=digest(comp)
        value["pair_comparison"]=comp
        value["pair_reading_schema"]={"comparison_sha256":digest(comp),"text":"本次双方关系的文字合参", "basis":[{"person":"A","system":"bazi","pointer":"/pillars","label":"实际双方四柱"}]}
        value["pair_synthesis_context"]=synthesis_context(records,"pair",comparison=comp)
    return value


def run(request_file,reports_dir):
    request=read_json(request_file,max_bytes=256000)
    from intake_autofill import resolve_request
    from intake_flow import IntakeError, MissingBasics
    try:
        reports_root=_reports_root(reports_dir)
        cache_dir=guard_output(reports_root/".place-cache")
        autofill=resolve_request(request,cache_dir=cache_dir)
    except IntakeError as exc:
        return {"status":"needs_input" if isinstance(exc,MissingBasics) else "invalid_input","job_id":None,"files":[],"questions":[],"warnings":[str(exc)]}
    except (ValueError,OSError):
        return {"status":"invalid_input","job_id":None,"files":[],"questions":[],"warnings":["报告与地点缓存须保存在可用的外置目录，不能写入插件或运行时目录。"]}
    if autofill["questions"]:
        return {"status":"needs_input","job_id":None,"files":[],"questions":autofill["questions"],"warnings":autofill["warnings"],"place_sources":autofill["sources"]}
    photo_manifest=Path(request_file).expanduser().resolve().parent/"photos.json"
    result=submit(reports_root,autofill["request"],photo_manifest=photo_manifest if photo_manifest.is_file() else None)
    if result.get("status") not in ("ready","partial"):
        return result
    root=reports_root/result["job_id"]
    if autofill["sources"]:
        write_new_json(root/"place-resolution.json",{"original_request":request,"sources":autofill["sources"],"warnings":autofill["warnings"]})
    handoff=describe(root)
    # Browser URLs belong to an optional local service. The agent uses real paths.
    handoff["calculation_status"]=result["status"]
    handoff["questions"]=result.get("questions",[])
    handoff["warnings"]=[*autofill["warnings"],*result.get("warnings",[])]
    if autofill["sources"]:
        handoff["place_sources_file"]=str(root/"place-resolution.json")
    handoff["draft_files"]=[{"role":f["role"],"path":str(root/f["filename"])} for f in result["files"]]
    write_new_json(root/"agent-handoff.json",handoff)
    return handoff


def pair_reading(reading,comparison,records):
    if not isinstance(reading,dict) or set(reading)-{"comparison_sha256","text","basis"}:
        raise ValueError("双人解读应包含比较哈希、文字与明确依据。")
    if reading.get("comparison_sha256")!=digest(comparison):
        raise ValueError("双人资料或比较结果已变，旧合参文字不再有效。")
    if not isinstance(reading.get("text"),str) or not 1<=len(reading["text"])<=16000:
        raise ValueError("双人解读文字长度无效。")
    refs=reading.get("basis")
    if not isinstance(refs,list) or not 1<=len(refs)<=30:
        raise ValueError("双人解读需要1–30条明确依据。")
    for ref in refs:
        if not isinstance(ref,dict) or set(ref)-{"person","system","pointer","label"} or ref.get("person") not in ("A","B"):
            raise ValueError("双人依据需明确来自A或B及实际结果定位。")
        index=0 if ref["person"]=="A" else 1
        if ref.get("system") not in records[index]["payloads"]:
            raise ValueError("双人解读引用的方法不在此人的实际结果中。")
        pointer=ref.get("pointer")
        if not isinstance(pointer,str) or not pointer.startswith("/") or len(pointer)>1000:
            raise ValueError("双人依据需要有效JSON pointer。")
        if "label" in ref and (not isinstance(ref["label"],str) or len(ref["label"])>500):
            raise ValueError("双人依据说明无效。")
        value=records[index]["payloads"][ref["system"]]
        try:
            for part in pointer.split("/")[1:]:
                part=part.replace("~1","/").replace("~0","~")
                value=value[int(part)] if isinstance(value,list) and part.isdecimal() else value[part]
        except (KeyError,IndexError,TypeError,ValueError) as exc:
            raise ValueError("双人解读依据无法在当前结果中定位。") from exc
    return copy.deepcopy(reading)


def _filename(name,role):
    name=re.sub(r'[\\/:*?"<>|\x00-\x1f]',"_",str(name)).strip(" .")[:90] or "报告"
    return name+("_双人合参.html" if role=="pair" else "_个人报告.html")


def _write_new(path,text):
    target=guard_output(path)
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open("x",encoding="utf-8",newline="\n") as stream:
        stream.write(text)
    return target


def _reader_photos(record):
    import base64
    captions={"palm_left":"左手掌","palm_right":"右手掌","palm_unknown":"手掌照片","portrait":"人像照片",
              "room":"房间照片","floorplan":"户型图","chart":"已有盘面","other":"补充照片"}
    images=[]
    for photo in record.get("photos",[]):
        if not photo.get("include_in_report",False):continue
        path=Path(photo["file"])
        if not path.is_file() or path.stat().st_size>6*1024*1024:
            raise ValueError("报告照片不存在或过大。")
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=photo["sha256"]:
            raise ValueError("照片已变化，请先核对这次保存的资料。")
        mime=photo.get("mime")
        if mime not in ("image/jpeg","image/png"):raise ValueError("报告照片格式无效。")
        images.append({"id":photo["id"],"kind":photo["kind"],"caption":captions.get(photo["kind"],"补充照片"),
                       "src":"data:"+mime+";base64,"+base64.b64encode(raw).decode("ascii"),"sha256":photo["sha256"]})
    return images


def finalize(job,output_dir=None,*,pair_reading_file=None,allow_structural_only=False,
             synthesis_a_file=None,synthesis_b_file=None,synthesis_pair_file=None,is_example=False,illustrations_file=None):
    root,request,records=snapshot(job)
    from report_illustrations import load_illustrations
    illustrations=load_illustrations(illustrations_file,records)
    destination=None
    if output_dir is not None:
        supplied=Path(output_dir).expanduser()
        if not supplied.is_absolute(): raise ValueError("交付目录应为绝对路径。")
        destination=guard_output(supplied/".location-check").parent
        if destination.exists() and not destination.is_dir(): raise ValueError("交付目录是已有文件。")
        if any(destination.is_relative_to(r["workspace"].resolve()) for r in records):
            raise ValueError("交付文件不能写入已提交的个人项目。")
    current=describe_snapshot(root,request,records)
    if current["pending_photo_review"] and not allow_structural_only:
        return {"status":"needs_photo_review","job_dir":str(root),"files":[],"pending":current["pending_photo_review"],
                "message":"先实际查看对应照片并记录可见特征，再完成相关文字。"}
    if pair_reading_file and request["mode"]!="pair":
        raise ValueError("单人任务不能提供双人解读文件。")
    synthesis_files={"A":synthesis_a_file,"B":synthesis_b_file,"pair":synthesis_pair_file}
    synthesis_mode=current["synthesis_required"] or any(synthesis_files.values())
    pending=[{"person":p["name"],"system":n["system"]} for p in current["people"] for n in p["needs_readings"]]
    if pending and not allow_structural_only:
        return {"status":"needs_interpretation","job_dir":str(root),"pending":pending,"files":[],"message":"先由Agent为实际结果补充有依据的解读，再导出最终HTML。"}
    comparison=None
    if request["mode"]=="pair":
        comparison=current["pair_comparison"]
        if pair_reading_file and any(synthesis_files.values()):
            raise ValueError("综合总结与旧式双人解读不能同时提供；综合报告使用 synthesis-pair。")
        if pair_reading_file and synthesis_mode and not allow_structural_only:
            raise ValueError("多方法综合报告使用 synthesis-pair 作为统一合参总结，请去掉旧式 pair-reading。")
        if pair_reading_file:
            comparison["interpretation"]=pair_reading(read_json(pair_reading_file,max_bytes=256000),comparison,records)
        elif not allow_structural_only and not synthesis_mode:
            return {"status":"needs_pair_interpretation","job_dir":str(root),"comparison_sha256":current["pair_comparison_sha256"],"files":[],"message":"双人报告还需Agent针对本次比较填写合参解读与依据。"}
    scopes=[r["role"].upper() for r in records]+(["pair"] if comparison is not None else [])
    if any(value and scope not in scopes for scope,value in synthesis_files.items()):
        raise ValueError("综合总结引用了本次任务不存在的人物或双人范围。")
    overviews={}
    if not allow_structural_only:
        from report_synthesis import validate_synthesis
        missing=[scope for scope in scopes if not synthesis_files[scope]]
        if synthesis_mode and missing:
            contexts={p["role"].upper():p["synthesis_context"] for p in current["people"]}
            if "pair" in scopes:contexts["pair"]=current["pair_synthesis_context"]
            return {"status":"needs_synthesis","job_dir":str(root),"files":[],
                    "pending":[{"scope":scope,"context":contexts[scope]} for scope in missing],
                    "message":"逐方法解读后还需综合分析、共同点与分歧、行动建议及实际方法依据，才可导出完整图文报告。"}
        for scope,filename in synthesis_files.items():
            if filename:
                overviews[scope]=validate_synthesis(read_json(filename,max_bytes=512000),records,scope,
                    comparison=comparison if scope=="pair" else None)
    elif any(synthesis_files.values()):
        raise ValueError("仅排盘模式不接受综合解读文件；完整报告请去掉仅结构选项。")
    if not allow_structural_only:
        from reader_language import audit_reader_report,audit_reader_text,language_from_record
        detailed=request["preferences"]["depth"]=="detailed"
        issues=audit_reader_report(records,overviews,detailed=detailed)
        if comparison is not None and comparison.get("interpretation"):
            for issue in audit_reader_text(comparison["interpretation"]["text"],detailed=False,language=language_from_record(records[0])):
                issues.append({**issue,"path":"pair.interpretation.text"})
        for record in records:
            for panel in record["report"]["panels"]:
                if panel["system"] in ("palm","face") and record["payloads"][panel["system"]].get("observation_status")=="agent_observed" and panel.get("reading_status")=="applied":
                    for issue in audit_reader_text(panel["traditional_interpretation"]["text"],detailed=False,language=language_from_record(record)):
                        issues.append({**issue,"path":record["role"]+"."+panel["system"]})
        if issues:
            return {"status":"needs_reader_edit","job_dir":str(root),"files":[],"issues":issues,
                    "message":"把文字补充完整并改成面向本人的白话后再导出。"}
    from personal_report import personal_html,pair_html
    def reader_report(record):
        report=copy.deepcopy(record["report"])
        report["delivery_stage"]="structure_only" if allow_structural_only else "interpreted"
        report["reader_photos"]=_reader_photos(record)
        for panel in report["panels"]:
            images=illustrations.get((record["role"].upper(),panel["system"]))
            if images:panel["illustrations"]=images
        return report
    documents=[]
    for record in records:
        report=reader_report(record)
        content=_offline_html(personal_html(report,record["payloads"],overview=overviews.get(record["role"].upper()),is_example=is_example))
        documents.append(("personal_"+record["role"],record["packed"]["person"]["name"],content))
    if comparison is not None:
        ar,br=reader_report(records[0]),reader_report(records[1])
        content=_offline_html(pair_html(ar,records[0]["payloads"],br,records[1]["payloads"],comparison,request["preferences"]["relationship"],
            overview=overviews.get("pair"),personal_overviews=[overviews[scope] for scope in ("A","B") if scope in overviews],is_example=is_example))
        documents.append(("pair",records[0]["packed"]["person"]["name"]+"与"+records[1]["packed"]["person"]["name"],content))
    # The export is immutable; previous reports remain usable and unmodified.
    exports=root/"deliveries"
    exports.mkdir(exist_ok=True)
    directory=None
    for index in range(1,100000):
        candidate=exports/f"r{index:06d}"
        try:
            candidate.mkdir()
            directory=candidate
            break
        except FileExistsError:
            continue
    if directory is None: raise ValueError("无法分配新的报告导出版本。")
    files=[]
    for role,name,content in documents:
        path=_write_new(directory/(role+".html"),content)
        files.append({"role":role,"name":name,"path":str(path),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
    if destination is not None:
        for record,(_,name,content) in zip(files,documents):
            wanted=destination/_filename(name,record["role"])
            for index in range(1,10000):
                path=wanted if index==1 else wanted.with_name(wanted.stem+f"_{index}"+wanted.suffix)
                try:
                    exported=_write_new(path,content)
                    record["delivery_path"]=str(exported)
                    break
                except FileExistsError:
                    continue
            else: raise ValueError("交付目录中的报告重名过多。")
    manifest={"status":"exported","stage":"structure_only" if allow_structural_only else "interpreted","job_id":root.name,
        "created":datetime.now(timezone.utc).isoformat(),"files":files,"revisions":{r["role"]:r["report"]["revision"] for r in records},
        "synthesis_contexts":{scope:overview["context_sha256"] for scope,overview in overviews.items()}}
    write_new_json(directory/"manifest.json",manifest)
    return manifest


def deliver(job,output_dir=None,**finalize_options):
    """Keep the immutable HTML export and record actual per-file PDF outcomes."""
    from report_pdf import export_pdf,MIN_PDF_BYTES,MAX_PDF_BYTES
    manifest=finalize(job,output_dir,**finalize_options)
    if manifest.get("status")!="exported":return manifest
    delivery=copy.deepcopy(manifest)
    directory=Path(delivery["files"][0]["path"]).parent
    for record in delivery["files"]:
        source=Path(record.get("delivery_path",record["path"]))
        target=source.with_suffix(".pdf")
        try:
            pdf=export_pdf(source,target)
            if pdf.get("status")=="exported":
                raw=target.read_bytes() if target.is_file() and not target.is_symlink() and target.stat().st_size<=MAX_PDF_BYTES else b""
                if (pdf.get("path")!=str(target) or not MIN_PDF_BYTES<=len(raw)<=MAX_PDF_BYTES
                        or not raw.startswith(b"%PDF-") or b"%%EOF" not in raw[-2048:]
                        or pdf.get("sha256")!=hashlib.sha256(raw).hexdigest() or pdf.get("size_bytes")!=len(raw)):
                    raise ValueError("invalid PDF export")
            record["pdf"]={k:pdf[k] for k in ("status","path","sha256","size_bytes","code","message") if k in pdf}
        except (OSError,ValueError):
            record["pdf"]={"status":"error","code":"invalid_pdf_export","message":"PDF未通过实际文件核对，HTML已保留。"}
    if any(record["pdf"].get("status")!="exported" for record in delivery["files"]):
        delivery["status"]="needs_pdf_export"
        delivery["message"]="HTML已保存，部分PDF尚未成功导出；请根据各文件的PDF状态继续处理。"
    delivery["delivery_manifest"]=str(directory/"delivery.json")
    write_new_json(directory/"delivery.json",delivery)
    return delivery


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    sub=p.add_subparsers(dest="operation",required=True)
    runp=sub.add_parser("run");runp.add_argument("--request",required=True);runp.add_argument("--reports-dir",required=True)
    statusp=sub.add_parser("status");statusp.add_argument("--job",required=True)
    for operation in ("finalize","deliver"):
        finalp=sub.add_parser(operation);finalp.add_argument("--job",required=True);finalp.add_argument("--output-dir");finalp.add_argument("--pair-reading");finalp.add_argument("--allow-structural-only",action="store_true")
        finalp.add_argument("--synthesis-a");finalp.add_argument("--synthesis-b");finalp.add_argument("--synthesis-pair")
        finalp.add_argument("--example",action="store_true");finalp.add_argument("--illustrations")
    updatep=sub.add_parser("update");updatep.add_argument("--job",required=True);updatep.add_argument("--patch",required=True);updatep.add_argument("--person",choices=("A","B"))
    a=p.parse_args(argv)
    try:
        if a.operation=="run": result=run(a.request,a.reports_dir)
        elif a.operation=="status": result=describe(a.job)
        elif a.operation=="update":
            from agent_updates import update_job
            result=update_job(a.job,read_json(a.patch,max_bytes=256000),person=a.person)
        else: result=(deliver if a.operation=="deliver" else finalize)(a.job,a.output_dir,pair_reading_file=a.pair_reading,allow_structural_only=a.allow_structural_only,
            synthesis_a_file=a.synthesis_a,synthesis_b_file=a.synthesis_b,synthesis_pair_file=a.synthesis_pair,is_example=a.example,illustrations_file=a.illustrations)
        print(json.dumps(result,ensure_ascii=False,allow_nan=False))
        if a.operation in ("finalize","deliver") and result.get("status")!="exported":return 3
        return 0 if result.get("status") not in ("error","invalid_input","needs_input") else 2
    except (OSError,ValueError) as exc:
        print(json.dumps({"status":"error","message":str(exc)},ensure_ascii=False))
        return 2


if __name__=="__main__": raise SystemExit(main())
