"""Offline visual Lenormand layouts and Western geomantic shield/house charts."""
import argparse
from copy import deepcopy
import hashlib
from html import escape
import json
import math
from pathlib import Path
import re
import secrets
import sys

sys.dont_write_bytecode = True
RULE_VERSION = "oracles-visual-v1"
RANDOM_ALGORITHM = "sha256-counter-rejection-v1"
CARD_ROWS = (
    ("骑士", "♞", "消息", "来访", "启动"), ("四叶草", "☘", "小机会", "轻快", "短暂"),
    ("船", "⛵", "距离", "探索", "移动"), ("房子", "⌂", "居所", "根基", "私域"),
    ("树", "♣", "成长", "积累", "根系"), ("云", "☁", "模糊", "不确定", "待澄清"),
    ("蛇", "∿", "曲折", "策略", "复杂性"), ("棺材", "▱", "结束", "暂停", "告别"),
    ("花束", "✿", "礼遇", "欣赏", "美感"), ("镰刀", "◜", "切分", "取舍", "突然性"),
    ("鞭子", "〰", "反复", "磨合", "争论"), ("鸟", "⌁", "交流", "议论", "躁动"),
    ("孩子", "●", "起步", "小规模", "新鲜感"), ("狐狸", "◇", "审慎", "灵活", "自我保护"),
    ("熊", "◆", "力量", "照护", "资源管理"), ("星星", "✧", "方向", "愿景", "连结"),
    ("鹳", "↗", "变化", "迁移", "改善"), ("狗", "◈", "信任", "同伴", "支持"),
    ("塔", "♜", "制度", "界限", "独立"), ("花园", "❀", "公开场合", "社群", "相遇"),
    ("山", "△", "阻力", "距离", "耐心"), ("岔路", "Y", "选项", "分流", "决定"),
    ("老鼠", "∙∙", "消耗", "琐碎", "损耗"), ("心", "♡", "喜爱", "关怀", "情感"),
    ("戒指", "○", "约定", "循环", "联结"), ("书", "▣", "学习", "资料", "未明信息"),
    ("信", "✉", "文字消息", "记录", "文件"), ("男士", "人", "人物位", "所指人物", "关系视角"),
    ("女士", "人", "人物位", "所指人物", "关系视角"), ("百合", "⚜", "平和", "成熟", "分寸"),
    ("太阳", "☀", "清晰", "活力", "可见性"), ("月亮", "☽", "感受", "声誉", "周期"),
    ("钥匙", "⚿", "入口", "关键点", "开启"), ("鱼", "⋈", "流动", "交换", "资源"),
    ("锚", "⚓", "稳定", "持续", "依托"), ("十字架", "✚", "负担", "责任", "信念"),
)
LENORMAND_CARDS = tuple({"number": i, "id": f"lenormand-{i:02}", "name": row[0],
                         "symbol": row[1], "keywords": list(row[2:])}
                        for i, row in enumerate(CARD_ROWS, 1))
SPREADS = {"pair": ("双牌", 2), "three": ("三牌", 3), "nine": ("九宫格", 9), "grand": ("大桌阵", 36)}
FIGURE_ROWS = (
    ("1111", "Via", "路", "移动", "变化"), ("2222", "Populus", "众", "集合", "回应"),
    ("1222", "Laetitia", "喜悦", "舒展", "轻快"), ("2221", "Tristitia", "沉郁", "下沉", "沉淀"),
    ("2122", "Rubeus", "红", "炽烈", "节制"), ("2212", "Albus", "白", "清晰", "审慎"),
    ("1211", "Puella", "少女", "协调", "柔和"), ("1121", "Puer", "少年", "行动", "冲劲"),
    ("2121", "Acquisitio", "增益", "汇集", "接纳"), ("1212", "Amissio", "失落", "放下", "流出"),
    ("2112", "Conjunctio", "结合", "交会", "连接"), ("1221", "Carcer", "拘束", "界限", "停留"),
    ("2111", "Caput Draconis", "龙首", "开端", "进入"), ("1112", "Cauda Draconis", "龙尾", "收尾", "离开"),
    ("2211", "Fortuna Major", "大吉", "积累", "稳固"), ("1122", "Fortuna Minor", "小吉", "助力", "阶段性"),
)
FIGURE_CATALOG = {row[0]: {"code": row[0], "latin_name": row[1], "name": row[2], "keywords": list(row[3:])}
                  for row in FIGURE_ROWS}
LINE_ORDER = ("火", "风", "水", "土")
ROLE_IDS = ("M1", "M2", "M3", "M4", "D1", "D2", "D3", "D4", "N1", "N2", "N3", "N4", "WR", "WL", "J", "R")
ROLE_LABELS = ("母一", "母二", "母三", "母四", "女一", "女二", "女三", "女四", "侄一", "侄二", "侄三", "侄四", "右证人", "左证人", "法官", "调和图")
HOUSE_SOURCE_IDS = {
    "sequential": ROLE_IDS[:12],
    "agrippa": ("M1", "D1", "N1", "M4", "D4", "N4", "M3", "D3", "N3", "M2", "D2", "N2"),
}
LIMITATIONS = {
    "lenormand": ["虚拟抽牌或用户给牌；不声称实体洗牌或超自然事件发生。", "关键词供文化象征和反思，不确证第三方秘密、健康、死亡或财务结果。",
                   "本版无逆位，不实现牌画朝向、骑士跳步或所有流派的大桌阵解释；人物牌不自动推断用户性别或身份。"],
    "geomancy": ["这里是西方点线土占；虚拟生成不等于实际在沙地或纸上划点。", "图名和关键词是文化符号，不构成医疗、财务或其他现实结果的保证。",
                  "宫盘只按所选对应表排图，不计算出生星盘、实际宫头、行星或不同流派的成全法。15图版不含第16调和图。"],
}


def _seed(value):
    if isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]{0,77}", value):
        value = int(value)
    if type(value) is not int or not 0 <= value < 2**256:
        raise ValueError("seed must be an integer or canonical decimal string in 0..2^256-1")
    return value


class _Sampler:
    def __init__(self, system, seed):
        self.system, self.seed, self.counter = system, _seed(seed), 0

    def below(self, bound):
        if type(bound) is not int or not 1 <= bound <= 36:
            raise ValueError("invalid sampler bound")
        cutoff = 2**256 - 2**256 % bound
        while True:
            payload = f"{RULE_VERSION}|{self.system}|{self.seed}|{self.counter}".encode("ascii")
            self.counter += 1
            value = int.from_bytes(hashlib.sha256(payload).digest(), "big")
            if value < cutoff:
                return value % bound


def _randomness(system, seed):
    chosen = secrets.randbits(128) if seed is None else _seed(seed)
    sampler = _Sampler(system, chosen)
    return sampler, {"source": "virtual_draw", "seed": str(chosen), "algorithm": RANDOM_ALGORITHM,
                     "namespace": f"{RULE_VERSION}|{system}", "seed_origin": "generated_by_secrets" if seed is None else "caller_supplied"}


def _question(params):
    value = params.get("question", "")
    if not isinstance(value, str) or len(value) > 2000:
        raise ValueError("question must be text of at most 2000 characters")
    return value


def _unknown(params, allowed):
    if not isinstance(params, dict) or any(not isinstance(k, str) for k in params):
        raise ValueError("params must be a JSON object with string keys")
    extra = set(params) - set(allowed)
    if extra:
        raise ValueError("unsupported parameters: " + ", ".join(sorted(extra)))


def _len_positions(spread, layout):
    count = SPREADS[spread][1]
    if spread == "grand":
        columns, rows = (9, 4) if layout == "9x4" else (8, 5)
    else:
        columns, rows = (3, 3) if spread == "nine" else (count, 1)
    cells = []
    labels = ("左上", "上中", "右上", "左中", "中心", "右中", "左下", "下中", "右下")
    for index in range(count):
        row, col = divmod(index, columns)
        if spread == "grand" and layout == "8x4+4" and index >= 32:
            row, col = 4, index - 32 + 2
        label = labels[index] if spread == "nine" else ("左位" if spread == "pair" and index == 0 else "右位" if spread == "pair" else f"第{index + 1}位")
        item = {"id": f"p{index + 1}", "index": index + 1, "label": label,
                "row": row + 1, "column": col + 1, "x": col * 112, "y": row * 150, "width": 104, "height": 142}
        if spread == "grand":
            item.update(house_number=index + 1, house_name=LENORMAND_CARDS[index]["name"])
        cells.append(item)
    return rows, columns, cells


def _len_svg(cells, width, height):
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="雷诺曼牌阵">',
             '<rect width="100%" height="100%" fill="#f5f2ff"/>']
    for cell in cells:
        x, y = cell["x"] + 4, cell["y"] + 4
        parts.extend((f'<g transform="translate({x} {y})">', '<rect width="104" height="142" rx="12" fill="#fffdf8" stroke="#a99abe"/>',
                      f'<text x="12" y="20" fill="#76638d" font-size="12">{cell["number"]}</text>',
                      f'<text x="52" y="62" text-anchor="middle" fill="#6f4b84" font-size="32">{escape(cell["symbol"])}</text>',
                      f'<text x="52" y="88" text-anchor="middle" font-size="17" fill="#342b42">{escape(cell["name"])}</text>',
                      f'<text x="52" y="108" text-anchor="middle" font-size="10" fill="#62586a">{escape(" · ".join(cell["keywords"][:2]))}</text>',
                      f'<text x="52" y="128" text-anchor="middle" font-size="10" fill="#887895">{escape("宫" + str(cell["house_number"]) + "·" + cell["house_name"] if "house_number" in cell else cell["label"])}</text>', '</g>'))
    parts.append('</svg>')
    return "".join(parts)


def _lenormand(params):
    _unknown(params, ("spread", "layout", "seed", "cards", "significator", "question"))
    spread = params.get("spread", "three")
    if not isinstance(spread, str) or spread not in SPREADS:
        raise ValueError("spread must be pair, three, nine or grand")
    default_layout = "9x4" if spread == "grand" else "3x3" if spread == "nine" else "line"
    layout = params.get("layout")
    if layout is None:
        layout = default_layout
    elif not isinstance(layout, str):
        raise ValueError("layout must be text when supplied")
    allowed_layouts = ("9x4", "8x4+4") if spread == "grand" else (default_layout,)
    if layout not in allowed_layouts:
        raise ValueError("layout is incompatible with the selected spread")
    question = _question(params)
    significator = params.get("significator")
    if significator is not None and (type(significator) is not int or not 1 <= significator <= 36):
        raise ValueError("significator must be a card number in 1..36")
    count, manual, seed = SPREADS[spread][1], params.get("cards"), params.get("seed")
    if manual is not None:
        if seed is not None:
            raise ValueError("manual cards cannot be combined with a sampling seed")
        if not isinstance(manual, list) or len(manual) != count or any(type(n) is not int or not 1 <= n <= 36 for n in manual):
            raise ValueError(f"{spread} requires exactly {count} card numbers in 1..36")
        if len(set(manual)) != count:
            raise ValueError("cards must be unique within one 36-card deck")
        numbers = list(manual)
        randomness = {"source": "user_supplied_cards", "seed": None, "algorithm": None}
    else:
        sampler, randomness = _randomness("lenormand", seed)
        pool, numbers = list(range(1, 37)), []
        for _ in range(count):
            numbers.append(pool.pop(sampler.below(len(pool))))
        randomness.update(counter_blocks_used=sampler.counter, sampling="uniform without replacement; fixed deck numbers 1..36")
    rows, columns, positions = _len_positions(spread, layout)
    cards = [{**deepcopy(LENORMAND_CARDS[n - 1]), **position, "card_id": LENORMAND_CARDS[n - 1]["id"],
              "position_id": position["id"]} for n, position in zip(numbers, positions)]
    groups = {"reading_order": list(range(1, count + 1)), "rows": [[c["index"] for c in cards if c["row"] == r] for r in range(1, rows + 1)]}
    if spread == "nine":
        groups.update(center=5, columns=[[c["index"] for c in cards if c["column"] == col] for col in range(1, 4)], diagonals=[[1, 5, 9], [3, 5, 7]])
    focus = None
    if significator is not None:
        target = next((c for c in cards if c["number"] == significator), None)
        focus = {"card_number": significator, "status": "in_spread" if target else "not_in_spread"}
        if target:
            focus.update(position_index=target["index"], row=target["row"], column=target["column"],
                         neighbors=[c["index"] for c in cards if c["index"] != target["index"]
                                    and abs(c["row"] - target["row"]) <= 1 and abs(c["column"] - target["column"]) <= 1])
    return {"schema_version": 1, "system": "lenormand", "status": "recorded",
            "input": {"spread": spread, "layout": layout, "question": question, "cards": list(manual) if manual is not None else None,
                      "seed": randomness["seed"], "significator": significator},
            "rules": {"version": RULE_VERSION, "deck_size": 36, "reversals": False, "position_order": "top to bottom, left to right; 8x4+4 last four centered in columns 3..6",
                      "grand_houses": "fixed positions 1..36 carry the same-numbered card theme; not the number of the drawn card",
                      "question_affects_draw": False, "artwork": "local text and simple vector card frames; no third-party card paintings"},
            "limitations": list(LIMITATIONS["lenormand"]), "randomness": randomness,
            "spread": {"key": spread, "name": SPREADS[spread][0], "layout": layout, "count": count, "rows": rows, "columns": columns},
            "cards": cards, "groups": groups, "significator": focus,
            "visual": {"type": "lenormand_grid", "width": columns * 112, "height": rows * 150,
                       "cells": deepcopy(cards), "svg": _len_svg(cards, columns * 112, rows * 150)}}


def add_figures(first, second):
    if not isinstance(first, str) or first not in FIGURE_CATALOG or not isinstance(second, str) or second not in FIGURE_CATALOG:
        raise ValueError("figures must use four top-to-bottom digits, each 1 or 2")
    return "".join("2" if a == b else "1" for a, b in zip(first, second))


def derive_shield(mothers, size=16):
    if type(size) is not int or size not in (15, 16):
        raise ValueError("shield_size must be 15 or 16")
    if not isinstance(mothers, list) or len(mothers) != 4 or any(not isinstance(c, str) or c not in FIGURE_CATALOG for c in mothers):
        raise ValueError("mothers must contain exactly four 4-digit figure strings using 1/2")
    values = list(mothers) + ["".join(m[row] for m in mothers) for row in range(4)]
    for offset in range(0, 14, 2):
        values.append(add_figures(values[offset], values[offset + 1]))
    if size == 16:
        values.append(add_figures(values[0], values[14]))
    return dict(zip(ROLE_IDS, values))


def _figure(code):
    return {**deepcopy(FIGURE_CATALOG[code]), "points": [int(n) for n in code],
            "lines": [{"index": i + 1, "element": element, "points": int(n)} for i, (element, n) in enumerate(zip(LINE_ORDER, code))],
            "dot_rows": [[0.5] if n == "1" else [0.28, 0.72] for n in code]}


def _dot_svg(code, center_x, first_y, gap=12, color="#392b4c"):
    result = []
    for row, digit in enumerate(code):
        for offset in ((0,) if digit == "1" else (-8, 8)):
            result.append(f'<circle cx="{center_x + offset:.2f}" cy="{first_y + row * gap:.2f}" r="3.3" fill="{color}"/>')
    return "".join(result)


def _shield_svg(nodes, edges, height):
    by_id = {n["id"]: n for n in nodes}
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 {height}" role="img" aria-label="西方土占盾盘">', '<rect width="100%" height="100%" fill="#f5f2ff"/>']
    for edge in edges:
        if edge["operation"] != "parity_addition":
            continue
        first, second = by_id[edge["from"]], by_id[edge["to"]]
        parts.append(f'<path d="M {first["x"]:.2f} {first["y"] + 82:.2f} L {second["x"]:.2f} {second["y"]:.2f}" stroke="#c7bdd6" fill="none"/>')
    for node in nodes:
        x, y = node["x"], node["y"]
        parts.extend((f'<rect x="{x - 53:.2f}" y="{y:.2f}" width="106" height="90" rx="10" fill="#fffdf8" stroke="#a99abe"/>',
                      f'<text x="{x:.2f}" y="{y + 16:.2f}" text-anchor="middle" font-size="12" fill="#77628c">{escape(node["role"])}</text>',
                      _dot_svg(node["code"], x, y + 30),
                      f'<text x="{x:.2f}" y="{y + 82:.2f}" text-anchor="middle" font-size="12" fill="#392b4c">{escape(node["name"])}</text>'))
    parts.append('</svg>')
    return "".join(parts)


def _house_svg(houses, judge):
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 620 620" role="img" aria-label="西方土占十二宫盘">',
             '<rect width="100%" height="100%" fill="#f5f2ff"/>', '<circle cx="310" cy="310" r="300" fill="#fffdf8" stroke="#c7bdd6"/>']
    for house in houses:
        angle = math.radians(195 - (house["house"] - 1) * 30)
        parts.append(f'<path d="M 310 310 L {310 + 300 * math.cos(angle):.2f} {310 + 300 * math.sin(angle):.2f}" stroke="#ddd5e7"/>')
        x, y = house["x"], house["y"]
        parts.extend((f'<text x="{x:.2f}" y="{y - 32:.2f}" text-anchor="middle" font-size="12" fill="#77628c">{house["house"]}宫 · {escape(house["source_figure"])}</text>',
                      _dot_svg(house["code"], x, y - 16, gap=11),
                      f'<text x="{x:.2f}" y="{y + 34:.2f}" text-anchor="middle" font-size="12" fill="#392b4c">{escape(house["name"])}</text>'))
    parts.extend(('<circle cx="310" cy="310" r="94" fill="#eee7f8" stroke="#b7a5c9"/>',
                  '<text x="310" y="277" text-anchor="middle" font-size="13" fill="#77628c">法官</text>',
                  _dot_svg(judge["code"], 310, 292),
                  f'<text x="310" y="350" text-anchor="middle" font-size="14" fill="#392b4c">{escape(judge["name"])}</text>', '</svg>'))
    return "".join(parts)


def _geomancy(params):
    _unknown(params, ("mothers", "point_counts", "seed", "shield_size", "house_mode", "question"))
    size, house_mode, question = params.get("shield_size", 16), params.get("house_mode", "sequential"), _question(params)
    if type(size) is not int or size not in (15, 16):
        raise ValueError("shield_size must be 15 or 16")
    if not isinstance(house_mode, str) or house_mode not in HOUSE_SOURCE_IDS:
        raise ValueError("house_mode must be sequential or agrippa")
    raw_mothers, counts, seed = params.get("mothers"), params.get("point_counts"), params.get("seed")
    if sum(value is not None for value in (raw_mothers, counts, seed)) > 1:
        raise ValueError("choose mothers, point_counts or seed, not more than one")
    if raw_mothers is not None:
        mothers = list(raw_mothers) if isinstance(raw_mothers, list) else raw_mothers
        derive_shield(mothers, size)  # Validate before making any chart.
        randomness = {"source": "user_supplied_mothers", "seed": None, "algorithm": None}
    elif counts is not None:
        if (not isinstance(counts, list) or len(counts) != 4 or any(not isinstance(row, list) or len(row) != 4 for row in counts)
                or any(type(n) is not int or not 1 <= n <= 1000000 for row in counts for n in row)):
            raise ValueError("point_counts must be four mothers of four positive integer counts in 1..1000000")
        mothers = ["".join("1" if n % 2 else "2" for n in row) for row in counts]
        randomness = {"source": "user_supplied_point_counts", "seed": None, "algorithm": None}
    else:
        sampler, randomness = _randomness("geomancy", seed)
        mothers = ["".join(str(1 + sampler.below(2)) for _ in LINE_ORDER) for _ in range(4)]
        randomness.update(counter_blocks_used=sampler.counter, sampling="16 independent uniform single/double lines; mother 1..4 then top to bottom")
    codes = derive_shield(mothers, size)
    places = {key: (7.5 - index, 0) for index, key in enumerate(ROLE_IDS[:8])}
    places.update({"N1": (7, 1), "N2": (5, 1), "N3": (3, 1), "N4": (1, 1), "WR": (6, 2), "WL": (2, 2), "J": (4, 3), "R": (4, 4)})
    parents = {"N1": ["M1", "M2"], "N2": ["M3", "M4"], "N3": ["D1", "D2"], "N4": ["D3", "D4"],
               "WR": ["N1", "N2"], "WL": ["N3", "N4"], "J": ["WR", "WL"], "R": ["M1", "J"]}
    nodes, edges = [], []
    for index, (key, code) in enumerate(codes.items()):
        x, row = places[key]
        if key.startswith("D"):
            origin = {"operation": "transpose", "parents": list(ROLE_IDS[:4]), "source_line": int(key[1])}
        elif key in parents:
            origin = {"operation": "parity_addition", "parents": parents[key]}
        else:
            origin = {"operation": "input", "parents": []}
        node = {**_figure(code), "id": key, "index": index + 1, "role": ROLE_LABELS[index],
                "row": row + 1, "x": x * 120, "y": row * 112 + 8, "width": 106, "height": 90, "derivation": origin}
        nodes.append(node)
        edges.extend({"from": parent, "to": key, "operation": origin["operation"]} for parent in origin["parents"])
    by_id = {node["id"]: node for node in nodes}
    houses = []
    for number, source in enumerate(HOUSE_SOURCE_IDS[house_mode], 1):
        angle = math.radians(180 - (number - 1) * 30)
        houses.append({**_figure(codes[source]), "house": number, "source_figure": source,
                       "x": round(310 + 226 * math.cos(angle), 6), "y": round(310 + 226 * math.sin(angle), 6)})
    height = (5 if size == 16 else 4) * 112
    judge_even = sum(int(n) for n in codes["J"]) % 2 == 0
    return {"schema_version": 1, "system": "geomancy", "status": "calculated",
            "input": {"mothers": deepcopy(raw_mothers), "point_counts": deepcopy(counts), "seed": randomness["seed"],
                      "shield_size": size, "house_mode": house_mode, "question": question},
            "rules": {"version": RULE_VERSION, "line_order_top_to_bottom": list(LINE_ORDER), "line_encoding": "1=odd/single point; 2=even/double points",
                      "question_affects_draw": False,
                      "addition": "same digits yield 2; different digits yield 1 (odd sum=1, even sum=2)",
                      "daughters": "Dj is line j of mothers M1,M2,M3,M4 in that order",
                      "nieces": {key: value for key, value in parents.items() if key.startswith("N")},
                      "right_witness": ["N1", "N2"], "left_witness": ["N3", "N4"], "judge": ["WR", "WL"],
                      "reconciler": ["M1", "J"] if size == 16 else "not present in the 15-figure variant",
                      "shield_display_order": "left to right top row D4,D3,D2,D1,M4,M3,M2,M1; mathematical IDs are unchanged",
                      "house_mode": house_mode, "house_mapping": [{"house": i + 1, "source_figure": key} for i, key in enumerate(HOUSE_SOURCE_IDS[house_mode])],
                      "house_visual_order": "house 1 at left; house 2 toward lower-left; house 4 at bottom; house 10 at top"},
            "limitations": list(LIMITATIONS["geomancy"]), "randomness": randomness, "initial_mothers": list(mothers),
            "shield": {"size": size, "figures": deepcopy(nodes), "edges": deepcopy(edges), "judge_id": "J", "reconciler_id": "R" if size == 16 else None},
            "house_chart": {"mode": house_mode, "houses": deepcopy(houses), "court_ids": ["WR", "WL", "J"] + (["R"] if size == 16 else [])},
            "checks": {"judge_has_even_total_points": judge_even, "figure_count_matches_variant": len(nodes) == size},
            "visual": {"type": "geomancy", "shield": {"width": 960, "height": height, "nodes": nodes, "edges": edges, "svg": _shield_svg(nodes, edges, height)},
                       "house": {"width": 620, "height": 620, "nodes": houses, "svg": _house_svg(houses, by_id["J"])}}}


def calculate(system, params):
    if system == "lenormand":
        return _lenormand(params)
    if system == "geomancy":
        return _geomancy(params)
    raise ValueError("system must be lenormand or geomancy")


def probe():
    return {"system": "oracles", "status": "ready", "input": {}, "rules": {"version": RULE_VERSION}, "limitations": [],
            "network": "not_used", "dependencies": "python_standard_library", "capabilities": {
                "lenormand": {"cards": 36, "spreads": {k: n[1] for k, n in SPREADS.items()}, "grand_layouts": ["9x4", "8x4+4"], "svg": True},
                "geomancy": {"figures": 16, "shield_sizes": [15, 16], "house_modes": list(HOUSE_SOURCE_IDS), "svg": True}}}


class _JsonParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)

    def print_help(self, file=None):
        print(json.dumps({"system": "oracles", "status": "help", "input": {}, "rules": {"version": RULE_VERSION},
                          "limitations": [], "help": self.format_help()}, ensure_ascii=False), file=file)


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate parameter key: {key}")
        value[key] = item
    return value


def _write_result(result, output=None):
    target = None
    if output is not None:
        from output_paths import guard_output
        supplied = Path(output).expanduser()
        if not supplied.is_absolute():
            raise ValueError("output must be an explicit absolute new file path")
        target = guard_output(supplied)
        if target.exists():
            raise ValueError("output already exists; choose a new path")
        result = {**result, "output_path": str(target)}
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
    print(text, end="")


def main(argv=None):
    parser = _JsonParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("system", nargs="?", choices=("lenormand", "geomancy"))
    parser.add_argument("--params", default="{}", help="JSON object; no automatic file or network input")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--output", help="new absolute JSON path outside installed code/resources/cache")
    args = None
    try:
        args = parser.parse_args(argv)
        if args.probe:
            if args.system is not None or args.params != "{}":
                raise ValueError("probe cannot be combined with a calculation request")
            result = probe()
        else:
            if args.system is None:
                raise ValueError("choose lenormand or geomancy, or use --probe")
            result = calculate(args.system, json.loads(args.params, object_pairs_hook=_unique_object))
        _write_result(result, args.output)
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({"system": getattr(args, "system", None), "status": "error", "input": {},
                          "rules": {"version": RULE_VERSION}, "limitations": [], "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
