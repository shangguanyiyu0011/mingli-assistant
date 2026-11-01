"""Deterministic annotations for known sixty-cycle pillars.

This module accepts calendar results; it neither calculates a birth time nor
infers unknown pillars. Relationship records report symbol co-occurrence only.
"""
from itertools import combinations, product

PILLAR_KEYS = ("year", "month", "day", "hour")
GAN = "甲乙丙丁戊己庚辛壬癸"
ZHI = "子丑寅卯辰巳午未申酉戌亥"
JIAZI = tuple(GAN[i % 10] + ZHI[i % 12] for i in range(60))
STEM_ELEMENTS = "木木火火土土金金水水"
BRANCH_ELEMENTS = "水土木木土火火土金金土水"
ELEMENTS = "木火土金水"
HIDDEN_STEMS = dict(zip(ZHI, ("癸", "己癸辛", "甲丙戊", "乙", "戊乙癸", "丙庚戊",
                              "丁己", "己丁乙", "庚壬戊", "辛", "戊辛丁", "壬甲")))
NAYIN_NAMES = (
    "海中金", "炉中火", "大林木", "路旁土", "剑锋金", "山头火", "涧下水", "城头土",
    "白蜡金", "杨柳木", "泉中水", "屋上土", "霹雳火", "松柏木", "长流水", "沙中金",
    "山下火", "平地木", "壁上土", "金箔金", "覆灯火", "天河水", "大驿土", "钗钏金",
    "桑柘木", "大溪水", "沙中土", "天上火", "石榴木", "大海水",
)
NAYIN = {pillar: NAYIN_NAMES[i // 2] for i, pillar in enumerate(JIAZI)}
GROWTH_STAGES = ("长生", "沐浴", "冠带", "临官", "帝旺", "衰", "病", "死", "墓", "绝", "胎", "养")
GROWTH_START = dict(zip(GAN, "亥午寅酉寅酉巳子申卯"))
PAIR_RULES = {
    "stem_combinations": ("甲己", "乙庚", "丙辛", "丁壬", "戊癸"),
    "branch_combinations": ("子丑", "寅亥", "卯戌", "辰酉", "巳申", "午未"),
    "branch_clashes": ("子午", "丑未", "寅申", "卯酉", "辰戌", "巳亥"),
    "branch_harms": ("子未", "丑午", "寅巳", "卯辰", "申亥", "酉戌"),
    "branch_breaks": ("子酉", "丑辰", "寅亥", "卯午", "巳申", "未戌"),
}
TRIPLE_RULES = {
    "triple_harmonies": (("申子辰", "水"), ("亥卯未", "木"), ("寅午戌", "火"), ("巳酉丑", "金")),
    "triple_meetings": (("寅卯辰", "木"), ("巳午未", "火"), ("申酉戌", "金"), ("亥子丑", "水")),
}


def validate_pillars(pillars):
    """Reject non-cycle pairs, missing keys and extra keys; allow explicit null."""
    if not isinstance(pillars, dict) or set(pillars) != set(PILLAR_KEYS):
        raise ValueError("pillars must contain exactly year, month, day, hour")
    for key in PILLAR_KEYS:
        value = pillars[key]
        if value is not None and (not isinstance(value, str) or value not in JIAZI):
            raise ValueError(f"Invalid sixty-cycle pillar {key}: {value!r}")
    return pillars


def stem_info(stem):
    if not isinstance(stem, str) or len(stem) != 1 or stem not in GAN:
        raise ValueError("stem must be one of the ten heavenly stems")
    i = GAN.index(stem)
    return {"character": stem, "element": STEM_ELEMENTS[i], "polarity": "阳" if i % 2 == 0 else "阴"}


def branch_info(branch):
    if not isinstance(branch, str) or len(branch) != 1 or branch not in ZHI:
        raise ValueError("branch must be one of the twelve earthly branches")
    i = ZHI.index(branch)
    return {"character": branch, "element": BRANCH_ELEMENTS[i], "polarity": "阳" if i % 2 == 0 else "阴"}


def ten_god(day_stem, other_stem):
    """Ten-god relation to the day stem; null reference stays unknown."""
    other = stem_info(other_stem)
    if day_stem is None:
        return None
    day = stem_info(day_stem)
    delta = (ELEMENTS.index(other["element"]) - ELEMENTS.index(day["element"])) % 5
    same = day["polarity"] == other["polarity"]
    return (("比肩", "劫财"), ("食神", "伤官"), ("偏财", "正财"),
            ("七杀", "正官"), ("偏印", "正印"))[delta][0 if same else 1]


def growth_stage(day_stem, branch):
    """Day-stem twelve-stage cycle: yang forward, yin backward; earth follows fire."""
    branch_info(branch)
    if day_stem is None:
        return None
    stem = stem_info(day_stem)
    step = 1 if stem["polarity"] == "阳" else -1
    return GROWTH_STAGES[(step * (ZHI.index(branch) - ZHI.index(GROWTH_START[day_stem]))) % 12]


def _record(pairs, rule, **extra):
    return {"rule": rule, "positions": [p[0] for p in pairs],
            "characters": [p[1] for p in pairs], **extra}


def _relations(pillars):
    stems = [(key, pillars[key][0]) for key in PILLAR_KEYS if pillars[key] is not None]
    branches = [(key, pillars[key][1]) for key in PILLAR_KEYS if pillars[key] is not None]
    result = {}
    for kind, rules in PAIR_RULES.items():
        pairs = stems if kind == "stem_combinations" else branches
        lookup = {frozenset(rule): rule for rule in rules}
        result[kind] = [_record((a, b), lookup[frozenset((a[1], b[1]))])
                        for a, b in combinations(pairs, 2) if frozenset((a[1], b[1])) in lookup]
    for kind, rules in TRIPLE_RULES.items():
        result[kind] = []
        for rule, element in rules:
            members = [[entry for entry in branches if entry[1] == char] for char in rule]
            # Empty member lists produce no combination: no half-combination is
            # reported as a complete three-branch relation.
            for chosen in product(*members):
                ordered = sorted(chosen, key=lambda item: PILLAR_KEYS.index(item[0]))
                result[kind].append(_record(ordered, rule, complete=True, traditional_element=element))
    result["punishments"] = []
    branch_set = {char for _, char in branches}
    for group in ("寅巳申", "丑戌未"):
        for source, target in zip(group, group[1:] + group[0]):
            for a in branches:
                for b in branches:
                    if a[1] == source and b[1] == target:
                        result["punishments"].append(_record(
                            (a, b), source + "刑" + target, direction="directed",
                            group=group, group_complete=set(group).issubset(branch_set)))
    for a, b in combinations(branches, 2):
        if {a[1], b[1]} == {"子", "卯"}:
            result["punishments"].append(_record((a, b), "子卯相刑", direction="mutual"))
    result["self_punishments"] = [_record((a, b), a[1] + a[1] + "自刑")
                                    for a, b in combinations(branches, 2)
                                    if a[1] == b[1] and a[1] in "辰午酉亥"]
    return result


def build_details(pillars):
    """Build JSON-compatible structural annotations without completing unknowns.

    Every physical position pair/triple is retained, including repetitions.
    Relations do not assess strength, transformation, favorable elements or fate.
    """
    validate_pillars(pillars)
    day_stem = pillars["day"][0] if pillars["day"] is not None else None
    details = {}
    for key in PILLAR_KEYS:
        pillar = pillars[key]
        if pillar is None:
            details[key] = None
            continue
        stem, branch = pillar
        details[key] = {
            "pillar": pillar, "stem": stem_info(stem), "branch": branch_info(branch),
            "is_day_master": key == "day", "ten_god": ten_god(day_stem, stem),
            "hidden_stems": [{**stem_info(s), "ten_god": ten_god(day_stem, s)} for s in HIDDEN_STEMS[branch]],
            "nayin": NAYIN[pillar], "growth_stage": growth_stage(day_stem, branch),
        }
    missing = [key for key in PILLAR_KEYS if pillars[key] is None]
    return {
        "complete": not missing, "missing_pillars": missing,
        "day_master": stem_info(day_stem) if day_stem is not None else None,
        "pillars": details, "relations": _relations(pillars),
        "chosen_convention": {
            "five_elements_polarity": "天干甲丙戊庚壬为阳、乙丁己辛癸为阴；地支子寅辰午申戌为阳，其余为阴。",
            "ten_gods": "以日干的五行生克和阴阳同异计算；日干对自身记比肩，另以 is_day_master 标识日柱。",
            "hidden_stems": "采用包内历法库藏干次序（巳为丙、庚、戊），不赋权重或藏干比例。",
            "growth_stage": {
                "method": "阳顺阴逆，戊随丙、己随丁；与包内历法库十二长生规则一致。",
                "starts": dict(GROWTH_START), "reference": "日干对各柱地支",
                "school_variation": "十二长生尤其土干寄宫存在派别差异；此为选定约定，并非唯一标准。",
            },
            "relationships": "仅标记已知柱位的符号关系；可并存，不判断合化、旺衰、吉凶或预测概率。三合三会须三种地支齐全；每组实际柱位组合分别记录。",
            "punishments": "采用寅→巳→申→寅、丑→戌→未→丑定向两支刑及子卯互刑；两支可记录刑，group_complete 标明三支是否齐全。自刑限辰午酉亥，同支至少出现于两个柱位。此为选定关系表，不代表唯一流派。",
            "unknowns": "未知柱保持 null；日柱未知时不计算十神和十二长生，已知柱间关系仍保留。",
        },
    }
