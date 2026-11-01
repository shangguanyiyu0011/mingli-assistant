"""Chinese form definitions for the local workbench; no personal defaults."""
from copy import deepcopy

VERSION = "5.2.0"
EXTRA_MODULES = {
    "xiaoliuren": "traditional_casts", "jinkoujue": "traditional_casts", "sukuyo": "traditional_casts",
    "qizheng": "astral_methods", "horary": "astral_methods", "taiyi": "taiyi",
    "yilin": "classic_oracles", "lingqijing": "classic_oracles",
    "lenormand": "oracles", "geomancy": "oracles",
}


def field(key, label, kind="text", **extra):
    return {"key": key, "label": label, "type": kind, **extra}


def select(key, label, values, default=None, **extra):
    options = [{"value": k, "label": v} for k, v in values]
    return field(key, label, "select", options=options, **({"default": default} if default is not None else {}), **extra)


def question():
    return field("question", "本次问题或记录", "textarea", placeholder="可选：记录你希望了解的主题", maxLength=2000)


def seed():
    return field("seed", "复现种子", "number", min=0, max=9007199254740991, help="留空会实际抽样并记录种子；表单限浏览器可精确表示的整数。")


def clock_fields(location=False, birth=False):
    result = [field("date", "出生日期" if birth else "起盘日期", "date", required=True),
              field("time", "出生钟点" if birth else "起盘钟点", "time", required=not birth),
              field("timezone", "时区", default="Asia/Shanghai", required=True,
                    help="使用 IANA 时区，例如 Asia/Shanghai、America/New_York。")]
    if location:
        result += [field("latitude", "纬度（北纬为正）", "number", required=True, min=-89, max=89, step="any"),
                   field("longitude", "经度（东经为正）", "number", required=True, min=-180, max=180, step="any")]
    return result


def item(id_, name, category, summary, fields, example, level="calculation", **extra):
    return {"id": id_, "name": name, "category": category, "summary": summary, "level": level,
            "fields": fields, "example": example, **extra}


def catalog():
    birth = {"date": "1990-05-17", "time": "14:30", "timezone": "Asia/Shanghai"}
    event = {"date": "2026-03-24", "time": "12:30", "timezone": "Asia/Shanghai"}
    geo = {"latitude": 31.23, "longitude": 121.47}
    systems = [
        item("bazi", "八字四柱", "东方术数", "四柱、藏干、十神与干支关系；未知时辰保留候选。",
             clock_fields(birth=True) + [select("calendar", "历法", [("solar", "公历"), ("lunar", "农历")], "solar"),
             field("leap", "农历闰月", "checkbox", show_when={"calendar": ["lunar"]}),
             select("gender", "用于起运的性别", [("", "不提供（不计算性别相关起运）"), ("male", "男"), ("female", "女")], ""),
             select("sect", "换日规则", [(2, "00:00 换日"), (1, "23:00 换日")], 2), question()], birth),
        item("iching", "周易六爻 · 梅花", "东方术数", "本卦、之卦、互卦与动爻；纳甲采用独立起卦时刻。",
             [select("method", "起卦方式", [("coins", "虚拟三钱法"), ("manual", "输入实际六爻"), ("meihua", "梅花数字法")], "coins"),
              field("lines", "六爻（初爻在前）", placeholder="7, 8, 9, 7, 8, 6", show_when={"method": ["manual"]}, required=True),
              field("numbers", "起卦数字", placeholder="两个或三个非负整数", show_when={"method": ["meihua"]}, required=True),
              seed(), field("najia", "显示纳甲、世应、六亲", "checkbox", default=True),
              field("cast_date", "起卦日期（可选）", "date"), field("cast_time", "起卦钟点（可选）", "time"),
              field("cast_timezone", "起卦时区", default="Asia/Shanghai"), question()],
             {"method": "coins", "seed": 42, "najia": True, "cast_date": "2026-03-24", "cast_time": "12:30", "cast_timezone": "Asia/Shanghai"}),
        item("ziwei", "紫微斗数", "东方术数", "十二宫本命盘，支持显式目标日期的流年、流月、流日。",
             clock_fields(birth=True) + [select("gender", "性别", [("", "请选择"), ("male", "男"), ("female", "女")], "", required=True),
              select("scope", "盘面层级", [("origin", "本命"), ("yearly", "流年"), ("monthly", "流月"), ("daily", "流日")], "origin"),
              field("target_date", "目标日期", "date", show_when={"scope": ["yearly", "monthly", "daily"]}, required=True),
              field("target_time", "目标钟点", "time", show_when={"scope": ["yearly", "monthly", "daily"]}, required=True), question()],
             {**birth, "gender": "male", "scope": "origin"}, "external_engine", prepare="ziwei"),
        item("astrology", "西方占星", "星象与历法", "真实星体黄经、上升、宫位与相位；使用明确地点和时区。",
             clock_fields(location=True, birth=True) + [select("house_system", "宫制", [("P", "普拉西德"), ("R", "雷吉奥蒙塔努斯"), ("W", "整宫制"), ("E", "等宫制")], "P"), question()],
             {**birth, **geo, "house_system": "P"}, "external_engine", prepare="astrology"),
        item("vedic", "恒星黄道基础", "星象与历法", "恒星黄道位置与月宿几何结构，保留岁差值选择。",
             clock_fields(location=True, birth=True) + [select("ayanamsa", "岁差值口径", [("lahiri", "Lahiri"), ("raman", "Raman"), ("fagan-bradley", "Fagan–Bradley")], "lahiri"), question()],
             {**birth, **geo, "ayanamsa": "lahiri"}, "sidereal_structure", prepare="astrology"),
        item("names", "姓名五格", "姓名与数字", "明确笔画口径，查看五格、三才和字库中的读音资料。",
             [field("surname", "姓", required=True), field("given", "名", required=True),
              field("strokes", "显式笔画（可选）", placeholder="按姓名顺序，例如 4, 8, 10", help="留空使用已准备的现代 IRG 字库；康熙笔画须独立核对。"),
              select("stroke_scheme", "字库口径", [("unihan-irG", "现代 IRG 笔画"), ("kangxi", "康熙口径（需明确笔画）")], "unihan-irG"), question()],
             {"surname": "王", "given": "明远", "strokes": "4,8,7", "stroke_scheme": "unihan-irG"}, prepare="names"),
        item("numerology", "数秘", "姓名与数字", "生日数字、个人年与明确的主数归约过程。",
             [field("date", "公历生日", "date", required=True), field("year", "目标公历年（可选）", "number", min=1, max=9999),
              select("method", "归约方法", [("all-digits", "全部数字相加"), ("component", "年月日分别归约")], "all-digits"),
              field("latin_name", "拉丁字母姓名（可选）"), question()], {"date": "1990-05-17", "year": 2026}),
        item("tarot", "塔罗", "牌占与符号", "无重复抽牌、正逆位及可复现的牌阵记录。",
             [select("spread", "牌阵", [("three", "三张牌"), ("single", "单张牌"), ("decision", "选择反思五牌"), ("celtic", "凯尔特十字")], "three"),
              seed(), field("upright_only", "仅正位", "checkbox"), question()], {"spread": "three", "seed": 42}, "symbolic_sampling"),
        item("electional", "黄历与择日参考", "星象与历法", "展示传统黄历表项；明确区分表项与个性化择日。",
             [field("date", "起始日期", "date", required=True), field("days", "天数", "number", default=7, min=1, max=31),
              field("topic", "用事项（可选）", placeholder="使用黄历中的准确用词，例如 嫁娶"), question()],
             {"date": "2026-03-24", "days": 7}, "calendar_table_only"),
    ]
    reference_specs = [
        ("palm", "手相观察", "观察与资料", "记录用户可见观察与一般传统术语，不从外貌推断人格、健康或寿命。", "visual_guidance"),
        ("face", "面相术语", "观察与资料", "保留观察记录；自动图像识别和个人命运推断不在本地工具能力内。", "visual_guidance"),
        ("fengshui", "风水空间资料", "观察与资料", "围绕真实平面、朝向与使用条件阅读传统资料。", "reference_only"),
        ("qimen", "奇门遁甲资料", "东方术数", "阅读已有盘及明确起局规则；本版保留资料入口。", "reference_only"),
        ("liuren", "大六壬资料", "东方术数", "阅读用户已有四课三传，与新增小六壬和金口诀分别处理。", "reference_only"),
        ("human_design", "人类图资料", "观察与资料", "阅读已有闸门、通道和计算口径；本版没有完整自动引擎。", "reference_only"),
    ]
    for id_, name, cat, summary, level in reference_specs:
        systems.append(item(id_, name, cat, summary, [field("notes", "已有盘面或观察记录", "textarea"), question()], {"notes": "示例：在这里记录已知条件与待核对的问题。"}, level))
    systems.extend([
        item("xiaoliuren", "小六壬", "东方术数", "月日时或报数起课，逐步展示六宫落点。", [], {}, is_new=True),
        item("jinkoujue", "六壬金口诀", "东方术数", "展示人元、贵神、将神、地分四位与传统结构关系。", [], {}, is_new=True),
        item("qizheng", "七政四余", "星象与历法", "七政实体与四余计算点分层展示；明确实际星历与传统约定。",
             clock_fields(location=True) + [select("node_model", "罗计交点口径", [("mean", "平均交点"), ("true", "真交点")], "mean"), question()],
             {**event, **geo}, "external_engine", prepare="astrology", is_new=True),
        item("taiyi", "太乙神数", "东方术数", "真实年、月、日、时局，显示局式、主客算与宫位星将。",
             [field("date", "起局日期（中国历日）", "date", required=True), field("time", "起局钟点（UTC+08）", "time", required=True),
              select("mode", "起局层级", [("year", "年局"), ("month", "月局"), ("day", "日局"), ("hour", "时局")], "hour"),
              select("method", "积年方法", [(0, "太乙统宗"), (1, "太乙金镜"), (2, "太乙淘金歌"), (3, "太乙局")], 1), question()],
             {"date": "2026-03-24", "time": "12:30", "mode": "hour", "method": 1}, "external_engine", prepare="taiyi", is_new=True),
        item("sukuyo", "宿曜", "星象与历法", "采用独立月日宿表，查看本命宿、值日宿与关系。", [], {}, is_new=True),
        item("yilin", "焦氏易林", "东方术数", "本卦、之卦对应林辞，原文与选择过程一起保留。", [], {}, is_new=True),
        item("lingqijing", "灵棋经", "东方术数", "真实模拟十二棋正反，匹配上中下棋形与原典。", [], {}, is_new=True),
        item("lenormand", "雷诺曼牌", "牌占与符号", "双牌、三牌、九宫格与大桌阵；保留组合顺序与牌位。",
             [select("spread", "牌阵", [("pair", "双牌"), ("three", "三张牌"), ("nine", "九宫格"), ("grand", "大桌阵 · 36张")], "nine"),
              select("layout", "大桌阵布局", [("9x4", "9 × 4"), ("8x4+4", "8 × 4 + 4")], "9x4", show_when={"spread": ["grand"]}),
              field("cards", "手动牌序（可选）", placeholder="1–36 的牌号，逗号分隔；填写时不使用种子"), seed(), question()],
             {"spread": "nine", "seed": 42}, "symbolic_sampling", is_new=True),
        item("geomancy", "西方土占", "牌占与符号", "四母、四女、四侄、证人、法官与调和图，显示推导关系。",
             [field("mothers", "手动四母（可选）", "textarea", placeholder="例如 1111 2222 1212 2121；火风水土从上到下，1单点2双点"), seed(),
              select("shield_size", "盾盘图数", [(16, "16图（含调和图）"), (15, "15图")], 16),
              select("house_mode", "宫盘方法", [("sequential", "顺序排宫"), ("agrippa", "Agrippa 排宫")], "sequential"), question()],
             {"seed": 42, "shield_size": 16, "house_mode": "sequential"}, "symbolic_sampling", is_new=True),
        item("horary", "卜卦占星", "星象与历法", "按提问时空排盘，展示七曜尊贵、相位和入相出相结构。",
             clock_fields(location=True) + [select("house_system", "宫制", [("R", "雷吉奥蒙塔努斯"), ("P", "普拉西德"), ("W", "整宫制")], "R"), question()],
             {**event, **geo, "house_system": "R"}, "external_engine", prepare="astrology", is_new=True),
    ])
    extra_forms(systems)
    return {"version": VERSION, "systems": deepcopy(systems)}


def extra_forms(systems):
    indexed = {s["id"]: s for s in systems}
    branches = [(b, b) for b in "子丑寅卯辰巳午未申酉戌亥"]
    def scoped(fields, key, values):
        return [{**f, "show_when": {key: values}} for f in fields]
    indexed["xiaoliuren"].update(fields=[
        select("mode", "起课方式", [("numbers", "报数"), ("lunar", "农历月日时")], "numbers"),
        field("numbers", "三个正整数", required=True, placeholder="例如 3, 5, 7", show_when={"mode": ["numbers"]}),
        field("lunar_month", "农历月", "number", min=1, max=12, required=True, show_when={"mode": ["lunar"]}),
        field("lunar_day", "农历日", "number", min=1, max=30, required=True, show_when={"mode": ["lunar"]}),
        select("hour_branch", "时支", branches, "子", show_when={"mode": ["lunar"]}),
        field("leap", "闰月（同编号月起数）", "checkbox", show_when={"mode": ["lunar"]}), question()],
        example={"mode": "numbers", "numbers": "3,5,7"})
    indexed["jinkoujue"].update(fields=[
        select("mode", "起课方式", [("datetime", "按日期钟点"), ("manual", "显式输入日时月将")], "datetime"),
        select("earth_branch", "地分", branches, "午"),
        *scoped(clock_fields(), "mode", ["datetime"]),
        field("day_pillar", "日柱（六十甲子）", required=True, placeholder="例如 丁卯", show_when={"mode": ["manual"]}),
        select("hour_branch", "时支", branches, "未", show_when={"mode": ["manual"]}),
        select("month_general_branch", "月将", branches, "卯", show_when={"mode": ["manual"]}),
        select("month_general_rule", "换将规则", [("solar_qi", "中气换将"), ("month_branch_he", "节月月支六合")], "solar_qi", show_when={"mode": ["datetime"]}),
        select("day_night_rule", "昼夜起贵规则", [("si_xu_day", "巳至戌为昼"), ("mao_shen_day", "卯至申为昼")], "si_xu_day"), question()],
        example={"mode": "manual", "day_pillar": "丁卯", "hour_branch": "未", "earth_branch": "午", "month_general_branch": "卯", "day_night_rule": "si_xu_day"})
    indexed["sukuyo"].update(fields=[
        select("input_calendar", "输入历法", [("solar", "公历日期转中国农历"), ("lunar", "明确农历月日")], "solar"),
        field("birth_date", "出生公历日期", "date", required=True, show_when={"input_calendar": ["solar"]}),
        field("target_date", "值日公历日期（可选）", "date", show_when={"input_calendar": ["solar"]}),
        field("partner_date", "对方公历日期（可选）", "date", show_when={"input_calendar": ["solar"]}),
        field("birth_month", "本命农历月", "number", min=1, max=12, required=True, show_when={"input_calendar": ["lunar"]}),
        field("birth_day", "本命农历日", "number", min=1, max=30, required=True, show_when={"input_calendar": ["lunar"]}),
        field("birth_leap", "本命闰月（同编号月）", "checkbox", show_when={"input_calendar": ["lunar"]}),
        field("target_month", "值日农历月（可选）", "number", min=1, max=12, show_when={"input_calendar": ["lunar"]}),
        field("target_day", "值日农历日（可选）", "number", min=1, max=30, show_when={"input_calendar": ["lunar"]}),
        field("partner_month", "对方农历月（可选）", "number", min=1, max=12, show_when={"input_calendar": ["lunar"]}),
        field("partner_day", "对方农历日（可选）", "number", min=1, max=30, show_when={"input_calendar": ["lunar"]}), question()],
        example={"input_calendar": "lunar", "birth_month": 2, "birth_day": 17, "target_month": 2, "target_day": 15})
    indexed["yilin"].update(fields=[
        select("method", "取辞方式", [("pair", "指定本卦、之卦"), ("coins", "虚拟三钱起卦"), ("lines", "输入实际六爻")], "pair"),
        field("base", "本卦序号（文王卦序）", "number", min=1, max=64, required=True, show_when={"method": ["pair"]}),
        field("changed", "之卦序号（文王卦序）", "number", min=1, max=64, required=True, show_when={"method": ["pair"]}),
        field("lines", "六爻（初爻在前）", required=True, placeholder="7,8,9,7,8,6", show_when={"method": ["lines"]}),
        {**seed(), "show_when": {"method": ["coins"]}}, question()], example={"method": "pair", "base": 1, "changed": 2})
    indexed["lingqijing"].update(fields=[
        select("method", "取式方式", [("counts", "输入上中下正面数"), ("toss", "虚拟投掷十二棋"), ("pieces", "输入十二棋实际正反")], "counts"),
        field("counts", "上、中、下正面棋数", required=True, placeholder="例如 1,1,1；各为0–4", show_when={"method": ["counts"]}),
        *[field(k, label + "四棋正反", required=True, placeholder="例如 1,0,1,0；1正面0反面", show_when={"method": ["pieces"]}) for k,label in (("upper", "上组"), ("middle", "中组"), ("lower", "下组"))],
        {**seed(), "show_when": {"method": ["toss"]}}, question()], example={"method": "counts", "counts": "1,1,1"})
    for id_ in ("lenormand", "geomancy"):
        fs = indexed[id_]["fields"]
        manual = "cards" if id_ == "lenormand" else "mothers"
        fs.insert(0, select("input_mode", "输入方式", [("random", "虚拟抽样"), ("manual", "实际牌序" if id_ == "lenormand" else "手动四母")], "random"))
        for f in fs:
            if f["key"] == manual:
                f.update(required=True, show_when={"input_mode": ["manual"]})
            elif f["key"] == "seed":
                f["show_when"] = {"input_mode": ["random"]}
        indexed[id_]["example"]["input_mode"] = "random"
    fs = indexed["qizheng"]["fields"]
    fs[-1:-1] = [
        select("node_orientation", "罗睺对应交点", [("ascending", "升交点"), ("descending", "降交点")], "ascending"),
        select("ziqi_model", "紫气模型", [("not_calculated", "未校准（不绘紫气）"), ("mean_cycle", "明确均速参考模型")], "not_calculated"),
        field("ziqi_epoch_utc", "紫气参考历元（UTC）", required=True, placeholder="2000-01-01T12:00:00Z", show_when={"ziqi_model": ["mean_cycle"]}),
        field("ziqi_epoch_longitude", "参考黄经（度）", "number", required=True, min=0, max=360, step="any", show_when={"ziqi_model": ["mean_cycle"]}),
        field("ziqi_period_days", "均速周期（天）", "number", required=True, min=1, step="any", show_when={"ziqi_model": ["mean_cycle"]}),
        field("ziqi_reference_label", "模型依据", required=True, placeholder="注明历表/版本；演示模型请明确标注", show_when={"ziqi_model": ["mean_cycle"]})]
    indexed["horary"]["fields"].insert(-1, field("quesited_house", "所问宫位（可选）", "number", min=1, max=12))
    indexed["horary"]["fields"][-1]["required"] = True
    indexed["horary"]["example"]["question"] = "这次沟通有哪些需要核实的信息？"
