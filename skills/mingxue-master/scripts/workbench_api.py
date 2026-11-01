"""Local calculation and result-to-diagram adapters. Invoked in isolated workers."""
import copy
import json
import math
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
from workbench_catalog import EXTRA_MODULES, catalog

ROOT = Path(__file__).resolve().parents[1]
PLANETS_ZH = dict(zip(("Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto"),
                      ("太阳", "月亮", "水星", "金星", "火星", "木星", "土星", "天王星", "海王星", "冥王星")))


def number_list(value, label):
    if isinstance(value, str):
        value = [x for x in re.split(r"[\s,，;；]+", value.strip()) if x]
    if not isinstance(value, list):
        raise ValueError(label + "应为整数序列。")
    result = []
    for part in value:
        if isinstance(part, bool) or not re.fullmatch(r"-?\d+", str(part)):
            raise ValueError(label + "只能包含整数。")
        result.append(int(part))
    return result


def safe_params(system, params):
    specs = {s["id"]: s for s in catalog()["systems"]}
    if system not in specs or not isinstance(params, dict):
        raise ValueError("请选择存在的方法并填写参数。")
    spec = specs[system]
    fields = {f["key"]: f for f in spec["fields"]}
    if set(params) - set(fields):
        raise ValueError("参数不属于当前方法：" + ", ".join(sorted(set(params) - set(fields))))
    value = {}
    for key, raw in params.items():
        f = fields[key]
        if raw is None or raw == "":
            continue
        if f["type"] == "checkbox":
            if type(raw) is not bool:
                raise ValueError(f["label"] + "应为开关。")
        elif f["type"] == "number":
            if isinstance(raw, bool) or not isinstance(raw, (float, int)) or not math.isfinite(raw):
                raise ValueError(f["label"] + "应为有限数值。")
            if "min" in f and raw < f["min"] or "max" in f and raw > f["max"]:
                raise ValueError(f["label"] + "超出可用范围。")
            if f.get("step") != "any" and type(raw) is not int:
                raise ValueError(f["label"] + "应为整数。")
        elif f["type"] == "select":
            if not any(type(raw) is type(o["value"]) and raw == o["value"] for o in f["options"]):
                raise ValueError(f["label"] + "不是可用选项。")
        elif not isinstance(raw, str) or len(raw) > f.get("maxLength", 8000):
            raise ValueError(f["label"] + "应为限定长度的文字。")
        value[key] = raw
    for f in fields.values():
        visible = all(value.get(k, fields.get(k, {}).get("default")) in values for k, values in f.get("show_when", {}).items())
        if f.get("required") and visible and f["key"] not in value:
            raise ValueError("请填写" + f["label"] + "。")
    return value


def prepare(system):
    from fortune import dispatch, find_system
    family = {"vedic": "astrology", "qizheng": "astrology", "horary": "astrology"}.get(system, system)
    if family not in ("astrology", "ziwei", "names", "taiyi"):
        raise ValueError("该体系不需要准备外置依赖。")
    args = ["--download"] if family == "names" else []
    result, code = dispatch(find_system(family), args, prepare=True)
    return {"system": system, "status": "ready" if code == 0 else "needs_setup", "result": result}


def calculate_legacy(system, p):
    from chart import build_chart
    if system in ("bazi", "astrology", "vedic", "ziwei"):
        options = {k: p[k] for k in ("calendar", "leap", "sect", "timezone", "gender") if k in p}
        if system != "bazi":
            options.pop("gender", None)
        chart = build_chart(p["date"], p.get("time"), **options)
        if system == "bazi":
            return {**chart, "system": "bazi", "status": "calculated" if len(chart["candidates"]) == 1 else "partial"}
        if system == "ziwei":
            from ziwei import build_ziwei
            return build_ziwei(chart=chart, gender=p.get("gender"), scope=p.get("scope", "origin"),
                target_date=p.get("target_date"), target_time=p.get("target_time"))
        from astrology import build_astrology
        return build_astrology(chart, latitude=p.get("latitude"), longitude=p.get("longitude"),
            house_system=p.get("house_system", "P"), zodiac="sidereal" if system == "vedic" else "tropical",
            ayanamsa=p.get("ayanamsa", "lahiri") if system == "vedic" else None)
    if system == "iching":
        from iching import coin_cast, meihua_cast, build_result, build_cast_context
        method = p.get("method", "coins")
        if method == "coins":
            lines, record = coin_cast(p.get("seed"))
        elif method == "meihua":
            lines, record = meihua_cast(number_list(p.get("numbers", ""), "起卦数字"))
        else:
            lines, record = number_list(p.get("lines", ""), "六爻"), {"method": "manual_6_7_8_9"}
        context = build_cast_context(p.get("cast_date"), p.get("cast_time"),
            timezone=p.get("cast_timezone") if p.get("cast_date") else None)
        return {**build_result(lines, method_record=record, include_najia=p.get("najia", False),
                            question=p.get("question"), cast_context=context), "status": "calculated"}
    if system == "tarot":
        from symbolic import tarot
        return tarot(p.get("spread", "three"), seed=p.get("seed"), question=p.get("question", ""), upright_only=p.get("upright_only", False))
    if system == "numerology":
        from symbolic import numerology
        return numerology(p["date"], year=p.get("year"), method=p.get("method", "all-digits"), latin_name=p.get("latin_name"))
    if system == "names":
        from name_analysis import analyze_name
        return analyze_name(p["surname"], p["given"], p.get("strokes"), stroke_scheme=p.get("stroke_scheme", "unihan-irG"),
                            stroke_standard="用户提供笔画（未核对字典）" if p.get("strokes") else "unspecified")
    if system == "electional":
        from almanac import lookup
        return lookup(p["date"], days=p.get("days", 7), topic=p.get("topic"))
    from fortune import find_system
    spec = find_system(system)
    return {"system": system, "status": spec["level"], "notes": p.get("notes", ""),
            "question": p.get("question", ""), "reference_text": (ROOT / spec["reference"]).read_text(encoding="utf-8"),
            "limitations": ["这是已有盘或观察的资料阅读入口，没有自动生成盘面。"]}


def calculate(system, params):
    p = safe_params(system, params)
    if system in EXTRA_MODULES:
        from extra_methods import calculate as additional
        arguments = copy.deepcopy(p)
        arguments.pop("input_mode", None)
        for key in ("cards", "numbers", "lines", "counts", "upper", "middle", "lower"):
            if key in arguments and isinstance(arguments[key], str):
                arguments[key] = number_list(arguments[key], key)
        if system == "geomancy" and arguments.get("mothers"):
            arguments["mothers"] = [x for x in re.split(r"[\s,，;；]+", arguments["mothers"].strip()) if x]
        if system in ("xiaoliuren", "jinkoujue", "sukuyo", "taiyi"):
            arguments.pop("question", None)
        if system == "sukuyo":
            arguments = {"leap_rule": "same_numbered_month"}
            for role in ("birth", "target", "partner"):
                if p.get("input_calendar", "solar") == "solar":
                    if p.get(role + "_date"):
                        arguments[role] = {"calendar": "solar", "date": p[role + "_date"]}
                elif p.get(role + "_month") is not None or p.get(role + "_day") is not None:
                    arguments[role] = {"calendar": "lunar", "month": p.get(role + "_month"),
                                       "day": p.get(role + "_day"), "leap": p.get(role + "_leap", False)}
        if system == "qizheng":
            model = arguments.pop("ziqi_model", "not_calculated")
            arguments["ziqi"] = {"model": model}
            for source, target in (("ziqi_epoch_utc", "epoch_utc"), ("ziqi_epoch_longitude", "epoch_longitude"),
                                   ("ziqi_period_days", "period_days"), ("ziqi_reference_label", "reference_label")):
                if source in arguments:
                    arguments["ziqi"][target] = arguments.pop(source)
        result = additional(system, arguments)
    else:
        result = calculate_legacy(system, p)
    spec = next(s for s in catalog()["systems"] if s["id"] == system)
    return {"system": system, "name": spec["name"], "params": p, "result": result, "view": diagram(system, result, spec)}


def _notes(result):
    notes = result.get("limitations", result.get("limits", []))
    values = notes if isinstance(notes, list) else [str(notes)]
    translations = {
        "Astronomical positions": "星体位置的实算不验证人格、合盘或未来事件预测。",
        "No birthplace": "不会根据城市名称猜测地点、时区或经纬度。",
        "Moshier analytical": "使用固定的 Moshier 解析星历；不会静默改用其他星历。",
        "House membership": "宫位归属按黄经扇区计算，不计星体黄纬。",
        "TT/UT1": "历史和未来时刻受所用闰秒表及 ΔT 模型精度限制。",
        "Not a personalized": "这里只检索黄历表项，不是跨流派的个性化择日。",
        "Traditional table labels": "传统宜忌表项不保证现实结果。",
        "Do not delay": "黄历表项不用于推迟医疗安排或必须遵守的期限。",
    }
    out = []
    for note in values:
        if not isinstance(note, str):
            continue
        translated = next((v for k, v in translations.items() if note.startswith(k)), None)
        if translated or re.search(r"[\u3400-\u9fff]", note):
            out.append(translated or note)
    return out


def view(kind, title, data, *, metrics=(), notes=(), subtitle=""):
    return {"kind": kind, "title": title, "subtitle": subtitle, "metrics": list(metrics), "notes": list(notes), "data": data}


def metric(label, value):
    return {"label": label, "value": str(value)}


def diagram(system, result, spec):
    title, notes = spec["name"], _notes(result)
    status = result.get("status")
    if status in ("error", "invalid_input", "needs_setup", "engine_unavailable", "needs_input", "unsupported_date", "unsupported_range", "unsupported_mode", "unsupported_boundary", "engine_error", "engine_integrity_error", "calculation_unavailable", "needs_dictionary"):
        message = result.get("message", result.get("reason", "此输入尚不能生成盘面，请查看规则或准备所需依赖。"))
        return view("reference", title, {"text": str(message)}, notes=notes, subtitle="需要补充条件")
    if system == "bazi":
        columns = []
        for key, label in (("year", "年柱"), ("month", "月柱"), ("day", "日柱"), ("hour", "时柱")):
            p = (result.get("details", {}).get("pillars", {}).get(key) or {})
            pillar = result.get("pillars", {}).get(key)
            columns.append({"label": label, "stem": pillar[0] if pillar else "?", "branch": pillar[1] if pillar else "?",
                "element": p.get("stem", {}).get("element", ""),
                "hidden": [x.get("character", "") + " · " + str(x.get("ten_god", "")) for x in p.get("hidden_stems", [])],
                "tags": [str(x) for x in (p.get("ten_god"), p.get("nayin"), p.get("growth_stage")) if x]})
        count = len(result.get("candidates", []))
        if count > 1:
            notes = [f"此输入保留 {count} 个真实时刻或干支候选；主图只显示各候选共有的四柱，问号表示尚未确定。", *notes]
        base_view = view("pillars", title, {"columns": columns}, notes=notes,
                    metrics=[metric("历法日期", result.get("solar") or "多个日期"), metric("农历", result.get("lunar") or "多个候选"), metric("候选数", count)])
        if count > 1:
            variants = []
            for i, c in enumerate(result["candidates"]):
                sample = {**result, "pillars": c["pillars"], "details": c["details"], "candidates": [c],
                          "solar": c.get("solar"), "lunar": c.get("lunar")}
                vv = diagram(system, sample, spec)
                ranges = c.get("time_ranges", [])
                label = ranges[0].get("original_start", "") if ranges else str(i + 1)
                vv["subtitle"] = "所选候选区间的结构，不表示已确定真实出生时辰。"
                variants.append({"label": "候选 " + str(i + 1) + " · " + label, "view": vv})
            base_view["variants"] = variants
        return base_view
    if system in ("astrology", "vedic"):
        candidates = result.get("candidates", [])
        if not candidates:
            return view("reference", title, {"text": "未给出确定钟点时，仅计算太阳位置区间；完整范围保留在数据中。"}, notes=notes)
        c = candidates[0]
        houses = c.get("houses", {})
        points = [{"label": PLANETS_ZH.get(p["name"], p["name"]), "longitude": p["longitude"],
                   "speed": p.get("longitude_speed_deg_per_day"), "type": "physical"} for p in c["planets"]]
        asc = houses.get("ascendant") or {}
        notes = ["按输入分钟区间起点绘制；原始数据保留该分钟的范围及末端位置。", *notes]
        if len(candidates) > 1:
            notes.insert(0, f"共有 {len(candidates)} 个时间候选，当前为候选 1。")
        base_view = view("wheel", title, {"points": points, "cusps": [h["longitude"] for h in houses.get("cusps", [])],
                    "ascendant": asc.get("longitude")}, notes=notes,
                    metrics=[metric("UTC", c["utc"]), metric("黄道", "恒星黄道" if system == "vedic" else "回归黄道"), metric("宫制", houses.get("system_code", "—"))])
        if len(candidates) > 1:
            base_view["variants"] = [{"label": "候选 " + str(i + 1) + " · " + cand["utc"],
                "view": diagram(system, {**result, "candidates": [cand]}, spec)} for i,cand in enumerate(candidates)]
        return base_view
    if system == "ziwei":
        chart = result.get("chart", result.get("result", {}))
        if not chart and "palaces" in result:
            chart = result
        palaces = chart.get("palaces", [])
        cells = [{"index": p["index"], "name": p["name"], "branch": p.get("earthlyBranch", ""),
                  "major": [s["name"] + ("·" + s["mutagen"] if s.get("mutagen") else "") for s in p.get("majorStars", [])],
                  "minor": [s["name"] for s in p.get("minorStars", [])],
                  "tags": (["身宫"] if p.get("isBodyPalace") else [])} for p in palaces]
        base_view = view("palaces", title, {"palaces": cells, "center": ["紫微斗数", str(result.get("input", {}).get("solar_date", "")), "本命"]}, notes=notes)
        layers = (result.get("horoscope") or {}).get("layers", {})
        variants = [{"label": "本命盘", "view": copy.deepcopy(base_view)}]
        for key,label in (("yearly", "流年"), ("monthly", "流月"), ("daily", "流日")):
            if key not in layers:
                continue
            layer = layers[key]
            flow_cells = []
            for p in layer["palaces"]:
                natal = next(c for c in cells if c["index"] == p["index"])
                flow_cells.append({**natal, "name": p["scope_palace"],
                    "major": ["本命·" + n for n in natal["major"]],
                    "minor": ["流曜·" + s["name"] for s in p.get("flow_stars", [])],
                    "tags": ["本命" + p["natal_palace"], *[m["star"] + "化" + m["mutagen"] for m in p.get("flow_mutagens", [])]]})
            flow_view = view("palaces", title + " · " + label, {"palaces": flow_cells, "center": [label, str(result.get("target", {}).get("date", "")), "叠加本命星曜"]},
                notes=["宫名与四化来自所选流运层，本命星曜另行标注。", *notes])
            variants.append({"label": label, "view": flow_view})
        if len(variants) > 1:
            base_view.update(variants=variants, variant_mode="views")
        return base_view
    if system in ("iching", "meihua"):
        hexagrams = []
        rows = result.get("lines_bottom_to_top", [])
        for kind, label in (("base", "本卦"), ("changed", "之卦"), ("nuclear", "互卦")):
            h = result["hexagrams"][kind]
            bits = h.get("bits_bottom_to_top", h.get("bits", []))
            if kind == "base":
                lines = [{"yang": r["yang"], "moving": r["moving"], "label": r["label"], "detail": r["type"]} for r in rows]
            elif kind == "changed":
                lines = [{"yang": r["changed_yang"], "moving": False, "label": str(r["position"])} for r in rows]
            else:
                lines = [{"yang": bool(int(b)), "moving": False, "label": str(i+1)} for i, b in enumerate(bits)]
            hexagrams.append({"title": label, "name": h.get("name", ""), "number": h.get("number"), "lines": lines})
        metrics=[metric("动爻", "、".join(map(str, result["moving_positions"])) or "无"), metric("爻序", "初爻在下")]
        if system == "meihua":
            bu=result["body_use"]
            metrics += [metric("体卦", bu["body"]["name"]+" · "+bu["body"]["element"]), metric("用卦", bu["use"]["name"]+" · "+bu["use"]["element"]), metric("体用关系", {"same_element":"比和", "source_generates_target":"体生用", "target_generates_source":"用生体", "source_controls_target":"体克用", "target_controls_source":"用克体"}[bu["relation"]])]
        return view("hexagrams", title, {"hexagrams": hexagrams}, notes=notes, metrics=metrics)
    if system == "tarot":
        return view("cards", result.get("spread_name", title), {"cards": [{"label": c["name"], "id": c["id"],
                    "position": c["position"], "keywords": [c["theme"]], "orientation": c["orientation"]} for c in result["cards"]],
                    "columns": 3 if len(result["cards"]) <= 3 else 5}, notes=["这是实际执行并记录的虚拟抽样，牌面符号供文化解读和反思。"])
    if system == "names":
        grids = result.get("five_grids") or {}
        return view("board", result.get("name", title), {"cells": [{"label": k, "value": str(v["number"]),
            "items": [v.get("element", "")], "active": k == "人格"} for k, v in grids.items()], "columns": 3},
            metrics=[metric("三才", (result.get("three_talents") or {}).get("label", "待核对")), metric("笔画口径", (result.get("stroke_provenance") or {}).get("standard_label", "字库"))], notes=notes)
    if system == "numerology":
        items = []
        for key, label in (("life_path", "生命路径数"), ("personal_year", "个人年"), ("name_expression", "姓名表达数")):
            raw = result.get(key)
            if raw is not None:
                reduced = raw.get("reduction", raw) if isinstance(raw, dict) else {"number": raw}
                items.append({"label": label, "value": str(reduced.get("value", reduced.get("number", "—"))),
                              "detail": " → ".join(map(str, reduced.get("trace", [])))})
        return view("numbers", title, {"items": items}, notes=notes)
    if system == "electional":
        return view("board", title, {"cells": [{"label": r["date"], "value": r["day_pillar"],
            "items": [r["lunar"], "宜：" + "、".join(r["yi"]), "忌：" + "、".join(r["ji"])], "active": False} for r in result["records"]], "columns": 3}, notes=notes)
    if system in EXTRA_MODULES:
        return extra_diagram(system, result, title, notes)
    return view("reference", title, {"text": result.get("reference_text", spec["summary"])}, notes=notes,
                subtitle="观察记录与传统资料" if spec["level"] == "visual_guidance" else "资料入口")


def extra_diagram(system, r, title, notes):
    if system == "dream":
        return view("board", title, {"cells":[{"label":e["chapter"], "value":e["text"],
            "items":e["matched_keywords"], "active":False} for e in r["matches"]], "columns":2}, notes=notes)
    if system in ("qizheng", "horary"):
        def wheel(c):
            w = c.get("wheel") or {}
            houses = w.get("houses") or {}
            uncalculated = [p.get("label", "") for p in w.get("points", []) if p.get("longitude") is None]
            n = list(notes)
            if uncalculated:
                n.insert(0, "未绘制：" + "、".join(uncalculated) + "（未提供已校准的模型）")
            n.append("轮盘对应候选分钟区间起点；完整时刻范围与相位结构保留在规则和数据中。")
            return view("wheel", title, {"points": [{"label": p["label"], "longitude": p["longitude"],
                "speed": p.get("longitude_speed_deg_per_day"), "type": p.get("kind"), "plot_style": p.get("plot_style")}
                for p in w.get("points", []) if p.get("longitude") is not None],
                "cusps": [h["longitude"] for h in houses.get("cusps", [])],
                "ascendant": (houses.get("ascendant") or {}).get("longitude")}, notes=n,
                metrics=[metric("UTC", c.get("utc", "")), metric("宫制", houses.get("system_code", "—")), metric("计算点", "实体与传统计算点分层")])
        candidates = r.get("candidates", [])
        if not candidates:
            return view("reference", title, {"text": r.get("reason", r.get("message", "需要明确起盘时空。"))}, notes=notes)
        result = wheel(candidates[0])
        if len(candidates) > 1:
            result["subtitle"] = "多个真实时刻候选，请分别查看"
            result["variants"] = [{"label": "候选 " + str(i + 1) + " · " + c["utc"], "view": wheel(c)} for i,c in enumerate(candidates)]
        return result
    if system == "xiaoliuren":
        return view("sixpalaces", title, {"cells": [{"label": p["name"], "name": p["name"], "index": p["index"],
            "row": p["row"], "col": p["column"], "element": p["element"], "active": p["index"] == r["final_palace"]["index"]} for p in r["palaces"]],
            "steps": r["steps"], "selected_index": r["final_palace"]["index"]}, notes=notes,
            metrics=[metric("落宫", r["final_palace"]["name"]), metric("起课路径", r["summary"])])
    if system == "jinkoujue":
        def board(c):
            return view("fourpositions", title, {"rows": c["four_positions"], "general_ring": c["general_plate"], "noble_ring": c["noble_plate"]},
                        notes=notes, metrics=[metric("日柱", c["day_pillar"]), metric("月将", c["month_general_branch"]), metric("地分", c["earth_branch"])])
        candidates = r["candidates"]
        result = board(candidates[0])
        if len(candidates) > 1:
            result["subtitle"] = "输入跨越规则边界，保留各个候选"
            result["variants"] = [{"label": c["candidate_id"] + " · 月将" + c["month_general_branch"], "view": board(c)} for c in candidates]
        return result
    if system == "sukuyo":
        relations = [r[k]["reading"] for k in ("daily_relation", "partner_relation") if r.get(k)]
        return view("mansion", title, {"nodes": r["visualization"]["nodes"], "relations": relations},
            metrics=[metric("本命宿", r["birth_mansion"]["label"]), metric("值日宿", (r.get("daily_mansion") or {}).get("label", "未指定")),
                     metric("对方宿", (r.get("partner_mansion") or {}).get("label", "未指定"))], notes=notes,
            subtitle="27宿顺序与关系图 · 非天文黄经")
    if system == "taiyi":
        chart = r["chart"]
        cells = sorted(r["nine_palaces"], key=lambda p:(p["row"],p["col"]))
        return view("board", title, {"cells": [{"label": str(p["number"]) + "宫 · " + p["name"],
            "value": p.get("door", ""), "items": [s["name"] + "·" + s["position"] for s in p["stars"]],
            "active": p["name"] == chart.get("positions",{}).get("太乙")} for p in cells], "columns": 3},
            metrics=[metric("局式", chart["bureau"]["文"]), metric("主算", chart["host_count"]), metric("客算", chart["guest_count"])],
            notes=["北在上；宫数采用太乙编号，与洛书编号分开。宫内星将保留原16方位标签。", *notes])
    if system == "lenormand":
        return view("cards", r["spread"]["name"], {"cards": [{"label": c["name"], "id": c["number"], "icon": c["symbol"],
            "position": c["label"], "keywords": c["keywords"], "row": c["row"], "column": c["column"]} for c in r["cards"]],
            "columns": r["spread"]["columns"], "layout": r["spread"]["layout"]}, notes=notes,
            metrics=[metric("牌数", r["spread"]["count"]), metric("布局", r["spread"]["layout"])])
    if system == "geomancy":
        figures = r["shield"]["figures"]
        result = view("shield", title, {"figures": [{"id": f["id"], "name": f["role"] + " · " + f["name"], "points": f["points"],
            "row": f["row"] - 1, "col": f["x"] / 120 - 0.5, "parents": f["derivation"]["parents"]} for f in figures]}, notes=notes,
            metrics=[metric("盾盘", str(len(figures)) + "图"), metric("宫盘方法", r["house_chart"]["mode"])])
        house_view = view("board", "西方土占 · 宫盘", {"cells": [{"label": str(h["house"]) + "宫", "value": h["name"],
            "items": [h["code"], "来自 " + h["source_figure"]], "active": False} for h in r["house_chart"]["houses"]], "columns": 4}, notes=notes)
        result["variants"] = [{"label": "盾盘", "view": copy.deepcopy(result)}, {"label": "十二宫", "view": house_view}]
        result["variant_mode"] = "views"
        return result
    if system in ("yilin", "lingqijing"):
        oracle = r["oracle"]
        data = {"title": oracle.get("title", "林辞" if system == "yilin" else "卦辞"), "text": oracle["text"],
                "source": "《焦氏易林》" if system == "yilin" else "《灵棋经》"}
        if system == "yilin":
            hs = []
            for key,label in (("base", "本卦"),("changed", "之卦")):
                h = r["hexagrams"][key]
                hs.append({"title": label, "name": h.get("name", ""), "number": h.get("number"),
                    "lines": [{"yang": bool(int(b)), "moving": False, "label": str(i+1)} for i,b in enumerate(h["lines_bottom_to_top"])]})
            data["hexagrams"] = hs
        else:
            data["counts"] = r["figure"]["counts"]
        return view("verse", title, data, notes=notes,
                    metrics=[metric("方法", r.get("method", r.get("input",{}).get("method", "")))])
    return view("reference", title, {"text": "请查看本次计算的结构化结果。"}, notes=notes)


def submit_request(reports_dir, request, *, photo_manifest=None):
    from intake_flow import _reports_root, submit
    from intake_autofill import resolve_request
    from output_paths import guard_output
    from project_store import write_new_json
    root=_reports_root(reports_dir)
    autofill=resolve_request(request,cache_dir=guard_output(root/".place-cache"))
    if autofill["questions"]:
        return {"status":"needs_input","job_id":None,"files":[],"questions":autofill["questions"],"warnings":autofill["warnings"]}
    value=submit(root,autofill["request"],photo_manifest=photo_manifest)
    if value.get("status") in ("ready","partial"):
        if autofill["sources"]:
            write_new_json(root/value["job_id"]/"place-resolution.json",{"original_request":request,"sources":autofill["sources"],"warnings":autofill["warnings"]})
        value["warnings"]=[*autofill["warnings"],*value.get("warnings",[])]
    return value


def main():
    try:
        req = json.loads(sys.stdin.read())
        if req.get("operation") == "prepare":
            value = prepare(req["system"])
        elif req.get("operation") == "submit":
            photo_manifest=req.pop("photo_manifest",None)
            value = submit_request(req.pop("reports_dir"), {k:v for k,v in req.items() if k != "operation"},photo_manifest=photo_manifest)
        elif req.get("operation") == "collect":
            if set(req)-{"operation","data_dir","request","photo_session","reserved_job","reservation_owner"} or not {"operation","data_dir","request"}<=set(req):
                raise ValueError("collect 仅接受服务端资料目录与原生请求。")
            from agent_intake import collect_request
            value = collect_request(req["data_dir"],req["request"],photo_session=req.get("photo_session"),reserved_job=req.get("reserved_job"),reservation_owner=req.get("reservation_owner"))
        else:
            value = calculate(req["system"], req.get("params", {}))
        print(json.dumps({"ok": True, "value": value}, ensure_ascii=False, allow_nan=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": {"code": "invalid_input", "message": str(exc)}}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
