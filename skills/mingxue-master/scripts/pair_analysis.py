"""Read-only structural comparison of two already-calculated person snapshots."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
import hashlib
import json
import math
import sys

sys.dont_write_bytecode = True
from astrology import ASPECTS, BODIES, SIGNS_ZH, angular_distance
import pillar_details as pd
from traditional_casts import MANSIONS, MONTH_FULL_MOON, RELATION_NINE, _mansion_relation

VERSION = "pair-structure-v1"
SYSTEMS = ("astrology", "bazi", "sukuyo", "ziwei", "names", "numerology")
TITLES = {"astrology": "西占交叉相位", "bazi": "八字双方结构", "sukuyo": "宿曜有向关系",
          "ziwei": "紫微命身与四化并列", "names": "姓名已知数理并列", "numerology": "数秘已知结构并列"}
PLANET_LABELS = dict(zip(BODIES, ("太阳", "月亮", "水星", "金星", "火星", "木星", "土星", "天王星", "海王星", "冥王星")))
ASPECT_LABELS = {"conjunction": "合相", "sextile": "六合", "square": "刑", "trine": "拱", "opposition": "冲"}
COMMON_LIMITS = ["本合参只读取双方已算结果，不联网、不重排盘、不补时辰、不重新抽牌。",
    "相位、干支及宿曜术语是所选规则中的结构关系，不是现实行为、感情成败或预测概率。",
    "不制造相容性百分分、命运总分或伴侣排名，不保证婚姻，也不判断寿命、健康或投资结果。",
    "出生原输入独立保留，用户问题和主题不会覆盖它；哈希仅定位输入版本，不证明预测有效性。"]


def _canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError("合参输入必须是有限、可序列化的JSON快照。") from exc


def _sha(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _object(value, label):
    if not isinstance(value, dict):
        raise ValueError(label + "须为对象。")
    return value


def _person(value, role):
    if value is None:
        return {"id": role, "label": "甲方" if role == "A" else "乙方", "present": False,
                "person": {}, "birth": None, "results": {}, "package_sha256": None}
    _object(value, role)
    raw = _canonical(value)
    if len(raw) > 20_000_000:
        raise ValueError("每人快照不得超过20MB；请传计算payload而非HTML或图片。")
    saved = json.loads(raw)
    person = _object(saved.get("person", {}), role + ".person")
    label = person.get("name") or ("甲方" if role == "A" else "乙方")
    if not isinstance(label, str) or not label.strip() or len(label) > 120:
        raise ValueError("人物标签须为1..120字文本。")
    birth = saved.get("birth")
    if birth is not None:
        _object(birth, role + ".birth")
    results = _object(saved.get("results", {}), role + ".results")
    if any(not isinstance(key, str) or not isinstance(result, dict) for key, result in results.items()):
        raise ValueError("results须为体系名到已算原始payload的对象映射。")
    return {"id": role, "label": label, "present": True, "person": person, "birth": birth,
            "results": results, "package_sha256": hashlib.sha256(raw).hexdigest()}


def _ref(person, system, pointer):
    result = person["results"][system]
    return {"person": person["id"], "label": person["label"], "system": system,
            "pointer": "/results/" + system + pointer, "result_pointer": pointer,
            "result_sha256": _sha(result), "schema_version": result.get("schema_version")}


def _fact(label, value, refs):
    return {"label": label, "value": value, "refs": refs}


def _panel(system, kind, data, summary, facts, limits=(), partial=False):
    return {"id": "synastry" if system == "astrology" else system, "title": TITLES[system], "kind": kind,
            "status": "partial" if partial else "calculated", "summary": summary, "facts": facts,
            "limits": list(limits), "data": data}


def _known(result, system, schemas=(1,)):
    if type(result.get("schema_version")) is not int or result["schema_version"] not in schemas:
        raise ValueError(system + "原结果的schema_version不受支持。")
    if result.get("status") not in (None, "ok", "calculated", "partial"):
        raise ValueError(system + "原结果尚未计算完成。")
    if system == "bazi" and result.get("system") not in (None, "bazi"):
        raise ValueError("八字结果类型不匹配。")
    if system != "bazi" and result.get("system") not in ({"name_five_grids", "names"} if system == "names" else {system}):
        raise ValueError(system + "结果类型不匹配；请传已算原始payload。")


def _utc(text):
    if not isinstance(text, str):
        raise ValueError("原盘UTC时刻缺失。")
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("原盘UTC格式无效。") from exc
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("原盘候选必须保留物理UTC。")
    return value


def _positions(candidate, person, path):
    _object(candidate, "星盘候选")
    _utc(candidate.get("utc"))
    planets = candidate.get("planets")
    if not isinstance(planets, list) or len(planets) > len(BODIES):
        raise ValueError("原盘须提供至多十个实体的实际黄经列表。")
    rows, seen = [], set()
    for i, item in enumerate(planets):
        _object(item, "天体位置")
        name, lon = item.get("name"), item.get("longitude")
        if name not in BODIES or name in seen or isinstance(lon, bool) or not isinstance(lon, (float, int)) or not math.isfinite(lon) or not 0 <= lon < 360:
            raise ValueError("原盘天体名重复/不支持或黄经无效。")
        seen.add(name)
        rows.append({"name": name, "label": PLANET_LABELS[name], "longitude": lon,
                     "source": _ref(person, "astrology", path + f"/planets/{i}/longitude")})
    return rows


def _wheel(person, result, sample, positions, index, range_record):
    houses = copy.deepcopy(sample.get("houses", {}))
    _object(houses, "原盘宫位")
    asc = houses.get("ascendant") or {}
    anchor = asc.get("longitude", 0)
    if isinstance(anchor, bool) or not isinstance(anchor, (float, int)) or not math.isfinite(anchor):
        anchor = 0
    return {"kind": "ecliptic_wheel", "person": person["id"], "label": person["label"], "candidate_index": index,
            "utc": sample["utc"], "valid_utc_range": range_record, "zodiac": copy.deepcopy(result["zodiac"]),
            "anchor_longitude": anchor, "orientation": "原盘上升在左；缺上升时0白羊在左，两盘独立显示而非合成盘。",
            "points": [{"id": p["name"], "name": p["name"], "label": p["label"], "longitude": p["longitude"],
                        "screen_angle_deg": (180 - (p["longitude"] - anchor)) % 360, "kind": "physical_body", "ref": p["source"]} for p in positions],
            "houses": houses}


def _astro_candidates(person):
    result = person["results"]["astrology"]
    _known(result, "astrology")
    zodiac = _object(result.get("zodiac"), "黄道口径")
    if zodiac.get("type") not in ("tropical", "sidereal") or zodiac["type"] == "sidereal" and not zodiac.get("ayanamsa"):
        raise ValueError("原盘黄道与恒星岁差口径必须明确。")
    if result.get("time_known") is not True or result.get("time_precision") == "shichen":
        return [], ["原盘未明确已知时辰，仅并列其太阳范围，不把中午或候选代表点补成出生盘。"]
    candidates = result.get("candidates")
    if not isinstance(candidates, list) or not candidates or len(candidates) > 32:
        raise ValueError("已知时辰原盘须保留1..32个实际UTC候选。")
    normalized, limits = [], []
    for i, candidate in enumerate(candidates):
        path = f"/candidates/{i}"
        points = _positions(candidate, person, path)
        interval = _object(candidate.get("valid_utc_range"), "候选UTC区间")
        start, end = _utc(interval.get("start")), _utc(interval.get("end"))
        if (start != _utc(candidate["utc"]) or end < start or type(interval.get("end_exclusive")) is not bool
                or interval["end_exclusive"] != (end != start)):
            raise ValueError("原盘代表时刻与保留UTC区间不一致。")
        uncertain = start != end or candidate.get("representative_only") is True
        endpoints = [{"role": "start", "utc": candidate["utc"], "positions": points}]
        if uncertain:
            limit = candidate.get("end_limit")
            if isinstance(limit, dict):
                if _utc(limit.get("utc")) != end:
                    raise ValueError("原盘终点采样与UTC区间不一致。")
                endpoints.append({"role": "exclusive_end_limit", "utc": limit["utc"],
                                  "positions": _positions(limit, person, path + "/end_limit")})
            else:
                limits.append(person["label"] + "的区间缺终点位置；只列已有采样，不补算。")
        missing = [body for body in BODIES if body not in {p["name"] for p in points}]
        normalized.append({"index": i, "utc": candidate["utc"], "valid_utc_range": copy.deepcopy(interval),
                           "representative_only": uncertain, "positions": points, "endpoint_samples": endpoints,
                           "missing_bodies": missing,
                           "wheel": _wheel(person, result, candidate, points, i, copy.deepcopy(interval))})
    if len(normalized) > 1:
        limits.append(person["label"] + "有多个真实UTC候选，逐项与另一方组合，未暗选第一盘。")
    if any(row["representative_only"] for row in normalized):
        limits.append("分钟区间的起点与独占终点仅为已有边界采样，不是全区间相位包络或精确出生时刻。")
    return normalized, limits


def cross_aspects(positions_a, positions_b):
    """Pure longitude geometry. A/B identities are never merged or deduplicated."""
    rows = []
    for first in positions_a:
        for second in positions_b:
            separation = angular_distance(first["longitude"], second["longitude"])
            for name, target, allowed in ASPECTS:
                orb = abs(separation - target)
                if orb <= allowed:
                    rows.append({"bodyA": first["name"], "bodyB": second["name"], "labelA": first["label"], "labelB": second["label"],
                                 "longitudeA": first["longitude"], "longitudeB": second["longitude"], "angle": separation,
                                 "aspect": name, "label": ASPECT_LABELS[name], "exact_angle": target, "orb": orb, "allowed_orb": allowed,
                                 "refs": [first["source"], second["source"]]})
    return sorted(rows, key=lambda row: (row["orb"], row["bodyA"], row["bodyB"], row["exact_angle"]))


def _synastry(a, b):
    ra, rb = a["results"]["astrology"], b["results"]["astrology"]
    ca, la = _astro_candidates(a)
    cb, lb = _astro_candidates(b)
    comparable = ra["zodiac"] == rb["zodiac"] and ra.get("frame") == rb.get("frame") and isinstance(ra.get("frame"), str)
    data = {"frame_comparable": comparable, "zodiac": {"A": ra["zodiac"], "B": rb["zodiac"]},
            "frames": {"A": ra.get("frame"), "B": rb.get("frame")}, "wheels": {"A": [c["wheel"] for c in ca], "B": [c["wheel"] for c in cb]},
            "candidate_pairs": [], "cross_aspects": [], "source_sun_ranges": {"A": ra.get("sun_ranges", []), "B": rb.get("sun_ranges", [])},
            "aspect_policy": [{"name": name, "angle": angle, "orb": orb} for name, angle, orb in ASPECTS]}
    limits = la + lb + ["跨出生盘角距是各自所选黄道中的黄经关系，不是同一天视场的天体夹角，也不是合成中点盘。"]
    if not comparable:
        limits.append("双方黄道/岁差或坐标框架不一致或未声明，仅并列原盘，不混算交叉相位。")
    if comparable:
        for first in ca:
            for second in cb:
                pair = {"candidateA": first["index"], "candidateB": second["index"], "utcA": first["utc"], "utcB": second["utc"],
                        "rangeA": first["valid_utc_range"], "rangeB": second["valid_utc_range"],
                        "representative_only": first["representative_only"] or second["representative_only"],
                        "missing_bodies": {"A": first["missing_bodies"], "B": second["missing_bodies"]},
                        "cross_aspects": cross_aspects(first["positions"], second["positions"]), "boundary_samples": []}
                if pair["representative_only"]:
                    for x in first["endpoint_samples"]:
                        for y in second["endpoint_samples"]:
                            pair["boundary_samples"].append({"sampleA": x["role"], "sampleB": y["role"], "utcA": x["utc"], "utcB": y["utc"],
                                                              "cross_aspects": cross_aspects(x["positions"], y["positions"])})
                data["candidate_pairs"].append(pair)
    if len(data["candidate_pairs"]) == 1:
        data["cross_aspects"] = data["candidate_pairs"][0]["cross_aspects"]
        data["cross_aspects_are_representative"] = data["candidate_pairs"][0]["representative_only"]
    partial = (not comparable or not ca or not cb or len(ca) != 1 or len(cb) != 1
               or any(c["representative_only"] or c["missing_bodies"] for c in ca + cb))
    refs = [_ref(a, "astrology", "/candidates"), _ref(b, "astrology", "/candidates")]
    facts = [_fact("原盘UTC候选数", {"A": len(ca), "B": len(cb)}, refs),
             _fact("保留的候选组合", len(data["candidate_pairs"]), refs),
             _fact("黄道口径", data["zodiac"], [_ref(a, "astrology", "/zodiac"), _ref(b, "astrology", "/zodiac")])]
    return _panel("astrology", "synastry", data, "两张原盘分别显示；每个UTC候选组合的交叉相位单独列出，不把相位数量当相容性分数。", facts, limits, partial)


def _bazi(a, b):
    values = {}
    for person in (a, b):
        result = person["results"]["bazi"]
        _known(result, "bazi", (3,))
        pillars = pd.validate_pillars(result.get("pillars"))
        if result.get("time_known") is False and pillars["hour"] is not None:
            raise ValueError("原盘明示未知时辰却含确定时柱，未将其作为已知柱位比较。")
        values[person["id"]] = {"pillars": copy.deepcopy(pillars), "day_master": pd.stem_info(pillars["day"][0]) if pillars["day"] else None,
                                "time_known": result.get("time_known"), "uncertainty": copy.deepcopy(result.get("uncertainty", [])),
                                "candidate_count": len(result.get("candidates", []))}
    pa, pb = values["A"]["pillars"], values["B"]["pillars"]
    relations = []
    labels = {"stem_combinations": "天干合", "branch_combinations": "地支六合", "branch_clashes": "地支冲", "branch_harms": "地支害", "branch_breaks": "地支破"}
    for ka, va in pa.items():
        if va is None:
            continue
        for kb, vb in pb.items():
            if vb is None:
                continue
            sides = [{"person": "A", "pillar": ka, "value": va}, {"person": "B", "pillar": kb, "value": vb}]
            refs = [_ref(a, "bazi", "/pillars/" + ka), _ref(b, "bazi", "/pillars/" + kb)]
            for kind, rules in pd.PAIR_RULES.items():
                chars = (va[0], vb[0]) if kind == "stem_combinations" else (va[1], vb[1])
                for rule in rules:
                    if frozenset(chars) == frozenset(rule):
                        relations.append({"kind": kind, "label": labels[kind], "rule": rule, "positions": copy.deepcopy(sides), "direction": "symmetric", "refs": refs})
            for group in ("寅巳申", "丑戌未"):
                edges = tuple(zip(group, group[1:] + group[0]))
                for source, target, direction in ((va[1], vb[1], "A_to_B"), (vb[1], va[1], "B_to_A")):
                    if (source, target) in edges:
                        relations.append({"kind": "punishments", "label": "定向刑的跨人符号边", "rule": source + "刑" + target,
                                          "positions": copy.deepcopy(sides), "direction": direction, "group": group,
                                          "source_position": sides[0] if direction == "A_to_B" else sides[1],
                                          "target_position": sides[1] if direction == "A_to_B" else sides[0],
                                          "group_complete": None, "scope": "pair edge only; not a combined personal punishment formation", "refs": refs})
            if {va[1], vb[1]} == {"子", "卯"}:
                relations.append({"kind": "punishments", "label": "子卯互刑符号边", "rule": "子卯相刑", "positions": sides, "direction": "mutual", "refs": refs})
    day_relation = None
    if pa["day"] and pb["day"]:
        first, second = pd.stem_info(pa["day"][0]), pd.stem_info(pb["day"][0])
        offset = (pd.ELEMENTS.index(second["element"]) - pd.ELEMENTS.index(first["element"])) % 5
        day_relation = {"A": first, "B": second, "relation": ("同五行", "A生B", "A克B", "B克A", "B生A")[offset],
                        "A_views_B": pd.ten_god(first["character"], second["character"]), "B_views_A": pd.ten_god(second["character"], first["character"]),
                        "refs": [_ref(a, "bazi", "/pillars/day"), _ref(b, "bazi", "/pillars/day")]}
    data = {"people": values, "day_master_relation": day_relation, "cross_relations": relations,
            "scope": "known consensus pillar positions only; no eight-pillar synthetic chart",
            "matrix": [{"pillarA": ka, "pillarB": kb, "relations": [i for i, row in enumerate(relations)
                        if row["positions"][0]["pillar"] == ka and row["positions"][1]["pillar"] == kb]}
                       for ka in pd.PILLAR_KEYS for kb in pd.PILLAR_KEYS]}
    facts = [_fact("双方已知四柱", {"A": pa, "B": pb}, [_ref(a, "bazi", "/pillars"), _ref(b, "bazi", "/pillars")])]
    if day_relation:
        facts.append(_fact("日主五行关系（术语）", day_relation, day_relation["refs"]))
    limits = ["只用原盘已确定的顶层柱位；不从不确定候选中任取时柱或日柱。",
              "两人的干支绝不并成一个八柱盘；跨人同支不标个人自刑，跨人三支不标任一人的完整三刑/合局。",
              "合冲害刑仅为两侧明确柱位的符号对应，不判断合化、旺衰、吉凶或现实相处行为；五行克制不等于一方伤害另一方。"]
    return _panel("bazi", "bazi_relations", data, "双方日主与已知柱位分别保留，只建立明确来源的跨人符号关系。", facts, limits,
                  any(v is None for v in list(pa.values()) + list(pb.values())))


def _sukuyo(a, b):
    people, tables = {}, []
    partial = False
    for person in (a, b):
        result = person["results"]["sukuyo"]
        _known(result, "sukuyo")
        mansion = _object(result.get("birth_mansion"), "本命宿")
        index = mansion.get("index")
        if (type(index) is not int or not 0 <= index < 27 or mansion.get("name") != MANSIONS[index]
                or mansion.get("id") != "mansion-" + str(index + 1) or mansion.get("label") != MANSIONS[index] + "宿"):
            raise ValueError("本命宿与当前明确的27宿序不一致。")
        table = result.get("month_table")
        valid = isinstance(table, list) and len(table) == 12 and all(isinstance(row, dict) and row.get("month") == i + 1
                  and row.get("fifteenth_day_mansion") == MONTH_FULL_MOON[i]
                  and row.get("first_day_mansion") == MANSIONS[(MANSIONS.index(MONTH_FULL_MOON[i]) - 14) % 27] for i, row in enumerate(table))
        rules = {rule.get("id"): rule for rule in result.get("rules", []) if isinstance(rule, dict)}
        leap_rule = result.get("input", {}).get("leap_rule")
        leap_source = "input.leap_rule"
        if leap_rule is None and "同编号" in rules.get("leap", {}).get("description", ""):
            leap_rule, leap_source = "same_numbered_month", "original rules.leap description"
        if not valid or not {"month_day_table", "three_nines"}.issubset(rules) or leap_rule != "same_numbered_month":
            raise ValueError("宿曜原结果未声明相同月日表/三九/闰月口径；不混用其他27宿算法。")
        tables.append(table)
        people[person["id"]] = {"birth_mansion": copy.deepcopy(mansion), "input": copy.deepcopy(result.get("input")),
                                "rules": copy.deepcopy(result.get("rules")), "month_table": copy.deepcopy(table),
                                "declared_leap_rule": leap_rule, "leap_rule_source": leap_source}
        partial = partial or not mansion.get("lunar", {}).get("date_verified", False) or result.get("status") == "partial"
    first, second = people["A"]["birth_mansion"], people["B"]["birth_mansion"]
    relation = _mansion_relation(first, second)
    refs = [_ref(a, "sukuyo", "/birth_mansion"), _ref(b, "sukuyo", "/birth_mansion"),
            _ref(a, "sukuyo", "/rules"), _ref(b, "sukuyo", "/rules")]
    data = {"people": people, "directed_relation": {**relation, "A_to_B": relation["source_to_target"], "B_to_A": relation["target_to_source"], "refs": refs},
            "same_declared_month_table": tables[0] == tables[1], "visualization": {"kind": "paired_mansion_wheel", "A_index": first["index"], "B_index": second["index"],
            "geometry": "27 calendar-table entries in equal diagram positions, not measured lunar longitude", "nodes": [{"index": i, "label": name + "宿", "is_A": i == first["index"], "is_B": i == second["index"]} for i, name in enumerate(MANSIONS)]}}
    return _panel("sukuyo", "mansion_relation", data, "从双方各自本命宿分别顺数，记录有向三九标签，不换算相处概率。",
                  [_fact("本命宿并列", {"A": first["label"], "B": second["label"]}, refs), _fact("有向三九关系", relation, refs)],
                  ["保留每方原农历日期、核验状态、月日表与闰月约定；未给年份的日期并未被本合参补验。",
                   "这不是月亮黄经、吠陀月宿或日本旧历的替代换算；安坏等名称不等于现实伤害或关系结局。"], partial)


def _ziwei(a, b):
    data, refs, partial = {"comparison_method": "parallel_only; no school-specific marriage rule"}, [], False
    for person in (a, b):
        r = person["results"]["ziwei"]
        _known(r, "ziwei")
        chart = _object(r.get("chart"), "紫微原盘")
        if not isinstance(r.get("natal_mutagens"), list):
            raise ValueError("紫微原盘缺少已算生年四化。")
        data[person["id"]] = {"soul_palace": copy.deepcopy(r.get("soul_palace")), "body_palace": copy.deepcopy(r.get("body_palace")),
            "natal_mutagens": copy.deepcopy(r["natal_mutagens"]), "soul_star": chart.get("soul"), "body_star": chart.get("body"),
            "five_elements_class": chart.get("fiveElementsClass"), "convention": copy.deepcopy(r.get("convention")),
            "source_scope": r.get("scope", "origin"), "source_target": copy.deepcopy(r.get("target"))}
        refs.extend(_ref(person, "ziwei", "/" + key) for key in ("soul_palace", "body_palace", "natal_mutagens", "convention", "scope", "target") if key in r)
        refs.extend(_ref(person, "ziwei", "/chart/" + key) for key in ("soul", "body", "fiveElementsClass") if key in chart)
        partial = partial or r.get("status") == "partial" or len(r["natal_mutagens"]) != 4 or not r.get("soul_palace") or not r.get("body_palace")
    return _panel("ziwei", "parallel", data, "只并列双方命宫、身宫和生年四化，不把任意配对法冒充流派合婚。",
                  [_fact("命身宫与生年四化", {"A": data["A"], "B": data["B"]}, refs)],
                  ["未应用紫微合婚、飞化互投或婚姻成败规则；原盘流运目标只作为来源元数据保留，本处只并列本命字段。"], partial)


def _names(a, b):
    data = {"comparison_method": "parallel_known_structure_only"}
    refs, partial = [], False
    if any(person["results"]["names"].get("mode") == "international" for person in (a,b)):
        for person in (a,b):
            r=person["results"]["names"]
            _known(r,"names")
            keys=("name","mode","writing","pronunciation","latin_numerology") if r.get("mode")=="international" else ("name","strokes","stroke_provenance","rule_id","five_grids","three_talents")
            data[person["id"]]={key:copy.deepcopy(r.get(key)) for key in keys}
            refs.extend(_ref(person,"names","/"+key) for key in keys if key in r and r[key] is not None)
            partial=partial or r.get("status")=="partial"
        return _panel("names","parallel",data,"分别保留双方姓名的原有书写组成与已算数值，不把拉丁字母数和汉字五格视为同一种量。",
                      [_fact("双方姓名的实际结果",{"A":data["A"],"B":data["B"]},refs)],
                      ["未提供的拉丁拼写不自动音译；不同姓名方法不用于相容性评分。"],partial)
    for person in (a, b):
        r = person["results"]["names"]
        _known(r, "names")
        grids = _object(r.get("five_grids"), "单姓名已知五格")
        data[person["id"]] = {k: copy.deepcopy(r.get(k)) for k in ("name", "strokes", "stroke_provenance", "rule_id", "five_grids", "three_talents")}
        refs.extend(_ref(person, "names", "/" + key) for key in ("name", "strokes", "stroke_provenance", "rule_id", "five_grids", "three_talents") if key in r)
        partial = partial or len(grids) != 5 or r.get("status") == "partial"
    data["same_formula_rule"] = data["A"]["rule_id"] == data["B"]["rule_id"] and data["A"]["rule_id"] is not None
    data["same_declared_stroke_provenance"] = data["A"]["stroke_provenance"] == data["B"]["stroke_provenance"]
    return _panel("names", "parallel", data, "姓名只并列已有笔画、五格和三才，笔画口径随原结果保留，不以数理推断两人相容性。",
                  [_fact("双方姓名数理", {"A": data["A"], "B": data["B"]}, refs)],
                  ["不同字库、笔画标准或候选姓名集合不能被当成同一口径；本合参不自动查字库或选择姓名。"], partial)


def _numerology(a, b):
    data = {"comparison_method": "parallel_existing_numbers_no_compatibility_scale"}
    refs = []
    partial = False
    for person in (a, b):
        r = person["results"]["numerology"]
        _known(r, "numerology")
        if not isinstance(r.get("life_path"), dict):
            raise ValueError("数秘原结果缺已算生命路径数。")
        reduction = r["life_path"].get("reduction")
        if not isinstance(reduction, dict) or type(reduction.get("number")) is not int:
            raise ValueError("数秘原结果缺明确归约数值，未重新计算。")
        data[person["id"]] = {k: copy.deepcopy(r.get(k)) for k in ("birth_date", "convention", "life_path", "personal_year", "name_expression")}
        refs.extend(_ref(person, "numerology", "/" + key) for key in ("birth_date", "convention", "life_path", "personal_year", "name_expression") if key in r)
        partial = partial or r.get("status") == "partial"
    data["same_reduction_convention"] = data["A"]["convention"] == data["B"]["convention"] and data["A"]["convention"] is not None
    return _panel("numerology", "parallel", data, "既有生日数、个人年与姓名数按各自归约规则并列，不生成相容性百分比。",
                  [_fact("双方已知数值及归约过程", {"A": data["A"], "B": data["B"]}, refs)],
                  ["原目标年和主数保留规则不被更换；不同目标年或归约法分别阅读，不重新归约或自动转写姓名。"], partial)


def compare_people(a: dict, b: dict, relationship="伴侣") -> dict:
    if not isinstance(relationship, str) or not relationship.strip() or len(relationship) > 80:
        raise ValueError("relationship须为1..80字关系主题，不是预测请求或评分规则。")
    first, second = _person(a, "A"), _person(b, "B")
    people = (first, second)
    evidence = {"algorithm": VERSION, "hash_scope": "supplied JSON snapshots only; not independent astronomical verification or predictive confidence",
                "rules_sha256": _sha({"aspects": ASPECTS, "pillar_pairs": pd.PAIR_RULES, "punishment_cycles": ["寅巳申", "丑戌未"],
                                      "mansion_order": MANSIONS, "month_anchors": MONTH_FULL_MOON, "three_nines": RELATION_NINE}), "people": {}}
    for person in people:
        evidence["people"][person["id"]] = {"label": person["label"], "present": person["present"], "package_sha256": person["package_sha256"],
            "birth_sha256": _sha(person["birth"]) if person["birth"] is not None else None,
            "birth_source": "independent supplied original input; never merged with question fields",
            "results": {system: {"sha256": _sha(r), "schema_version": r.get("schema_version"), "status": r.get("status"),
                                 "input_sha256": _sha(r["input"]) if "input" in r else None, "source_chart": copy.deepcopy(r.get("source_chart"))}
                        for system, r in person["results"].items()}}
    result = {"schema_version": 1, "system": "pair_analysis", "status": "partial", "relationship": relationship,
              "people": [p["label"] for p in people], "person_records": [{k: copy.deepcopy(p[k]) for k in ("id", "label", "person", "birth")} for p in people],
              "panels": [], "limits": list(COMMON_LIMITS), "evidence": evidence, "plot_data": {},
              "not_compared_systems": {p["id"]: [s for s in p["results"] if s not in SYSTEMS] for p in people}}
    functions = {"astrology": _synastry, "bazi": _bazi, "sukuyo": _sukuyo, "ziwei": _ziwei, "names": _names, "numerology": _numerology}
    for system in SYSTEMS:
        if system not in first["results"] and system not in second["results"]:
            continue
        missing = [p["id"] for p in people if system not in p["results"]]
        if missing:
            panel = _panel(system, "unavailable", {"missing_people": missing}, "缺少另一方的同体系已算结果，未补盘或生成配对结论。", [], partial=True)
        else:
            try:
                panel = functions[system](first, second)
            except (ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
                panel = _panel(system, "unavailable", {"source_error": str(exc)}, "原结果字段或规则口径不足，保留来源而不制造合参结论。", [], [str(exc)], True)
        result["panels"].append(panel)
        if system == "astrology" and panel["kind"] == "synastry":
            result["plot_data"]["synastry"] = panel["data"]
    if not result["panels"]:
        result["limits"].append("没有双方可读取的受支持已算结果；请先分别完成个人结果。")
    if not all(p["present"] for p in people):
        result["limits"].append("缺少一方完整人物快照；本结果未伪造第二人。")
    if result["panels"] and all(p["status"] == "calculated" for p in result["panels"]) and all(p["present"] for p in people):
        result["status"] = "calculated"
    return result
