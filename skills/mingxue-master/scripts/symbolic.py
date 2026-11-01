"""Offline numerology arithmetic and explicitly recorded virtual tarot draws."""
import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
MASTER_OPTIONS = {"none": (), "11,22": (11, 22), "11,22,33": (11, 22, 33)}
LETTER_VALUES = {chr(65 + i): i % 9 + 1 for i in range(26)}
DECK_ID = "rws-strength08-justice11-v1"
DRAW_ALGORITHM = "sha256-counter-rejection-v1"
MAJOR_NAMES = ("愚者", "魔术师", "女祭司", "皇后", "皇帝", "教皇", "恋人", "战车", "力量", "隐士", "命运之轮",
               "正义", "倒吊人", "死神", "节制", "恶魔", "高塔", "星星", "月亮", "太阳", "审判", "世界")
MAJOR_THEMES = ("起步与开放", "资源与行动", "观察与内省", "照料与创造", "结构与责任", "传统与学习", "价值与选择",
                "方向与自律", "耐心与克制", "独处与求知", "变化与周期", "公平与承担", "暂停与换位", "结束与转变",
                "协调与适度", "依赖与束缚", "动摇与重建", "希望与修复", "模糊与想象", "清晰与活力", "回顾与回应", "整合与完成")
SUITS = {"wands": ("权杖", "行动与创造"), "cups": ("圣杯", "情感与关系"),
         "swords": ("宝剑", "思考与冲突"), "pentacles": ("星币", "资源与日常")}
RANKS = (("ace", "一", "新起点"), ("02", "二", "协调与选择"), ("03", "三", "交流与发展"),
         ("04", "四", "稳定与停留"), ("05", "五", "变化与张力"), ("06", "六", "调整与互助"),
         ("07", "七", "检视与应对"), ("08", "八", "投入与转向"), ("09", "九", "积累与界限"),
         ("10", "十", "完成与负担"), ("page", "侍从", "探索与学习"), ("knight", "骑士", "推进与节奏"),
         ("queen", "王后", "照顾与熟练"), ("king", "国王", "组织与担当"))
# Specific minor-card lenses preserve familiar pictorial distinctions; they
# are reflection prompts rather than promises or assessments of a real person.
MINOR_THEMES = {
    "wands": ("创意萌芽", "规划与眺望", "拓展与等待", "庆祝与归属", "竞争与磨合", "认可与展示", "立场与防守",
              "推进与信息", "韧性与戒备", "责任与过载", "好奇与试验", "热情与冲动", "自信与亲和", "愿景与统筹"),
    "cups": ("感受萌芽", "相遇与互相回应", "友谊与分享", "倦怠与重新留意", "失落与尚存资源", "回忆与熟悉感",
             "想象与选择过多", "离开与追寻", "满足与愿望", "归属与共同愿景", "敏感与新讯息", "理想与邀约",
             "同理与情绪界限", "沉着与情感管理"),
    "swords": ("澄清与判断", "僵持与暂缓", "伤心与理解", "休息与复原空间", "争执与代价", "过渡与远行",
               "策略与隐瞒", "受限感与可用空间", "焦虑与反复思虑", "结束与承受", "求知与警觉", "速度与锋芒",
               "清晰与界限", "规则与理性"),
    "pentacles": ("实际机会", "调配与灵活", "协作与技艺", "持有与控制", "匮乏感与求助", "给予与接受",
                  "投入与评估", "练习与专注", "自立与享受", "传承与共同资源", "学习与实践", "稳步与重复",
                  "照料与务实", "管理与稳定"),
}
SPREADS = {
    "single": ("单牌", ("当前可观察的主题",)),
    "three": ("三牌反思", ("处境", "张力或阻力", "可选行动")),
    "decision": ("选择反思五牌", ("现状", "选项A的观察角度", "选项B的观察角度", "需要核实的信息", "可行下一步")),
    "celtic": ("凯尔特十字反思", ("核心处境", "交叉张力", "意识目标", "根基", "近期背景", "可能的近期路径",
                                      "自我视角", "环境视角", "希望与担忧", "一种可能的发展路径（非预言）")),
}


def build_deck():
    result = [{"id": f"major-{i:02}", "name": name, "arcana": "major", "number": i,
               "theme": MAJOR_THEMES[i]} for i, name in enumerate(MAJOR_NAMES)]
    for suit, (label, domain) in SUITS.items():
        for i, (rank, rank_label, _) in enumerate(RANKS):
            result.append({"id": f"{suit}-{rank}", "name": label + rank_label, "arcana": "minor",
                           "suit": suit, "rank": rank, "domain": domain, "theme": MINOR_THEMES[suit][i]})
    return tuple(result)


DECK = build_deck()
CARD_INDEX = {card["id"]: card for card in DECK}


class JsonParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)

    def print_help(self, file=None):
        print(json.dumps({"help": self.format_help()}, ensure_ascii=False), file=file)


def write_result(value, output=None):
    target = None
    if output is not None:
        supplied = Path(output).expanduser()
        if not supplied.is_absolute():
            raise ValueError("--output must be an absolute path")
        target = supplied.resolve()
        from output_paths import guard_output
        guard_output(target)
        protected = [ROOT, ROOT.parent.parent / "runtime", ROOT.parent.parent / "engine-cache",
                     Path(tempfile.gettempdir()).resolve() / "mingxue-master-cache"]
        protected.extend(Path(os.environ[key]).expanduser().resolve() for key in
                         ("MINGXUE_RESOURCE_DIR", "MINGXUE_CACHE_DIR") if os.environ.get(key))
        if (any(target.is_relative_to(p.resolve()) for p in protected)
                or any(p.name.casefold() in {"runtime", "cache", "engine-cache", "__pycache__", "mingxue-master-cache"}
                       for p in (target, *target.parents))):
            raise ValueError("output must be outside the skill, runtime and cache directories")
        if target.exists():
            raise ValueError("output already exists; choose a new path to preserve the original")
        value = {**value, "output_path": str(target)}
    rendered = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(rendered)
    print(rendered, end="")


def reduce_number(number, masters=(11, 22, 33)):
    if type(number) is not int or number < 0:
        raise ValueError("reduction requires a nonnegative integer")
    if not isinstance(masters, (tuple, list)) or any(type(n) is not int or n not in (11, 22, 33) for n in masters):
        raise ValueError("masters may contain only 11, 22 and 33")
    trace = [number]
    while number > 9 and number not in masters:
        number = sum(int(digit) for digit in str(number))
        trace.append(number)
    return {"number": number, "trace": trace, "is_master": number in masters}


def parse_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("date must be an actual Gregorian date in YYYY-MM-DD form")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("date must be an actual Gregorian date in YYYY-MM-DD form") from exc


def _date_number(year, month, day, method, masters):
    components = {"year": year, "month": month, "day": day}
    if method == "all-digits":
        raw = f"{year:04}{month:02}{day:02}"
        result = reduce_number(sum(int(n) for n in raw), masters)
        return {"digits": raw, "digit_sum": result["trace"][0], "reduction": result}
    parts = {key: reduce_number(value, masters) for key, value in components.items()}
    result = reduce_number(sum(item["number"] for item in parts.values()), masters)
    return {"components": parts, "component_sum": result["trace"][0], "reduction": result}


def name_expression(latin_name, masters=(11, 22, 33)):
    if not isinstance(latin_name, str) or not re.fullmatch(r"[A-Za-z '\-]+", latin_name) or not re.search(r"[A-Za-z]", latin_name):
        raise ValueError("latin-name accepts ASCII A-Z/a-z plus spaces, apostrophes and hyphens; supply your own transliteration explicitly")
    letters = [c for c in latin_name.upper() if c in LETTER_VALUES]
    values = [LETTER_VALUES[c] for c in letters]
    return {"input": latin_name, "letters": "".join(letters), "values": values,
            "mapping": LETTER_VALUES, "sum": sum(values),
            "reduction": reduce_number(sum(values), masters),
            "transliteration": "none; no Han-character pinyin or diacritic conversion"}


def numerology(birth_date, *, year=None, masters=(11, 22, 33), method="all-digits", latin_name=None):
    born = parse_date(birth_date)
    # Validate configuration even when an intermediate value happens to be 1..9.
    reduce_number(0, masters)
    if method not in ("all-digits", "component"):
        raise ValueError("method must be all-digits or component")
    if year is not None and (type(year) is not int or not 1 <= year <= 9999):
        raise ValueError("target year must be an integer in 1..9999")
    result = {"schema_version": 1, "system": "numerology", "status": "calculated", "birth_date": born.isoformat(),
              "convention": {"method": method, "preserve_master_numbers": list(masters),
                             "master_rule": "stop at a configured master encountered during reduction; do not manufacture one",
                             "year_boundary": "January 1 for personal year; no birthday boundary",
                             "calendar": "Gregorian; no timezone conversion"},
              "life_path": _date_number(born.year, born.month, born.day, method, masters),
              "personal_year": None, "name_expression": None,
              "interpretation_scope": "Cultural number symbolism for reflection; no personality test or factual prediction."}
    if year is not None:
        result["personal_year"] = {"year": year, **_date_number(year, born.month, born.day, method, masters),
                                   "rule": "birth month/day plus target year; February 29 stays month=2, day=29 even in non-leap years"}
    if latin_name is not None:
        result["name_expression"] = name_expression(latin_name, masters)
    return result


class CounterRandom:
    """Versioned integer sampler: reproducible without Python random details."""
    def __init__(self, seed):
        if type(seed) is not int or not 0 <= seed < 2**256:
            raise ValueError("seed must be an integer in 0..2^256-1")
        self.seed, self.counter = seed, 0

    def randbelow(self, bound):
        if type(bound) is not int or not 1 <= bound <= 78:
            raise ValueError("sampling bound must be 1..78")
        limit = 2**256 - (2**256 % bound)
        while True:
            data = f"{DRAW_ALGORITHM}|{self.seed}|{self.counter}".encode("ascii")
            self.counter += 1
            value = int.from_bytes(hashlib.sha256(data).digest(), "big")
            if value < limit:
                return value % bound


def parse_manual_cards(text):
    if not isinstance(text, str) or not text:
        raise ValueError("cards must be card-id:upright or card-id:reversed, comma separated")
    result = []
    for token in text.split(","):
        parts = token.split(":")
        if len(parts) != 2 or parts[0] not in CARD_INDEX or parts[1] not in ("upright", "reversed"):
            raise ValueError(f"invalid manual card {token!r}; use an exact deck id and upright/reversed")
        result.append((parts[0], parts[1]))
    return result


def tarot(spread="three", *, seed=None, cards=None, question="", upright_only=False):
    if spread not in SPREADS:
        raise ValueError("unknown spread")
    if not isinstance(question, str):
        raise ValueError("question must be text")
    if type(upright_only) is not bool:
        raise ValueError("upright_only must be boolean")
    name, positions = SPREADS[spread]
    if cards is not None:
        if seed is not None or upright_only:
            raise ValueError("manual cards cannot be combined with seed or upright-only sampling")
        picked = parse_manual_cards(cards)
        if len(picked) != len(positions):
            raise ValueError(f"{spread} requires exactly {len(positions)} manual cards")
        if len({c[0] for c in picked}) != len(picked):
            raise ValueError("manual cards must be unique within a single-deck spread")
        randomness = {"source": "user_supplied_cards", "seed": None, "algorithm": None}
    else:
        final_seed = secrets.randbits(128) if seed is None else seed
        rng = CounterRandom(final_seed)
        pool, picked = [card["id"] for card in DECK], []
        for _ in positions:
            card_id = pool.pop(rng.randbelow(len(pool)))
            orientation = "upright" if upright_only or rng.randbelow(2) == 0 else "reversed"
            picked.append((card_id, orientation))
        randomness = {"source": "virtual_draw", "seed": str(final_seed), "algorithm": DRAW_ALGORITHM,
                      "seed_origin": "generated_by_secrets" if seed is None else "caller_supplied",
                      "sampling": "uniform without replacement; each enabled orientation has probability 1/2",
                      "upright_only": upright_only, "question_affects_draw": False,
                      "deck_order": DECK_ID, "counter_blocks_used": rng.counter}
    spread_cards = []
    for i, ((card_id, orientation), position) in enumerate(zip(picked, positions)):
        card = CARD_INDEX[card_id]
        theme = card["theme"]
        spread_cards.append({**card, "position_index": i + 1, "position": position, "orientation": orientation,
                             "orientation_label": "正位" if orientation == "upright" else "逆位",
                             "symbolic_lens": theme if orientation == "upright" else theme + "：可检视受阻、过度或内化的一面",
                             "reflection_question": f"在“{position}”上，“{theme}”让你想到什么可核实的经历或可选行动？"})
    return {"schema_version": 1, "system": "tarot", "status": "recorded", "deck_id": DECK_ID,
            "deck_size": len(DECK), "spread": spread, "spread_name": name, "positions": list(positions),
            "question": question, "randomness": randomness, "cards": spread_cards,
            "interpretation_scope": "Recorded virtual or user-supplied cards and cultural symbols; no physical draw, supernatural event, medical or financial outcome is asserted."}


def probe():
    return {"status": "ready", "network": "not_used", "dependencies": "python_standard_library",
            "numerology": {"life_path": True, "personal_year": True, "latin_name_expression": True,
                           "methods": ["all-digits", "component"], "master_options": list(MASTER_OPTIONS)},
            "tarot": {"deck_id": DECK_ID, "cards": len(DECK), "unique_ids": len(CARD_INDEX),
                      "draw_algorithm": DRAW_ALGORITHM, "spreads": {key: len(value[1]) for key, value in SPREADS.items()},
                      "manual_cards": True, "upright_reversed": True}}


def main(argv=None):
    parser = JsonParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--probe", action="store_true")
    sub = parser.add_subparsers(dest="command", parser_class=JsonParser)
    numbers = sub.add_parser("numerology", allow_abbrev=False)
    numbers.add_argument("--date")
    numbers.add_argument("--year", type=int)
    numbers.add_argument("--masters", choices=MASTER_OPTIONS, default="11,22,33")
    numbers.add_argument("--method", choices=("all-digits", "component"), default="all-digits")
    numbers.add_argument("--latin-name")
    cards = sub.add_parser("tarot", allow_abbrev=False)
    cards.add_argument("--spread", choices=SPREADS, default="three")
    cards.add_argument("--seed", type=int)
    cards.add_argument("--cards", help="e.g. major-00:upright,cups-02:reversed,swords-ace:upright")
    cards.add_argument("--question", default="")
    cards.add_argument("--upright-only", action="store_true")
    cards.add_argument("--list-deck", action="store_true")
    for child in (numbers, cards):
        child.add_argument("--output", help="new absolute JSON path outside skill/runtime/cache")
        child.add_argument("--probe", action="store_true", default=argparse.SUPPRESS)
    try:
        args = parser.parse_args(argv)
        if args.probe:
            value = probe()
        elif args.command == "numerology":
            value = numerology(args.date, year=args.year, masters=MASTER_OPTIONS[args.masters],
                               method=args.method, latin_name=args.latin_name)
        elif args.command == "tarot":
            if args.list_deck:
                if args.seed is not None or args.cards is not None or args.upright_only:
                    raise ValueError("list-deck cannot be combined with draw/card inputs")
                value = {"system": "tarot", "deck_id": DECK_ID, "cards": list(DECK)}
            else:
                value = tarot(args.spread, seed=args.seed, cards=args.cards, question=args.question,
                              upright_only=args.upright_only)
        else:
            raise ValueError("choose numerology or tarot, or use --probe")
        write_result(value, getattr(args, "output", None))
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
