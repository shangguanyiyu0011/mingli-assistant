"""Deterministic Mei Hua casting and source-bound classical dream lookup."""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

import iching
from chart import calendar_library
from time_conversion import load_zone

BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
CHINA = timezone(timedelta(hours=8))
ASSETS = Path(__file__).resolve().parents[1] / "assets/classic-oracles"
ELEMENTS = {"乾":"金", "兑":"金", "离":"火", "震":"木", "巽":"木", "坎":"水", "艮":"土", "坤":"土"}


def validate(system, params):
    allowed = {"numbers", "date", "time", "timezone", "fold", "question"} if system == "meihua" else {"text"}
    if not isinstance(params, dict) or set(params) - allowed:
        raise ValueError("参数对象含不支持的字段。")
    if system == "dream":
        value = params.get("text")
        if not isinstance(value, str) or not value.strip() or len(value) > 4000:
            raise ValueError("请用4000字以内的文字描述梦境。")
        return
    if "question" in params and (not isinstance(params["question"], str) or len(params["question"]) > 4000):
        raise ValueError("问题须为4000字以内文字。")
    if "numbers" in params:
        ns = params["numbers"]
        if not isinstance(ns, list) or len(ns) not in (2, 3) or any(type(n) is not int or not 0 <= n <= 10**9 for n in ns):
            raise ValueError("梅花报数须为两个或三个0至十亿的整数。")
        if set(params) & {"date", "time", "timezone", "fold"}:
            raise ValueError("报数法与时间法分别提交，不能混用。")
    elif set(params) & {"date", "time", "timezone", "fold"}:
        _instant(params)


def _instant(p):
    if not all(isinstance(p.get(k), str) and p[k] for k in ("date", "time", "timezone")):
        raise ValueError("时间梅花须明确提问日期、钟点与IANA时区。")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", p["date"]) or not re.fullmatch(r"\d{2}:\d{2}(?::\d{2})?", p["time"]):
        raise ValueError("日期须为YYYY-MM-DD，钟点须为HH:MM或HH:MM:SS。")
    wall = datetime.fromisoformat(p["date"] + "T" + p["time"])
    if not 1583 <= wall.year <= 9998:
        raise ValueError("梅花历法支持1583至9998年。")
    if "fold" in p and (type(p["fold"]) is not int or p["fold"] not in (0, 1)):
        raise ValueError("fold须为0或1。")
    zone = load_zone(p["timezone"])
    candidates = {}
    for fold in (0, 1):
        aware = wall.replace(tzinfo=zone, fold=fold)
        utc = aware.astimezone(timezone.utc)
        back = utc.astimezone(zone)
        if back.replace(tzinfo=None) == wall:
            candidates[utc] = back.fold
    if not candidates:
        raise ValueError("提问钟点在当地不存在。")
    if len(candidates) > 1:
        if "fold" not in p:
            raise ValueError("提问钟点重复，须明确fold后起卦。")
        return next(utc for utc, fold in candidates.items() if fold == p["fold"])
    return next(iter(candidates))


def meihua(p):
    if "numbers" in p:
        values, method = iching.meihua_cast(p["numbers"])
    else:
        instant = _instant(p)
        local = instant.astimezone(CHINA)
        lunar = calendar_library().Solar.fromYmdHms(local.year, local.month, local.day, local.hour, local.minute, local.second).getLunar()
        year = (lunar.getYear() - 4) % 12 + 1
        hour = (local.hour + 1) // 2 % 12 + 1
        subtotal = year + abs(lunar.getMonth()) + lunar.getDay()
        total = subtotal + hour
        values, method = iching.meihua_cast([subtotal, total, total])
        method.update(method="meihua_datetime", original={k:p[k] for k in ("date", "time", "timezone", "fold") if k in p},
            utc=instant.isoformat(), china_clock=local.isoformat(),
            lunar={"year":lunar.getYear(), "month":abs(lunar.getMonth()), "day":lunar.getDay(), "leap":lunar.getMonth()<0,
                   "year_branch_number":year, "year_branch":BRANCHES[year-1], "hour_number":hour, "hour_branch":BRANCHES[hour-1]},
            upper_formula="农历年支序数+月+日，除8余0取8", lower_formula="年支序数+月+日+时支序数，除8余0取8",
            moving_formula="年支序数+月+日+时支序数，除6余0取6", convention="UTC+08中国农历日；00:00换日；闰月同月数；年支按农历年")
    result = iching.build_result(values, method_record=method, question=p.get("question", ""))
    result["system"] = "meihua"
    upper = method["computed"]["upper_number"]
    lower = method["computed"]["lower_number"]
    moving = method["computed"]["moving_position"]
    # Body/use placement follows xuquangeo's MIT calculator; see third-party notices.
    body_number, use_number = (upper, lower) if moving <= 3 else (lower, upper)
    def trigram(number):
        name = iching.TRIGRAM_ROWS[number-1][0]
        return {"number":number, "name":name, "element":ELEMENTS[name]}
    body, use = trigram(body_number), trigram(use_number)
    result["body_use"] = {"body":body, "use":use, "moving_position":moving,
        "body_position":"upper" if moving<=3 else "lower", "use_position":"lower" if moving<=3 else "upper",
        "relation":iching.element_relation(body["element"], use["element"])}
    return result


@lru_cache(maxsize=1)
def _dictionary():
    raw = (ASSETS / "zhougong.json").read_bytes()
    manifest = json.loads((ASSETS / "zhougong-source.json").read_text(encoding="utf-8"))
    if hashlib.sha256(raw).hexdigest() != manifest.get("dataset_sha256"):
        raise ValueError("周公解梦古文词库校验失败。")
    data = json.loads(raw)
    if not isinstance(data, dict) or len(data.get("entries", [])) != 988 or len(data.get("chapters", [])) != 27:
        raise ValueError("周公解梦古文词库不完整。")
    return data, hashlib.sha256(raw).hexdigest()


def _keyword_present(word, text, japanese):
    needle = word.casefold()
    if re.search(r"[가-힣]", needle):
        # Korean particles belong to a noun; syllables inside an unrelated word do not.
        endings = r"에서|으로|에게|한테|부터|까지|처럼|보다|하고|은|는|이|가|을|를|와|과|의|에|로|도|만"
        if needle in {"물", "집", "방", "바다"}:
            endings = r"속에서|속으로|속에|속|" + endings
        particles = r"(?:" + endings + r")?"
        return bool(re.search(r"(?<![가-힣])" + re.escape(needle) + particles + r"(?![가-힣])", text))
    if re.search(r"[a-z]", needle):
        return bool(re.search(r"(?<![a-z])" + re.escape(needle) + r"(?![a-z])", text))
    if japanese and len(needle) == 1 and re.fullmatch(r"[\u3400-\u9fff]", needle):
        return bool(re.search(r"(?<![\u3400-\u9fff])" + re.escape(needle) + r"(?![\u3400-\u9fff])", text))
    return needle in text


def dream(p):
    data, sha = _dictionary()
    text = p["text"]
    lowered = text.casefold()
    japanese = bool(re.search(r"[\u3040-\u30ff]|[月火水木金土日]曜日?", text))
    matches = []
    for entry in data["entries"]:
        words = set(entry.get("aliases", []))
        # Full original clauses are independently searchable; noun aliases avoid guessing a symbol from unrelated prose.
        words.add(entry["text"])
        found = []
        for word in words:
            if not isinstance(word, str) or not word:
                continue
            if _keyword_present(word, lowered, japanese):
                found.append(word)
        if found:
            matches.append({"id":entry["id"], "chapter":entry["chapter"], "text":entry["text"], "matched_keywords":sorted(found),
                "source_line":entry["source_line"], "source_token":entry["source_token"]})
    matches.sort(key=lambda e:(e["text"] not in e["matched_keywords"], -max(map(len, e["matched_keywords"])), -len(e["matched_keywords"]), e["id"]))
    selected = []
    covered = set()
    for entry in matches:
        if set(entry["matched_keywords"]) - covered:
            selected.append(entry)
            covered.update(entry["matched_keywords"])
            if len(selected) == 12:
                break
    selected_ids = {e["id"] for e in selected}
    selected.extend(e for e in matches if e["id"] not in selected_ids)

    return {"schema_version":1, "system":"dream", "status":"calculated", "input":{"text":text},
        "lookup_status":"matched" if matches else "no_match", "matches":selected[:12], "total_matches":len(matches),
        "source":{**data["source"], "dataset_sha256":sha}, "interpretation_scope":"classical_text_lookup",
        "limitations":["古文词条属于传统文本；梦境自述与检索命中不构成现实预测或心理诊断。"]}


def calculate(system, params):
    if system not in ("meihua", "dream"):
        raise ValueError("未知方法。")
    if params == {}:
        return {"system":system, "status":"needs_input", "message":"请描述梦境。" if system=="dream" else "请明确提供报数或提问时刻。"}
    validate(system, params)
    if system == "meihua" and not set(params) & {"numbers", "date"}:
        return {"system":system, "status":"needs_input", "message":"请明确提供报数或提问时刻。"}
    return meihua(params) if system == "meihua" else dream(params)
