"""Validated, path-free personal intake -> isolated offline personal/pair reports.

Request validation and planning never create report files or start engine preparation.
Only submit() accepts a trusted server-selected reports root, never a request field.
"""
from __future__ import annotations

import copy
from datetime import date, datetime, timedelta, timezone
import html
from html.parser import HTMLParser
import importlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import secrets

import workflow
from chart import build_chart, calendar_library, get_resources, validate_shichen
from output_paths import protected_output_roots
from project_store import contained, read_json, write_new_json
from time_conversion import load_zone
from fortune import registry

EXTRAS = {"xiaoliuren", "jinkoujue", "qizheng", "taiyi", "sukuyo", "yilin", "lingqijing", "lenormand", "geomancy", "horary", "meihua", "dream"}
PUBLIC_FILES = {"personal-a.html", "personal-b.html", "pair.html"}
_BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
_ROOT_KEYS = {"mode", "people", "preferences", "method_options"}
_PREF_KEYS = {"systems", "topic", "question", "depth", "relationship", "answers", "virtual_draws", "cast", "cast_place", "prepare_engines", "language", "ui_language"}
_METHOD_KEYS = {
    "bazi": {"sect", "true_solar", "yun_sect", "fold", "time_basis"},
    "ziwei": {"algorithm", "year_divide", "day_divide", "fix_leap", "scope", "target_date", "target_time", "target_time_index", "horoscope_divide"},
    "astrology": {"zodiac", "house_system", "ayanamsa"}, "vedic": {"house_system", "ayanamsa"},
    "names": {"stroke_scheme", "stroke_standard", "stroke_reference", "pronunciation", "meaning_note", "surname_reading", "given_reading"},
    "numerology": {"date", "year", "masters", "method", "latin_name"},
    "iching": {"lines", "method", "numbers", "direction", "najia", "seed", "question", "cast_date", "cast_time", "cast_timezone", "cast_sect", "cast_fold", "cast_time_basis", "cast_longitude", "cast_true_solar"},
    "meihua": {"numbers", "date", "time", "timezone", "fold", "question"},
    "dream": set(),
    "tarot": {"spread", "seed", "cards", "question", "upright_only"},
    "electional": {"date", "days", "time", "topic"},
    "palm": {"observations"}, "face": {"observations"},
    "fengshui": set(), "qimen": set(), "liuren": set(), "human_design": set(),
    "xiaoliuren": {"mode", "numbers", "lunar_month", "lunar_day", "hour_branch", "leap", "leap_rule"},
    "jinkoujue": {"mode", "day_pillar", "hour_branch", "earth_branch", "month_general_branch", "date", "time", "timezone", "sect", "fold", "month_general_rule", "day_night_rule", "day_night"},
    "qizheng": {"date", "time", "timezone", "longitude", "latitude", "fold", "house_system", "zodiac", "ayanamsa", "question", "node_model", "node_orientation", "ziqi"},
    "horary": {"date", "time", "timezone", "longitude", "latitude", "fold", "house_system", "zodiac", "ayanamsa", "question", "quesited_house"},
    "taiyi": {"date", "time", "timezone", "mode", "method"},
    "sukuyo": {"birth", "target", "partner", "leap_rule"},
    "yilin": {"method", "base", "changed", "lines", "iching_result", "seed", "question"},
    "lingqijing": {"method", "counts", "pieces", "seed", "question"},
    "lenormand": {"spread", "layout", "cards", "seed", "significator", "question"},
    "geomancy": {"mothers", "point_counts", "seed", "shield_size", "house_mode", "question"},
}


class IntakeError(ValueError):
    pass


class MissingBasics(IntakeError):
    pass


def _obj(value, allowed, label):
    if not isinstance(value, dict) or set(value) - allowed:
        raise IntakeError(label + "必须为对象，且不得含未知键、路径、引擎或保存位置。")
    return copy.deepcopy(value)


def _text(value, label, maximum=4000, required=False):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()) or "\x00" in value:
        raise IntakeError(label + "须为有效文字。")
    return value


def _int(value, label, low, high):
    if type(value) is not int or not low <= value <= high:
        raise IntakeError(label + "须为范围内整数，不能用布尔值代替。")
    return value


def _number(value, label, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise IntakeError(label + "须为范围内有限数值。")
    return value


def _choice(value, label, values):
    if type(value) not in (str, int) or value not in values:
        raise IntakeError(label + "不是支持的明确选项。")
    return value


def _boolean(value, label):
    if type(value) is not bool:
        raise IntakeError(label + "须为布尔值。")
    return value


def _json_budget(value):
    count, active = 0, set()
    def walk(item, depth=0):
        nonlocal count
        count += 1
        if depth > 24 or count > 20000:
            raise IntakeError("提交数据层数或数量过多。")
        if type(item) in (dict, list):
            if id(item) in active or len(item) > 1000:
                raise IntakeError("提交数据存在循环或过大容器。")
            active.add(id(item))
            if isinstance(item, dict):
                for key, val in item.items():
                    if not isinstance(key, str) or len(key) > 128:
                        raise IntakeError("提交数据的键必须为短文字。")
                    walk(val, depth+1)
            else:
                for val in item:
                    walk(val, depth+1)
            active.remove(id(item))
        elif type(item) is float and not math.isfinite(item):
            raise IntakeError("提交数据不接受NaN或无穷大。")
        elif type(item) not in (str, int, float, bool, type(None)):
            raise IntakeError("提交只接受JSON值。")
    walk(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise IntakeError("提交JSON无效。") from exc
    if len(encoded) > 256000:
        raise IntakeError("提交数据超过256KB。")


def _date_parts(value, label, lunar=False):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise IntakeError(label + "须为YYYY-MM-DD。")
    y,m,d = map(int, value.split("-"))
    if lunar:
        _int(y,label,1,9999); _int(m,label,1,12); _int(d,label,1,30)
    else:
        try:
            date(y,m,d)
        except ValueError as exc:
            raise IntakeError(label + "不是实际公历日期。") from exc
    return y,m,d


def _time(value, label):
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{2}:[0-9]{2}(?::[0-9]{2})?", value):
        raise IntakeError(label + "须为HH:MM或HH:MM:SS，未知请留空。")
    try:
        datetime.fromisoformat("2000-01-01T"+value)
    except ValueError as exc:
        raise IntakeError(label + "不是实际钟点。") from exc
    return value


def _zone(value, label):
    _text(value,label,120,True)
    try:
        load_zone(value,get_resources())
    except (ValueError, OSError) as exc:
        raise IntakeError(label + "须为本地支持的明确IANA时区。") from exc
    return value


def _geo(value, label):
    value = _obj(value,{"latitude","longitude"},label)
    if set(value) not in (set(), {"latitude","longitude"}):
        raise IntakeError(label + "经纬度须成对填写。")
    for key,bound in (("latitude",90),("longitude",180)):
        if key in value:
            _number(value[key],label+"."+key,-bound,bound)
    return value


def _seed(value):
    if isinstance(value,str):
        if not re.fullmatch(r"0|[1-9][0-9]{0,77}",value):
            raise IntakeError("seed须为无前导零的非负十进制整数。")
        value=int(value)
    return _int(value,"seed",0,2**256-1)


def _int_array(value,label,count,low,high):
    if not isinstance(value,list) or len(value) not in count:
        raise IntakeError(label+"数量不符合该方法。")
    return [_int(x,label,low,high) for x in value]


def _lunar_object(value,label):
    value=_obj(value,{"calendar","date","year","month","day","leap"},label)
    calendar=value.get("calendar","lunar")
    _choice(calendar,label+".calendar",{"lunar","solar"})
    if calendar=="solar":
        if set(value)-{"calendar","date"}:
            raise IntakeError(label+"公历日期不能混入农历字段。")
        if "date" in value:
            _date_parts(value["date"],label)
    else:
        if "date" in value:
            raise IntakeError(label+"农历请明确year/month/day，不混date。")
        for key,low,high in (("year",1,9999),("month",1,12),("day",1,30)):
            if key in value:
                _int(value[key],label+key,low,high)
        if "leap" in value:
            _boolean(value["leap"],label+"leap")
    if (calendar=="solar" and "date" in value) or (calendar=="lunar" and {"month","day"}<=set(value)):
        from traditional_casts import _lunar_input
        try:
            _lunar_input(value,label)
        except ValueError as exc:
            raise IntakeError(label+"的历法日期不成立。") from exc
    return value


def _validate_options(system,value):
    p=_obj(value,_METHOD_KEYS[system],"method_options."+system)
    if system == "meihua":
        from new_oracles import validate
        try:
            validate(system,p)
        except ValueError as exc:
            raise IntakeError(str(exc)) from exc
    # Every accepted scalar is checked here; no path-bearing native argument is exposed.
    for key in ("question","topic","latin_name","stroke_standard","stroke_reference","pronunciation","meaning_note","surname_reading","given_reading"):
        if key in p:
            _text(p[key],key,4000)
    for key in ("true_solar","fix_leap","najia","upright_only","cast_true_solar","leap"):
        if key in p:
            _boolean(p[key],key)
    for key in ("sect","yun_sect","cast_sect"):
        if key in p:
            _int(p[key],key,1,2)
    for key in ("fold","cast_fold"):
        if key in p:
            _int(p[key],key,0,1)
    for key in ("target_time_index",):
        if key in p:
            _int(p[key],key,0,12)
    for key in ("latitude","longitude","cast_longitude"):
        if key in p:
            _number(p[key],key,-90 if key=="latitude" else -180,90 if key=="latitude" else 180)
    for key in ("date","target_date","cast_date"):
        if key in p:
            _date_parts(p[key],key)
    for key in ("time","target_time","cast_time"):
        if key in p:
            if _time(p[key],key) is None:
                raise IntakeError(key+"若未知应省略该原生参数。")
    for key in ("timezone","cast_timezone"):
        if key in p:
            _zone(p[key],key)
    if "seed" in p:
        p["seed"]=_seed(p["seed"])
    enums={"time_basis":{"local-clock","standard-time","true-solar-time"},"cast_time_basis":{"local-clock","standard-time","true-solar-time"},
           "algorithm":{"default","zhongzhou"},"year_divide":{"normal","exact"},"day_divide":{"forward","current"},
           "horoscope_divide":{"normal","exact"},"scope":{"origin","yearly","monthly","daily"},
           "house_system":{"P","K","O","R","C","E","W"},"zodiac":{"tropical","sidereal"},
           "ayanamsa":{"lahiri","raman","fagan-bradley"},"stroke_scheme":{"unihan-irG","kangxi"},
           "direction":{"bottom-to-top","top-to-bottom"},"hour_branch":set(_BRANCHES),"earth_branch":set(_BRANCHES),
           "month_general_branch":set(_BRANCHES),"leap_rule":{"same_numbered_month"},
           "month_general_rule":{"explicit","solar_qi","month_branch_he"},"day_night_rule":{"si_xu_day","mao_shen_day"},
           "day_night":{"auto","day","night"},"node_model":{"mean","true"},"node_orientation":{"ascending","descending"},
           "house_mode":{"sequential","agrippa"}}
    for key,values in enums.items():
        if key in p:
            _choice(p[key],key,values)
    if system in ("astrology","qizheng","horary"):
        if p.get("zodiac")=="sidereal" and not p.get("ayanamsa"):
            raise IntakeError("恒星黄道须明确岁差口径。")
        if p.get("zodiac","tropical")=="tropical" and "ayanamsa" in p:
            raise IntakeError("回归黄道不能混入岁差参数。")
        if system=="horary" and p.get("zodiac","tropical")!="tropical":
            raise IntakeError("当前卜卦占星尊贵表仅接受回归黄道。")
    if "ziqi" in p:
        z=_obj(p["ziqi"],{"model","epoch_utc","epoch_longitude","period_days","reference_label"},"ziqi")
        _choice(z.get("model"),"ziqi.model",{"not_calculated","mean_cycle"})
        if z["model"]=="not_calculated" and set(z)!={"model"}:
            raise IntakeError("未计算紫气不能混入均速模型参数。")
        if z["model"]=="mean_cycle":
            if set(z)!={"model","epoch_utc","epoch_longitude","period_days","reference_label"}:
                raise IntakeError("均速紫气须明确全部参考参数。")
            from astral_methods import astro
            try:
                epoch=astro._utc(z["epoch_utc"])
            except (ValueError,TypeError) as exc:
                raise IntakeError("紫气历元须为明确UTC时刻。") from exc
            if not 1583<=epoch.year<=2999:
                raise IntakeError("紫气历元超出支持范围。")
            _number(z["epoch_longitude"],"紫气参考黄经",0,359.99999999999994)
            _number(z["period_days"],"紫气周期",1,10000000)
            _text(z["reference_label"],"紫气模型依据",300,True)
    bounds={"base":(1,64),"changed":(1,64),"lunar_month":(1,12),"lunar_day":(1,30),"quesited_house":(1,12),
            "days":(1,31),"year":(1,9999),"significator":(1,36)}
    for key,(low,high) in bounds.items():
        if key in p:
            _int(p[key],key,low,high)
    if "day_pillar" in p:
        stems="甲乙丙丁戊己庚辛壬癸"
        valid={stems[i%10]+_BRANCHES[i%12] for i in range(60)}
        _choice(p["day_pillar"],"日柱",valid)
    if system=="bazi":
        return p
    methods={"numerology":{"all-digits","component"},"iching":{"manual","coins","meihua"},
             "xiaoliuren":{"numbers","lunar"},"jinkoujue":{"manual","datetime"},
             "yilin":{"pair","lines","coins","iching"},"lingqijing":{"counts","pieces","toss"},
             "taiyi":{"year","month","day","hour"}}
    if system in methods:
        field="mode" if system in ("xiaoliuren","jinkoujue","taiyi") else "method"
        if field in p:
            _choice(p[field],field,methods[system])
    if system=="taiyi" and "method" in p:
        _int(p["method"],"太乙积年法",0,3)
    if "lines" in p:
        p["lines"]=_int_array(p["lines"],"六爻",{6},6,9)
    if "numbers" in p:
        p["numbers"]=_int_array(p["numbers"],"起数",{3} if system=="xiaoliuren" else {2,3},1 if system=="xiaoliuren" else 0,1000000000)
    if system=="yilin":
        from classic_oracles import _params,_iching_input
        _params(system,p)
        if "iching_result" in p:
            _iching_input(p["iching_result"])
    if system=="lingqijing":
        from classic_oracles import _params,_piece_rows
        _params(system,p)
        if "counts" in p:
            p["counts"]=_int_array(p["counts"],"上中下棋数",{3},0,4)
        if "pieces" in p:
            _piece_rows(p["pieces"])
    if system=="iching":
        method=p.get("method","manual")
        if method=="manual" and set(p)&{"seed","numbers"}:
            raise IntakeError("手动六爻不能混入seed或numbers。")
        if method=="coins" and set(p)&{"lines","numbers","direction"}:
            raise IntakeError("软件三钱不能混入实际六爻或数字起卦。")
        if method=="meihua" and set(p)&{"lines","seed","direction"}:
            raise IntakeError("梅花数字法不能混入六爻或seed。")
    if system=="xiaoliuren":
        mode=p.get("mode","numbers")
        if mode=="numbers" and set(p)&{"lunar_month","lunar_day","hour_branch","leap","leap_rule"}:
            raise IntakeError("小六壬报数不能混入农历参数。")
        if mode=="lunar" and "numbers" in p:
            raise IntakeError("小六壬月日时不能混入numbers。")
    if system=="jinkoujue":
        mode=p.get("mode","manual" if set(p)&{"day_pillar","hour_branch","month_general_branch"} else "datetime")
        if set(p)&{"day_pillar","hour_branch","month_general_branch"}:
            p.setdefault("mode",mode)
        if mode=="manual" and set(p)&{"date","time","timezone","sect","fold"}:
            raise IntakeError("金口诀手工模式不能混入钟点参数。")
        if mode=="datetime" and set(p)&{"day_pillar","hour_branch","month_general_branch"}:
            raise IntakeError("金口诀时间法不能混入手工日时月将。")
        if "month_general_rule" in p and p["month_general_rule"] not in ({"explicit"} if mode=="manual" else {"solar_qi","month_branch_he"}):
            raise IntakeError("月将规则与所选金口诀模式不符。")
    if system=="numerology":
        if "masters" in p:
            _choice(p["masters"],"主数口径",{"none","11,22","11,22,33"})
        if "latin_name" in p and (not re.fullmatch(r"[A-Za-z '\-]+",p["latin_name"]) or not re.search(r"[A-Za-z]",p["latin_name"])):
            raise IntakeError("字母数秘须明确拉丁字母姓名，不从称呼自动转写。")
    if system in ("lenormand","geomancy") and "question" in p:
        _text(p["question"],"本方法问题",2000)
    if system=="names":
        for key in ("stroke_standard","stroke_reference","pronunciation","meaning_note","surname_reading","given_reading"):
            if key in p:
                _text(p[key],"姓名"+key,4000,True)
        if p.get("stroke_standard")=="__dictionary_derived__":
            raise IntakeError("姓名笔画标准不可使用内部保留口径。")
    if system=="ziwei":
        if "target_time" in p and "target_time_index" in p:
            raise IntakeError("紫微流运钟点与时辰序号只能选一个。")
        if p.get("scope","origin")=="origin" and set(p)&{"target_date","target_time","target_time_index"}:
            raise IntakeError("紫微目标时期须明确流运scope。")
    if system=="electional":
        if "topic" in p:
            _text(p["topic"],"黄历表用事项",30,True)
        if "date" in p and int(p["date"][:4])<1583:
            raise IntakeError("黄历表仅支持1583年及以后。")
        if "date" in p:
            try:
                date.fromisoformat(p["date"])+timedelta(days=p.get("days",1)-1)
            except OverflowError as exc:
                raise IntakeError("黄历表日期范围越界。") from exc
    if system=="tarot":
        from symbolic import SPREADS,parse_manual_cards
        _choice(p.get("spread","three"),"塔罗牌阵",set(SPREADS))
        if "cards" in p:
            if isinstance(p["cards"],list) and all(isinstance(x,str) for x in p["cards"]):
                p["cards"]=",".join(p["cards"])
            if not isinstance(p["cards"],str):
                raise IntakeError("塔罗手工牌须为明确牌号与正逆位。")
            cards=parse_manual_cards(p["cards"])
            if len(cards)!=len(SPREADS[p.get("spread","three")][1]) or len({x[0] for x in cards})!=len(cards):
                raise IntakeError("塔罗手工牌数量不符或有重复。")
            if "seed" in p or p.get("upright_only"):
                raise IntakeError("手工牌不与seed或仅正位抽样混用。")
    if system=="lenormand":
        spread=p.get("spread","three")
        _choice(spread,"雷诺曼牌阵",{"pair","three","nine","grand"})
        if "layout" in p:
            _choice(p["layout"],"布局",{"9x4","8x4+4"} if spread=="grand" else {"3x3"} if spread=="nine" else {"line"})
        if "cards" in p:
            p["cards"]=_int_array(p["cards"],"雷诺曼牌",{{"pair":2,"three":3,"nine":9,"grand":36}[spread]},1,36)
            if len(set(p["cards"]))!=len(p["cards"]) or "seed" in p:
                raise IntakeError("雷诺曼手工牌不能重复或混入seed。")
    if system=="geomancy":
        if "shield_size" in p:
            _int(p["shield_size"],"盾盘图数",15,16)
        if sum(key in p for key in ("mothers","point_counts","seed"))>1:
            raise IntakeError("土占四母、点数、seed只能选一种。")
        if "mothers" in p:
            from oracles import derive_shield
            derive_shield(p["mothers"],p.get("shield_size",16))
        if "point_counts" in p:
            rows=p["point_counts"]
            if not isinstance(rows,list) or len(rows)!=4:
                raise IntakeError("土占须有四组点数。")
            for row in rows:
                _int_array(row,"土占点数",{4},1,1000000)
    if system=="sukuyo":
        for key in ("birth","target","partner"):
            if key in p:
                p[key]=_lunar_object(p[key],"宿曜"+key)
                required={"date"} if p[key].get("calendar","lunar")=="solar" else {"month","day"}
                if not required<=set(p[key]):
                    raise IntakeError("宿曜日期对象须完整；未知请省略该可选对象。")
    if system in ("palm","face") and "observations" in p:
        from visual_intake import validate_observations
        p["observations"]=validate_observations(system,p["observations"])
    return p


def normalize_request(request, *, allow_agent_observations=False, allow_unresolved_places=False):
    """Validate every person and every supplied method before any job/report write."""
    _json_budget(request)
    source=_obj(request,_ROOT_KEYS,"request")
    mode=_choice(source.get("mode"),"mode",{"single","pair"})
    people=source.get("people")
    if not isinstance(people,list) or len(people)!=(1 if mode=="single" else 2):
        raise IntakeError("single须一人，pair须两人，每人资料独立。")
    normalized=[]
    for index,raw in enumerate(people):
        person=_obj(raw,{"person","birth","birthplace","location","name","photos","observations","dream"},"people")
        if not isinstance(person.get("person"),dict):
            raise MissingBasics("请先填写每人的称呼、出生日期、历法和时区。")
        identity=_obj(person["person"],{"name","notes"},"person")
        if "name" not in identity:
            raise MissingBasics("请填写每人的真实称呼。")
        _text(identity["name"],"称呼",80,True)
        if PureWindowsPath(identity["name"]).is_absolute() or identity["name"].startswith("/"):
            raise IntakeError("称呼不能是文件路径。")
        if "notes" in identity:
            _text(identity["notes"],"个人说明",4000)
        birthplace=person.get("birthplace")
        if birthplace is not None:
            _text(birthplace,"出生地点",240,True)
        birth=None
        if person.get("birth") is not None:
            birth=_obj(person["birth"],{"date","time","shichen","calendar","leap","timezone","gender"},"birth")
            if not {"date","calendar"}<=set(birth) or not birth.get("timezone") and not (allow_unresolved_places and birthplace):
                raise MissingBasics("请填写出生日期、历法与出生地点；已有明确时区的旧资料也可使用，时辰可以未知。")
            calendar=_choice(birth["calendar"],"历法",{"solar","lunar"})
            y,m,d=_date_parts(birth["date"],"出生日期",calendar=="lunar")
            if not 1583<=y<=9998:
                raise IntakeError("出生历法支持1583至9998年；古代记录请另用明确历法资料入口。")
            birth["time"]=_time(birth.get("time"),"出生钟点")
            try:
                validate_shichen(birth.get("shichen"), birth["time"])
            except ValueError as exc:
                raise IntakeError("出生时辰须为十二地支之一，且不能同时填写准确钟点。") from exc
            if birth.get("timezone") not in (None,""):
                _zone(birth["timezone"],"出生时区")
            else:
                birth["timezone"]=None
            if "leap" in birth:
                _boolean(birth["leap"],"闰月")
            if calendar=="solar" and birth.get("leap"):
                raise IntakeError("公历输入不能标闰月。")
            if calendar=="lunar":
                lib=calendar_library()
                month=lib.LunarYear.fromYear(y).getMonth(-m if birth.get("leap",False) else m)
                if month is None or month.getYear()!=y or d>month.getDayCount():
                    raise IntakeError("该年农历月日或闰月不存在。")
            if birth.get("gender") in (None,""):
                birth["gender"]=None
            else:
                _choice(birth["gender"],"传统排盘性别",{"male","female"})
        item={"person":identity,"birth":birth,"location":_geo(person.get("location",{}),"出生地点")}
        if "dream" in person:
            _text(person["dream"],"梦境描述",4000)
            if person["dream"].strip():
                item["dream"]=person["dream"]
        if birthplace is not None:
            item["birthplace"]=birthplace
        if "name" in person and person["name"] is not None:
            naming=_obj(person["name"],{"mode","full_name","latin_name","pronunciation","surname","given","strokes"},"name")
            if naming.get("mode")=="international":
                if set(naming)-{"mode","full_name","latin_name","pronunciation"}:
                    raise IntakeError("国际姓名不能混用汉字姓、名或笔画。")
                from name_analysis import validate_international_name
                validate_international_name(naming.get("full_name"),naming.get("latin_name"),naming.get("pronunciation"))
            elif set(naming)-{"surname","given","strokes"} or not {"surname","given"}<=set(naming):
                raise IntakeError("姓名学须明确surname和given，不从称呼拆姓与名。")
            else:
                from name_analysis import validate_name
                validate_name(naming["surname"],"姓"); validate_name(naming["given"],"名")
            if "strokes" in naming:
                naming["strokes"]=_int_array(naming["strokes"],"姓名笔画",{len(naming["surname"]+naming["given"])},1,64)
                known={}
                for char,count in zip(naming["surname"]+naming["given"],naming["strokes"]):
                    if char in known and known[char]!=count:
                        raise IntakeError("同一姓名字在同一笔画口径内不能填不同笔画。")
                    known[char]=count
            item["name"]=naming
        from photo_uploads import PhotoError, normalize_refs, normalize_observations
        try:
            photos=normalize_refs(person.get("photos",[]),"A" if index==0 else "B")
            if photos or "photos" in person:
                item["photos"]=photos
            if "observations" in person:
                item["observations"]=normalize_observations(person["observations"],photos,allow_agent_observations=allow_agent_observations)
        except PhotoError as exc:
            raise IntakeError(str(exc)) from exc
        normalized.append(item)
    ids=[ref["id"] for person in normalized for ref in person.get("photos",[])]
    if len(ids)>12 or len(set(ids))!=len(ids):
        raise IntakeError("同一照片不能重复或跨人引用，最多12张。")
    preferences=_obj(source.get("preferences",{}),_PREF_KEYS,"preferences")
    for key in ("language","ui_language"):
        if key in preferences:
            _choice(preferences[key],key,{"zh-CN","en","ja","ko"}|({"auto"} if key=="language" else set()))
    preferences.setdefault("systems","auto")
    valid={x["id"] for x in registry()}
    if preferences["systems"]=="all":
        preferences["systems"]=[x["id"] for x in registry()]
    if preferences["systems"]!="auto":
        ids=preferences["systems"]
        if not isinstance(ids,list) or not 1<=len(ids)<=len(valid) or any(not isinstance(x,str) or x not in valid for x in ids) or len(set(ids))!=len(ids):
            raise IntakeError("systems须为auto、all或最多27个不重复的体系ID。")
    independent = preferences["systems"] != "auto" and set(preferences["systems"]) <= {"meihua","dream"}
    if any(person["birth"] is None and not person.get("dream") for person in normalized) and not independent:
        raise MissingBasics("请填写出生资料，或选择梅花易数、填写梦境后继续独立分析。")
    for key,default,limit in (("topic","综合分析",200),("question","",4000),("relationship","伴侣",80),("depth","detailed",20)):
        preferences.setdefault(key,default)
        _text(preferences[key],key,limit,key in ("topic","relationship"))
    _choice(preferences["depth"],"报告深度",{"brief","detailed"})
    for key in ("virtual_draws","prepare_engines"):
        preferences.setdefault(key,False)
        _boolean(preferences[key],key)
    answers=preferences.setdefault("answers",{})
    if not isinstance(answers,dict) or len(answers)>50:
        raise IntakeError("问答须为最多50项可读文字键。")
    for key,value in answers.items():
        _text(key,"问题键",100,True)
        if key in ("_relationship_context","_report_language"):
            raise IntakeError("answers不能填写系统保留的上下文字段。")
        if isinstance(value,list):
            if len(value)>20:
                raise IntakeError("选择题答案过多。")
            for choice in value:
                _text(choice,"选择题答案",2000)
        else:
            _text(value,"问答答案",2000)
    if "cast_place" in preferences:
        _text(preferences["cast_place"],"提问地点",240,True)
    if preferences.get("cast") is not None:
        cast=_obj(preferences["cast"],{"date","time","timezone","latitude","longitude","datetime_utc"},"cast")
        temporal={"date","time","timezone"}
        if "datetime_utc" in cast:
            from intake_autofill import utc_instant
            utc_instant(cast["datetime_utc"])
            if temporal&set(cast) or not (allow_unresolved_places and (preferences.get("cast_place") or cast.get("timezone"))):
                raise IntakeError("当前提问时刻须配合提问地点自动换算，不能同时填写另一组当地时间。")
        if temporal&set(cast):
            pending_zone=allow_unresolved_places and preferences.get("cast_place") and cast.get("timezone") in (None,"")
            if not {"date","time"}<=set(cast) or not pending_zone and not temporal<=set(cast):
                raise IntakeError("起式日期、钟点与时区须完整成组；也可仅填写提问地点。")
            _date_parts(cast["date"],"起式日期")
            cast["time"]=_time(cast["time"],"起式钟点")
            if cast["time"] is None:
                raise IntakeError("已填写起式时间字段时须提供明确钟点；未知可仅保留提问地点。")
            if pending_zone:
                cast["timezone"]=None
            else:
                _zone(cast["timezone"],"起式时区")
        _geo({k:cast[k] for k in ("latitude","longitude") if k in cast},"提问地点")
        preferences["cast"]=cast
    options=_obj(source.get("method_options",{}),valid,"method_options")
    options={system:_validate_options(system,value) for system,value in options.items()}
    if mode=="pair" and any("observations" in options.get(system,{}) for system in ("palm","face")):
        raise IntakeError("双人观察须分别放入people各自的observations，不能复用全局观察。")
    return {"mode":mode,"people":normalized,"preferences":preferences,"method_options":options}


def _combine_explicit(options,derived,label):
    result=copy.deepcopy(options)
    for key,value in derived.items():
        if key in result and result[key]!=value:
            raise IntakeError(label+"存在两处互相冲突的明确输入。")
        result[key]=value
    return result


def _calendar_dates(birth):
    y,m,d=map(int,birth["date"].split("-"))
    if birth["calendar"]=="solar":
        return birth["date"],{"calendar":"solar","date":birth["date"]}
    solar=calendar_library().Lunar.fromYmd(y,-m if birth.get("leap",False) else m,d).getSolar()
    return solar.toYmd(),{"calendar":"lunar","year":y,"month":m,"day":d,"leap":birth.get("leap",False)}


def _cast_lunar(cast):
    shared=build_chart(cast["date"],cast["time"],timezone=cast["timezone"])
    # Both the Chinese lunar date and the hour branch use the same real UTC+08
    # clock. A repeated or interval clock is usable only when all endpoints
    # produce one date/hour cell; never select one candidate by list order.
    china=timezone(timedelta(hours=8))
    cells=set()
    for row in shared["time_context"]["valid_utc_ranges"]:
        start=datetime.fromisoformat(row["start"])
        end=datetime.fromisoformat(row["end"])
        samples=(start,end-timedelta(microseconds=1) if end>start and row.get("end_exclusive") else end)
        for instant in samples:
            clock=instant.astimezone(china)
            cells.add((clock.date().isoformat(),_BRANCHES[((clock.hour+1)//2)%12]))
    if len(cells)!=1:
        return None
    day,hour_branch=cells.pop()
    y,m,d=map(int,day.split("-"))
    lunar=calendar_library().Solar.fromYmd(y,m,d).getLunar()
    return {"lunar_month":abs(lunar.getMonth()),"lunar_day":lunar.getDay(),"hour_branch":hour_branch,"leap":lunar.getMonth()<0}


def plan_request(request, *, allow_agent_observations=False):
    """Return normalized workflow inputs/deferred questions; do not start jobs or draw."""
    source=normalize_request(request,allow_agent_observations=allow_agent_observations,allow_unresolved_places=True)
    from intake_autofill import pending_places
    pending=pending_places(source)
    if pending:
        return {"request":source,"people":[],"questions":pending,"warnings":["地点资料已保留，计算前须联网核实经纬度和当地时区；尚未起盘或抽样。"],"pending_places":pending}
    pref=source["preferences"]
    cast=pref.get("cast")
    plans=[]; questions=[]; warnings=[]
    for person_index,person in enumerate(source["people"]):
        birth=copy.deepcopy(person["birth"]); geo=person["location"]
        solar_date,lunar_birth=_calendar_dates(birth) if birth else (None,None)
        if pref["systems"]=="auto":
            selected=["bazi","numerology","sukuyo"] if birth else []
            if birth and (birth["time"] or birth.get("shichen")) and birth.get("gender"):
                selected.append("ziwei")
            if birth and (birth["time"] or birth.get("shichen")) and geo:
                selected.append("astrology")
            if person.get("name"):
                selected.append("names")
            if person.get("dream"):
                selected.append("dream")
            selected += [key for key,value in source["method_options"].items() if value and key not in selected]
            for system,kinds in (("palm",{"palm_left","palm_right","palm_unknown"}),("face",{"portrait"})):
                if system not in selected and (system in person.get("observations",{}) or any(p["kind"] in kinds for p in person.get("photos",[]))):
                    selected.append(system)
        else:
            selected=list(pref["systems"])
        flow={"schema_version":1,"person":copy.deepcopy(person["person"]),"birth":birth,"location":copy.deepcopy(geo),
              "topic":pref["topic"],"question":pref["question"],"report_depth":pref["depth"],
              "questionnaire":copy.deepcopy(pref["answers"]),"systems":selected,"options":{},"settings":{},"deferred":{}}
        if "language" in pref or "ui_language" in pref or person.get("dream"):
            from reader_language import resolve_report_language
            flow["questionnaire"]["_report_language"]=resolve_report_language(source)
        if source["mode"]=="pair":
            flow["questionnaire"]["_relationship_context"]=pref["relationship"]
        if person.get("name"):
            flow["name"]=copy.deepcopy(person["name"])
            for field,part in (("surname_reading","surname"),("given_reading","given")):
                reading=source["method_options"].get("names",{}).get(field)
                if reading is not None and (person["name"].get("mode")=="international" or len(reading.split())!=len(person["name"][part])):
                    raise IntakeError("姓名读音须按明确分开的姓与名逐字填写空格分隔音节。")
        inline={}
        def defer(system,reason,required):
            if system in flow["deferred"]:
                entry=flow["deferred"][system]
                entry["reason"] += " "+reason if reason not in entry["reason"] else ""
                entry["required_inputs"]=list(dict.fromkeys([*entry["required_inputs"],*required]))
                question=next(item for item in questions if item["person_index"]==person_index and item["system"]==system)
                question.update(question=entry["reason"],required_inputs=list(entry["required_inputs"]))
                return
            flow["deferred"][system]={"reason":reason,"required_inputs":list(required)}
            questions.append({"person_index":person_index,"person_name":person["person"]["name"],"system":system,
                              "question":reason,"required_inputs":required,"optional":True,
                              "choices":["补充资料后重新生成","暂跳过此方法"]})
        for system in selected:
            p=copy.deepcopy(source["method_options"].get(system,{}))
            if not birth and (system in {"bazi","ziwei","astrology","vedic"} or system=="numerology" and "date" not in p or system=="sukuyo" and "birth" not in p or system=="qizheng" and not {"date","time","timezone","latitude","longitude"}<=set(p)):
                defer(system,"本方法需要出生资料；可以先阅读其他已提供材料的分析。",["出生日期及本方法所需的时空资料"])
                continue
            if system=="bazi":
                settings={k:p[k] for k in ("sect","true_solar","yun_sect") if k in p}
                if settings:
                    flow["settings"]["bazi"]=settings
                for key in ("time_basis","fold"):
                    if key in p:
                        birth[key]=p[key]
                if (p.get("true_solar") or p.get("time_basis")=="true-solar-time") and not geo:
                    defer(system,"真太阳时需要本人明确经度。",["出生经度"])
                continue
            if system=="ziwei":
                settings={k:p[k] for k in ("algorithm","year_divide","day_divide","fix_leap") if k in p}
                if settings:
                    flow["settings"]["ziwei"]=settings
                p={k:v for k,v in p.items() if k not in settings}
                if not (birth["time"] or birth.get("shichen")) or not birth.get("gender"):
                    defer(system,"紫微完整个人盘仍需明确时辰和所用传统性别规则。",["出生钟点","传统排盘性别"])
                if p.get("scope","origin")!="origin" and (not p.get("target_date") or not set(p)&{"target_time","target_time_index"}):
                    defer(system,"流运需要明确目标日期和目标钟点或时辰，不默认今天或中午。",["目标日期","目标钟点或时辰"])
            elif system=="astrology":
                if p:
                    flow["settings"]["astrology"]=p
                if not (birth["time"] or birth.get("shichen")) or not geo:
                    defer(system,"星盘图需要明确出生钟点和出生经纬度；没有补造中午盘。",["出生钟点","出生经纬度"])
                continue
            elif system=="vedic":
                if not (birth["time"] or birth.get("shichen")) or not geo:
                    defer(system,"恒星盘需要明确出生钟点和出生经纬度。",["出生钟点","出生经纬度"])
            elif system=="names":
                if not person.get("name"):
                    defer(system,"姓名学须明确分开的姓与名，不能从称呼拆猜。",["姓","名"])
                else:
                    if person["name"].get("mode")=="international" and set(p)-{"pronunciation"}:
                        raise IntakeError("国际姓名不使用汉字笔画或逐字拼音设置。")
                    flow["name"]=_combine_explicit(flow["name"],p,"姓名")
                continue
            elif system=="numerology":
                p=_combine_explicit(p,{"date":solar_date},"数秘生日") if birth else p
            elif system=="sukuyo":
                p=_combine_explicit(p,{"birth":lunar_birth},"宿曜本人日期") if birth else p
            elif system in ("qizheng","horary"):
                if system=="qizheng" and birth:
                    derived={"date":solar_date,"timezone":birth["timezone"]}
                    if birth["time"]:
                        derived["time"]=birth["time"]
                    derived.update(geo)
                    p=_combine_explicit(p,derived,"七政本人生辰")
                    if not birth["time"] or not geo:
                        defer(system,"七政四余需要本人明确钟点和经纬度。",["出生钟点","出生经纬度"])
                    if not 1583<=int(solar_date[:4])<=2999:
                        defer(system,"现有天文引擎支持1583至2999年的实时时空。",["引擎支持范围内的日期或独立历史盘面"])
                elif system=="horary":
                    if cast:
                        derived={k:cast[k] for k in ("date","time","timezone","latitude","longitude") if k in cast}
                        if pref["question"].strip():
                            derived["question"]=pref["question"]
                        p=_combine_explicit(p,derived,"卜卦提问时空")
                    if not cast or not cast.get("time") or not pref["question"].strip():
                        defer(system,"卜卦占星需要独立提问日期、钟点、时区和明确问题，不借用生日。",["提问时刻","提问时区","独立问题"])
                    if not {"latitude","longitude"}<=set(p):
                        defer(system,"卜卦地点须由提问地点明确提供，不能借用出生地点。",["提问经纬度"])
                    if cast and "date" in cast and not 1583<=int(cast["date"][:4])<=2999:
                        defer(system,"现有天文引擎支持1583至2999年的提问时空。",["引擎支持范围内的提问日期"])
            elif system=="taiyi":
                if cast:
                    p=_combine_explicit(p,{k:cast[k] for k in ("date","time","timezone") if cast.get(k) is not None},"太乙起局时刻")
                if not cast or not cast.get("time") or cast.get("timezone")!="Asia/Shanghai" or not {"mode","method"}<=set(p):
                    defer(system,"太乙须明确中国日期钟点、Asia/Shanghai时区、起局层级和积年法。",["中国日期钟点","Asia/Shanghai时区","mode","method"])
                elif len(cast["time"])!=5:
                    defer(system,"当前太乙接口按分钟起局，请明确HH:MM口径。",["明确分钟钟点"])
                elif not 1900<=int(cast["date"][:4])<=2100:
                    defer(system,"当前太乙历法校验范围为1900至2100年。",["支持范围内的起局日期或独立历史盘面"])
            elif system=="jinkoujue":
                if not cast or not cast.get("time") or not p.get("earth_branch"):
                    defer(system,"金口诀需独立起课时刻和明确地分，不从问题猜地分。",["起课时刻与时区","earth_branch地分"])
                elif p.get("mode","datetime")=="manual":
                    if not {"day_pillar","hour_branch","month_general_branch"}<=set(p):
                        defer(system,"手工金口诀还需日柱、时支、月将。",["日柱","时支","月将"])
                else:
                    p.setdefault("mode","datetime")
                    p=_combine_explicit(p,{k:cast[k] for k in ("date","time","timezone")},"金口诀起课时刻")
            elif system=="xiaoliuren":
                if p.get("mode","numbers")=="numbers" and "numbers" in p:
                    pass
                elif cast and cast.get("time"):
                    if p.get("mode")=="numbers":
                        defer(system,"报数法尚未给三个明确正整数。",["三个正整数"])
                    else:
                        actual=_cast_lunar(cast)
                        if actual is None:
                            defer(system,"起课历日存在多个候选，尚不能取唯一月日时。",["确定起课日期时刻"])
                        else:
                            p=_combine_explicit(p,{"mode":"lunar",**actual},"小六壬起课历法")
                else:
                    defer(system,"小六壬需明确三个报数，或独立起课日期钟点与时区。",["三个报数或独立起课时刻"])
            elif system=="electional":
                if not cast or cast.get("timezone")!="Asia/Shanghai":
                    defer(system,"黄历须明确中国历日的起始日期和时区，不从生日取用事日期。",["用事日期","Asia/Shanghai时区"])
                else:
                    p=_combine_explicit(p,{"date":cast["date"]},"黄历用事日期")
                    _validate_options(system,p)
            elif system=="dream":
                if person.get("dream"):
                    p={"text":person["dream"]}
                else:
                    defer(system,"可填写本人梦境后解读。",["梦境描述"])
            elif system=="meihua":
                if "numbers" not in p and cast and cast.get("time"):
                    p=_combine_explicit(p,{k:cast[k] for k in ("date","time","timezone") if cast.get(k) is not None},"梅花提问时刻")
                if not set(p)&{"numbers","date"}:
                    defer(system,"梅花易数需明确报数或提问时刻。",["两个或三个报数，或提问日期钟点与时区"])
                elif "numbers" not in p:
                    _validate_options(system,p)
                if pref["question"].strip():
                    p=_combine_explicit(p,{"question":pref["question"]},"梅花问题")
            elif system=="iching":
                method=p.get("method")
                if method is None:
                    method="manual" if "lines" in p else "meihua" if "numbers" in p else "coins" if pref["virtual_draws"] else "manual"
                    p["method"]=method
                if method=="coins" and not pref["virtual_draws"]:
                    defer(system,"尚未授权软件起卦，可填写实际六爻或主动开启虚拟抽样。",["实际六爻或明确虚拟抽样授权"])
                elif method=="manual" and "lines" not in p:
                    defer(system,"周易需要实际六爻；未默认起卦。",["六个6/7/8/9"])
                elif method=="meihua" and "numbers" not in p:
                    defer(system,"梅花数字法需明确起数。",["两个或三个起数"])
                if cast:
                    for key in ("date","time","timezone"):
                        if cast.get(key) is not None:
                            p=_combine_explicit(p,{"cast_"+key:cast[key]},"周易独立起卦时刻")
                # Validate only the explicit calendar context; never invoke a casting/drawing function here.
                from iching import build_cast_context
                try:
                    build_cast_context(p.get("cast_date"),p.get("cast_time"),timezone=p.get("cast_timezone"),
                                       sect=p.get("cast_sect"),fold=p.get("cast_fold"),time_basis=p.get("cast_time_basis"),
                                       longitude=p.get("cast_longitude"),true_solar=p.get("cast_true_solar",False))
                except (ValueError,TypeError) as exc:
                    raise IntakeError("周易独立起卦历法参数不完整、冲突或无效。") from exc
            elif system=="yilin":
                if not p:
                    p={"method":"coins"} if pref["virtual_draws"] else {}
                method=p.get("method","pair")
                complete=(method=="pair" and {"base","changed"}<=set(p) or method=="lines" and "lines" in p or method=="iching" and "iching_result" in p)
                if method=="coins" and not pref["virtual_draws"] or not complete and method!="coins":
                    defer(system,"易林需明确卦对、实际六爻或主动授权软件三钱。",["卦对/六爻或虚拟抽样授权"])
            elif system=="lingqijing":
                if not p:
                    p={"method":"toss"} if pref["virtual_draws"] else {}
                method=p.get("method","counts")
                if method=="toss" and not pref["virtual_draws"] or method=="counts" and "counts" not in p or method=="pieces" and "pieces" not in p:
                    defer(system,"灵棋经需实际棋数/十二面，或主动授权虚拟投棋。",["实际棋形或虚拟抽样授权"])
            elif system in ("tarot","lenormand","geomancy"):
                manual=("cards" in p) if system in ("tarot","lenormand") else bool(set(p)&{"mothers","point_counts"})
                if not manual and not pref["virtual_draws"]:
                    defer(system,"本方法尚无实物数据且未授权虚拟抽样。",["实际牌/点数或明确虚拟抽样授权"])
                elif system=="tarot" and not p:
                    p={"spread":"three"}
            elif system in ("palm","face"):
                if system in person.get("observations",{}):
                    if "observations" in p:
                        raise IntakeError("本人观察与全局旧观察重复，请仅保留本人观察。")
                    inline[system]=copy.deepcopy(person["observations"][system])
                elif "observations" in p:
                    inline[system]=p.pop("observations")
                else:
                    kinds={"palm_left","palm_right","palm_unknown"} if system=="palm" else {"portrait"}
                    uploaded=any(photo["kind"] in kinds for photo in person.get("photos",[]))
                    defer(system,"已收到本人照片，等待Agent实际查看；上传校验没有观察内容。" if uploaded else "可补充本人照片或明确自述；本表不接受任意本地图片路径。",["实际查看后的本人观察" if uploaded else "本人照片或明确可见观察资料"])
            elif system in ("fengshui","qimen","liuren","human_design"):
                defer(system,"这是资料阅读入口，还需真实平面或已有盘面，不由出生表自动补盘。",["真实平面/已有盘面及口径"])
            flow["options"][system]={"params":p} if system in EXTRAS else p
        if birth and "bazi" in selected and not geo and (flow["settings"].get("bazi",{}).get("true_solar") or birth.get("time_basis")=="true-solar-time"):
            for system in selected:
                if system in {"bazi","ziwei","astrology","vedic"}:
                    defer(system,"共享出生钟口径要求真太阳时但缺明确经度；保留原规则，暂不预排该共享盘。",["出生经度"])
        plans.append({"workflow_input":flow,"inline_observations":inline})
        if birth and birth.get("shichen"):
            warnings.append(person["person"]["name"]+"：只知道"+birth["shichen"]+"时，保留整段候选；占星仅计算安全的太阳区间，不确定上升与宫位。")
        elif birth and birth["time"] is None:
            warnings.append(person["person"]["name"]+"：时辰未知，保留实际候选，不补中午。")
    # Validate the resulting public workflow schema before the first job write.
    for plan in plans:
        workflow.normalize_input(plan["workflow_input"])
        # An impossible wall clock or unsupported calendar is invalid input even
        # if a particular optional method is deferred. No engine or random draw is involved.
        flow=plan["workflow_input"]
        birth=copy.deepcopy(flow["birth"])
        if birth is None:
            continue
        convention=flow["settings"].get("bazi",{})
        options={**convention,**birth}
        if flow["location"]:
            options["longitude"]=flow["location"]["longitude"]
        if "bazi" in flow["deferred"] and not flow["location"]:
            options["true_solar"]=False
            options["time_basis"]="local-clock"
        day=options.pop("date"); clock=options.pop("time",None)
        try:
            build_chart(day,clock,**options)
        except (ValueError,TypeError,OverflowError) as exc:
            raise IntakeError("出生日期、钟点或时间口径不成立；重复钟点可保留候选，不能填写不存在的当地钟点。") from exc
    return {"request":source,"people":plans,"questions":questions,"warnings":warnings}


def _reports_root(value):
    if not isinstance(value,(str,os.PathLike)) or not Path(value).expanduser().is_absolute():
        raise IntakeError("报告根目录必须由服务器指定为绝对路径。")
    root=Path(value).expanduser().resolve()
    if root==Path(root.anchor) or root.exists() and not root.is_dir():
        raise IntakeError("报告根目录必须为独立文件夹。")
    if any(root.is_relative_to(p.resolve()) or p.resolve().is_relative_to(root) for p in protected_output_roots()):
        raise IntakeError("报告根目录不得与插件、引擎、资源或Python目录重叠。")
    return root


class _OfflineHTML(HTMLParser):
    def __init__(self,**kwargs):
        super().__init__(**kwargs)
        self.in_style=False

    def handle_starttag(self,tag,attrs):
        if tag.lower()=="style":
            self.in_style=True
        for key,value in attrs:
            if key.lower() in ("src","href","xlink:href","action","poster","srcset") or tag.lower()=="object" and key.lower()=="data":
                if not value:
                    continue
                if key.lower()=="srcset" or not value.startswith(("#","data:")):
                    raise IntakeError("个人报告仍含外部或相对文件依赖，尚不能作为离线单文件交付。")
            if key.lower()=="style" and value:
                _offline_css(value)

    def handle_endtag(self,tag):
        if tag.lower()=="style":
            self.in_style=False

    def handle_data(self,value):
        if self.in_style:
            _offline_css(value)


def _offline_css(value):
    css_urls=re.findall(r"\burl\(\s*(['\"]?)(.*?)\1\s*\)",html.unescape(value),re.I|re.S)
    if re.search(r"@import\b",value,re.I) or any(not target.strip().startswith(("data:","#")) for _,target in css_urls):
        raise IntakeError("报告含外部或相对样式资源。")


def _offline_html(value):
    # Up to 30 MiB opt-in photos plus original packaged art are base64 inlined.
    if not isinstance(value,str) or "<html" not in value.lower() or len(value)>128*1024*1024:
        raise IntakeError("生成的个人报告不是有效完整HTML。")
    parser=_OfflineHTML(convert_charrefs=True)
    parser.feed(value)
    parser.close()
    return value


def _committed(project,response):
    status=workflow.project_status(project)
    report_path=Path(status["report"]).resolve()
    if not report_path.is_relative_to(project.resolve()) or status["active_revision"]!=response["revision"]:
        raise IntakeError("个人报告提交版本不一致。")
    report=read_json(report_path.with_name("report.json"),max_bytes=20000000)
    source=read_json(report_path.with_name("input.json"),max_bytes=2000000)
    payloads={system:read_json(contained(project,item["file"]),max_bytes=20000000) for system,item in status["components"].items()}
    return report,source,payloads,_offline_html(report_path.read_text(encoding="utf-8"))


def submit(reports_root,request:dict, *, photo_manifest=None, allow_agent_observations=False):
    """Create one isolated job and return only whitelisted public filenames/URLs."""
    try:
        plan=plan_request(request,allow_agent_observations=allow_agent_observations)
        if plan.get("pending_places"):
            return {"status":"needs_input","job_id":None,"files":[],"warnings":plan["warnings"],"questions":plan["questions"]}
        from photo_uploads import read_manifest, validate_request_photos
        validate_request_photos(plan["request"],read_manifest(photo_manifest) if photo_manifest else None)
        root=_reports_root(reports_root)
    except MissingBasics as exc:
        return {"status":"needs_input","job_id":None,"files":[],"warnings":[str(exc)],"questions":[]}
    except IntakeError as exc:
        return {"status":"invalid_input","job_id":None,"files":[],"warnings":[str(exc)],"questions":[]}
    except (ValueError,TypeError,OSError,RuntimeError):
        return {"status":"invalid_input","job_id":None,"files":[],"warnings":["输入或本地资料校验未通过，请检查所填日期、参数与资料状态。"],"questions":[]}
    job=None
    try:
        root.mkdir(parents=True,exist_ok=True)
        for _ in range(5):
            job_id=secrets.token_hex(16)
            if not re.fullmatch(r"[0-9a-f]{32}",job_id):
                raise IntakeError("任务标识生成失败。")
            candidate=root/job_id
            try:
                candidate.mkdir()
                job=candidate
                break
            except FileExistsError:
                continue
    except (OSError,ValueError):
        return {"status":"error","job_id":None,"files":[],"warnings":["任务目录暂不可用，请重新提交。"],"questions":[]}
    if job is None:
        return {"status":"error","job_id":None,"files":[],"warnings":["任务目录暂不可用，请重新提交。"]}
    pref=plan["request"]["preferences"]
    warnings=list(plan["warnings"])
    try:
        from photo_uploads import copy_photos, observation_image
        private_photo_manifest=copy_photos(plan["request"],photo_manifest,job)
        write_new_json(job/"submitted-input.json",plan["request"])
        records=[]; pages=[]; partial=False
        for index,person_plan in enumerate(plan["people"]):
            label="a" if index==0 else "b"
            data=copy.deepcopy(person_plan["workflow_input"])
            for system,observations in person_plan["inline_observations"].items():
                path=job/("private-observations-"+label+"-"+system+".json")
                write_new_json(path,observations)
                data["options"].setdefault(system,{})["observations"]=str(path)
                image=observation_image(private_photo_manifest,plan["request"],index,system)
                if image:
                    data["options"][system]["image"]=image
            project=job/("project-"+label)
            response=workflow.run_project(project,data,prepare_engines=pref["prepare_engines"])
            report,committed,payloads,rendered=_committed(project,response)
            missing=response["status"]!="ready" or bool(data["deferred"])
            partial |= missing
            name=committed["person"]["name"]
            title=name+"的个人报告"+("（含待补条件）" if missing else "")
            filename="personal-"+label+".html"
            pages.append((filename,"personal_"+label,title,rendered))
            records.append((report,committed,payloads))
            for system,entry in data["deferred"].items():
                warnings.append(name+" · "+system+"："+entry["reason"])
            if response["status"]!="ready" and not data["deferred"]:
                warnings.append(name+"：部分方法仍有缺条件，已在个人报告中明确列出。")
        if plan["request"]["mode"]=="pair":
            pair=importlib.import_module("pair_analysis")
            personal=importlib.import_module("personal_report")
            a,b=records
            comparison=pair.compare_people({"person":a[1]["person"],"birth":a[1]["birth"],"results":a[2]},
                                           {"person":b[1]["person"],"birth":b[1]["birth"],"results":b[2]},pref["relationship"])
            rendered=_offline_html(personal.pair_html(a[0],a[2],b[0],b[2],comparison,pref["relationship"]))
            partial |= comparison.get("status")!="calculated"
            pages.append(("pair.html","pair",a[1]["person"]["name"]+"与"+b[1]["person"]["name"]+"的合参报告",rendered))
            write_new_json(job/"private-pair-comparison.json",comparison)
        # Publish the top-level files only after every personal/pair HTML passes offline checks.
        files=[]
        for filename,role,title,rendered in pages:
            if filename not in PUBLIC_FILES:
                raise IntakeError("报告文件名不在公开白名单。")
            with (job/filename).open("x",encoding="utf-8",newline="\n") as stream:
                stream.write(rendered)
            files.append({"role":role,"title":title,"filename":filename,"url":f"/files/{job_id}/{filename}"})
        return {"status":"partial" if partial else "ready","job_id":job_id,"files":files,
                "warnings":warnings,"questions":plan["questions"]}
    except Exception as exc:
        # Diagnostic details stay private; absolute filesystem paths never enter the response.
        for filename in PUBLIC_FILES:
            try:
                (job/filename).unlink(missing_ok=True)
            except OSError:
                pass
        try:
            write_new_json(job/"private-error.json",{"type":type(exc).__name__,"message":str(exc)})
        except OSError:
            pass
        return {"status":"error","job_id":job_id,"files":[],
                "warnings":["本次报告尚未完成，已保留独立任务记录；未把不完整页面作为成品返回。"],"questions":plan["questions"]}
