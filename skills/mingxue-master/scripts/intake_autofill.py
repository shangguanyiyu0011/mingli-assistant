"""Resolve only supplied place names before calculation; never infer a host timezone.

Open-Meteo Geocoding (GeoNames): https://open-meteo.com/en/docs/geocoding-api
The public endpoint is for non-commercial use. Queries contain places only, never
names, birthdays, questions or photos. City/district coordinates are representative.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import hashlib
from http.client import HTTPException
import json
from pathlib import Path
import re
import os
import secrets
import threading
import time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, HTTPRedirectHandler, build_opener

ENDPOINT = "https://geocoding-api.open-meteo.com/v1/search"
DOCS = "https://open-meteo.com/en/docs/geocoding-api"
MAX_RESPONSE = 512000
_lock = threading.Lock()
_last_request = 0.0


class PlaceLookupError(ValueError):
    pass


def utc_instant(value):
    from intake_flow import IntakeError
    try:
        if not isinstance(value,str) or len(value)>50 or "T" not in value:
            raise ValueError()
        instant=datetime.fromisoformat(value.replace("Z","+00:00"))
        if instant.utcoffset()!=timedelta(0):
            raise ValueError()
        return instant
    except ValueError as exc:
        raise IntakeError("当前提问时刻须为含Z或+00:00的真实UTC日期时间。") from exc


def pending_places(request):
    pending=[]
    for index,person in enumerate(request["people"]):
        if person.get("birth") and person.get("birthplace") and (not person.get("location") or not person["birth"].get("timezone")):
            pending.append({"person_index":index,"system":"place_lookup","question":person["person"]["name"]+"的出生地点待自动核实："+person["birthplace"],
                            "required_inputs":[f"people[{index}].birthplace"],"optional":False})
    pref=request["preferences"];cast=pref.get("cast") or {}
    timed=bool(set(cast)&{"datetime_utc","date","time"})
    if pref.get("cast_place") and (not {"latitude","longitude"}<=set(cast) or timed and not cast.get("timezone")) or "datetime_utc" in cast:
        pending.append({"system":"place_lookup","question":"提问地点及当地时间待自动核实。","required_inputs":["preferences.cast_place"],"optional":False})
    return pending


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise PlaceLookupError("地点服务返回了非预期跳转，请稍后重试。")


def _read_json(query):
    global _last_request
    url=ENDPOINT+"?"+urlencode({"name":query,"count":20,"language":"zh","format":"json"})
    request=Request(url,headers={"User-Agent":"MingliAssistant-PlaceResolver/1.0","Accept":"application/json"})
    # Serialize requests and leave at least one second between their starts.
    with _lock:
        delay=1.0-(time.monotonic()-_last_request)
        if delay>0:
            time.sleep(delay)
        _last_request=time.monotonic()
        try:
            with build_opener(_NoRedirect()).open(request,timeout=12) as response:
                raw=response.read(MAX_RESPONSE+1)
            if len(raw)>MAX_RESPONSE:
                raise ValueError()
            value=json.loads(raw)
            json.dumps(value,allow_nan=False)
            if not isinstance(value,dict) or value.get("error") or not isinstance(value.get("results",[]),list):
                raise ValueError()
            return value.get("results",[])
        except (OSError,URLError,ValueError,HTTPException) as exc:
            raise PlaceLookupError("暂时连不上地点查询服务；资料已保留，请联网后重试，尚未计算。") from exc


def _matches(rows,query,retrieved_epoch):
    from intake_flow import _geo, _zone
    result=[];seen=set()
    for row in rows:
        if not isinstance(row,dict) or type(row.get("id")) is not int or row["id"] in seen:
            raise PlaceLookupError("地点服务数据不完整，尚不能安全使用。")
        try:
            geo=_geo({key:row[key] for key in ("latitude","longitude")},"查询结果")
            zone=_zone(row["timezone"],"查询结果时区")
            if not isinstance(row.get("name"),str) or not row["name"].strip():
                raise ValueError()
            if row.get("feature_code") is not None and not isinstance(row["feature_code"],str):
                raise ValueError()
            parts=list(dict.fromkeys(row[key] for key in ("country","admin1","admin2","admin3","admin4","name") if row.get(key)))
            if any(not isinstance(part,str) or len(part)>240 for part in parts):
                raise ValueError()
        except (KeyError,ValueError,TypeError) as exc:
            raise PlaceLookupError("地点来源未提供可用的坐标或当地时区，请补充国家、省州及城市后重试。") from exc
        seen.add(row["id"])
        result.append({"label":" · ".join(parts),**geo,"timezone":zone,"country_code":row.get("country_code"),
            "source":{"provider":"Open-Meteo Geocoding / GeoNames","url":ENDPOINT+"?"+urlencode({"name":query,"count":20,"language":"zh","format":"json"}),
                      "documentation":DOCS,"geonames_id":row["id"],"feature_code":row.get("feature_code"),
                      "admin1":row.get("admin1"),
                      "administrative_names":[row[key] for key in ("admin1","admin2","admin3","admin4") if row.get(key)],
                      "retrieved_at":datetime.fromtimestamp(retrieved_epoch,timezone.utc).isoformat(timespec="seconds")},
            "precision":"城市或区县代表点，不是门牌或出生医院的精确坐标"})
    return result


def _queries(query):
    """Chinese administrative strings use only explicit named areas, never a guess."""
    # Try the original name first: 河北区 is a district, not 河北 + 区.
    provinces="河北 山西 辽宁 吉林 黑龙江 江苏 浙江 安徽 福建 江西 山东 河南 湖北 湖南 广东 海南 四川 贵州 云南 陕西 甘肃 青海 台湾".split()
    prefix=re.match(r"^(中华人民共和国|中国)?("+"|".join(provinces)+r")([^省,，\s].*)$",query)
    if prefix:
        country,province,local=prefix.groups()
        head,*tail=re.split(r"([,，].*)",local,maxsplit=1)
        if re.fullmatch(r"[\u3400-\u9fff]{2,40}",head) and head[0] not in "市区县州" and "自治" not in head:
            if not re.search(r"[市区县]",head):
                head+="市"
            candidates=list(_queries((country or "")+province+"省"+head+"".join(tail)))
            yield query.replace("，",","),candidates[0][1]
            yield from candidates
            return
    areas=re.findall(r"([^省市区县,，\s]+[省市区县])",query)
    areas=[re.sub(r"^(?:中华人民共和国|中国)","",part) for part in areas]
    if areas:
        areas=list(dict.fromkeys(areas))
        province=next((part for part in areas if part.endswith(("省","自治区","特别行政区"))),None)
        qualifiers=[part.strip() for part in re.split("[,，]",query) if part.strip() and not re.search(r"[省市区县]",part)]
        if query.startswith(("中国","中华人民共和国")) and "中国" not in qualifiers:
            qualifiers.append("中国")
        local=[part for part in areas if part!=province]
        for area in reversed(local[-3:]):
            qualifier=_plain_area(province) if province else qualifiers[0] if qualifiers else None
            # Preserve explicit country qualifiers rather than dropping a contradiction.
            expected=(qualifiers if province else qualifiers[1:])+([province] if province else [])+local[:local.index(area)+1]
            for name in dict.fromkeys((_plain_area(area),area)):
                yield name+(", "+qualifier if qualifier else ""),expected
        if not local:
            yield query.replace("，",","),None
    else:
        yield query.replace("，",","),None


def _plain_area(text):
    return re.sub(r"(?:特别行政区|维吾尔自治区|壮族自治区|回族自治区|自治区|省|市|区|县)$","",text.strip())


def search_places(query, *, cache_dir=None):
    from intake_flow import _text
    _text(query,"待查地点",240,True)
    if re.search(r"[\x00-\x1f]",query):
        raise PlaceLookupError("地点请填写国家、省州及城市或区县名称。")
    for lookup,areas in _queries(query.strip()):
        cache=Path(cache_dir)/(hashlib.sha256(lookup.encode("utf-8")).hexdigest()+".json") if cache_dir else None
        rows=None;retrieved_epoch=time.time()
        if cache and cache.is_file() and not cache.is_symlink() and cache.stat().st_size<=MAX_RESPONSE:
            try:
                stored=json.loads(cache.read_text(encoding="utf-8"))
                if stored["query"]==lookup and 0<=time.time()-stored["retrieved_epoch"]<30*86400:
                    rows=stored["rows"]
                    retrieved_epoch=stored["retrieved_epoch"]
            except (OSError,ValueError,KeyError,TypeError):
                pass
        if rows is None:
            rows=_read_json(lookup)
            if cache and not cache.is_symlink():
                cache.parent.mkdir(parents=True,exist_ok=True)
                temporary=cache.with_suffix("."+secrets.token_hex(8)+".tmp")
                try:
                    with temporary.open("x",encoding="utf-8") as stream:
                        json.dump({"query":lookup,"retrieved_epoch":retrieved_epoch,"rows":rows},stream,ensure_ascii=False,allow_nan=False)
                    os.replace(temporary,cache)
                finally:
                    temporary.unlink(missing_ok=True)
        if not isinstance(rows,list) or len(rows)>20:
            raise PlaceLookupError("地点服务返回了不完整的候选列表，请稍后重试。")
        matches=_matches(rows,lookup,retrieved_epoch)
        if areas:
            def verified(match,area):
                if area.endswith(("省","自治区","特别行政区")):
                    return _plain_area(area)==_plain_area(match["source"]["admin1"] or "")
                if _plain_area(area) not in {_plain_area(part) for part in match["label"].split(" · ")}:
                    return False
                # An explicit administrative area must not become a same-name village.
                if area.endswith(("市","区","县")):
                    administrative=match["source"]["administrative_names"]
                    feature=match["source"]["feature_code"] or ""
                    if area in administrative and match["label"].split(" · ")[-1]==area:
                        return True
                    allowed=("PPLA","PPLC","ADM") if area.endswith("市") else ("PPLA3","PPLA4","PPLA5","ADM3","ADM4","ADM5")
                    return feature.startswith(allowed) and _plain_area(match["label"].split(" · ")[-1])==_plain_area(area)
                return True
            matches=[match for match in matches if all(verified(match,area) for area in areas)]
        if matches:
            for match in matches:
                if areas:
                    match["precision"]="按输入行政区查询到"+areas[-1]+"的城市或区县代表点；非门牌精度；更细的原地址未核实"
            return matches
    return []


def resolve_request(request, *, cache_dir=None):
    """Return a canonical request, auditable sources, and blocking plain-language questions."""
    from intake_flow import normalize_request
    native=normalize_request(request,allow_unresolved_places=True)
    sources=[];questions=[];warnings=[]

    def resolve(query,path):
        try:
            matches=search_places(query,cache_dir=cache_dir)
        except (PlaceLookupError,OSError) as exc:
            questions.append({"system":"place_lookup","question":str(exc),"required_inputs":[path],"optional":False})
            return None
        sources.append({"field":path,"query":query,"matches":copy.deepcopy(matches)})
        if len(matches)!=1:
            reason="有多个同名或近似地点，请补充国家、省州、城市或区县，不能自动选择第一项。" if matches else "没有查到这个地点，请改填城市或区县名称，并附国家或省州，例如：深圳, 广东。"
            questions.append({"system":"place_lookup","question":query+"："+reason,"required_inputs":[path],"matches":matches,"optional":False})
            return None
        warnings.append(query+"："+matches[0]["precision"]+"；来源 Open-Meteo / GeoNames。")
        return matches[0]

    def fill(target,match,keys,path):
        for key in keys:
            if target.get(key) is not None and target.get(key)!="" and target[key]!=match[key]:
                label={"latitude":"纬度","longitude":"经度","timezone":"当地时区"}[key]
                questions.append({"system":"place_lookup","question":path+"原有"+label+"与地点来源不一致，请核实地点后再计算；没有覆盖原值。","required_inputs":[path],"optional":False})
            else:
                target[key]=match[key]

    for index,person in enumerate(native["people"]):
        if person.get("birth") and person.get("birthplace"):
            match=resolve(person["birthplace"],f"people[{index}].birthplace")
            if match:
                fill(person["location"],match,("latitude","longitude"),"出生地点")
                fill(person["birth"],match,("timezone",),"出生地点时区")
    pref=native["preferences"];cast=pref.get("cast")
    if pref.get("cast_place"):
        match=resolve(pref["cast_place"],"preferences.cast_place")
        if match:
            if not isinstance(cast,dict):
                cast=pref["cast"]={}
            keys=("latitude","longitude","timezone") if set(cast)&{"datetime_utc","date","time"} else ("latitude","longitude")
            fill(cast,match,keys,"提问地点")
    if cast and "datetime_utc" in cast and cast.get("timezone") and not questions:
        from chart import get_resources
        from time_conversion import load_zone
        local=utc_instant(cast["datetime_utc"]).astimezone(load_zone(cast["timezone"],get_resources()))
        if local.replace(fold=0).utcoffset()!=local.replace(fold=1).utcoffset():
            questions.append({"system":"place_lookup","question":"该提问时刻遇到当地夏令时回拨，当前起式接口还不能唯一传递这次钟点；请由Agent核实时刻口径后再计算。","required_inputs":["preferences.cast.datetime_utc"],"optional":False})
        else:
            cast.pop("datetime_utc")
            cast.update(date=local.date().isoformat(),time=local.strftime("%H:%M:%S"))
    if not questions:
        native=normalize_request(native)
    return {"request":native,"sources":sources,"questions":questions,"warnings":warnings}
