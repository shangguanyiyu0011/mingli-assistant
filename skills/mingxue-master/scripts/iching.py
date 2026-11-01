"""离线周易结构工具：六爻数值、三钱抽样、梅花数字起卦与可选纳甲。"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import random
import sys
import tempfile

sys.dont_write_bytecode = True
SKILL_ROOT = Path(__file__).resolve().parents[1]

# Every bit sequence in this module runs from the bottom line to the top line.
TRIGRAM_ROWS = (
    ("乾", "111", "天", "金"), ("兑", "110", "泽", "金"),
    ("离", "101", "火", "火"), ("震", "100", "雷", "木"),
    ("巽", "011", "风", "木"), ("坎", "010", "水", "水"),
    ("艮", "001", "山", "土"), ("坤", "000", "地", "土"),
)
TRIGRAMS = {
    bits: {"name": name, "bits_bottom_to_top": bits, "nature": nature,
           "element": element, "xiantian_number": i + 1, "symbol": "☰☱☲☳☴☵☶☷"[i]}
    for i, (name, bits, nature, element) in enumerate(TRIGRAM_ROWS)
}
# Rows = upper trigram, columns = lower; both use the explicit xiantian order.
KING_WEN_MATRIX = (
    (1, 10, 13, 25, 44, 6, 33, 12), (43, 58, 49, 17, 28, 47, 31, 45),
    (14, 38, 30, 21, 50, 64, 56, 35), (34, 54, 55, 51, 32, 40, 62, 16),
    (9, 61, 37, 42, 57, 59, 53, 20), (5, 60, 63, 3, 48, 29, 39, 8),
    (26, 41, 22, 27, 18, 4, 52, 23), (11, 19, 36, 24, 46, 7, 15, 2),
)
HEXAGRAM_NAMES = (
    "乾 坤 屯 蒙 需 讼 师 比 小畜 履 泰 否 同人 大有 谦 豫 随 蛊 临 观 "
    "噬嗑 贲 剥 复 无妄 大畜 颐 大过 坎 离 咸 恒 遁 大壮 晋 明夷 家人 睽 "
    "蹇 解 损 益 夬 姤 萃 升 困 井 革 鼎 震 艮 渐 归妹 丰 旅 巽 兑 涣 节 "
    "中孚 小过 既济 未济"
).split()
THEMES = (
    "始创与自强 承载与配合 初生与困难 启蒙与求教 等待与准备 争议与分寸 "
    "组织与纪律 亲近与协作 小量积蓄 谨慎履行 通达与交流 阻隔与反省 "
    "共同目标 丰有与节制 谦逊与平衡 预备与振作 随时调整 整治积弊 "
    "接近与照顾 观察与省察 排除梗阻 文饰与实质 剥落与止损 回返与恢复 "
    "诚实与自然 蓄养与约束 养护与言食 过载与担当 重险与习练 明辨与依附 "
    "感应与交流 恒常与坚持 退避与保全 力量与分寸 上升与自省 隐晦与守护 "
    "家内与职责 差异与求同 阻碍与求助 松解与缓和 减损与取舍 增益与互助 "
    "决断与节制 相遇与边界 汇聚与秩序 渐升与积累 困境与自守 公共资源与养护 "
    "变革与时机 更新与承载 震动与警醒 停止与安定 渐进与次序 关系与位置 "
    "丰盛与盛衰 旅居与谨慎 渐入与沟通 喜悦与交流 涣散与凝聚 节制与限度 "
    "诚信与感通 小事与谨慎 已成与维护 未成与续进"
).split()
HEXAGRAMS = {}
for _upper_index, _upper in enumerate(TRIGRAM_ROWS):
    for _lower_index, _lower in enumerate(TRIGRAM_ROWS):
        _number = KING_WEN_MATRIX[_upper_index][_lower_index]
        _name = HEXAGRAM_NAMES[_number - 1]
        _bits = _lower[1] + _upper[1]
        _full = (_name + "为" + _upper[2] if _upper == _lower
                 else _upper[2] + _lower[2] + _name)
        HEXAGRAMS[_bits] = {
            "number": _number, "name": _name, "full_name": _full,
            "symbol": chr(0x4DC0 + _number - 1), "bits_bottom_to_top": _bits,
            "upper": TRIGRAMS[_upper[1]], "lower": TRIGRAMS[_lower[1]],
            "cultural_theme": THEMES[_number - 1],
        }

NAJIA = {
    "乾": (("甲", "子寅辰"), ("壬", "午申戌")),
    "兑": (("丁", "巳卯丑"), ("丁", "亥酉未")),
    "离": (("己", "卯丑亥"), ("己", "酉未巳")),
    "震": (("庚", "子寅辰"), ("庚", "午申戌")),
    "巽": (("辛", "丑亥酉"), ("辛", "未巳卯")),
    "坎": (("戊", "寅辰午"), ("戊", "申戌子")),
    "艮": (("丙", "辰午申"), ("丙", "戌子寅")),
    "坤": (("乙", "未巳卯"), ("癸", "丑亥酉")),
}
BRANCH_ELEMENTS = dict(zip("子丑寅卯辰巳午未申酉戌亥", "水土木木土火火土金金土水"))
GENERATES = dict(zip("木火土金水", "火土金水木"))
CONTROLS = dict(zip("木火土金水", "土金水木火"))
STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
SEXAGENARY = tuple(STEMS[i % 10] + BRANCHES[i % 12] for i in range(60))
SIX_GODS = ("青龙", "朱雀", "勾陈", "螣蛇", "白虎", "玄武")
SIX_GOD_START = dict(zip(STEMS, (0, 0, 1, 1, 2, 3, 4, 4, 5, 5)))
BRANCH_COMBINATIONS = {frozenset(pair) for pair in ("子丑", "寅亥", "卯戌", "辰酉", "巳申", "午未")}
BRANCH_CLASHES = {frozenset(pair) for pair in ("子午", "丑未", "寅申", "卯酉", "辰戌", "巳亥")}
PALACE_STAGES = ("本宫", "一世", "二世", "三世", "四世", "五世", "游魂", "归魂")
PALACE_MASKS = (0, 1, 3, 7, 15, 31, 23, 16)
SHI_POSITIONS = (6, 1, 2, 3, 4, 5, 4, 3)
PALACES = {}
for _trigram in TRIGRAMS.values():
    _pure = _trigram["bits_bottom_to_top"] * 2
    for _stage, _mask, _shi in zip(PALACE_STAGES, PALACE_MASKS, SHI_POSITIONS):
        _key = "".join(str(int(bit) ^ ((_mask >> i) & 1)) for i, bit in enumerate(_pure))
        if _key in PALACES:
            raise RuntimeError("八宫生成结果发生重叠")
        PALACES[_key] = {"name": _trigram["name"], "element": _trigram["element"],
                         "stage": _stage, "shi_position": _shi,
                         "ying_position": (_shi + 2) % 6 + 1}


def validate_lines(values):
    if not isinstance(values, (list, tuple)) or len(values) != 6:
        raise ValueError("必须给出六个爻值，第一次/初爻在前，最后一次/上爻在后")
    if any(type(v) is not int or v not in (6, 7, 8, 9) for v in values):
        raise ValueError("每个爻值必须是整数 6、7、8、9；不接受 0—3 编码")
    return list(values)


def normalize_lines(values, direction="bottom-to-top"):
    lines = validate_lines(values)
    if direction not in ("bottom-to-top", "top-to-bottom"):
        raise ValueError("direction 必须明确为 bottom-to-top 或 top-to-bottom")
    return lines if direction == "bottom-to-top" else list(reversed(lines))


def hexagram(bits):
    if isinstance(bits, (tuple, list)):
        if len(bits) != 6 or any(type(v) is not int or v not in (0, 1) for v in bits):
            raise ValueError("卦码需要六个 0/1 整数，自下而上")
        bits = "".join(str(v) for v in bits)
    if not isinstance(bits, str) or len(bits) != 6 or any(c not in "01" for c in bits):
        raise ValueError("卦码需要六个 0/1，自下而上")
    # Copies prevent callers from changing the shared static catalog.
    return json.loads(json.dumps(HEXAGRAMS[bits], ensure_ascii=False))


def line_label(position, yang):
    value = "九" if yang else "六"
    if position == 1:
        return "初" + value
    if position == 6:
        return "上" + value
    return value + "一二三四五六"[position - 1]


def coin_cast(seed=None):
    if seed is not None and type(seed) is not int:
        raise ValueError("seed 必须是整数或省略")
    rng = random.SystemRandom() if seed is None else random.Random(seed)
    draws = [[2 + rng.getrandbits(1) for _ in range(3)] for _ in range(6)]
    return [sum(row) for row in draws], {
        "method": "three_coins", "seed": seed, "seed_provided": seed is not None,
        "rng": "system_random" if seed is None else "python_random_MT19937_getrandbits",
        "rng_runtime": "Python " + sys.version.split()[0],
        "coin_convention": {"value_2": "预先约定的字面/阴", "value_3": "预先约定的背面/阳"},
        "sampling": "每爻三个独立均衡二值抽样，共六次；各次自下而上",
        "coin_values_bottom_to_top": draws,
        "line_sums_bottom_to_top": [sum(row) for row in draws],
        "replay": "无 seed 时仍可用记录的 line_sums_bottom_to_top 作 --lines 完整重排；不声称 seed 可复现",
        "note": "均衡硬币模型的抽样机制不代表现实事件的预测概率。",
    }


def meihua_cast(numbers):
    if not isinstance(numbers, (list, tuple)) or len(numbers) not in (2, 3):
        raise ValueError("数字起卦需要两个或三个非负整数")
    if any(type(n) is not int or n < 0 for n in numbers):
        raise ValueError("数字起卦只接受非负整数，不接受负数、小数、布尔值")
    first, second = numbers[:2]
    moving_source = numbers[2] if len(numbers) == 3 else first + second
    upper, lower, moving = first % 8 or 8, second % 8 or 8, moving_source % 6 or 6
    bits = TRIGRAM_ROWS[lower - 1][1] + TRIGRAM_ROWS[upper - 1][1]
    values = [7 if c == "1" else 8 for c in bits]
    values[moving - 1] = 9 if bits[moving - 1] == "1" else 6
    return values, {
        "method": "meihua_numbers", "numbers": list(numbers),
        "convention": "数字起卦的一种公开约定；不是所有梅花流派的唯一规则",
        "upper_formula": "第一数 mod 8，余 0 取 8",
        "lower_formula": "第二数 mod 8，余 0 取 8",
        "moving_formula": "第三数 mod 6，余 0 取 6" if len(numbers) == 3 else "两数之和 mod 6，余 0 取 6",
        "xiantian_order": "乾1、兑2、离3、震4、巽5、坎6、艮7、坤8",
        "computed": {"upper_number": upper, "lower_number": lower, "moving_position": moving,
                     "moving_source": moving_source},
    }


def relative(palace_element, line_element):
    if palace_element not in GENERATES or line_element not in GENERATES:
        raise ValueError("六亲计算需要有效五行")
    if line_element == palace_element:
        return "兄弟"
    if GENERATES[line_element] == palace_element:
        return "父母"
    if GENERATES[palace_element] == line_element:
        return "子孙"
    return "妻财" if CONTROLS[palace_element] == line_element else "官鬼"


def element_relation(source, target):
    """A directed symbolic relation, never a numerical strength or outcome score."""
    if source not in GENERATES or target not in GENERATES:
        raise ValueError("五行关系需要有效五行")
    if source == target:
        return "same_element"
    if GENERATES[source] == target:
        return "source_generates_target"
    if GENERATES[target] == source:
        return "target_generates_source"
    return "source_controls_target" if CONTROLS[source] == target else "target_controls_source"


def branch_relation(source, target):
    if (not isinstance(source, str) or not isinstance(target, str) or len(source) != 1 or len(target) != 1
            or source not in BRANCHES or target not in BRANCHES):
        raise ValueError("冲合关系需要单个有效地支")
    pair = frozenset((source, target))
    return {"same_branch": source == target, "liu_he": pair in BRANCH_COMBINATIONS,
            "liu_chong": pair in BRANCH_CLASHES,
            "element_relation": element_relation(BRANCH_ELEMENTS[source], BRANCH_ELEMENTS[target])}


def six_gods(day_pillar):
    if day_pillar not in SEXAGENARY:
        raise ValueError("六神需要合法六十甲子日辰")
    start = SIX_GOD_START[day_pillar[0]]
    return list(SIX_GODS[start:] + SIX_GODS[:start])


def xun_kong(day_pillar):
    if day_pillar not in SEXAGENARY:
        raise ValueError("旬空需要合法六十甲子日辰")
    head = SEXAGENARY.index(day_pillar) // 10 * 10
    return {"xun_head": SEXAGENARY[head],
            "branches": [BRANCHES[(head + 10) % 12], BRANCHES[(head + 11) % 12]],
            "meaning": "日辰所在十日旬未出现的两个地支；只标旬空，不判真空假空或应期"}


def monthly_element_state(month_branch, line_element):
    if month_branch not in BRANCH_ELEMENTS:
        raise ValueError("月建须为单个地支")
    relation = element_relation(BRANCH_ELEMENTS[month_branch], line_element)
    return {"same_element": "旺", "source_generates_target": "相", "target_generates_source": "休",
            "target_controls_source": "囚", "source_controls_target": "死"}[relation]


def _calendar_modules():
    # Calendar loading remains lazy: a cast without a time needs no resource cache.
    scripts = str(Path(__file__).resolve().parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import chart
    import case_lookup
    if any(not Path(module.__file__).resolve().is_relative_to(Path(scripts)) for module in (chart, case_lookup)):
        raise ValueError("历法模块来自另一个安装目录，请在新的Python进程中运行")
    return chart, case_lookup.load_chart


def _calendar_candidates(source_candidates, prefix):
    grouped = {}
    for source_index, candidate in enumerate(source_candidates):
        pillars = candidate["pillars"]
        month, day = pillars["month"], pillars["day"]
        if month not in SEXAGENARY or day not in SEXAGENARY:
            raise ValueError("起卦历法候选缺少可核验的月柱或日辰")
        sect = candidate["sect"]
        key = (sect, month, day)
        if key not in grouped:
            grouped[key] = {
                "candidate_id": prefix + "-" + str(len(grouped) + 1), "sect": sect,
                "month": {"pillar": month, "branch": month[1], "element": BRANCH_ELEMENTS[month[1]]},
                "day": {"pillar": day, "stem": day[0], "branch": day[1], "element": BRANCH_ELEMENTS[day[1]]},
                "six_gods_bottom_to_top": six_gods(day), "xun_kong": xun_kong(day),
                "source_candidate_indices": [], "valid_time_ranges": [], "representative_clock_records": [],
            }
        item = grouped[key]
        item["source_candidate_indices"].append(source_index)
        item["valid_time_ranges"].extend(deepcopy(candidate["time_ranges"]))
        item["representative_clock_records"].append(deepcopy(candidate["time"]))
    return list(grouped.values())


def build_cast_context(date_value=None, time_value=None, *, timezone=None, chart_path=None,
                       sect=None, fold=None, time_basis=None, longitude=None, true_solar=False):
    """Use only a caller-declared casting time; never reuse a birth chart implicitly.

    ``chart_path`` explicitly declares a canonical schema-3 file to represent this
    cast's time. The canonical loader recomputes and verifies it before use.
    """
    if chart_path is None and date_value is None:
        if (time_value is not None or timezone is not None or sect is not None or fold is not None
                or time_basis is not None or longitude is not None or true_solar):
            raise ValueError("起卦时间参数需要 --cast-date；不能只给钟点、时区或规则")
        return {"schema_version": 1, "purpose": "casting_time", "status": "not_supplied",
                "note": "没有提供起卦时间；未推定当前时间，也未借用出生时间，继续仅作卦象结构排盘"}
    if chart_path is not None and (date_value is not None or time_value is not None or timezone is not None
            or sect is not None or fold is not None or time_basis is not None or longitude is not None or true_solar):
        raise ValueError("--cast-chart 与其他cast时间参数不可合用；按文件原口径验证，不悄悄覆盖")
    if chart_path is None and timezone is None:
        raise ValueError("显式起卦日期需要 --cast-timezone IANA时区，不从出生地点或系统时区猜测")
    chart, load_chart = _calendar_modules()
    if chart_path is not None:
        value = load_chart(chart_path)
        source = {"type": "canonical_schema3", "path": str(Path(chart_path).expanduser().resolve()),
                  "declared_role": "调用方以cast-chart明确声明文件记录的是本次起卦时间，不能自动沿用出生盘"}
    else:
        value = chart.build_chart(date_value, time_value, calendar="solar", timezone=timezone,
                                  sect=2 if sect is None else sect, fold=fold,
                                  time_basis="local-clock" if time_basis is None else time_basis,
                                  longitude=longitude, true_solar=true_solar)
        source = {"type": "explicit_casting_datetime", "declared_role": "本次起卦时间，独立于出生时间",
                  "day_change_choice": "software_default_sect_2" if sect is None else "explicit"}
    selected = _calendar_candidates(value["candidates"], "selected")
    alternatives = _calendar_candidates(value["convention_alternatives"], "alternative")
    uncertainty = deepcopy(value["uncertainty"])
    for item in uncertainty:
        if item["code"] == "unknown_birth_time":
            item.update({"code": "unknown_cast_time", "detail": "起卦钟点未知；完整有效时间范围保留，代表时刻不代表实际起卦时刻。"})
    return {"schema_version": 1, "purpose": "casting_time", "status": "calculated_with_candidates",
            "source": source, "input": deepcopy(value["input"]),
            "time_known": value["time_known"], "time_precision": value["time_precision"],
            "time_context": deepcopy(value["time_context"]), "convention": deepcopy(value["convention"]),
            "candidates": selected, "convention_alternatives": alternatives, "uncertainty": uncertainty,
            "notes": deepcopy(value["notes"]),
            "solar_terms_on_date": deepcopy(value["solar_terms_on_date"]),
            "scope": "月建按真实瞬间的节界；日辰按已声明起卦钟点及换日口径。日月相同的候选可分组，但完整时间范围与歧义仍保留。"}


def _validate_cast_context(context):
    if (not isinstance(context, dict) or context.get("schema_version") != 1
            or context.get("purpose") != "casting_time"):
        raise ValueError("cast_context 必须来自 build_cast_context，不能传入出生盘或任意日月对象")
    if context.get("status") == "not_supplied":
        return context
    if context.get("status") != "calculated_with_candidates" or not context.get("candidates"):
        raise ValueError("cast_context 缺少已验证的起卦历法候选")
    for candidate in context["candidates"] + context.get("convention_alternatives", []):
        if (candidate.get("day", {}).get("pillar") not in SEXAGENARY
                or candidate.get("month", {}).get("pillar") not in SEXAGENARY):
            raise ValueError("cast_context 的日月候选无效")
    return context


def _temporal_rows(rows, candidate):
    day_branch, month_branch = candidate["day"]["branch"], candidate["month"]["branch"]
    result = []
    for row in rows:
        pos, branch = row["position"], row["branch"]
        result.append({"position": pos, "branch": branch,
                       "six_god": candidate["six_gods_bottom_to_top"][pos - 1],
                       "xun_kong": branch in candidate["xun_kong"]["branches"],
                       "month_branch_element_state": monthly_element_state(month_branch, row["element"]),
                       "month_to_line": branch_relation(month_branch, branch),
                       "day_to_line": branch_relation(day_branch, branch)})
    return result


def temporal_structure(najia, context):
    def one(candidate):
        return {"candidate_id": candidate["candidate_id"], "sect": candidate["sect"],
                "month_pillar": candidate["month"]["pillar"], "day_pillar": candidate["day"]["pillar"],
                "xun_kong": deepcopy(candidate["xun_kong"]),
                "base_rows_bottom_to_top": _temporal_rows(najia["base_rows_bottom_to_top"], candidate),
                "changed_rows_bottom_to_top": _temporal_rows(najia["changed_rows_bottom_to_top"], candidate)}
    return {"status": "partial_calendar_structure", "candidates": [one(c) for c in context["candidates"]],
            "convention_alternatives": [one(c) for c in context["convention_alternatives"]],
            "convention": {
                "monthly_state": "按月建地支本气五行给旺相休囚死：同旺、月生爻相、爻生月休、爻克月囚、月克爻死；辰戌丑未一律按土月。",
                "state_scope": "这是单一月支五行简表，不是全派综合旺衰；死仅为传统分类术语，不指疾病、寿命或死亡。",
                "relations": "同支、六合、六冲和有方向的五行生克仅作结构标记；月冲是常见月破的结构条件，不据此判爻无力。",
                "no_inference": "不自动判合化、暗动、日破、真空假空、用神、应期、吉凶或现实预测概率。",
                "changed_rows": "变卦六行用于对照；仅原moving_positions对应行是实际动爻所化，不能视为六行全动。"}}


def najia_rows(gua, reference_element):
    rows = []
    for half_index, key in enumerate(("lower", "upper")):
        stem, branches = NAJIA[gua[key]["name"]][half_index]
        for i, branch in enumerate(branches):
            element = BRANCH_ELEMENTS[branch]
            rows.append({"position": half_index * 3 + i + 1, "stem": stem,
                         "branch": branch, "stem_branch": stem + branch,
                         "element": element, "relative": relative(reference_element, element)})
    return rows


def najia_structure(base, changed, moving):
    palace = dict(PALACES[base["bits_bottom_to_top"]])
    rows = najia_rows(base, palace["element"])
    changed_rows = najia_rows(changed, palace["element"])
    for row, changed_row in zip(rows, changed_rows):
        pos = row["position"]
        row.update({"shi": pos == palace["shi_position"], "ying": pos == palace["ying_position"],
                    "moving": pos in moving})
        changed_row["corresponds_to_moving_line"] = pos in moving
    line_relations = [{"positions": [a["position"], b["position"]],
                       "source_branch": a["branch"], "target_branch": b["branch"],
                       **branch_relation(a["branch"], b["branch"])}
                      for i, a in enumerate(rows) for b in rows[i + 1:]]
    transformations = [{"position": a["position"], "base_branch": a["branch"],
                        "changed_branch": b["branch"], "direction": "changed_to_base",
                        **branch_relation(b["branch"], a["branch"])}
                       for a, b in zip(rows, changed_rows) if a["position"] in moving]
    return {"status": "structural_only", "palace": palace, "base_rows_bottom_to_top": rows,
            "changed_rows_bottom_to_top": changed_rows,
            "base_line_pair_relations": line_relations, "moving_transformations": transformations,
            "relation_scope": "本卦两爻关系与动爻化支对本位的有向关系，仅标地支冲合和五行生克，不自动判作用成立、合化或吉凶。",
            "relative_reference": "本卦所属宫五行；变卦纳甲六亲仍以本卦宫五行为参照",
            "changed_row_note": "六行展示变卦整体纳甲；corresponds_to_moving_line 标出实际动爻位置，不将六行都当发动",
            "not_calculated": ["起卦日期及日月建", "六神", "旬空", "旺衰", "伏神", "用神与应期", "综合吉凶断语"]}


def reading_targets(base, changed, moving):
    """Common changing-line text-selection convention, without inventing quotes."""
    still = [p for p in range(1, 7) if p not in moving]
    n = len(moving)
    if n == 0:
        targets = [{"hexagram": "base", "kind": "卦辞"}]
    elif n in (1, 2):
        targets = [{"hexagram": "base", "kind": "爻辞", "position": p,
                    "primary": p == max(moving)} for p in moving]
    elif n == 3:
        targets = [{"hexagram": key, "kind": "卦辞", "primary": key == "base"}
                   for key in ("base", "changed")]
    elif n in (4, 5):
        targets = [{"hexagram": "changed", "kind": "爻辞", "position": p,
                    "primary": p == min(still)} for p in still]
    elif base["number"] in (1, 2):
        targets = [{"hexagram": "base", "kind": "用九" if base["number"] == 1 else "用六"}]
    else:
        targets = [{"hexagram": "changed", "kind": "卦辞"}]
    for target in targets:
        gua = base if target["hexagram"] == "base" else changed
        target.update({"hexagram_number": gua["number"], "hexagram_name": gua["name"]})
    return {"convention": "常见的朱熹变占取辞规则；并非所有易学流派通用",
            "targets": targets,
            "text_status": "本工具不附经文全文；引用卦爻辞前须另核可靠版本，不把 cultural_theme 当经文",
            "interpretation_status": "取辞位置与文化阅读线索，不是已验证的事件预测"}


def build_result(values, *, method_record=None, direction="bottom-to-top", include_najia=False, question=None,
                 cast_context=None):
    values = validate_lines(values)
    normalized = normalize_lines(values, direction)
    bits = [v % 2 for v in normalized]
    moving = [i + 1 for i, v in enumerate(normalized) if v in (6, 9)]
    changed_bits = [1 - b if i + 1 in moving else b for i, b in enumerate(bits)]
    base, changed = hexagram(bits), hexagram(changed_bits)
    cast_context = _validate_cast_context(build_cast_context() if cast_context is None else cast_context)
    nuclear = hexagram(bits[1:4] + bits[2:5])
    rows = [{"position": i + 1, "value": v, "yang": bool(bits[i]),
             "type": {6: "老阴", 7: "少阳", 8: "少阴", 9: "老阳"}[v],
             "label": line_label(i + 1, bits[i]), "moving": i + 1 in moving,
             "changed_yang": bool(changed_bits[i])} for i, v in enumerate(normalized)]
    result = {
        "ok": True, "schema_version": 1, "system": "iching",
        "input": {"values_as_supplied": values, "direction": direction, "question": question},
        "method": method_record if method_record is not None else {"method": "manual_6_7_8_9"},
        "conventions": {"line_order": "bottom-to-top", "positions": "初爻1 至 上爻6",
                        "values": "6老阴变阳，7少阳不变，8少阴不变，9老阳变阴",
                        "nuclear": "本卦2/3/4爻为下互、3/4/5爻为上互"},
        "lines_bottom_to_top": rows, "moving_positions": moving,
        "hexagrams": {"base": base, "changed": changed, "nuclear": nuclear,
                      "opposite": hexagram([1 - b for b in bits]), "reversed": hexagram(list(reversed(bits)))},
        "reading": reading_targets(base, changed, moving),
        "cast_context": deepcopy(cast_context),
        "assessment": {"type": "traditional_cultural_structure", "predictive_probability": None,
                       "note": "卦象、五行和文化主题只供文本阅读与反思；不用于疾病或死亡诊断，不保证投资、婚姻等现实结果。"},
    }
    if include_najia:
        result["najia"] = najia_structure(base, changed, moving)
        if cast_context["status"] != "not_supplied":
            result["najia"]["status"] = "structural_with_calendar"
            result["najia"]["temporal_analysis"] = temporal_structure(result["najia"], cast_context)
            result["najia"]["not_calculated"] = ["综合旺衰判定", "伏神", "用神与应期", "综合吉凶断语"]
    return result


def validate_output_path(output, *, overwrite=False):
    if not output:
        raise ValueError("文件输出需要显式指定 --output 绝对路径")
    supplied = Path(output).expanduser()
    if not supplied.is_absolute():
        raise ValueError("--output 必须是绝对路径")
    if supplied.suffix.lower() != ".json" or ":" in supplied.name:
        raise ValueError("--output 必须是普通 .json 文件路径")
    target = supplied.resolve()
    from output_paths import guard_output
    guard_output(target)
    protected = [SKILL_ROOT, (Path(tempfile.gettempdir()) / "mingxue-master-cache").resolve()]
    protected += [Path(os.environ[key]).expanduser().resolve()
                  for key in ("MINGXUE_RESOURCE_DIR", "MINGXUE_RUNTIME_DIR", "MINGXUE_CACHE_DIR") if os.environ.get(key)]
    if (any(target.is_relative_to(root) for root in protected)
            or any(p.name.casefold() in ("runtime", "cache", "engine-cache", "mingxue-master-cache")
                   for p in target.parents)):
        raise ValueError("用户输出不得写入 skill、runtime、资源或 cache 目录")
    if supplied.is_symlink() or (hasattr(supplied, "is_junction") and supplied.is_junction()):
        raise ValueError("--output 不接受符号链接或目录联接作为文件")
    if target.exists() and (not overwrite or not target.is_file()):
        raise ValueError("目标已存在；确认该具体文件可替换时才添加 --overwrite")
    return target


def write_result(result, target=None):
    if target is not None:
        result["output_path"] = str(target)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix="." + target.name + ".", dir=target.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(rendered)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    print(rendered, end="")


class JsonParser(argparse.ArgumentParser):
    def error(self, message):
        print(json.dumps({"ok": False, "error": {"code": "invalid_input", "message": message}}, ensure_ascii=False))
        raise SystemExit(2)


def main(argv=None):
    parser = JsonParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--probe", action="store_true", help="只报告离线能力，无需输出文件")
    parser.add_argument("--catalog", action="store_true", help="导出八卦与64卦结构目录，需 --output")
    parser.add_argument("--method", choices=("manual", "coins", "meihua"), default="manual")
    parser.add_argument("--lines", nargs="+", help="六个6/7/8/9，空格分隔或一个逗号串；初爻在前")
    parser.add_argument("--direction", choices=("bottom-to-top", "top-to-bottom"), default=None,
                        help="手动输入方向；省略采用已声明的 bottom-to-top")
    parser.add_argument("--seed", type=int, help="仅三钱法；整数 seed 用于同一Python抽样机制重现")
    parser.add_argument("--numbers", nargs="+", type=int, help="仅梅花数字法；两个或三个非负整数")
    parser.add_argument("--najia", action="store_true", help="显式加纳甲、八宫、世应、六亲结构，不作完整六爻断卦")
    parser.add_argument("--cast-date", help="可选起卦公历日期 YYYY-MM-DD；独立于出生日期，不默认当前时间")
    parser.add_argument("--cast-time", help="起卦钟点 HH:MM[:SS]；省略时保留完整日期候选")
    parser.add_argument("--cast-timezone", help="显式起卦日期所用IANA时区，不能借用出生时区")
    parser.add_argument("--cast-chart", help="明确声明记录本次起卦时间的canonical schema3 JSON；按原时间口径重算验证")
    parser.add_argument("--cast-sect", type=int, choices=(1, 2), help="独立起卦换日规则：1=23:00，2=00:00（默认2）")
    parser.add_argument("--cast-fold", type=int, choices=(0, 1), help="选择重复起卦钟点的前/后真实瞬间；省略保留两者")
    parser.add_argument("--cast-time-basis", choices=("local-clock", "standard-time", "true-solar-time"),
                        help="起卦所记钟点口径，默认local-clock")
    parser.add_argument("--cast-longitude", type=float, help="可选起卦经度，东经为正；太阳钟口径必须提供")
    parser.add_argument("--cast-true-solar", action="store_true", help="明确选择按已有近似太阳钟校正起卦日辰；不重复校正已给太阳钟")
    parser.add_argument("--question", help="可选所问事项，原样保留在JSON结果；显式保存时写入指定文件")
    parser.add_argument("--output", help="可选：保存到绝对 .json 路径；实际起卦省略时只输出stdout，禁止 skill/runtime/cache")
    parser.add_argument("--overwrite", action="store_true", help="明确替换已存在的具体输出文件")
    parser.add_argument("--json", action="store_true", help="兼容参数；stdout 始终 JSON")
    args = parser.parse_args(argv)
    try:
        if args.overwrite and args.output is None:
            raise ValueError("--overwrite 仅可与显式 --output 文件路径合用")
        if args.probe or args.catalog:
            if args.probe and args.catalog:
                raise ValueError("--probe 与 --catalog 不可合用")
            if args.method != "manual" or any(v is not None for v in (args.lines, args.direction, args.seed, args.numbers, args.question,
                    args.cast_date, args.cast_time, args.cast_timezone, args.cast_chart, args.cast_sect,
                    args.cast_fold, args.cast_time_basis, args.cast_longitude)) or args.najia or args.cast_true_solar:
                raise ValueError("--probe/--catalog 不接受起卦输入")
            if args.probe:
                if args.output or args.overwrite:
                    raise ValueError("--probe 不写文件，不接受 --output/--overwrite")
                print(json.dumps({"ok": True, "system": "iching", "offline": True,
                                  "methods": ["manual", "coins", "meihua"], "trigrams": len(TRIGRAMS),
                                  "hexagrams": len(HEXAGRAMS), "najia": "structural_only",
                                  "casting_calendar": "optional_offline_iana_schema3_candidates",
                                  "temporal_relations": ["日辰", "节界月建", "六神", "旬空", "月支五行简表", "冲合生克"],
                                  "file_output_requires_absolute_path": True,
                                  "stdout_only_supported": True}, ensure_ascii=False))
                return 0
            target = validate_output_path(args.output, overwrite=args.overwrite)
            write_result({"ok": True, "schema_version": 1, "system": "iching_catalog",
                          "trigrams": list(TRIGRAMS.values()), "line_order": "bottom-to-top",
                          "hexagrams": sorted(HEXAGRAMS.values(), key=lambda g: g["number"])}, target)
            return 0
        target = validate_output_path(args.output, overwrite=args.overwrite) if args.output is not None else None
        if args.method == "manual":
            if args.seed is not None or args.numbers is not None or args.lines is None:
                raise ValueError("manual 需要 --lines，且不接受 --seed/--numbers")
            try:
                values = [int(piece.strip()) for token in args.lines for piece in token.split(",")]
            except ValueError as exc:
                raise ValueError("--lines 必须是六个6/7/8/9整数") from exc
            record, direction = {"method": "manual_6_7_8_9"}, args.direction or "bottom-to-top"
        elif args.method == "coins":
            if args.lines is not None or args.numbers is not None or args.direction is not None:
                raise ValueError("coins 不接受 --lines/--numbers/--direction；投掷顺序固定自下而上")
            values, record = coin_cast(args.seed)
            direction = "bottom-to-top"
        else:
            if args.lines is not None or args.seed is not None or args.direction is not None:
                raise ValueError("meihua 不接受 --lines/--seed/--direction")
            values, record = meihua_cast(args.numbers)
            direction = "bottom-to-top"
        cast_context = build_cast_context(args.cast_date, args.cast_time, timezone=args.cast_timezone,
                                         chart_path=args.cast_chart, sect=args.cast_sect, fold=args.cast_fold,
                                         time_basis=args.cast_time_basis, longitude=args.cast_longitude,
                                         true_solar=args.cast_true_solar)
        result = build_result(values, method_record=record, direction=direction,
                              include_najia=args.najia, question=args.question, cast_context=cast_context)
        write_result(result, target)
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
