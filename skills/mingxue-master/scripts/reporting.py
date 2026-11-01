"""Readable local reports derived from recorded calculation artifacts."""
from __future__ import annotations

import html
import hashlib
import json
from pathlib import Path

LABELS = {"bazi": "八字", "iching": "周易", "ziwei": "紫微斗数", "astrology": "西方占星",
          "vedic": "恒星黄道基础", "names": "姓名", "numerology": "数秘", "tarot": "塔罗",
          "electional": "黄历", "palm": "手相观察", "face": "面相观察", "fengshui": "风水资料",
          "qimen": "奇门资料", "liuren": "六壬资料", "human_design": "人类图资料"}
LABELS.update({"xiaoliuren":"小六壬", "jinkoujue":"六壬金口诀", "qizheng":"七政四余", "taiyi":"太乙神数",
               "sukuyo":"宿曜", "yilin":"焦氏易林", "lingqijing":"灵棋经", "lenormand":"雷诺曼", "geomancy":"西方土占", "horary":"卜卦占星"})
PLANETS = {"Sun": "太阳", "Moon": "月亮", "Mercury": "水星", "Venus": "金星", "Mars": "火星",
           "Jupiter": "木星", "Saturn": "土星", "Uranus": "天王星", "Neptune": "海王星", "Pluto": "冥王星"}
SIGNS = dict(zip(("Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"),
                 ("白羊", "金牛", "双子", "巨蟹", "狮子", "处女", "天秤", "天蝎", "射手", "摩羯", "水瓶", "双鱼")))
STYLE = """body{max-width:1060px;margin:32px auto;padding:0 20px;background:#faf9f6;color:#263238;font:16px/1.75 system-ui,'Microsoft YaHei',sans-serif}h1{font-size:28px}h2{font-size:21px}h3{font-size:18px}header,.card{background:#fff;border:1px solid #dedbd3;border-radius:12px;padding:20px 24px;margin:18px 0}.meta{color:#5c666c;font-size:14px}.badge{display:inline-block;padding:2px 9px;border-radius:6px;background:#edf2ef;font-size:13px}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid #e8e6e0;padding:9px;text-align:left;vertical-align:top}a{color:#1b635c;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f5f2;padding:16px;font-size:12px}li{margin:6px 0}.notice{border-left:3px solid #9b8354;padding-left:14px}details{margin-top:14px}footer{font-size:13px;color:#687478;margin:28px 0}@media print{body{background:white}.card{break-inside:avoid}details{display:none}}"""


def text(value):
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def summarize(system, value, state):
    facts, limits = [], []
    def fact(label, item, pointer):
        facts.append({"label": label, "value": item, "pointer": pointer})
    if state not in ("ready", "partial", "reference_only", "intake_only"):
        return {"facts": [], "limits": [str(value.get("message") or value.get("reason") or value.get("error") or "本模块尚缺输入或运行条件。")],
                "reading": "补齐本模块所列条件后可继续；本轮其余模块独立保留。"}
    if system == "bazi":
        fact("四柱", value.get("pillars"), "/pillars")
        fact("日主结构", value.get("details", {}).get("day_master"), "/details/day_master")
        fact("时间候选数", len(value.get("candidates", [])), "/candidates")
        reading = "四柱与基础关系按本次钟点、时区和换日口径生成；传统格局、调候等解释需分别采用相应规则。"
        if not value.get("time_known"):
            limits.append("出生时辰未知；时柱与依赖时辰的解释未确定。")
    elif system == "ziwei":
        fact("命宫", value.get("soul_palace"), "/soul_palace")
        fact("身宫", value.get("body_palace"), "/body_palace")
        fact("五行局", value.get("chart", {}).get("fiveElementsClass"), "/chart/fiveElementsClass")
        fact("生年四化", value.get("natal_mutagens"), "/natal_mutagens")
        if value.get("scope", "origin") != "origin":
            fact("流运层级与目标", {"scope": value.get("scope"), "target": value.get("target")}, "/target")
        reading = "宫位、星曜与四化分别记录；本命结构与显式目标日期的流运分层阅读。"
        if value.get("gender_dependent_omitted"):
            limits.append("未给出传统性别规则，相关星曜或流运字段已抑制。")
    elif system in ("astrology", "vedic"):
        fact("黄道口径", value.get("zodiac"), "/zodiac")
        fact("太阳星座", SIGNS.get(value.get("sun_sign"), value.get("sun_sign")), "/sun_sign")
        candidates = value.get("candidates", [])
        fact("实际时刻候选数", len(candidates), "/candidates")
        if candidates:
            fact("天体位置", [{"天体": PLANETS.get(p.get("name"), p.get("name")),
                               "星座": SIGNS.get(p.get("sign"), p.get("sign")), "黄经": p.get("longitude"),
                               "逆行": p.get("retrograde")} for p in candidates[0].get("planets", [])], "/candidates/0/planets")
            houses = candidates[0].get("houses", {})
            fact("宫位计算", houses.get("status"), "/candidates/0/houses/status")
            if houses.get("status") != "calculated":
                limits.append(str(houses.get("reason") or "本轮未计算宫位。"))
        else:
            fact("未知时辰太阳区间", value.get("sun_ranges", []), "/sun_ranges")
            limits.append("未知时辰只保留太阳区间；没有补造中午星盘。")
        reading = "星座、相位与宫位来自实际天文位置；热带与恒星黄道采用各自明确的坐标口径。"
        if system == "vedic":
            limits.append("本模块为恒星黄道与月宿几何，不含完整分盘和大运。")
    elif system == "names":
        if value.get("mode") == "international":
            fact("姓名原文", value.get("full_name"), "/full_name")
            fact("书写组成", value.get("writing"), "/writing")
            fact("本人提供读音", value.get("pronunciation"), "/pronunciation")
            fact("拉丁字母表达数", value.get("latin_numerology"), "/latin_numerology")
            return {"facts": facts, "reading": "保留姓名原文，按实际文字组成和本人提供的读音讨论；明确的拉丁拼写按既有字母数规则计算。",
                    "limits": ["不自动音译或套用汉字五格；文字组成不代表国籍、人格或命运。"]}
        if value.get("system") == "name_candidate_comparison":
            fact("候选姓名", value.get("candidates"), "/candidates")
            fact("谐音提醒", value.get("homophone_reminders"), "/homophone_reminders")
            fact("笔画口径一致性", value.get("same_declared_stroke_convention"), "/same_declared_stroke_convention")
            return {"facts": facts, "reading": "候选按输入顺序比较字形、已选读音和数理；读音相同只作语音提醒，不生成命运排名。", "limits": ["谐音仅覆盖已确定读音、同批候选及用户提供的关注词。"]}
        fact("姓名", value.get("name"), "/name")
        fact("逐字笔画", value.get("strokes"), "/strokes")
        fact("笔画口径", value.get("stroke_provenance"), "/stroke_provenance")
        fact("五格", value.get("five_grids"), "/five_grids")
        fact("三才", value.get("three_talents", {}).get("label"), "/three_talents/label")
        reading = "五格与三才是按声明笔画完成的数理结构；读音、字形、字义和谐音另作文字比较。"
        limits.extend(text(item) for item in value.get("pending_inputs", []))
    elif system == "iching":
        fact("六爻自下而上", value.get("lines_bottom_to_top"), "/lines_bottom_to_top")
        fact("卦与变化", value.get("hexagrams"), "/hexagrams")
        fact("动爻", value.get("moving_positions"), "/moving_positions")
        if value.get("cast_context"):
            fact("起卦时间依据", value["cast_context"], "/cast_context")
        reading = "本、变、互、错、综分别用于传统符号阅读；出生时刻与起卦时刻分开保存。"
    elif system == "numerology":
        for field in ("life_path", "personal_year", "latin_name", "method", "master_numbers"):
            if field in value:
                fact(field, value[field], "/" + field)
        reading = "数值依明示归约约定生成，保留计算过程；不同归约法分别阅读。"
    elif system == "tarot":
        for field in ("spread", "cards", "randomness", "seed", "draw", "method"):
            if field in value:
                fact(field, value[field], "/" + field)
        reading = "本次软件抽样或用户手工给牌已记录；后续只修改报告主题时沿用同一抽取结果。"
    elif system == "electional":
        fact("日期表", value.get("records", []), "/records")
        reading = "宜忌、值日和冲煞是所选历法表的条目；具体用事条件另列。"
        limits.append("此处是黄历表检索，不是全派个性择日。")
    elif system in ("palm", "face"):
        for field in ("observation_status", "user_reported_observations", "image", "quality"):
            if field in value:
                fact(field, value[field], "/" + field)
        reading = "图片检查与显式观察分别记录；覆盖标注仅对应已提供的可见区域和坐标。"
        limits.append("容器与元数据检查不进行掌纹或面部识别。")
    elif system in ("xiaoliuren", "jinkoujue", "sukuyo", "qizheng", "horary", "taiyi", "yilin", "lingqijing", "lenormand", "geomancy"):
        for key, label in (("summary", "计算摘要"), ("input", "本次输入"), ("oracle", "原典取辞"),
                           ("final_palace", "落宫"), ("birth_mansion", "本命宿"), ("four_positions", "四位"),
                           ("chart", "盘面结构"), ("spread", "牌阵"), ("cards", "牌序"), ("initial_mothers", "四母")):
            if key in value:
                fact(label, value[key], "/" + key)
        reading = "本方法按独立输入与声明规则生成；盘面与原文对应关系保留，不与其他体系合成预测概率。"
        limits.extend(value.get("limitations", []))
    else:
        fact("资料入口", value.get("reference"), "/reference")
        fact("所需输入", value.get("required_inputs"), "/required_inputs")
        reading = "按已有盘面和指定规则查阅资料；本模块没有自动排盘结果。"
    return {"facts": [item for item in facts if item["value"] is not None], "reading": reading, "limits": limits}


def build_report(revision, source, profile, components, payloads, comparisons):
    question_context = {"topic": source["topic"], "question": source["question"]}
    if source.get("person"):
        question_context["person"] = source["person"]
    if source.get("questionnaire"):
        question_context["questionnaire"] = source["questionnaire"]
    question_hash = hashlib.sha256(json.dumps(question_context,
        ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    panels = []
    for system, component in components.items():
        summary = summarize(system, payloads[system], component["state"])
        supplied = source.get("readings", {}).get(system)
        interpretation = None
        reading_status = "not_provided"
        if supplied:
            if supplied["result_sha256"] != component["sha256"] or supplied["question_hash"] != question_hash:
                reading_status = "stale"
                summary["limits"].append("输入结果或问题已变化，旧版解释已失效，未沿用到本报告。")
            else:
                try:
                    verify_basis(supplied["basis"], payloads[system])
                    interpretation, reading_status = supplied, "applied"
                except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
                    reading_status = "invalid_basis"
                    summary["limits"].append("本次解释的依据未通过定位检查：" + str(exc))
        panels.append({"system": system, "title": LABELS.get(system, system), "state": component["state"],
                       "result_file": component["file"], "result_sha256": component["sha256"],
                       "reused_from": component.get("reused_from"), "reading_status": reading_status,
                       "traditional_interpretation": interpretation, **summary})
    unresolved = [panel["title"] for panel in panels if panel["state"] not in ("ready", "partial", "reference_only")]
    effective = {}
    for system, payload in payloads.items():
        if system == "bazi" and isinstance(payload.get("input"), dict):
            effective[system] = {key: payload["input"].get(key) for key in
                ("sect", "true_solar", "time_basis", "timezone", "longitude", "calendar", "leap")}
            effective[system]["day_change"] = "23:00" if payload["input"]["sect"] == 1 else "00:00"
        elif system == "ziwei" and isinstance(payload.get("convention"), dict):
            effective[system] = {key: payload["convention"].get(key) for key in
                ("algorithm", "year_divide", "day_divide", "fix_leap", "horoscope_divide")}
            if isinstance(payload.get("horoscope"), dict):
                effective[system]["flow_convention"] = payload["horoscope"].get("convention")
        elif system in ("astrology", "vedic") and isinstance(payload.get("zodiac"), dict):
            effective[system] = {"zodiac": payload["zodiac"]}
            if payload.get("candidates"):
                effective[system]["house_system"] = payload["candidates"][0].get("houses", {}).get("system_code")
        elif system == "names":
            effective[system] = {"stroke_provenance": payload.get("stroke_provenance"),
                                 "stroke_conventions": payload.get("stroke_conventions")}
    return {"schema_version": 1, "revision": revision, "topic": source["topic"], "question": source["question"], "question_hash": question_hash,
            "person": source.get("person", {"name": "个人"}),
            "birth_input": source.get("birth"), "location_input": source.get("location"),
            "questionnaire": source.get("questionnaire", {}), "report_depth": source.get("report_depth", "detailed"),
            "selected_profile": profile, "effective_settings": effective, "panels": panels, "comparisons": comparisons,
            "overview": {"selected_systems": [panel["title"] for panel in panels], "unresolved_systems": unresolved,
                         "reused_systems": [panel["title"] for panel in panels if panel["reused_from"]]},
            "interpretation": "各体系按实际输入与规则并列阅读，相关主题可作叙事对照；没有合并命运评分或预测概率。",
            "input_version_notice": "本报告固定属于所列版本。当前有效版本以项目index.html与project.json为准。"}


def verify_basis(items, payload):
    from project_store import contained
    root = Path(__file__).resolve().parents[1]
    for item in items:
        if item["kind"] == "calculation":
            value = payload
            for raw in item["pointer"].split("/")[1:]:
                key = raw.replace("~1", "/").replace("~0", "~")
                value = value[int(key)] if isinstance(value, list) and key.isdecimal() else value[key]
        else:
            if item["kind"] == "resource":
                from resources import get_resources
                base = Path(get_resources())
            else:
                base = root
            if not contained(base, item["file"]).is_file():
                raise ValueError("referenced evidence file is not available")


def report_html(report, payloads):
    from personal_report import personal_html
    return personal_html(report, payloads)


def legacy_report_html(report, payloads):
    escape = html.escape
    parts = ["<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
             "<title>综合命理报告</title><style>" + STYLE + "</style>",
             "<header><div class='badge'>综合命理 · " + escape(report["revision"]) + "</div><h1>" + escape(report["topic"]) + "</h1>",
             "<p>" + escape(report["question"]) + "</p><p class='meta'>" + escape(report["input_version_notice"]) + "</p>",
             "<p class='notice'>" + escape(report["interpretation"]) + "</p>",
             "<details><summary>所选预设与实际采用口径</summary><p>所选预设提供默认参数；显式输入及实际适配器结果列在实际口径中。</p><pre>" +
             escape(json.dumps({"所选预设": {"id": report["selected_profile"]["id"], "label": report["selected_profile"]["label"]},
                 "实际口径": report["effective_settings"]}, ensure_ascii=False, indent=2)) + "</pre></details></header>"]
    for panel in report["panels"]:
        relative = "results/" + panel["system"] + ".json"
        parts.extend(["<section class='card'><h2>" + escape(panel["title"]) + " <span class='badge'>" + escape(panel["state"]) + "</span></h2>",
                      "<p>" + escape(panel["reading"]) + "</p>"])
        if panel["traditional_interpretation"]:
            interpretation = panel["traditional_interpretation"]
            parts.append("<h3>本次传统解释</h3><p style='white-space:pre-line'>" + escape(interpretation["text"]) + "</p>")
            labels = [item.get("label", item.get("pointer", "计算结果")) + (" · " + item["section"] if item.get("section") else "") for item in interpretation["basis"]]
            parts.append("<p class='meta'>解释依据：" + escape("；".join(labels)) + "。定位检查说明依据可用，不代表自动验证了文字推论。</p>")
        if panel["reused_from"]:
            parts.append("<p class='meta'>输入与实现指纹一致，复用 " + escape(panel["reused_from"]) + " 的计算；报告按本轮主题重新生成。</p>")
        parts.append("<table><thead><tr><th>项目</th><th>实际结果</th></tr></thead><tbody>")
        for fact in panel["facts"]:
            parts.append("<tr><td>" + escape(fact["label"]) + "</td><td>" + escape(text(fact["value"])) + "</td></tr>")
        parts.append("</tbody></table>")
        if panel["limits"]:
            parts.append("<ul>" + "".join("<li>" + escape(item) + "</li>" for item in panel["limits"]) + "</ul>")
        parts.append("<p class='meta'>依据：<a href='" + relative + "'>本体系计算JSON</a> · SHA256 " + escape(panel["result_sha256"]) + "</p>")
        annotation = payloads[panel["system"]].get("annotation", {})
        if annotation.get("status") == "created":
            parts.append("<p><a href='" + escape(annotation["file"], quote=True) + "'>查看实际观察的坐标标注</a></p>")
        elif annotation:
            parts.append("<p class='notice'>覆盖标注未生成：" + escape(text(annotation.get("error") or annotation.get("reason"))) + "</p>")
        parts.append("<details><summary>查看原始计算与口径</summary><pre>" + escape(json.dumps(payloads[panel["system"]], ensure_ascii=False, indent=2)) + "</pre></details></section>")
    if report["comparisons"]:
        parts.append("<section class='card'><h2>规则预设对照</h2><pre>" + escape(json.dumps(report["comparisons"], ensure_ascii=False, indent=2)) + "</pre></section>")
    parts.append("<footer>本地生成 · 仅使用本版本记录的计算与输入 · <a href='../../index.html'>返回项目版本</a></footer></html>")
    return "\n".join(parts)


def index_html(project):
    entries = []
    for item in reversed(project["revisions"]):
        active = item["id"] == project["active_revision"]
        entries.append("<tr><td><a href='versions/" + item["id"] + "/report.html'>" + item["id"] + "</a></td><td>" + ("当前版本" if active else "已被新版本替代") + "</td><td>" + html.escape(item["status"]) + "</td><td>" + html.escape(item["created"]) + "</td></tr>")
    return "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>综合命理项目</title><style>" + STYLE + "</style><header><h1>综合命理项目</h1><p>当前有效版本：" + html.escape(project["active_revision"]) + "。历史报告保留原有输入与结果。</p></header><section class='card'><table><tr><th>报告</th><th>有效性</th><th>状态</th><th>生成时间（UTC）</th></tr>" + "".join(entries) + "</table></section></html>"
