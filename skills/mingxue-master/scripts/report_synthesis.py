"""Evidence-bound narrative synthesis of already verified person snapshots.

This module validates structure and references; it neither writes a reading nor
establishes the truth of an interpretation, prediction or cross-system agreement.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import sys

sys.dont_write_bytecode=True
VERSION="report-synthesis-v1"
FIELDS={"context_sha256","summary","themes","agreements","differences","actions","limitations"}
REFERENCE={"reference_only","reference"}
OBSERVATION={"intake_only","observation","observation_only"}
UNAVAILABLE={"needs_setup","engine_unavailable","needs_input","ambiguous_input","error","invalid_input",
             "unsupported_range","unsupported_date","unsupported_mode","unsupported_boundary","engine_integrity_error",
             "engine_error","calculation_unavailable","needs_dictionary"}
COVERAGE_NOTE="计数只表示所选方法的资料与计算完成度，不是命运概率、匹配评分或预测可信度。跨体系主题对照不构成独立验证，也不作投票。"
HIGHLIGHTS={
    "bazi":[("日主","/details/day_master")],
    "numerology":[("生命路径归约数","/life_path/reduction/number")],
    "sukuyo":[("本命宿","/birth_mansion/label")],
    "ziwei":[("命宫","/soul_palace")],
    "astrology":[("太阳星座","/sun_sign")],"vedic":[("恒星太阳星座","/sun_sign")],
    "names":[("姓名","/name")],
    "iching":[("本卦","/hexagrams/base/name"),("之卦","/hexagrams/changed/name")],
    "yilin":[("易林卦对","/oracle/label")],"lingqijing":[("灵棋课名","/oracle/title")],
    "xiaoliuren":[("所到六宫","/final_palace/name")],
    "taiyi":[("太乙局式","/chart/bureau/文")],
    "tarot":[("牌阵","/spread_name")],"lenormand":[("牌阵","/spread/name")],
    "electional":[("历表钟口径","/calendar_basis/clock")],
}
# A narrow unsupported-score guard, not a truth detector. Actual calculation
# percentages without a fate/compatibility scoring claim remain ordinary text.
SCORE_CLAIM=re.compile(r"(?:匹配度|相容度|合婚评分|命运评分|运势评分)\s*[:：=为是]?\s*[0-9]+(?:\.[0-9]+)?\s*(?:[%％分]|/\s*100)|[0-9]+(?:\.[0-9]+)?\s*[%％]\s*(?:匹配|相容|预测准确)")
IDENTITY_META={"system","system_id","system_name","schema","schema_version","record_schema","status","ok","success",
               "version","software_version","engine_version","library_version","protocol_version","abi","engine_abi",
               "available","installed","job_id","project_id","record_id","revision","candidate_id","sha256",
               "deck_id","deck_version","schema_type","system_type","engine_name","library_name"}
CONTEXT_META={"input","inputs","params","parameters","options","settings","profile","selected_profile","person","birth","location",
              "question","questionnaire","topic","target","date","time","timezone","gender","birth_date","solar_date","lunar_date",
              "target_date","target_time","solar","lunar","solar_year","solar_candidates","lunar_candidates","time_known","time_precision",
              "scope","method","methods","method_name","algorithm","convention","conventions","chosen_convention","effective_settings",
              "rules","rule","rule_version","randomness","seed","seed_origin","draw","cast_record","protocol","evidence",
              "source_chart","source","engine","engine_info","provenance","stroke_provenance","calendar_basis","time_context",
              "house_system","system_code","zodiac","frame","limitations","notes","warnings","interpretation_scope","assessment",
              "text_status","interpretation_status","text_source","path","file","filename","directory"}
RESULT_ROOTS={
    "bazi":{"pillars","details","candidates","convention_alternatives","yun","solar_terms_on_date","corrections"},
    "astrology":{"candidates","sun_ranges","sun_sign"},"vedic":{"candidates","sun_ranges","sun_sign"},
    "ziwei":{"soul_palace","body_palace","chart","natal_mutagens","horoscope"},
    "names":{"five_grids","three_talents","characters","candidates","homophone_reminders","latin_numerology","writing"},
    "numerology":{"life_path","personal_year","name_expression"},
    "sukuyo":{"birth_mansion","daily_mansion","daily_relation","partner_mansion","partner_relation"},
    "qizheng":{"candidates"},"horary":{"candidates"},
    "iching":{"hexagrams","moving_positions","lines_bottom_to_top","najia","reading","cast_context"},
    "tarot":{"cards"},"xiaoliuren":{"steps","three_positions","final_palace","visualization"},
    "jinkoujue":{"four_positions","candidates","convention_alternatives","visualization"},
    "taiyi":{"chart","nine_palaces"},"yilin":{"hexagrams","oracle","line_values_bottom_to_top","moving_positions"},
    "lingqijing":{"figure","oracle"},"lenormand":{"cards","significator"},
    "geomancy":{"shield","house_chart"},"electional":{"records"},
}


class SynthesisError(ValueError):
    pass


def _canonical(value,maximum=40000000):
    try:
        raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")
    except (ValueError,TypeError,RecursionError,UnicodeError) as exc:
        raise SynthesisError("综合资料必须为有限、可序列化的JSON值。") from exc
    if len(raw)>maximum:
        raise SynthesisError("综合资料超过大小限制。")
    return raw


def _sha(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _meta_key(value):
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])","_",value).replace("-","_").lower()


def _identity_key(value):
    key=_meta_key(value)
    return key in IDENTITY_META or key.endswith(("_sha256","_hash"))


def _context_key(value):
    key=_meta_key(value)
    return key in CONTEXT_META or key.endswith(("_input","_inputs","_convention","_conventions"))


def _result_content(value,depth=0):
    """A result container containing only identity/protocol keys is not evidence."""
    if depth>40:
        return False
    if isinstance(value,dict):
        return bool(value) and any(not _identity_key(key) and not _context_key(key) and _result_content(item,depth+1)
                                   for key,item in value.items())
    if isinstance(value,list):
        # An empty calculated relation/moving-line set is still a real output.
        return not value or any(_result_content(item,depth+1) for item in value)
    return value is not None


def _basis_kind(system,pointer,value):
    tokens=[part.replace("~1","/").replace("~0","~") for part in pointer.split("/")[1:]]
    if any(_identity_key(token) for token in tokens):
        raise SynthesisError("纯身份、版本、状态或摘要元字段不能作综合结论依据。")
    if any(_context_key(token) for token in tokens):
        return "context"
    if tokens[0] not in RESULT_ROOTS.get(system,set()) or not _result_content(value):
        return "context"
    return "result"


def _text(value,label,maximum,*,scores=True):
    if not isinstance(value,str) or not value.strip() or len(value)>maximum or "\x00" in value:
        raise SynthesisError(label+"须为有界非空文字。")
    if scores and SCORE_CLAIM.search(value):
        raise SynthesisError("综合叙述不能提供未实现的命运、合婚或匹配评分。")
    return value


def _pointer(payload,pointer):
    if not isinstance(pointer,str) or not pointer.startswith("/") or len(pointer)>1000:
        raise SynthesisError("依据须为实际payload的JSON pointer。")
    parts=pointer.split("/")[1:]
    if len(parts)>64 or any(re.search(r"~(?![01])",part) for part in parts):
        raise SynthesisError("依据pointer转义或深度无效。")
    value=payload
    try:
        for raw in parts:
            key=raw.replace("~1","/").replace("~0","~")
            if isinstance(value,list):
                if not re.fullmatch(r"0|[1-9][0-9]*",key):
                    raise SynthesisError("数组依据须使用规范的非负索引。")
                value=value[int(key)]
            elif isinstance(value,dict):
                value=value[key]
            else:
                raise SynthesisError("依据pointer经过了非容器字段。")
    except (KeyError,IndexError,TypeError,ValueError) as exc:
        raise SynthesisError("综合依据无法在当前实际结果中定位。") from exc
    if value is None:
        raise SynthesisError("尚未确定的null字段不能作为已计算结论依据。")
    return value


def _selected(records,scope):
    if scope not in ("A","B","pair") or not isinstance(records,(list,tuple)) or not 1<=len(records)<=2:
        raise SynthesisError("scope须为A、B或pair，记录须为独立的1至2个人物。")
    indexed={}
    for record in records:
        if not isinstance(record,dict) or record.get("role") not in ("a","b","A","B"):
            raise SynthesisError("人物记录须保留snapshot的A/B角色。")
        role=record["role"].upper()
        if role in indexed:
            raise SynthesisError("不能把同一人物角色重复合入综合。")
        indexed[role]=record
    wanted=("A","B") if scope=="pair" else (scope,)
    if any(role not in indexed for role in wanted):
        raise SynthesisError("综合所需的人物记录缺失。")
    return [(role,indexed[role]) for role in wanted]


def _category(state,payload,system):
    native=payload.get("status")
    if native is not None and not isinstance(native,str):
        raise SynthesisError("方法原生状态须为文字或未提供。")
    if state in REFERENCE:
        return "reference",False
    if state in OBSERVATION:
        return "observation",False
    if state=="needs_input":
        return "needs_input",False
    if state in ("ready","partial"):
        candidates=payload.get("candidates")
        partial_name=system=="names" and state=="partial" and (payload.get("five_grids") or
            isinstance(candidates,list) and any(isinstance(item,dict) and item.get("five_grids") for item in candidates))
        if native in REFERENCE|OBSERVATION or native in UNAVAILABLE and not (
            partial_name
        ):
            raise SynthesisError("方法状态与实际结果不一致，不能称为已计算。")
        return state,True
    return "unavailable",False


def _extract(records,scope,comparison):
    from fortune import registry,compatible_system
    known={item["id"] for item in registry()}
    subjects=[]; items=[]; binding=[]; highlights=[]; available={}; required=[]; packages={}; relationships={}
    for role,record in _selected(records,scope):
        packed=record.get("packed"); report=record.get("report"); payloads=record.get("payloads")
        if not all(isinstance(value,dict) for value in (packed,report,payloads)):
            raise SynthesisError("综合须读取snapshot的packed、report和实际payloads。")
        if packed.get("results")!=payloads:
            raise SynthesisError("人物包与结果映射不一致。")
        identity=packed.get("person")
        if not isinstance(identity,dict):
            raise SynthesisError("人物包缺少明确称呼。")
        name=_text(identity.get("name"),"人物称呼",120,scores=False)
        relationship=record.get("relationship","")
        if not isinstance(relationship,str) or len(relationship)>80:
            raise SynthesisError("关系背景须为当前收集的有界文字。")
        relationships[role]=relationship
        packages[role]=_sha(packed)
        if "person" in report and report["person"]!=identity:
            raise SynthesisError("报告与人物包的称呼资料不一致。")
        birth=packed.get("birth")
        if "birth_input" in report and report["birth_input"]!=birth:
            raise SynthesisError("报告与人物包的出生资料不一致。")
        location=report.get("location_input",{})
        if location is None:
            location={}
        if not isinstance(location,dict) or birth is not None and not isinstance(birth,dict):
            raise SynthesisError("主体出生／地点资料须保留原生对象。")
        if "location" in packed and packed["location"]!=location:
            raise SynthesisError("报告与人物包的地点资料不一致。")
        question_hash=report.get("question_hash")
        if not isinstance(question_hash,str) or not re.fullmatch(r"[a-f0-9]{64}",question_hash):
            raise SynthesisError("综合缺少当前问题上下文摘要。")
        subject={"person":role,"name":name,"birth":copy.deepcopy(birth),"location":copy.deepcopy(location),"question_hash":question_hash}
        subjects.append(subject)
        panels=report.get("panels")
        if not isinstance(panels,list) or not 1<=len(panels)<=25:
            raise SynthesisError("综合需要实际所选方法面板。")
        seen=set(); methods=[]
        for panel in panels:
            if not isinstance(panel,dict) or panel.get("system") not in known or panel["system"] in seen:
                raise SynthesisError("方法面板须为已知、无重复的体系。")
            system=panel["system"]; seen.add(system)
            payload=payloads.get(system)
            if not isinstance(payload,dict) or payload.get("system") is not None and not compatible_system(payload["system"],system):
                raise SynthesisError("面板与实际payload体系不一致。")
            state=panel.get("state")
            _text(state,"方法状态",80,scores=False)
            result_sha=panel.get("result_sha256")
            if not isinstance(result_sha,str) or not re.fullmatch(r"[a-f0-9]{64}",result_sha):
                raise SynthesisError("方法缺少已提交结果摘要。")
            kind,calculated=_category(state,payload,system)
            title=_text(panel.get("title",system),"方法标题",120,scores=False)
            reading_status=panel.get("reading_status","not_provided")
            _text(reading_status,"解读状态",80,scores=False)
            reading=panel.get("traditional_interpretation") if reading_status=="applied" else None
            if reading_status=="applied" and not isinstance(reading,dict):
                raise SynthesisError("应用中的解读缺少实际文字与依据对象。")
            if reading is not None and (reading.get("result_sha256")!=result_sha or reading.get("question_hash")!=question_hash):
                raise SynthesisError("应用中的解读绑定与当前结果或问题不一致。")
            item={"person":role,"system":system,"title":title,"state":state,"kind":kind,"calculated":calculated,
                  "reading_status":reading_status,"result_sha256":result_sha}
            items.append(item)
            methods.append({"system":system,"state":state,"native_status":payload.get("status"),"result_sha256":result_sha,
                            "payload_sha256":_sha(payload),"reading_status":reading_status,"applied_reading":copy.deepcopy(reading)})
            available[(role,system)]={"payload":payload,"coverage":item}
            if calculated:
                required.append({"person":role,"system":system,"title":title})
                for label,pointer in HIGHLIGHTS.get(system,[]):
                    try:
                        value=_pointer(payload,pointer)
                    except SynthesisError:
                        continue
                    if len(_canonical(value))<=2048:
                        highlights.append({"person":role,"system":system,"label":label,"value":copy.deepcopy(value),
                                           "pointer":pointer,"result_sha256":result_sha})
        if seen!=set(payloads):
            raise SynthesisError("所选面板与实际结果集合不一致。")
        binding.append({"person":role,"identity":copy.deepcopy(identity),"birth":copy.deepcopy(birth),"location":copy.deepcopy(location),
                        "question_hash":question_hash,"relationship":relationship,"methods":sorted(methods,key=lambda value:value["system"])})
    if scope=="pair":
        if not isinstance(comparison,dict) or comparison.get("system")!="pair_analysis" or comparison.get("status") not in ("calculated","partial"):
            raise SynthesisError("双人综合必须传同一snapshot实际计算的comparison。")
        if comparison.get("people")!=[subject["name"] for subject in subjects]:
            raise SynthesisError("合参主体与综合的A/B称呼不一致。")
        evidence=comparison.get("evidence")
        evidence=evidence.get("people") if isinstance(evidence,dict) else None
        if not isinstance(evidence,dict) or any(not isinstance(evidence.get(role),dict) or evidence[role].get("package_sha256")!=digest for role,digest in packages.items()):
            raise SynthesisError("合参证据不是当前双方人物结果包，不能借用旧比较。")
        if any(value and value!=comparison.get("relationship") for value in relationships.values()):
            raise SynthesisError("合参关系背景与当前人物上下文不一致。")
        reading_context=comparison.get("reading_context")
        if reading_context is not None and reading_context!={subject["person"]:subject["question_hash"] for subject in subjects}:
            raise SynthesisError("合参问题上下文与当前双方报告不一致。")
        comparison_hash=_sha(comparison)
    else:
        if comparison is not None:
            raise SynthesisError("个人综合不接受双人比较对象。")
        comparison_hash=None
    counts={key:0 for key in ("selected","ready","partial","calculated","needs_input","reference","observation","unavailable")}
    for item in items:
        counts["selected"]+=1
        counts[item["kind"]]+=1
        counts["calculated"]+=int(item["calculated"])
    content={"version":VERSION,"scope":scope,"subjects":binding,"comparison_sha256":comparison_hash}
    context={"scope":scope,"context_sha256":_sha(content),"subjects":subjects,"coverage":items,"coverage_counts":counts,
             "coverage_note":COVERAGE_NOTE,"required_systems":required if scope!="pair" else [],"highlights":highlights,
             "relationship":comparison.get("relationship") if scope=="pair" else relationships[scope]}
    if scope=="pair":
        context["comparison_sha256"]=comparison_hash
    return context,available


def synthesis_context(records,scope,*,comparison=None):
    """Create immutable-content binding and actual coverage; never calculate or draw."""
    return _extract(records,scope,comparison)[0]


def validate_synthesis(value,records,scope,*,comparison=None):
    """Validate current binding and meaningful, topic-relevant result references."""
    if not isinstance(value,dict) or set(value)!=FIELDS:
        raise SynthesisError("综合JSON须严格包含context_sha256、summary、themes、agreements、differences、actions、limitations；不能自填状态或指标。")
    _canonical(value,512000)
    context,available=_extract(records,scope,comparison)
    if value["context_sha256"]!=context["context_sha256"]:
        raise SynthesisError("综合上下文已变化，旧综合不能套用于当前人物、结果或解读。")
    summary=_text(value["summary"],"综合总结",12000)
    calculated_by_person={role:{system for (who,system),source in available.items() if who==role and source["coverage"]["calculated"]}
                          for role in ("A","B")}
    if scope=="pair":
        theme_method_minimum=1 if len(calculated_by_person["A"] & calculated_by_person["B"])==1 else 2
    else:
        theme_method_minimum=2 if len(calculated_by_person[scope])>=2 else 1
    people=set(); sections={}
    for field,minimum,maximum in (("themes",1,20),("agreements",0,15),("differences",0,15),("actions",1,20)):
        entries=value[field]
        if not isinstance(entries,list) or not minimum<=len(entries)<=maximum:
            raise SynthesisError(field+"条目数不符合综合协议。")
        checked=[]
        for entry in entries:
            if not isinstance(entry,dict) or set(entry)!={"title","text","basis"}:
                raise SynthesisError("每条综合主题、对照或行动须严格含title/text/basis。")
            _text(entry["title"],"条目标题",120)
            _text(entry["text"],"条目文字",6000)
            refs=entry["basis"]
            if not isinstance(refs,list) or not 1<=len(refs)<=50:
                raise SynthesisError("每条综合叙述须有1至50条实际计算依据。")
            local_people=set(); methods=set(); unique=set()
            for ref in refs:
                if not isinstance(ref,dict) or set(ref)!={"person","system","pointer","label"} or ref["person"] not in ("A","B"):
                    raise SynthesisError("依据须严格标明A/B、体系、pointer与label。")
                system=ref["system"]
                if not isinstance(system,str) or (ref["person"],system) not in available:
                    raise SynthesisError("依据跨人、跨scope或指向未选择的方法。")
                source=available[(ref["person"],system)]
                if not source["coverage"]["calculated"]:
                    raise SynthesisError("资料入口、观察或未计算方法不能充当已计算依据；请在限制中说明。")
                _text(ref["label"],"依据说明",300)
                actual_value=_pointer(source["payload"],ref["pointer"])
                reference_kind=_basis_kind(system,ref["pointer"],actual_value)
                key=(ref["person"],system,ref["pointer"])
                if key in unique:
                    raise SynthesisError("同一条目不能重复引用相同人物方法字段。")
                unique.add(key)
                if reference_kind=="result":
                    local_people.add(ref["person"]); methods.add(system)
                    people.add(ref["person"])
            if field in ("agreements","differences"):
                if len(methods)<2:
                    raise SynthesisError("跨体系共性／分歧每条至少涉及两种不同实际方法；双方同一方法只计一种。")
                if scope=="pair" and local_people!={"A","B"}:
                    raise SynthesisError("双人共性／分歧每条都须引用A与B，不能借其他条目凑齐双方。")
            if field=="themes":
                if scope=="pair" and local_people!={"A","B"}:
                    raise SynthesisError("每个双人综合主题都须有A与B的实质结果，不能用其他条目或规则字段凑齐双方。")
                if len(methods)<theme_method_minimum:
                    raise SynthesisError(f"综合主题遗漏实质方法联系；每个主题须连接至少{theme_method_minimum}种已算方法的结果，不能只在其他条目凑齐方法。")
            checked.append(copy.deepcopy(entry))
        sections[field]=checked
    if scope=="pair":
        if people!={"A","B"}:
            raise SynthesisError("双人综合须有双方的实际计算依据。")
    # Individual themes keep their multi-method requirement; unused methods
    # need not be forced into an unrelated life topic just to satisfy coverage.
    limitations=value["limitations"]
    if not isinstance(limitations,list) or len(limitations)>30:
        raise SynthesisError("综合限制须为至多30项文字。")
    for text in limitations:
        _text(text,"综合限制",2000)
    return {**context,"status":"validated","summary":summary,**sections,"limitations":copy.deepcopy(limitations)}
