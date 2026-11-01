"""Reader-facing presentation of verified results; never alter chart facts."""
from __future__ import annotations
import copy
import json
import re
from pathlib import Path

NAMES={"bazi":"八字四柱","ziwei":"紫微斗数","astrology":"西方占星","vedic":"印度占星·基本星位",
       "names":"姓名学","numerology":"数秘","iching":"周易","tarot":"塔罗","electional":"择日",
       "palm":"手相","face":"面相","fengshui":"风水","qimen":"奇门遁甲","liuren":"大六壬","human_design":"人类图",
       "xiaoliuren":"小六壬","jinkoujue":"金口诀","qizheng":"七政四余","taiyi":"太乙神数","sukuyo":"宿曜",
       "yilin":"焦氏易林","lingqijing":"灵棋经","lenormand":"雷诺曼","geomancy":"西方土占","horary":"问事占星"}
INTERNAL=re.compile(r"本模块|本算法|本方法|逐项|解释|口径|容许度|结构标记|输入|输出|原始数据|适配器|哈希|权限|接口|前端|后端|缓存|数据结构|端点|调用|鉴权|序列化|渲染|命令行|运行时|客户端|服务端|占位符|\b(?:payload|provider|schema|scope|sha256|workbench|api|json|backend|frontend|endpoint|permission)\b",re.I)
SUPPORT_KEYS={"notes","rules","limitations","warnings","evidence","input","method","convention","conventions",
              "randomness","source_chart","raw","engine_dir","source_file","validation"}


def report_locale(report):
    questionnaire=report.get('questionnaire') or {}
    language = questionnaire.get('_report_language','zh-CN') if isinstance(questionnaire,dict) else 'zh-CN'
    return language if language in ('zh-CN','en','ja','ko') else 'zh-CN'


def report_translator(language):
    path=Path(__file__).resolve().parents[1]/'ui/report-locales.json'
    dictionary=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    words=dictionary.get(language,{}) if language!='zh-CN' else {}
    literals=[k for k in sorted(words,key=len,reverse=True) if len(k)>=2]
    pattern=re.compile('|'.join(map(re.escape,literals))) if literals else None
    def translate(source,values=None):
        source=str(source)
        translated=words.get(source,pattern.sub(lambda m:words[m[0]],source) if pattern else source)
        if values:
            for key,value in values.items():translated=translated.replace('{'+key+'}',str(value))
        return translated
    return translate


def available(panel,payload):
    if panel.get("state") in ("ready","partial"):
        return True
    return (panel.get("system") in ("palm","face") and panel.get("state")=="intake_only"
            and panel.get("reading_status")=="applied" and payload.get("observation_status")=="agent_observed"
            and bool(payload.get("photo_refs")) and bool(payload.get("user_reported_observations",{}).get("features")))


def condition(system,payload):
    if system=="bazi" and not payload.get("time_known",True):
        return "出生时辰未定。"
    if system=="names" and payload.get("status") not in (None,"ok","calculated"):
        return "姓名的笔画或读音还有需要确认的地方，相关细节先保留。"
    return ""


def unknown_bazi_view(payload):
    candidates=payload.get("candidates") or []
    samples=[c.get("pillars",{}) for c in candidates if isinstance(c,dict)]
    if not samples:samples=[payload.get("pillars",{})]
    columns=[]
    shichen=payload.get("input",{}).get("shichen")
    for key,label in (("year","年柱"),("month","月柱"),("day","日柱"),("hour","时柱")):
        values=sorted({str(p[key]) for p in samples if isinstance(p,dict) and p.get(key)}) if key!="hour" or shichen else []
        columns.append({"key":key,"title":label,"values":values,"certain":len(values)==1})
    notice="子时跨午夜，保留早晚两段。" if shichen=="子" else ""
    return {"kind":"bazi_unknown","title":"八字四柱","subtitle":"","metrics":[],"notes":[],
            "data":{"columns":columns,"notice":notice}}


def reader_view(view,system,payload):
    if system=="bazi" and (not payload.get("time_known",True) or any(v is None for v in payload.get("pillars",{}).values())):
        return unknown_bazi_view(payload)
    if system=='names' and payload.get('mode')=='international' and isinstance(payload.get('writing'),dict):
        writing=payload['writing']
        scripts={'Latin':'拉丁字母','Han':'汉字','Hiragana':'平假名','Katakana':'片假名','Hangul':'韩文字母','Other':'其他文字'}
        items=[{'label':'完整姓名','value':payload.get('full_name') or payload.get('name',''),'literal':True},
               {'label':'字母数量','value':writing.get('letter_count',0)},
               {'label':'文字构成','value':' · '.join(f'{scripts.get(k,k)}: {v}' for k,v in writing.get('scripts',{}).items() if v)}]
        number=payload.get('latin_numerology')
        if isinstance(number,dict) and isinstance(number.get('reduction'),dict):
            items.append({'label':'姓名表达数','value':number['reduction'].get('number'),
                          'detail':' → '.join(map(str,number['reduction'].get('trace',[])))})
        return {'kind':'numbers','title':NAMES['names'],'metrics':[],'notes':[],'data':{'items':items}}
    if system=='names' and payload.get('calculation_status')=='calculated' and isinstance(payload.get('five_grids'),dict):
        grids=payload['five_grids']
        items=[{'label':label,'value':grids[label]['number'],
                'detail':' · '.join(str(grids[label][key]) for key in ('element','yin_yang') if grids[label].get(key))}
               for label in ('天格','人格','地格','外格','总格')
               if isinstance(grids.get(label),dict) and grids[label].get('number') is not None]
        if items:
            metrics=[{'label':'完整姓名','value':payload.get('name',''),'literal':True}]
            if isinstance(payload.get('strokes'),list):
                metrics.append({'label':'逐字笔画','value':' · '.join(f'{s["character"]} {s["count"]}' for s in payload['strokes'] if isinstance(s,dict) and 'character' in s and 'count' in s),'literal':True})
            if isinstance(payload.get('three_talents'),dict) and payload['three_talents'].get('label'):
                metrics.append({'label':'三才','value':payload['three_talents']['label']})
            return {'kind':'numbers','title':NAMES['names'],'metrics':metrics,'notes':[],'data':{'items':items}}
    def project(value):
        if isinstance(value,list):return [project(v) for v in value]
        if not isinstance(value,dict):return copy.deepcopy(value)
        return {k:project(v) for k,v in value.items() if k not in SUPPORT_KEYS}
    result=project(view)
    result["title"]=NAMES.get(system,view.get("title",system))
    result["subtitle"]=""
    result["notes"]=[]
    result["metrics"]=[m for m in result.get("metrics",[]) if not INTERNAL.search(str(m.get("label",m.get("name",""))))
                       and not INTERNAL.search(str(m.get("value","")))]
    return result


def overview_for_reader(overview,allowed,language='zh-CN'):
    if overview is None:return None
    result=copy.deepcopy(overview)
    result["coverage"]=[c for c in result.get("coverage",[]) if (c.get("person"),c.get("system")) in allowed]
    translate=report_translator(language)
    for row in result["coverage"]:
        row["title"]=translate(NAMES.get(row["system"],row.get("title",row["system"])))
    result["highlights"]=[h for h in result.get("highlights",[]) if (h.get("person"),h.get("system")) in allowed]
    result.pop("coverage_counts",None)
    result.pop("coverage_note",None)
    result.pop("required_systems",None)
    omitted=set(NAMES)-{system for _,system in allowed}
    result["limitations"]=[v for v in result.get("limitations",[]) if not any(NAMES[s] in v for s in omitted)]
    return result
