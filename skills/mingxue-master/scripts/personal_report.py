"""Self-contained, person-bound visual HTML; no server or external assets required."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def public_data(value):
    """Keep the input/result evidence, without machine-specific runtime paths."""
    private_keys = {"engine_dir", "dictionary_dir", "directory", "executable", "command", "source_file",
                    "cache_directory", "cache_root", "source_root", "workspace", "resource_root", "python_executable"}
    if isinstance(value, dict):
        return {k: public_data(v) for k,v in value.items() if k not in private_keys}
    if isinstance(value, list):
        return [public_data(v) for v in value]
    if isinstance(value, str) and (re.search(r"[A-Za-z]:[\\/]", value) or value.startswith(("/Users/", "/home/", "/tmp/"))):
        return "本机运行位置已省略"
    return value


def person_data(report):
    person = report.get("person") or {"name": "个人"}
    annotated = {image.get('src') for panel in report.get('panels',[]) for image in panel.get('illustrations',[]) if image.get('kind') == 'photo_annotation'}
    annotated_ids = {image['source_photo_id'] for panel in report.get('panels',[]) for image in panel.get('illustrations',[]) if image.get('kind') == 'generated_photo_annotation' and image.get('source_photo_id')}
    return {"name": person.get("name", "个人"), "person": person, "birth": report.get("birth_input"),
            "location": report.get("location_input"), "questionnaire": report.get("questionnaire", {}),
            "photos":[image for image in report.get("reader_photos",[]) if image.get('src') not in annotated and image.get('id') not in annotated_ids]}


def panels(report, payloads, person_index=None):
    from fortune import find_system
    from workbench_api import diagram
    from workbench_catalog import catalog
    titles = {s["id"]:s["name"] for s in catalog()["systems"]}
    rows = []
    from reader_projection import available,condition,reader_view,NAMES,report_locale,report_translator
    translate=report_translator(report_locale(report))
    for panel in report["panels"]:
        system = panel["system"]
        payload = payloads[system]
        if not available(panel,payload):
            continue
        spec = {**find_system(system), "name": titles.get(system, panel["title"])}
        try:
            visual = {} if system=='names' and payload.get('mode')=='international' else diagram(system, payload, spec)
        except (ValueError, KeyError, TypeError, IndexError):
            visual = None
        if panel["state"] in ("reference_only", "intake_only"):
            visual = None
        plain_condition=condition(system,payload)
        limits=[translate(plain_condition)] if plain_condition else []
        row = {"id": system if person_index is None else f"{person_index}-{system}", "system": system,
            "title": translate(NAMES.get(system,titles.get(system, panel["title"]))), "state": panel["state"], "reading": "",
            "interpretation": panel.get("traditional_interpretation"), "facts": panel["facts"],
            "limits": limits, "view": reader_view(visual,system,payload) if visual is not None else None, "raw": payload,
            "reader_available":True,"next_step":"",
            "evidence": {"result_sha256": panel["result_sha256"], "question_hash": report["question_hash"],
                         "revision": report["revision"], "reading_status": panel.get("reading_status")}}
        if person_index is not None:
            row["person_index"] = person_index
        if panel.get("illustrations"):
            row["illustrations"] = panel["illustrations"]
        rows.append(row)
    return rows


def structural_reading(system, payload, panel):
    """Describe this result's actual structure, without manufacturing a forecast."""
    if panel["state"] not in ("ready", "partial"):
        return panel["reading"]
    if system == "bazi":
        pillars = payload.get("pillars", {})
        text = "本次四柱为" + "、".join(label + "“" + (pillars.get(key) or "未定") + "”" for key,label in (("year","年柱"),("month","月柱"),("day","日柱"),("hour","时柱"))) + "。"
        dm = payload.get("details", {}).get("day_master")
        if dm:
            text += "日主为" + dm["character"] + dm["element"] + "；下图分别列出各柱藏干、十神和纳音。"
        if len(payload.get("candidates", [])) > 1:
            text += "输入保留" + str(len(payload["candidates"])) + "个候选，未确定的时辰不会自动补齐。"
        return text
    if system in ("astrology", "vedic", "qizheng", "horary"):
        candidates = payload.get("candidates", [])
        if len(candidates) != 1:
            return "本次保留" + str(len(candidates)) + "个实际时刻候选或连续区间，各候选分别阅读，不默认选择其中一个。"
        c = candidates[0]
        planets = c.get("planets", c.get("bodies", []))
        if isinstance(planets, dict):
            planets = list(planets.values())
        from workbench_api import PLANETS_ZH
        records = [p for p in planets if isinstance(p, dict) and p.get("name",p.get("id")) in ("Sun","Moon")]
        parts = [PLANETS_ZH.get(p.get("name",p.get("id")), "星体") + "位于" + str(p.get("sign_zh",p.get("sign", ""))) + "，黄经" + str(round(p["longitude"],2)) + "°" for p in records]
        text = "；".join(parts) + "。" if parts else "轮盘采用这次记录的真实起盘时空与所选宫制。"
        if system == "qizheng" and payload.get("status") == "partial":
            text += "紫气参考尚未校准，图中只绘已算出的七政与其余计算点。"
        elif system == "horary":
            text += "本次问题、宫位、尊贵和局部入出相分别记录，不自动生成成败裁决。"
        return text
    if system == "ziwei":
        chart = payload.get("chart", {})
        soul,body=payload.get("soul_palace") or {},payload.get("body_palace") or {}
        soul_label=soul.get("branch", "未定") if isinstance(soul,dict) else str(soul)
        body_label=(str(body.get("name", "未定"))+"·"+str(body.get("branch", "未定"))) if isinstance(body,dict) else str(body)
        return "本次命宫落“" + soul_label + "”，身宫落“" + body_label + "”，五行局为“" + str(chart.get("fiveElementsClass", "未定")) + "”。十二宫按实际安星结果展示；选有流运时分别查看对应层。"
    if system in ("xiaoliuren", "jinkoujue", "sukuyo") and payload.get("summary"):
        return payload["summary"] + "。各步起式与所用规则保留在盘面及数据中。"
    if system == "taiyi" and payload.get("chart"):
        c = payload["chart"]
        return "本次为" + c["bureau"]["文"] + "，主算" + str(c["host_count"]) + "、客算" + str(c["guest_count"]) + "。九宫保留太乙专用编号及原16方位标签。"
    if system in ("yilin", "lingqijing"):
        oracle = payload.get("oracle", {})
        return "本次对应“" + str(oracle.get("label",payload.get("figure",{}).get("name", "所选课式"))) + "”，下方同时展示实际起式与原典取辞。"
    if system in ("tarot", "lenormand"):
        cards = payload.get("cards", [])
        return "本次记录的牌序为：" + "、".join(c.get("name", "") for c in cards) + "。各牌位置及抽样或手工输入方式分别保留，问题的文字不改变已记录的抽取结果。"
    if system == "geomancy":
        judge = next((f for f in payload.get("shield",{}).get("figures",[]) if f.get("id")=="J"), {})
        return "本次四母为" + "、".join(payload.get("initial_mothers", [])) + "；依次转置和奇偶相加得到法官图“" + judge.get("name", "未定") + "”。盾盘与所选宫盘分别展示。"
    if system == "names" and payload.get("five_grids"):
        return "本次分析姓名为“" + payload.get("name", "") + "”。五格为" + "、".join(k + str(v["number"]) for k,v in payload["five_grids"].items()) + "，三才为“" + payload.get("three_talents",{}).get("label", "未定") + "”；计算以所列笔画来源为准。"
    if system == "numerology" and payload.get("life_path"):
        r = payload["life_path"]["reduction"]
        return "按本次生日与归约约定，生命路径数为" + str(r["number"]) + "，过程为" + " → ".join(map(str,r["trace"])) + "。这些是所选符号体系的计算结构。"
    return panel["reading"]


def personal_html(report, payloads, *, overview=None,is_example=False):
    from reader_projection import report_locale,report_translator
    language=report_locale(report);translate=report_translator(language)
    person = person_data(report)
    title = person["name"] + " · " + translate('个人命理图谱')
    data = {"schema_version": 1, "kind": "personal", "language":language, "title": title, "subject": person["name"], "people": [person],
        "meta": {"revision": report["revision"], "created": datetime.now(timezone.utc).isoformat(), "topic": report["topic"],
            "question": report["question"], "depth": report.get("report_depth", "detailed"),
            "questionnaire": report.get("questionnaire", {}), "profile": report["selected_profile"],
            "effective_settings": report["effective_settings"], "input_version_notice": report["input_version_notice"],
            "delivery_stage": report.get("delivery_stage", "interpreted" if all(p.get("reading_status")=="applied" for p in report["panels"] if p["state"] in ("ready","partial")) else "structure_only"),
            "interpretation": report["interpretation"], "question_hash": report["question_hash"],"is_example":is_example},
        "panels": panels(report, payloads), "rule_comparisons": report.get("comparisons", [])}
    if overview is not None:
        from reader_projection import overview_for_reader
        role=overview.get("scope","A")
        data["overview"]=overview_for_reader(overview,{(role,p["system"]) for p in data["panels"]},language)
    return document(data)


def pair_html(a_report, a_payloads, b_report, b_payloads, comparison, relationship="伴侣", *, overview=None,personal_overviews=None,is_example=False):
    from reader_projection import report_locale,report_translator
    language=report_locale(a_report if a_report.get('questionnaire',{}).get('_report_language') else b_report)
    translate=report_translator(language)
    people = [person_data(a_report), person_data(b_report)]
    data = {"schema_version": 1, "kind": "pair", "language":language, "title": people[0]["name"] + " × " + people[1]["name"] + " · "+translate('双人合参图谱'),
        "people": people, "meta": {"created": datetime.now(timezone.utc).isoformat(), "relationship": relationship,
            "revision": a_report["revision"] + " / " + b_report["revision"], "topic": a_report["topic"],
            "question": a_report["question"], "depth": a_report.get("report_depth", "detailed"),
            "delivery_stage": a_report.get("delivery_stage", "interpreted" if comparison.get("interpretation") else "structure_only"),
            "input_version_notice": "双方各自的输入和结果分别固定于所列版本。",
            "interpretation": "","is_example":is_example},
        "panels": panels(a_report, a_payloads, 0) + panels(b_report, b_payloads, 1),
        "comparison": {"interpretation":comparison["interpretation"]} if comparison.get("interpretation") else None}
    if overview is not None:
        from reader_projection import overview_for_reader
        allowed={("A" if p["person_index"]==0 else "B",p["system"]) for p in data["panels"]}
        data["overview"]=overview_for_reader(overview,allowed,language)
    if personal_overviews:
        from reader_projection import overview_for_reader
        allowed={("A" if p["person_index"]==0 else "B",p["system"]) for p in data["panels"]}
        data["personal_overviews"]=[overview_for_reader(v,allowed,language) for v in personal_overviews]
    return document(data)


def document(data):
    projected = public_data(data)
    from reader_projection import report_translator
    language=projected.get('language','zh-CN')
    if language not in ('zh-CN','en','ja','ko'):language='zh-CN'
    projected['language']=language
    translate=report_translator(language)
    from reader_art import art_bundle
    tarot_cards=[card for p in projected.get('panels',[]) if p.get('system')=='tarot' for card in p.get('raw',{}).get('cards',[])]
    projected['art']=art_bundle((p.get('system') for p in projected.get('panels',[])),tarot_cards=tarot_cards)
    projected["document_sha256"] = digest(projected)
    raw = json.dumps(projected, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    raw = raw.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    css = (ROOT / "ui/report.css").read_text(encoding="utf-8")
    renderer = (ROOT / "ui/renderer.js").read_text(encoding="utf-8")
    script = (ROOT / "ui/report.js").read_text(encoding="utf-8")
    dictionary_path=ROOT/'ui/report-locales.json'
    dictionaries=json.loads(dictionary_path.read_text(encoding='utf-8')) if dictionary_path.is_file() else {}
    renderer='window.MINGXUE_LOCALES='+json.dumps(dictionaries,ensure_ascii=False)+';window.MingxueReportLanguage='+json.dumps(language)+';\n'+(ROOT/'ui/i18n.js').read_text(encoding='utf-8')+'\n'+renderer
    def inline(text):
        return re.sub(r"</script", r"<\\/script", text, flags=re.I)
    fallback = ["<noscript><h1>" + html.escape(projected["title"]) + "</h1>",
                "<p>" + html.escape(projected["meta"].get("topic", "")) + "</p><p>" + html.escape(projected["meta"].get("question", "")) + "</p>"]
    if projected["meta"].get("is_example"):
        fallback.append("<p>"+html.escape(translate('以下人物资料为虚构，不对应真人。'))+"</p>")
    for overview in [projected.get("overview"),*projected.get("personal_overviews",[])]:
        if not overview:
            continue
        names="、".join(str(p.get("name", "")) for p in overview.get("subjects",[]))
        fallback.append("<section><h2>"+html.escape(names+" · "+translate('综合命理分析'))+"</h2>")
        fallback.extend("<p>"+html.escape(p)+"</p>" for p in re.split(r"\n\s*\n",overview.get("summary", "")) if p.strip())
        for key,title in (("themes","分项解读"),("agreements","相近的地方"),("differences","需要分开看的地方"),("actions","行动建议")):
            if overview.get(key):
                fallback.append("<h3>"+html.escape(translate(title))+"</h3>")
            for item in overview.get(key,[]):
                fallback.append("<h4>"+html.escape(item["title"])+"</h4>")
                fallback.extend("<p>"+html.escape(p)+"</p>" for p in re.split(r"\n\s*\n",item["text"]) if p.strip())
        fallback.append("</section>")
    for panel in projected["panels"]:
        fallback.append("<section><h2>" + html.escape(translate(panel["title"])) + "</h2>")
        from visual_annotations import illustration_html
        for image in panel.get("illustrations",[]):
            fallback.append('<div class="analysis-illustrations">'+illustration_html(image,panel['system'],translate)+'</div>')
        if panel.get("interpretation"):
            fallback.extend("<p>"+html.escape(paragraph)+"</p>" for paragraph in re.split(r"\n\s*\n",panel["interpretation"]["text"]) if paragraph.strip())
        fallback.append("</section>")
    fallback.append("</noscript>")
    return ("<!doctype html><html lang=\""+language+"\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'\">"
        "<title>" + html.escape(projected["title"]) + "</title><style>" + css.replace("</style", "<\\/style") + "</style></head>"
        "<body><div id=\"report-app\"></div>" + "".join(fallback) + "<script id=\"report-data\" type=\"application/json\">" + raw + "</script>"
        "<script>" + inline(renderer) + "</script><script>" + inline(script) + "</script></body></html>")
