"""Ziwei natal and dated horoscope charts through an isolated engine (ABI 1)."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
from resources import ResourceError

ENGINE_VERSION = "2.6.3"
ENGINE_ABI = 1
SKILL_ROOT = Path(__file__).resolve().parent.parent
BRIDGE = Path(__file__).with_name("ziwei_bridge.cjs")


class ZiweiError(ValueError):
    def __init__(self, status, message, **details):
        super().__init__(message)
        self.status, self.details = status, details


def engine_directory(value=None):
    raw = value or os.environ.get("MINGXUE_ZIWEI_ENGINE")
    if raw:
        result = Path(raw)
    else:
        from runtime_paths import engine_directory as persistent_engine_directory
        result = persistent_engine_directory("ziwei", ENGINE_VERSION)
    result = result.expanduser().resolve()
    if result.is_relative_to(SKILL_ROOT):
        raise ZiweiError("invalid_input", "引擎缓存必须位于 Skill 目录外，避免将第三方依赖放入纯净包。")
    return result


def node_executable():
    from bootstrap import find_node
    try:
        return find_node()
    except (ValueError, OSError) as exc:
        raise ZiweiError("needs_setup", f"未找到健康 Node.js 18+；请显式安装或设置 MINGXUE_NODE。{exc}") from exc


def setup_hint(directory):
    return ["python", "scripts/prepare_ziwei.py", "--engine-dir", str(directory)]


def call_engine(payload, engine_dir=None):
    directory = engine_directory(engine_dir)
    manifest = directory / "node_modules" / "iztro" / "package.json"
    if not manifest.is_file():
        raise ZiweiError("needs_setup", "紫微引擎尚未准备；探针与排盘均不会自动联网安装。",
                         prepare_command=setup_hint(directory), engine_dir=str(directory))
    try:
        version = json.loads(manifest.read_text(encoding="utf-8"))["version"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise ZiweiError("needs_setup", "引擎清单损坏，请在独立缓存重新准备。") from exc
    if version != ENGINE_VERSION:
        raise ZiweiError("needs_setup", f"引擎版本须为 {ENGINE_VERSION}，实际为 {version}。",
                         prepare_command=setup_hint(directory))
    integrity = "legacy_version_only"
    cache_marker = directory / "mingxue-engine.json"
    if cache_marker.is_file():
        try:
            marker = json.loads(cache_marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ZiweiError("engine_integrity_error", "引擎缓存元数据损坏；请显式修复缓存。") from exc
        if not isinstance(marker, dict):
            raise ZiweiError("engine_integrity_error", "引擎缓存元数据格式无效。")
        if marker.get("integrity_schema_version") == 1:
            from prepare_ziwei import verify_engine_directory
            verify_engine_directory(directory, allow_legacy=True)
            integrity = "verified"
    request = dict(payload, engine_dir=str(directory))
    try:
        process = subprocess.run([node_executable(), str(BRIDGE)], input=json.dumps(request, ensure_ascii=False),
                                 text=True, encoding="utf-8", capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ZiweiError("engine_error", f"紫微引擎无法执行：{exc}") from exc
    try:
        result = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise ZiweiError("engine_error", "紫微引擎未返回有效 JSON。") from exc
    if process.returncode or result.get("status") == "engine_error":
        raise ZiweiError("engine_error", result.get("error", "紫微引擎执行失败。"))
    if result.get("engine", {}).get("abi") != ENGINE_ABI:
        raise ZiweiError("engine_error", "紫微引擎适配 ABI 不匹配。")
    result["engine"]["integrity"] = integrity
    return result


def probe(engine_dir=None):
    return call_engine({"action": "probe"}, engine_dir)


def time_index(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{2}:\d{2}(?::\d{2})?", value):
        raise ZiweiError("invalid_input", "时间须为 HH:MM 或 HH:MM:SS。")
    try:
        clock = datetime.fromisoformat("2000-01-01T" + value)
    except ValueError as exc:
        raise ZiweiError("invalid_input", "无效时间。") from exc
    return 12 if clock.hour == 23 else (clock.hour + 1) // 2


def solar_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ZiweiError("invalid_input", "日期须为公历 YYYY-MM-DD。")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ZiweiError("invalid_input", "无效公历日期。") from exc
    # Pinned engine depends on a modern Chinese calendar; no historical extrapolation.
    if not 1900 <= parsed.year <= 2100:
        raise ZiweiError("unsupported_range", "当前紫微适配仅验收公历 1900..2100 年。")
    return value


def resolve_chart(chart):
    """Accept only one resolved schema-3 clock; never take an arbitrary representative."""
    if not isinstance(chart, dict) or chart.get("schema_version") != 3:
        raise ZiweiError("invalid_input", "--chart 仅接受共享 chart.py 的 schema_version=3 JSON。")
    context = chart.get("time_context", {})
    if not isinstance(context, dict) or not isinstance(chart.get("input"), dict):
        raise ZiweiError("invalid_input", "共享盘 time_context/input 须为对象。")
    from chart import validate_shichen
    source = chart["input"]
    try:
        validate_shichen(source.get("shichen"), source.get("time"))
    except ValueError as exc:
        raise ZiweiError("invalid_input", str(exc)) from exc
    if (chart.get("time_precision") == "shichen") != (source.get("shichen") is not None):
        raise ZiweiError("invalid_input", "共享盘须保留时辰输入与 shichen 精度，不能降为准确分钟。")
    if chart.get("time_known") is not True:
        raise ZiweiError("needs_input", "出生时辰未知，不能确定紫微命身宫和星曜；未生成完整盘。", required=["time"])
    if context.get("fold_status") == "unresolved":
        raise ZiweiError("ambiguous_input", "共享盘仍有夏令时重复钟点候选，请先选择 fold。")
    rows = chart.get("candidates")
    if not isinstance(rows, list) or len(rows) != 1:
        raise ZiweiError("ambiguous_input", "共享盘仍有多个时间/四柱候选，请先解决边界或时辰。")
    row = rows[0]
    if not isinstance(row, dict) or not isinstance(row.get("time"), dict):
        raise ZiweiError("invalid_input", "共享盘候选缺少 time 对象。")
    clocks = row.get("time") or {}
    raw = clocks.get("chart_clock")
    if not isinstance(raw, str):
        raise ZiweiError("invalid_input", "共享盘缺少已采用的 chart_clock。")
    try:
        adopted = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ZiweiError("invalid_input", "共享盘 chart_clock 无效。") from exc
    # A shared minute might cross a solar-clock boundary while retaining one Bazi
    # tuple. Conservative rejection avoids silently selecting the first second.
    uncertainty = chart.get("uncertainty", [])
    if not isinstance(uncertainty, list) or any(not isinstance(item, dict) for item in uncertainty):
        raise ZiweiError("invalid_input", "共享盘 uncertainty 须为对象数组。")
    for item in uncertainty:
        if item.get("code") in {"solar_clock_near_boundary", "within_input_calendar_dates"}:
            raise ZiweiError("ambiguous_input", "共享盘在日界/时辰边缘，请补充精确时间后再排完整紫微盘。")
    if chart.get("time_precision") == "shichen":
        from time_conversion import chart_clock, load_zone
        from astrology import validate_chart
        try:
            ranges = validate_chart(chart)
            zone = load_zone(context.get("timezone"))
            possible = set()
            for a, b in ranges:
                for instant in (a + min(timedelta(seconds=0.5), (b - a) / 2), b - min(timedelta(seconds=0.5), (b - a) / 2)):
                    wall = chart_clock(instant, zone, source.get("time_basis", "local-clock"),
                                       source.get("longitude"), source.get("true_solar", False))
                    possible.add((wall.date().isoformat(), time_index(wall.strftime("%H:%M:%S"))))
        except ValueError as exc:
            raise ZiweiError("invalid_input", "共享盘的时辰区间或时间口径无效。") from exc
        if len(possible) != 1:
            raise ZiweiError("ambiguous_input", "时辰区间仍跨历日、早晚子或采用时辰边界，未选择任一候选。")
        day, index = possible.pop()
        return {"solar_date": solar_date(day), "time_index": index,
                "clock_source": "shared_chart.schema3.time_context.valid_utc_ranges",
                "adopted_clock": None, "time_precision": "shichen", "valid_utc_ranges": context["valid_utc_ranges"],
                "time_basis": context.get("chart_time_basis"), "timezone": context.get("timezone"),
                "gender": source.get("gender"),
                "shared_calendar_note": "完整真实区间内采用历日与时辰一致；没有将代表分钟作为出生钟点。"}
    return {"solar_date": solar_date(adopted.date().isoformat()), "time_index": time_index(adopted.strftime("%H:%M:%S")),
            "clock_source": "shared_chart.schema3.candidates[0].time.chart_clock",
            "adopted_clock": raw, "time_basis": clocks.get("chart_time_basis", context.get("chart_time_basis")),
            "timezone": context.get("timezone"), "gender": (chart.get("input") or {}).get("gender"),
            "shared_calendar_note": "紫微农历按已采用钟点的公历日由引擎换算；不是共享八字盘的固定 UTC+08 农历标签。"}


def stable_chart(charts):
    """Intersect two real engine results if no gender was supplied."""
    first = charts[0]
    if len(charts) == 1:
        return first, []
    other, omitted = charts[1], []
    result = {}
    for key, value in first.items():
        if key in {"gender", "palaces"}:
            continue
        if value == other.get(key):
            result[key] = value
        else:
            omitted.append(key)
    result["gender"] = None
    result["palaces"] = []
    for left, right in zip(first["palaces"], other["palaces"]):
        row = {}
        for key, value in left.items():
            if key in {"majorStars", "minorStars", "adjectiveStars"}:
                row[key] = [star for star in value if star in right.get(key, [])]
                if row[key] != value or row[key] != right.get(key):
                    omitted.append(f"palaces[{left['index']}].{key}.gender_dependent_stars")
            elif key in {"decadal", "ages", "changsheng12", "boshi12"}:
                # These are gender-sensitive traditional-rule families even on a
                # particular date where one returned value happens to coincide.
                omitted.append(f"palaces[{left['index']}].{key}")
            elif value == right.get(key):
                row[key] = value
            else:
                omitted.append(f"palaces[{left['index']}].{key}")
        result["palaces"].append(row)
    return result, omitted


FLOW_SCOPES = ("yearly", "monthly", "daily")


def resolve_target(scope, target_date=None, target_time=None, target_index=None):
    if scope not in ("origin", *FLOW_SCOPES):
        raise ZiweiError("invalid_input", "scope 须为 origin/yearly/monthly/daily。")
    if scope == "origin":
        if any(item is not None for item in (target_date, target_time, target_index)):
            raise ZiweiError("invalid_input", "提供流运目标时必须明确 --scope yearly/monthly/daily。")
        return None
    if target_date is None or target_time is None and target_index is None:
        raise ZiweiError("needs_input", "流运需要显式目标公历日期和目标钟点/时辰；不会取系统今天或补时辰。",
                         required=["target_date", "target_time or target_index"])
    solar_date(target_date)
    if target_time is not None and target_index is not None:
        raise ZiweiError("invalid_input", "target_time 与 target_index 只能提供一个。")
    if target_index is not None and (type(target_index) is not int or not 0 <= target_index <= 12):
        raise ZiweiError("invalid_input", "target_index 须为 0..12（0 早子，12 晚子）。")
    return {"date": target_date, "time": target_time,
            "time_index": time_index(target_time) if target_time is not None else target_index,
            "time_basis": "as-supplied adopted wall-clock", "calendar": "solar", "timezone": None}


def _flow_layer(item, scope, natal_palaces):
    """Validate genuine flow fields and map their physical palace indices."""
    if not isinstance(item, dict):
        raise ZiweiError("engine_error", f"引擎缺少真实 {scope} 流运数据。")
    names, mutagens, stars = item.get("palaceNames"), item.get("mutagen"), item.get("stars")
    if (type(item.get("index")) is not int or not 0 <= item["index"] < 12 or
        not isinstance(names, list) or len(names) != 12 or not all(isinstance(name, str) for name in names) or len(set(names)) != 12 or
        not isinstance(mutagens, list) or len(mutagens) != 4 or not all(isinstance(x, str) and x for x in mutagens) or
        not isinstance(stars, list) or len(stars) != 12 or any(not isinstance(group, list) for group in stars)):
        raise ZiweiError("engine_error", f"引擎 {scope} 流运宫位/四化/流曜不完整。")
    for group in stars:
        if any(not isinstance(star, dict) or not star.get("name") or star.get("scope") != scope for star in group):
            raise ZiweiError("engine_error", f"引擎 {scope} 流曜作用层级不符，不能用本命星曜代替。")
    flow_mutagens = []
    for transformation, star_name in zip(("禄", "权", "科", "忌"), mutagens):
        locations = [p for p in natal_palaces if any(star.get("name") == star_name for group in
                     ("majorStars", "minorStars", "adjectiveStars") for star in p[group])]
        if len(locations) != 1:
            raise ZiweiError("engine_error", f"流运四化星 {star_name} 未能对应唯一实际本命宫位。")
        place = locations[0]
        flow_mutagens.append({"star": star_name, "mutagen": transformation, "palace_index": place["index"],
                              "natal_palace": place["name"], "scope_palace": names[place["index"]]})
    result = dict(item, data_source="engine.horoscope", flow_mutagens=flow_mutagens)
    result["palaces"] = [{"index": p["index"], "natal_palace": p["name"], "scope_palace": names[p["index"]],
                          "flow_stars": stars[p["index"]],
                          "flow_mutagens": [value for value in flow_mutagens if value["palace_index"] == p["index"]]}
                         for p in natal_palaces]
    return result


def build_horoscope(response, scope, target, natal_palaces, gender, horoscope_divide, day_divide):
    rows = response.get("horoscopes")
    if not isinstance(rows, list) or len(rows) != (1 if gender else 2):
        raise ZiweiError("engine_error", "引擎未返回与实际出生输入对应的流运盘。")
    requested = FLOW_SCOPES[:FLOW_SCOPES.index(scope) + 1]
    result, omitted = {}, []
    for level in requested:
        item = (rows[0].get("layers") or {}).get(level)
        if not gender and item != (rows[1].get("layers") or {}).get(level):
            omitted.append(level)
            continue
        result[level] = _flow_layer(item, level, natal_palaces)
    if scope not in result:
        raise ZiweiError("needs_input", f"所求 {scope} 流运依赖传统规则性别，请明确提供 gender。", required=["gender"])
    context = {}
    for level in ("decadal", "age"):
        value = (rows[0].get("context") or {}).get(level)
        if gender is None:
            context[level] = {"status": "not_calculated", "reason": "requires explicit traditional-rule gender"}
            omitted.append(level)
        elif not isinstance(value, dict) or type(value.get("index")) is not int or not 0 <= value["index"] < 12:
            context[level] = {"status": "unavailable", "reason": "outside engine age/decadal coverage; invalid sentinel was suppressed"}
        else:
            context[level] = value
    lunar = response.get("target_lunar")
    if not isinstance(lunar, dict) or not all(key in lunar for key in ("lunarYear", "lunarMonth", "lunarDay", "isLeap")):
        raise ZiweiError("engine_error", "引擎缺少目标农历日期，不能判定流月/闰月口径。")
    return {"status": "partial" if omitted else "ok", "scope": scope, "target": target,
            "data_source": "engine.horoscope", "solar_date": rows[0].get("solarDate"),
            "lunar_date": rows[0].get("lunarDate"), "target_lunar": lunar, "layers": result, "context": context,
            "gender_dependent_omitted": omitted,
            "convention": {
                "horoscope_divide": horoscope_divide,
                "year_boundary": "农历正月初一" if horoscope_divide == "normal" else "引擎立春日期（并非精确交节瞬间）",
                "month_boundary": "农历月；闰月15/16日分段" if horoscope_divide == "normal" else "引擎节月干支（时辰代表点），流月宫位仍按农历月及闰月半月",
                "target_calendar_basis": "目标采用钟点的公历日给引擎换算农历；不自动使用出生地时区，不取机器当前日期",
                "target_clock_precision": "引擎使用显式时辰的代表点（0取00:30，其余取该时辰起始小时:30），不按输入分秒判定交节",
                "leap_month": "流运固定把闰月1..15日/16日起分段；出生闰月后半月也参与流月定位，独立于本命fix_leap选项",
                "late_zi": "按当日早子计算目标干支；流日宫序使用目标原农历日" if day_divide == "current" else "晚子目标日干支按次日；流日宫序仍使用目标原农历日，这是固定引擎口径，未改作统一切日",
                "age_divide": "normal: 农历年虚岁；仅显式gender时输出大限/小限上下文",
                "index_basis": "index、stars与palaceNames均按本命十二地支宫位的物理索引；flow_mutagens映射到真实本命四化星所在宫",
            }}


def build_ziwei(date_value=None, time_value=None, *, index=None, chart=None, gender=None,
                engine_dir=None, algorithm="default", year_divide="normal", day_divide="forward", fix_leap=True,
                scope="origin", target_date=None, target_time=None, target_index=None, horoscope_divide="normal"):
    target = resolve_target(scope, target_date, target_time, target_index)
    source_chart = None
    if chart is not None:
        if date_value is not None or time_value is not None or index is not None:
            raise ZiweiError("invalid_input", "--chart 与 --date/--time/--time-index 不能混用。")
        birth = resolve_chart(chart)
        # Input-chain identity only; this digest is not predictive confidence.
        source_chart = {"schema_version": 3, "input_hash": hashlib.sha256(json.dumps(
            chart["input"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()}
        inherited_gender = birth.pop("gender")
        if gender is not None and inherited_gender is not None and gender != inherited_gender:
            raise ZiweiError("invalid_input", "显式 gender 与共享盘输入冲突。")
        gender = gender or inherited_gender
    else:
        if time_value is not None and index is not None:
            raise ZiweiError("invalid_input", "--time 与 --time-index 只能提供一个。")
        birth = {"solar_date": solar_date(date_value), "clock_source": "explicit_adopted_wall_clock",
                 "time_basis": "as-supplied; no timezone/DST/solar correction", "timezone": None}
        if time_value is None and index is None:
            raise ZiweiError("needs_input", "紫微完整盘需要明确出生时辰；不会默认补子时或午时。", required=["time or time_index"])
        if index is not None and (type(index) is not int or not 0 <= index <= 12):
            raise ZiweiError("invalid_input", "time_index 须为 0..12（0 早子，12 晚子）。")
        birth["time_index"] = time_index(time_value) if time_value is not None else index
        birth["adopted_clock"] = f"{date_value} {time_value}" if time_value is not None else None
    if gender not in (None, "male", "female"):
        raise ZiweiError("invalid_input", "gender 只能是 male/female；未提供时只输出双规则共有部分。")
    if algorithm not in {"default", "zhongzhou"} or year_divide not in {"normal", "exact"} or day_divide not in {"forward", "current"} or horoscope_divide not in {"normal", "exact"} or type(fix_leap) is not bool:
        raise ZiweiError("invalid_input", "无效流派或历法选项。")
    if target and target["date"] < birth["solar_date"]:
        raise ZiweiError("invalid_input", "流运目标日期早于采用的出生日期。")
    settings = {"algorithm": algorithm, "year_divide": year_divide, "day_divide": day_divide,
                "fix_leap": fix_leap, "horoscope_divide": horoscope_divide}
    payload = dict(action="chart", solar_date=birth["solar_date"], time_index=birth["time_index"], gender=gender, settings=settings)
    if target:
        payload.update(scope=scope, target=target)
    response = call_engine(payload, engine_dir)
    charts = response.get("charts")
    if not isinstance(charts, list) or len(charts) != (1 if gender else 2):
        raise ZiweiError("engine_error", "引擎返回盘数量不符合性别输入约定。")
    result, omitted = stable_chart(charts)
    palaces = result.get("palaces", [])
    if len(palaces) != 12 or len({p.get("index") for p in palaces}) != 12:
        raise ZiweiError("engine_error", "引擎未返回十二个不同宫位。")
    mutagens = [{"palace_index": p["index"], "palace": p["name"], "star": s["name"], "mutagen": s["mutagen"]}
                for p in palaces for group in ("majorStars", "minorStars", "adjectiveStars") for s in p[group] if s.get("mutagen")]
    if len(mutagens) != 4 or {s["mutagen"] for s in mutagens} != {"禄", "权", "科", "忌"}:
        raise ZiweiError("engine_error", "引擎生年四化不完整。")
    soul = next((p for p in palaces if p["name"] == "命宫"), None)
    body = next((p for p in palaces if p.get("isBodyPalace")), None)
    horoscope = build_horoscope(response, scope, target, palaces, gender, horoscope_divide, day_divide) if target else None
    return {"schema_version": 1, "system": "ziwei", "status": "ok" if gender else "partial", "scope": scope, "target": target,
            "engine": response["engine"], "input": dict(birth, gender=gender), "source_chart": source_chart,
            "convention": dict(settings,
                algorithm_detail="引擎通用安星规则" if algorithm == "default" else "引擎中州安星规则（并非全部中州派实践）",
                calendar="公历输入，经引擎按采用钟点的公历日换算中国农历；不调用八字四柱反推紫微星盘",
                calendar_basis="adopted-clock solar calendar date + engine Chinese lunar conversion; not the shared Bazi fixed-UTC+08 lunar label",
                year_boundary="农历正月初一" if year_divide == "normal" else "引擎立春边界",
                late_zi="23:00 晚子按次日安星" if day_divide == "forward" else "23:00 晚子按当日早子安星",
                leap_month="闰月1..15按本月，16日起按次月；晚子 forward 的月份索引沿用引擎特例，不另手工移月" if fix_leap else "闰月不按半月调整",
                time_indices="0=00:00..00:59; 1=01:00..02:59; ...; 11=21:00..22:59; 12=23:00..23:59",
                four_mutagens="引擎所选算法默认生年四化表；不混用其他门派表"),
            "chart": result, "soul_palace": {"index": soul["index"], "name": soul["name"], "branch": soul["earthlyBranch"]} if soul else None,
            "body_palace": {"index": body["index"], "name": body["name"], "branch": body["earthlyBranch"]} if body else None,
            "natal_mutagens": mutagens, "gender_dependent_omitted": omitted, "horoscope": horoscope,
            "limits": ["本命十二宫与生年四化；流运仅在显式目标日期/时辰时另列真实分层数据，不计算匹配率、合盘或自动格局断语。",
                       "engine chineseDate 是紫微引擎自身历法信息，不能覆盖共享八字盘四柱。",
                       "没有性别输入时，分别计算两种传统规则，只保留共有数据；性别相关星曜、长生/博士、大限/小限不作推定。" if not gender else "性别仅按用户显式提供的传统排盘规则使用。"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="隔离引擎紫微本命与显式日期流运排盘；所有结果以 JSON 输出")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--engine-dir")
    parser.add_argument("--date")
    parser.add_argument("--time")
    parser.add_argument("--time-index", type=int)
    parser.add_argument("--chart", type=Path)
    parser.add_argument("--gender", choices=("male", "female"))
    parser.add_argument("--algorithm", choices=("default", "zhongzhou"), default="default")
    parser.add_argument("--year-divide", choices=("normal", "exact"), default="normal")
    parser.add_argument("--day-divide", choices=("forward", "current"), default="forward")
    parser.add_argument("--fix-leap", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--scope", choices=("origin", *FLOW_SCOPES), default="origin")
    parser.add_argument("--target-date")
    parser.add_argument("--target-time")
    parser.add_argument("--target-time-index", type=int)
    parser.add_argument("--horoscope-divide", choices=("normal", "exact"), default="normal")
    args = parser.parse_args(argv)
    try:
        if args.probe:
            result = probe(args.engine_dir)
        else:
            if args.chart:
                from case_lookup import load_chart
                data = load_chart(args.chart)
            else:
                data = None
            result = build_ziwei(args.date, args.time, index=args.time_index, chart=data, gender=args.gender,
                                 engine_dir=args.engine_dir, algorithm=args.algorithm, year_divide=args.year_divide,
                                 day_divide=args.day_divide, fix_leap=args.fix_leap, scope=args.scope,
                                 target_date=args.target_date, target_time=args.target_time, target_index=args.target_time_index,
                                 horoscope_divide=args.horoscope_divide)
        code = 0
    except ZiweiError as exc:
        result = {"system": "ziwei", "status": exc.status, "message": str(exc), **exc.details}
        code = 2
    except (OSError, ValueError, ResourceError) as exc:
        result = {"system": "ziwei", "status": "invalid_input", "message": str(exc)}
        code = 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
