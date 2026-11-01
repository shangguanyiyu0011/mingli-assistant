"""Offline structural calculators for three traditional calendrical methods."""
import argparse
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
JIAZI = tuple(STEMS[i % 10] + BRANCHES[i % 12] for i in range(60))
BRANCH_ELEMENTS = dict(zip(BRANCHES, "水土木木土火火土金金土水"))
STEM_ELEMENTS = dict(zip(STEMS, "木木火火土土金金水水"))
GENERATES = dict(zip("木火土金水", "火土金水木"))
CONTROLS = dict(zip("木火土金水", "土金水木火"))
CHINA = timezone(timedelta(hours=8))
PALACE_NAMES = ("大安", "留连", "速喜", "赤口", "小吉", "空亡")
PALACE_ELEMENTS = ("木", "土", "火", "金", "水", "土")
PALACE_THEMES = ("安定与保持", "停留与反复", "消息与进展", "表达与分歧", "协作与小步", "未定与留白")
GENERAL_NAMES = ("神后", "大吉", "功曹", "太冲", "天罡", "太乙", "胜光", "小吉", "传送", "从魁", "河魁", "登明")
NOBLES = (("贵人", "丑"), ("螣蛇", "巳"), ("朱雀", "午"), ("六合", "卯"),
          ("勾陈", "辰"), ("青龙", "寅"), ("天空", "戌"), ("白虎", "申"),
          ("太常", "未"), ("玄武", "子"), ("太阴", "酉"), ("天后", "亥"))
NOBLE_ANCHORS = {"甲": ("丑", "未"), "戊": ("丑", "未"), "庚": ("丑", "未"),
                 "乙": ("子", "申"), "己": ("子", "申"), "丙": ("亥", "酉"), "丁": ("亥", "酉"),
                 "壬": ("巳", "卯"), "癸": ("巳", "卯"), "辛": ("午", "寅")}
MONTH_HE = dict(zip(BRANCHES, "子丑寅卯辰巳午未申酉戌亥"))
for _pair in ("子丑", "寅亥", "卯戌", "辰酉", "巳申", "午未"):
    MONTH_HE[_pair[0]], MONTH_HE[_pair[1]] = _pair[1], _pair[0]
QI_GENERALS = dict(zip(("冬至", "大寒", "雨水", "春分", "谷雨", "小满", "夏至", "大暑", "处暑", "秋分", "霜降", "小雪"),
                      "丑子亥戌酉申未午巳辰卯寅"))
# A lunar-month/day table, independent of longitude-based lunar mansions.
MANSIONS = tuple("角亢氐房心尾箕斗女虚危室壁奎娄胃昴毕觜参井鬼柳星张翼轸")
MONTH_FULL_MOON = tuple("翼角氐心箕女室娄昴觜鬼星")
RELATION_NINE = ("命", "荣", "衰", "安", "危", "成", "坏", "友", "亲")
DEFAULT_PARAMS = {
    "xiaoliuren": {"mode": "numbers", "numbers": [3, 5, 7]},
    "jinkoujue": {"mode": "manual", "day_pillar": "丁卯", "hour_branch": "未", "earth_branch": "午",
                   "month_general_branch": "卯", "day_night_rule": "si_xu_day"},
    "sukuyo": {"birth": {"calendar": "lunar", "month": 2, "day": 17},
                "target": {"calendar": "lunar", "month": 2, "day": 15}, "leap_rule": "same_numbered_month"},
}
COMMON_LIMIT = "传统文化结构计算不提供现实事件的科学预测概率，不用于疾病、死亡、投资或婚姻结果保证。"


def _keys(value, allowed):
    if not isinstance(value, dict):
        raise ValueError("params及日期输入必须是JSON对象")
    unknown = set(value) - set(allowed)
    if unknown:
        raise ValueError("不支持的参数：" + ", ".join(sorted(unknown)))


def _integer(value, label, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label} 必须是 {low}..{high} 的整数")
    return value


def _branch(value, label):
    if not isinstance(value, str) or len(value) != 1 or value not in BRANCHES:
        raise ValueError(label + " 必须是单个十二地支")
    return value


def _element_relation(source, target):
    if source == target:
        return "same_element"
    if GENERATES[source] == target:
        return "source_generates_target"
    if GENERATES[target] == source:
        return "target_generates_source"
    return "source_controls_target" if CONTROLS[source] == target else "target_controls_source"


def _result(system, params, rules, limitations):
    return {"schema_version": 1, "system": system, "status": "calculated", "input": deepcopy(params),
            "rules": rules, "limitations": [*limitations, COMMON_LIMIT]}


def _palaces():
    return [{"id": "palace-" + str(i + 1), "index": i, "number": i + 1, "name": name,
             "element": PALACE_ELEMENTS[i], "cultural_theme": PALACE_THEMES[i],
             "row": (1, 0, 0, 0, 1, 1)[i], "column": (0, 0, 1, 2, 2, 1)[i]}
            for i, name in enumerate(PALACE_NAMES)]


def _xiaoliuren(params):
    _keys(params, {"mode", "numbers", "lunar_month", "lunar_day", "hour_branch", "leap", "leap_rule"})
    mode = params.get("mode", "numbers")
    if mode == "numbers":
        if any(key in params for key in ("lunar_month", "lunar_day", "hour_branch", "leap", "leap_rule")):
            raise ValueError("报数法不能混入农历月日时参数")
        nums = params.get("numbers")
        if not isinstance(nums, list) or len(nums) != 3:
            raise ValueError("numbers 必须是三个正整数")
        nums = [_integer(n, "报数", 1, 1_000_000_000) for n in nums]
        labels = ("第一数", "第二数", "第三数")
    elif mode == "lunar":
        if "numbers" in params:
            raise ValueError("月日时法不能混入numbers")
        month = _integer(params.get("lunar_month"), "农历月份", 1, 12)
        day = _integer(params.get("lunar_day"), "农历日期", 1, 30)
        hour = _branch(params.get("hour_branch"), "hour_branch")
        if type(params.get("leap", False)) is not bool:
            raise ValueError("leap 必须是布尔值")
        if params.get("leap_rule", "same_numbered_month") != "same_numbered_month":
            raise ValueError("本模块仅支持显式记录的闰月同编号月起数约定")
        nums, labels = [month, day, BRANCHES.index(hour) + 1], ("月", "日", "时")
    else:
        raise ValueError("小六壬mode须为numbers或lunar")
    palaces, current, steps = _palaces(), 0, []
    for label, count in zip(labels, nums):
        start = current
        current = (start + count - 1) % 6
        steps.append({"label": label, "count": count, "start_index": start, "end_index": current,
                      "start_palace": PALACE_NAMES[start], "end_palace": PALACE_NAMES[current],
                      "formula": f"({start}+{count}-1) mod 6 = {current}",
                      "full_cycles": (count - 1) // 6, "forward_steps_after_start": (count - 1) % 6,
                      "path_preview_indices": [(start + k) % 6 for k in range(min(count, 12))],
                      "preview_truncated": count > 12})
    result = _result("xiaoliuren", params, [
        {"id": "six_palace_order", "description": "大安、留连、速喜、赤口、小吉、空亡六宫顺行，当前宫计1，逐阶段接着起数。"},
        {"id": "sequential_inclusive", "formula": "next=(current+count-1) mod 6；第一次从大安索引0开始"},
        {"id": "calendar", "description": "月日时为农历月/农历日/子1至亥12；闰月同编号起数。报数取三个正整数，不将0悄悄替换成其他数。"},
        {"id": "elements", "description": "选定六宫五行为木、土、火、金、水、土；保留流派差异，不说成唯一表。"}],
        ["仅实现六宫递数与步骤；未实现道门九宫、活六神、综合断语或应期。",
         "手工月日未指定农历年份，不验证某年该月是否存在三十日；不自动使用当前时辰。"])
    result.update({"mode": mode, "numbers_used": nums, "palaces": palaces, "steps": steps,
                   "three_positions": [{"stage": i + 1, "label": labels[i], "palace": palaces[s["end_index"]]}
                                       for i, s in enumerate(steps)],
                   "final_palace": deepcopy(palaces[current]), "summary": " → ".join(s["end_palace"] for s in steps),
                   "visualization": {"kind": "six_palaces", "nodes": deepcopy(palaces),
                                     "cycle_edges": [[i, (i + 1) % 6] for i in range(6)],
                                     "steps": deepcopy(steps), "selected_index": current}})
    return result


def _calendar_api():
    scripts = str(Path(__file__).resolve().parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import chart
    if not Path(chart.__file__).resolve().is_relative_to(Path(scripts)):
        raise ValueError("历法模块来自另一安装目录，请使用新Python进程")
    return chart


def _zi_stem(day_stem, branch):
    return STEMS[((STEMS.index(day_stem) % 5) * 2 + BRANCHES.index(branch)) % 10]


def _month_general_at(utc_text):
    chart = _calendar_api()
    lib = chart.calendar_library()
    instant = datetime.fromisoformat(utc_text)
    if instant.tzinfo is None:
        raise ValueError("中气比较必须使用明确UTC偏移的真实瞬间")
    instant = instant.astimezone(CHINA)
    lunar = lib.Solar.fromYmdHms(instant.year, instant.month, instant.day,
                                instant.hour, instant.minute, instant.second).getLunar()
    qi = lunar.getPrevQi(False)
    name = qi.getName()
    if name not in QI_GENERALS:
        raise ValueError("离线中气名称不在已核对月将表中：" + name)
    return QI_GENERALS[name], {"rule": "solar_qi", "previous_qi": name,
                               "qi_china_clock": qi.getSolar().toYmdHms(), "comparison_clock": instant.isoformat()}


def _four_positions(day_pillar, hour_branch, earth_branch, month_general, day_night_rule, day_night="auto"):
    if day_pillar not in JIAZI:
        raise ValueError("day_pillar 须是合法六十甲子日柱")
    hour = BRANCHES.index(_branch(hour_branch, "hour_branch"))
    earth = BRANCHES.index(_branch(earth_branch, "earth_branch"))
    general = BRANCHES.index(_branch(month_general, "month_general_branch"))
    if day_night_rule not in ("si_xu_day", "mao_shen_day"):
        raise ValueError("day_night_rule 须为si_xu_day或mao_shen_day")
    if day_night not in ("auto", "day", "night"):
        raise ValueError("day_night 须为auto/day/night")
    day_branches = "巳午未申酉戌" if day_night_rule == "si_xu_day" else "卯辰巳午未申"
    is_day = hour_branch in day_branches if day_night == "auto" else day_night == "day"
    anchor_branch = NOBLE_ANCHORS[day_pillar[0]][0 if is_day else 1]
    anchor = BRANCHES.index(anchor_branch)
    direction = 1 if anchor_branch in "亥子丑寅卯辰" else -1
    general_plate, noble_plate = [], []
    for index, branch in enumerate(BRANCHES):
        jiang = (general + index - hour) % 12
        noble_index = ((index - anchor) * direction) % 12
        noble_name, noble_branch = NOBLES[noble_index]
        general_plate.append({"earth_branch": branch, "general_branch": BRANCHES[jiang],
                              "general_name": GENERAL_NAMES[jiang], "selected": index == earth})
        noble_plate.append({"earth_branch": branch, "noble_name": noble_name, "noble_branch": noble_branch,
                            "noble_index": noble_index, "selected": index == earth})
    selected_general, selected_noble = general_plate[earth], noble_plate[earth]
    jiang_branch, noble_branch = selected_general["general_branch"], selected_noble["noble_branch"]
    human = _zi_stem(day_pillar[0], earth_branch)
    rows = [
        {"id": "human", "label": "人元", "stem": human, "element": STEM_ELEMENTS[human]},
        {"id": "noble", "label": "贵神", "name": selected_noble["noble_name"], "branch": noble_branch,
         "dun_stem": _zi_stem(day_pillar[0], noble_branch), "element": BRANCH_ELEMENTS[noble_branch]},
        {"id": "general", "label": "将神", "name": selected_general["general_name"], "branch": jiang_branch,
         "dun_stem": _zi_stem(day_pillar[0], jiang_branch), "element": BRANCH_ELEMENTS[jiang_branch]},
        {"id": "earth", "label": "地分", "branch": earth_branch, "element": BRANCH_ELEMENTS[earth_branch]},
    ]
    relations = [{"source": a["id"], "target": b["id"], "source_element": a["element"], "target_element": b["element"],
                  "relation": _element_relation(a["element"], b["element"])}
                 for i, a in enumerate(rows) for b in rows[i + 1:]]
    steps = [
        {"id": "general_rotation", "description": "月将加占时，地盘顺数至地分", "month_general": month_general,
         "hour_branch": hour_branch, "earth_branch": earth_branch, "formula": f"({general}+{earth}-{hour}) mod 12",
         "result_branch": jiang_branch},
        {"id": "noble_anchor", "day_stem": day_pillar[0], "day_night": "day" if is_day else "night",
         "day_night_rule": day_night_rule, "day_branches": day_branches, "day_night_override": day_night,
         "anchor_branch": anchor_branch, "direction": "forward" if direction == 1 else "reverse",
         "direction_rule": "贵人起点在亥子丑寅卯辰顺排，在巳午未申酉戌逆排；不把所有昼占都当顺排。",
         "result": selected_noble["noble_name"]},
        {"id": "five_rat_dun", "description": "五子元遁，甲己甲子、乙庚丙子、丙辛戊子、丁壬庚子、戊癸壬子",
         "zi_stem": _zi_stem(day_pillar[0], "子"), "human_stem": human,
         "note": "贵神/将神的dun_stem是该日遁干，与神将本体的固定干支称谓分开。"},
    ]
    return {"day_pillar": day_pillar, "hour_branch": hour_branch, "earth_branch": earth_branch,
            "month_general_branch": month_general, "four_positions": rows,
            "general_plate": general_plate, "noble_plate": noble_plate, "relations": relations, "steps": steps,
            "visualization": {"kind": "four_positions", "rows": deepcopy(rows), "general_ring": deepcopy(general_plate),
                              "noble_ring": deepcopy(noble_plate), "earth_order": list(BRANCHES), "selected_earth_index": earth}}


def _jinkoujue(params):
    _keys(params, {"mode", "day_pillar", "hour_branch", "earth_branch", "month_general_branch", "date", "time", "timezone",
                  "sect", "fold", "month_general_rule", "day_night_rule", "day_night"})
    mode = params.get("mode", "manual")
    earth = _branch(params.get("earth_branch"), "earth_branch")
    day_night_rule, day_night = params.get("day_night_rule", "si_xu_day"), params.get("day_night", "auto")
    result = _result("jinkoujue", params, [
        {"id": "four_positions", "description": "自上而下：人元、贵神、将神、地分；地分须用户先定，不从问题文本猜测。"},
        {"id": "month_general", "description": "手工月将显式输入；时间法可选solar_qi中气换将，或month_branch_he节界月支六合取将。"},
        {"id": "noble", "description": "采用甲戊庚丑未、乙己子申、丙丁亥酉、壬癸巳卯、辛午寅的昼夜表；起点落支定顺逆。"},
        {"id": "day_night", "description": "默认si_xu_day：巳至戌为昼；可明确改mao_shen_day：卯至申为昼，或手工day/night。不是天文日出日落。"}],
        ["只完成选定规则的四位起课与结构生克，不是完整大六壬四课三传或金口诀综合断法。",
         "贵神表、昼夜划分、月将换法存在流派差异；此处保留所选规则，不自动混用。"])
    boards, alternatives = [], []
    if mode == "manual":
        if any(k in params for k in ("date", "time", "timezone", "sect", "fold")):
            raise ValueError("手工四位模式不能混入时间参数")
        if params.get("month_general_rule", "explicit") != "explicit":
            raise ValueError("手工模式month_general_rule只能为explicit")
        board = _four_positions(params.get("day_pillar"), params.get("hour_branch"), earth,
                                params.get("month_general_branch"), day_night_rule, day_night)
        board.update({"candidate_id": "selected-1", "calendar_verified": False,
                      "month_general_source": {"rule": "explicit", "note": "手工输入月将，未校验是否对应某个实际日期"}})
        boards = [board]
    elif mode == "datetime":
        if any(k in params for k in ("day_pillar", "hour_branch", "month_general_branch")):
            raise ValueError("时间四位模式不能以手工日时或月将覆盖历法")
        if not all(params.get(k) for k in ("date", "time", "timezone")):
            raise ValueError("时间起课须明确date、time、IANA timezone；不借用出生时间或当前时间")
        rule = params.get("month_general_rule", "solar_qi")
        if rule not in ("solar_qi", "month_branch_he"):
            raise ValueError("month_general_rule须为solar_qi或month_branch_he")
        chart = _calendar_api().build_chart(params["date"], params["time"], timezone=params["timezone"],
                                            sect=params.get("sect", 2), fold=params.get("fold"))
        def build_candidates(candidates, prefix):
            grouped = {}
            for item in candidates:
                for interval in item["time_ranges"]:
                    p = item["pillars"]
                    if rule == "solar_qi":
                        month_general, source = _month_general_at(interval["start_utc"])
                    else:
                        month_general = MONTH_HE[p["month"][1]]
                        source = {"rule": rule, "month_pillar": p["month"], "description": "节界月支六合取月将"}
                    key = (item["sect"], p["day"], p["hour"][1], month_general)
                    if key not in grouped:
                        board = _four_positions(p["day"], p["hour"][1], earth, month_general, day_night_rule, day_night)
                        board.update({"candidate_id": prefix + "-" + str(len(grouped) + 1), "calendar_verified": True,
                                      "sect": item["sect"], "month_general_source": source, "valid_time_ranges": []})
                        grouped[key] = board
                    grouped[key]["valid_time_ranges"].append(deepcopy(interval))
            return list(grouped.values())
        boards = build_candidates(chart["candidates"], "selected")
        alternatives = build_candidates(chart["convention_alternatives"], "alternative")
        result["calendar_context"] = {k: deepcopy(chart[k]) for k in ("input", "time_context", "time_precision", "uncertainty", "convention")}
    else:
        raise ValueError("金口诀mode须为manual或datetime")
    result.update({"mode": mode, "candidates": boards, "convention_alternatives": alternatives,
                   "status": "calculated_with_candidates" if len(boards) > 1 else "calculated",
                   "summary": "；".join(" / ".join(r["label"] + (r.get("stem") or r.get("name", "") + r.get("branch", ""))
                                                       for r in b["four_positions"]) for b in boards)})
    if len(boards) == 1:
        result["four_positions"] = deepcopy(boards[0]["four_positions"])
        result["visualization"] = deepcopy(boards[0]["visualization"])
    else:
        result["visualization"] = {"kind": "candidate_boards", "candidate_ids": [b["candidate_id"] for b in boards]}
    return result


def _lunar_input(value, label):
    _keys(value, {"calendar", "date", "year", "month", "day", "leap"})
    calendar = value.get("calendar", "lunar")
    if calendar == "solar":
        if any(k in value for k in ("year", "month", "day", "leap")):
            raise ValueError(label + "公历输入只能给date")
        raw = value.get("date")
        if not isinstance(raw, str) or len(raw) != 10:
            raise ValueError(label + "公历日期须为YYYY-MM-DD")
        parsed = date.fromisoformat(raw)
        if parsed.isoformat() != raw or not 1583 <= parsed.year <= 9998:
            raise ValueError(label + "日期范围须为1583—9998年且格式固定")
        lib = _calendar_api().calendar_library()
        lunar = lib.Solar.fromYmd(parsed.year, parsed.month, parsed.day).getLunar()
        signed_month = lunar.getMonth()
        return {"year": lunar.getYear(), "month": abs(signed_month), "day": lunar.getDay(), "leap": signed_month < 0,
                "calendar_basis": "公历日按固定UTC+08中国农历换算，不宣称日本天保历或现代天文月宿", "date_verified": True}
    if calendar != "lunar" or "date" in value:
        raise ValueError(label + "calendar须为lunar或solar，农历不能混date")
    month = _integer(value.get("month"), label + "农历月", 1, 12)
    day = _integer(value.get("day"), label + "农历日", 1, 30)
    leap = value.get("leap", False)
    if type(leap) is not bool:
        raise ValueError("leap必须是布尔值")
    year = value.get("year")
    if year is not None:
        year = _integer(year, label + "农历年", 1583, 9998)
        lib = _calendar_api().calendar_library()
        actual = lib.LunarYear.fromYear(year).getMonth(-month if leap else month)
        if actual is None or actual.getYear() != year or day > actual.getDayCount():
            raise ValueError(label + "农历年月日或闰月在该年不存在")
    return {"year": year, "month": month, "day": day, "leap": leap,
            "calendar_basis": "明确输入的农历月日；未给年份时只按月日表计算", "date_verified": year is not None}


def _mansion(lunar):
    anchor = MONTH_FULL_MOON[lunar["month"] - 1]
    index = (MANSIONS.index(anchor) + lunar["day"] - 15) % 27
    return {"id": "mansion-" + str(index + 1), "index": index, "name": MANSIONS[index],
            "label": MANSIONS[index] + "宿", "lunar": deepcopy(lunar),
            "steps": {"month": lunar["month"], "full_moon_anchor": anchor,
                      "day_offset_from_15": lunar["day"] - 15,
                      "formula": f"({MANSIONS.index(anchor)}+{lunar['day']}-15) mod 27 = {index}"}}


def _relation_label(offset):
    return "业" if offset == 9 else "胎" if offset == 18 else RELATION_NINE[offset % 9]


def _mansion_relation(source, target):
    offset = (target["index"] - source["index"]) % 27
    reverse = (-offset) % 27
    a, b = _relation_label(offset), _relation_label(reverse)
    if offset == 0:
        family = "命"
    elif offset in (9, 18):
        family = "业胎"
    else:
        family = next(name for name in ("荣亲", "友衰", "安坏", "危成") if set(name) == {a, b})
    return {"source_id": source["id"], "target_id": target["id"], "forward_steps": offset,
            "reverse_steps": reverse, "source_to_target": a, "target_to_source": b,
            "family": family, "nine_group": offset // 9 + 1,
            "reading": f"从{source['label']}顺数，{target['label']}属{a}；反向属{b}，关系组为{family}。",
            "scope": "三九分类的有向位置关系，不换算相处概率，不把坏、危等术语解释为现实伤害或必然事件。"}


def _sukuyo(params):
    _keys(params, {"birth", "target", "partner", "leap_rule"})
    if params.get("leap_rule", "same_numbered_month") != "same_numbered_month":
        raise ValueError("本模块闰月采用明确的same_numbered_month约定，不自动套其他流派")
    if "birth" not in params:
        raise ValueError("宿曜需要birth月日对象")
    birth = _mansion(_lunar_input(params["birth"], "本命"))
    target = _mansion(_lunar_input(params["target"], "值日")) if "target" in params else None
    partner = _mansion(_lunar_input(params["partner"], "对方")) if "partner" in params else None
    table = [{"month": month, "first_day_mansion": MANSIONS[(MANSIONS.index(anchor) - 14) % 27],
              "fifteenth_day_mansion": anchor} for month, anchor in enumerate(MONTH_FULL_MOON, 1)]
    nodes = [{"id": "mansion-" + str(i + 1), "index": i, "name": name, "label": name + "宿",
              "relation_from_birth": _relation_label((i - birth["index"]) % 27),
              "is_birth": i == birth["index"], "is_daily": target is not None and i == target["index"],
              "is_partner": partner is not None and i == partner["index"]} for i, name in enumerate(MANSIONS)]
    result = _result("sukuyo", params, [
        {"id": "month_day_table", "description": "采用十二月十五日望宿表，正月翼、二月角……从十五日按日期差逆顺数；27宿不含牛。",
         "formula": "mansion_index=(month_full_moon_index+lunar_day-15) mod 27"},
        {"id": "three_nines", "description": "从本命顺数：命荣衰安危成坏友亲；第二组首为业，第三组首为胎。关系方向分别记录。"},
        {"id": "leap", "description": "闰月按同编号月表；这是本模块明确采用的约定，不称为原经明定闰法。"},
        {"id": "calendar", "description": "公历输入复用离线中国农历换算；本算法不计算月球黄经，不调用吠陀27宿。"}],
        ["本命宿与值日宿是月日表结果，不是当日月球实际黄经所在星宿。",
         "中国农历与日本旧历可能在日界或置闰上不同；此模块明确为中国农历换算版。",
         "未给农历年份时不验证当年该月是否有三十日；闰月口径存在差异。"])
    result.update({"birth_mansion": birth, "daily_mansion": target, "partner_mansion": partner,
                   "daily_relation": _mansion_relation(birth, target) if target else None,
                   "partner_relation": _mansion_relation(birth, partner) if partner else None,
                   "month_table": table,
                   "summary": "本命" + birth["label"] + ("，值日" + target["label"] if target else ""),
                   "visualization": {"kind": "mansion_wheel", "nodes": nodes, "month_table": deepcopy(table),
                                     "birth_index": birth["index"], "daily_index": target["index"] if target else None,
                                     "partner_index": partner["index"] if partner else None}})
    return result


def calculate(system, params):
    if not isinstance(system, str) or system not in DEFAULT_PARAMS:
        raise ValueError("system须为xiaoliuren、jinkoujue或sukuyo")
    if not isinstance(params, dict):
        raise ValueError("params须为JSON对象")
    return {"xiaoliuren": _xiaoliuren, "jinkoujue": _jinkoujue, "sukuyo": _sukuyo}[system](deepcopy(params))


def _invalid_constant(value):
    raise ValueError("JSON不接受NaN或Infinity")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON含重复参数：" + key)
        result[key] = value
    return result


class JsonParser(argparse.ArgumentParser):
    def error(self, message):
        print(json.dumps({"system": "traditional_casts", "status": "error", "input": {}, "rules": [],
                          "limitations": [], "error": {"code": "invalid_input", "message": message}}, ensure_ascii=False))
        raise SystemExit(2)


def main(argv=None):
    parser = JsonParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("system", nargs="?", choices=tuple(DEFAULT_PARAMS))
    parser.add_argument("--params", help="显式JSON参数对象；默认样例见--probe，不自动使用当前时间")
    parser.add_argument("--probe", action="store_true", help="报告三个离线模块及默认样例")
    args = parser.parse_args(argv)
    try:
        if args.probe:
            if args.params is not None:
                raise ValueError("--probe不能与--params合用")
            result = {"system": "traditional_casts", "status": "available", "input": {}, "rules": [], "limitations": [],
                      "systems": {s: {"status": "available", "default_params": deepcopy(DEFAULT_PARAMS[s])}
                                  for s in ([args.system] if args.system else DEFAULT_PARAMS)}}
        else:
            if args.system is None or args.params is None:
                raise ValueError("实际计算需要SYSTEM --params JSON，不自动代入默认样例")
            params = json.loads(args.params, parse_constant=_invalid_constant, object_pairs_hook=_unique_object)
            result = calculate(args.system, params)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
