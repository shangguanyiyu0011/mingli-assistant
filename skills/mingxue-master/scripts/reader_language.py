"""Pure, conservative editorial checks for Agent-authored reader prose.

Issues are private editing instructions, never report content. These checks do
not judge whether an interpretation is accurate, insightful or predictive.
"""
from __future__ import annotations

import re
import unicodedata

HAN=re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U000323af]")
KANA=re.compile(r"[\u3041-\u3096\u30a1-\u30fa\uff66-\uff9d]")
HANGUL=re.compile(r"[\u1100-\u11ff\u3131-\u318e\uac00-\ud7a3]")
WORDS=re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?")
LANGUAGES=frozenset({"zh-CN","en","ja","ko"})
INTERNAL_ZH=("本模块","本模组","本算法","本方法","逐项","解释","口径","容许度","结构标记",
             "权限","接口","前端","后端","缓存","数据结构","端点","调用","鉴权","序列化","渲染","命令行","运行时","客户端","服务端","占位符",
             "输入","输出","哈希","合成版式","版式演示","原始数据","尚未实现","未实现","本模块实现","当前实现","实现指纹","具体实现","适配器",
             "本模塊","本模組","逐項","解釋","口徑","容許度","結構標記","輸入","輸出","雜湊",
             "原始數據","尚未實現","未實現","本模塊實現","當前實現","實現指紋","具體實現","適配器")
INTERNAL_EN=re.compile(r"(?<![A-Za-z0-9])(?:payloads?|providers?|schema|scope|sha(?:[-_]?256)?|hash|api|json|adapters?|implementation|backend|frontend|endpoint|permissions?)(?![A-Za-z0-9])",re.I)
PARAGRAPHS=re.compile(r"\n[ \t]*\n(?:[ \t]*\n)*")
SENTENCES=re.compile(r"[。！？!?；;\n]+")
REPEAT_RUN=re.compile(r"(.{2,40}?)(?:\1){2,}")
READER_BOILERPLATE=re.compile(r"若只是了解[^。！？\n]{0,16}文化背景|这份日表只涉及提问当天|没有比较其他日期|也没有时辰表|具体信息到[^。！？\n]{0,24}为止|最有内容的阅读|供你辨认这幅[^。！？\n]{0,32}组成|各自更直接的材料展开")
FOREIGN_BOILERPLATE=re.compile(r"this report only (?:covers|includes)|the most meaningful reading|このレポートは.{0,12}のみを|이 보고서는.{0,12}만을 다",re.I)
INTERNAL_OTHER=("内部データ","実装の詳細","プレースホルダー","내부 데이터","구현 세부","플레이스홀더")
SHORT_RESULT_SYSTEMS=frozenset({"electional","taiyi","sukuyo","xiaoliuren","yilin"})
MAX_TEXT=120000


def detect_prose_language(text):
    """Use actual prose, not short names, dates or the program's method labels."""
    # Tag syntax is not prose; this does not sanitize or change delivered text.
    text=re.sub(r"</?[A-Za-z][^<>]*>"," ",_normalize(text))
    han=len(HAN.findall(text)); kana=len(KANA.findall(text)); hangul=len(HANGUL.findall(text))
    words=WORDS.findall(text); latin=sum(map(len,words))
    if hangul>=8 and hangul>=han+kana and hangul*2>=latin:
        return "ko"
    japanese_text=kana>=2 and han+kana>=8 and kana*10>=han+kana
    short_japanese_question=kana>=1 and 3<=han+kana<=40 and re.search(r"[？?]\s*$",text)
    if (japanese_text or short_japanese_question) and (han+kana)*2>=latin:
        return "ja"
    if (han>=8 or han>=4 and re.search(r"[。！？?]",text)) and han*2>=latin:
        return "zh-CN"
    if len(words)>=3 and latin>=15 and latin>2*(han+kana+hangul):
        if not han+kana+hangul and re.fullmatch(r"[A-Za-z '\-]+",text.strip()) and all(w[0].isupper() for w in words):
            return None
        return "en"
    return None


def resolve_report_language(request):
    preferences=request.get("preferences",{})
    selected=preferences.get("language","auto")
    if selected in LANGUAGES:
        return selected
    question=preferences.get("question","")
    detected=detect_prose_language(question)
    if detected:
        return detected
    notes="\n".join(person.get("person",{}).get("notes","") for person in request.get("people",[]))
    return detect_prose_language(notes) or preferences.get("ui_language","zh-CN")


def language_from_record(record):
    if not isinstance(record,dict):
        return "zh-CN"
    report=record.get("report",record)
    answers=report.get("questionnaire",{}) if isinstance(report,dict) else {}
    return answers.get("_report_language","zh-CN") if isinstance(answers,dict) else "zh-CN"


def _issue(code,path,message,**details):
    return {"code":code,"path":path,"message":message,**details}


def _normalize(text):
    return unicodedata.normalize("NFKC",text).replace("\r\n","\n").replace("\r","\n")


def _internal_terms(text):
    found={}
    for term in INTERNAL_ZH+INTERNAL_OTHER:
        index=text.find(term)
        if index>=0:
            found[term]=index
    for match in INTERNAL_EN.finditer(text):
        found.setdefault(match.group().lower(),match.start())
    return sorted(found,key=lambda term:(found[term],-len(term)))


def _word_sequence(paragraph,language="zh-CN"):
    """Reject obvious short-word strings, not ordinary short Chinese clauses."""
    tokens=[token for token in re.split(r"[\s/|、:：;；=+]+",paragraph) if token]
    if len(tokens)<12:
        return False
    if language=="en":
        return len(tokens)>=12 and not re.search(r"[.!?]",paragraph) and all(re.fullmatch(r"[A-Za-z]{1,16}",token) for token in tokens)
    script=HAN if language=="zh-CN" else re.compile(HAN.pattern+"|"+KANA.pattern) if language=="ja" else HANGUL
    punctuation=r"[。！？!?]" if language=="zh-CN" else r"[。！？.!?]"
    short=sum(1 for token in tokens if 1<=len(script.findall(token))<=8 and not re.search(punctuation,token))
    # Require a dense short-token form. Natural sentence punctuation keeps
    # multi-clause prose out of this rule even when it contains cultural terms.
    return short/len(tokens)>=0.85 and len(re.findall(punctuation,paragraph))<2


def _content(text,language):
    if language=="en":
        return WORDS.findall(text.lower())
    if language=="ja":
        return re.findall(HAN.pattern+"|"+KANA.pattern,text)
    return (HANGUL if language=="ko" else HAN).findall(text)


def _stats(text,language="zh-CN"):
    paragraphs=[piece.strip() for piece in PARAGRAPHS.split(text.strip()) if piece.strip()]
    seen_sentences=set(); seen_paragraphs=set(); readable=0; count=0; sequences=0
    raw_han=len(_content(text,language))
    for paragraph in paragraphs:
        if _word_sequence(paragraph,language):
            sequences+=1
            continue
        canonical=" ".join(_content(paragraph,language))
        if canonical in seen_paragraphs:
            continue
        seen_paragraphs.add(canonical)
        local=0
        for sentence in (re.split(r"[。.!?;\n]+",paragraph) if language in ("en","ko") else SENTENCES.split(paragraph)):
            tokens=_content(sentence,language)
            value=" ".join(tokens) if language=="en" else "".join(tokens)
            if not value:
                continue
            # Exact repeated runs and identical sentences do not inflate length.
            value=REPEAT_RUN.sub(r"\1",value)
            if value in seen_sentences:
                continue
            seen_sentences.add(value)
            local+=len(WORDS.findall(value)) if language=="en" else len(value)
        readable+=local
        if local>=(20 if language=="en" else 40):
            count+=1
    return {"readable_han":readable,"raw_han":raw_han,"paragraphs":count,"word_sequences":sequences}


def _audit(text,path,*,minimum_han=0,minimum_paragraphs=0,check_detail=False,language="zh-CN"):
    if not isinstance(language,str) or language not in LANGUAGES:
        return [_issue("invalid_reader_language",path,"报告语言须为zh-CN、en、ja或ko。")]
    if not isinstance(text,str):
        return [_issue("invalid_reader_text",path,"待交付的正文必须是文字。")]
    if len(text)>MAX_TEXT:
        return [_issue("reader_text_too_large",path,"正文过长，请拆成清楚的内容并删去重复。",maximum=MAX_TEXT,actual=len(text))]
    normalized=_normalize(text)
    issues=[]
    detected=detect_prose_language(normalized)
    if detected and detected!=language:
        issues.append(_issue("reader_language_mismatch",path,"正文须使用本次资料选择的报告语言。",expected=language,actual=detected))
    terms=_internal_terms(normalized)
    if terms:
        issues.append(_issue("internal_language",path,"请改成直接对本人说的日常话，删去内部说明词。",terms=terms))
    filler=list(dict.fromkeys(match.group() for pattern in (READER_BOILERPLATE,FOREIGN_BOILERPLATE) for match in pattern.finditer(normalized)))
    if filler:
        issues.append(_issue("reader_boilerplate",path,"删去介绍报告范围、做过什么或没有做什么的套话，直接写具体结论。",phrases=filler))
    if not check_detail:
        return issues
    stats=_stats(normalized,language)
    if language=="en":
        minimum_han=(minimum_han+1)//2
    if stats["readable_han"]<minimum_han:
        issues.append(_issue("insufficient_reader_detail",path,"请围绕本人把内容写具体；空白、技术词串和机械重复不计入正文。",
                             minimum=minimum_han,actual=stats["readable_han"]))
    if stats["paragraphs"]<minimum_paragraphs:
        issues.append(_issue("insufficient_reader_paragraphs",path,"请用空行分开自然段，每段至少有一段完整而具体的话。",
                             minimum=minimum_paragraphs,actual=stats["paragraphs"]))
    if stats["word_sequences"]:
        issues.append(_issue("reader_word_sequence",path,"请把成串的短词写成读者能顺着理解的句子。",count=stats["word_sequences"]))
    if stats["raw_han"]>=120 and stats["readable_han"]<stats["raw_han"]*0.60:
        issues.append(_issue("mechanical_reader_repetition",path,"正文有明显重复，不能靠换标点、重复句子或重复段落凑篇幅。"))
    return issues


def audit_reader_text(text,detailed=False,language="zh-CN"):
    """Detailed readings need a result, its meaning, and useful context."""
    if type(detailed) is not bool:
        return [_issue("invalid_reader_option","/detailed","detailed须为明确布尔值。")]
    return _audit(text,"/text",minimum_han=180,minimum_paragraphs=1,check_detail=detailed,language=language)


def _focused(records,scope):
    selected=[r.get("report",{}) for r in records if scope=="pair" or r.get("role","").upper()==scope]
    text=" ".join(str(r.get(k,"")) for r in selected for k in ("topic","question"))
    questions=" ".join(str(r.get("question","")) for r in selected)
    if re.search(r"全面|一切|各方面|整体|全方位|综合(?:分析|命理|运势)|comprehensive|all aspects|overall (?:life|reading)|総合|全般|종합|전반",questions,re.I):
        return False
    return bool(questions.strip() or text.replace("综合分析", "").strip())


def _calculated(record):
    report=record.get("report") if isinstance(record,dict) else None
    if not isinstance(report,dict) or not isinstance(report.get("panels"),list):
        return set()
    return {panel["system"] for panel in report["panels"] if isinstance(panel,dict) and
            isinstance(panel.get("system"),str) and panel.get("state") in ("ready","partial")}


def _duplicate_body(text,path,seen,language="zh-CN"):
    if not isinstance(text,str):
        return []
    key=(" " if language=="en" else "").join(_content(_normalize(text),language))
    if len(key)<120:
        return []
    if key in seen:
        return [_issue("duplicate_reader_body",path,"这段与同一份内容中的另一篇长文相同，请写出本人的具体侧重。",related_path=seen[key])]
    seen[key]=path
    return []


def audit_reader_report(records,overviews,detailed=True,language=None):
    """Audit only Agent prose, never questions, birth inputs, basis or machine notes.

    Existing binding/reference validation belongs to the report pipeline. With
    0/1 calculated methods (or 0/1 common methods for a pair), overview length
    requirements are waived rather than demanding invented material.
    """
    if type(detailed) is not bool:
        return [_issue("invalid_reader_option","/detailed","detailed须为明确布尔值。")]
    if language is not None and (not isinstance(language,str) or language not in LANGUAGES):
        return [_issue("invalid_reader_language","/language","报告语言须为zh-CN、en、ja或ko。")]
    if not isinstance(records,(list,tuple)) or not 1<=len(records)<=2:
        return [_issue("invalid_reader_records","/records","需提供本次一至两人的已校验内容。")]
    if overviews is None:
        overviews={}
    if not isinstance(overviews,dict) or set(overviews)-{"A","B","pair"}:
        return [_issue("invalid_reader_overviews","/overviews","综合文字须按A、B或pair分开。")]
    issues=[]; calculated={}; seen=set()
    locales={}
    for ri,record in enumerate(records):
        path=f"/records/{ri}"
        if not isinstance(record,dict) or record.get("role") not in ("a","b","A","B"):
            issues.append(_issue("invalid_reader_record",path,"个人内容缺少明确的A/B归属。")); continue
        role=record["role"].upper()
        locale=language if language is not None else language_from_record(record)
        locales[role]=locale
        if role in seen:
            issues.append(_issue("duplicate_reader_record",path,"同一人物不能重复加入。")); continue
        seen.add(role);calculated[role]=_calculated(record)
        report=record.get("report")
        if not isinstance(report,dict) or not isinstance(report.get("panels"),list):
            issues.append(_issue("invalid_reader_panels",path+"/report/panels","缺少本人的内容清单。")); continue
        repeated_bodies={}
        for pi,panel in enumerate(report["panels"]):
            if not isinstance(panel,dict) or panel.get("state") not in ("ready","partial"):
                continue
            interpretation=panel.get("traditional_interpretation")
            text=interpretation.get("text") if isinstance(interpretation,dict) else None
            # A single calendar or positional result can be complete in a short passage.
            short_result=panel.get("system") in SHORT_RESULT_SYSTEMS
            minimum=40 if short_result else 180
            found=_audit(text,path+f"/report/panels/{pi}/traditional_interpretation/text",
                         minimum_han=minimum,minimum_paragraphs=0 if short_result else 1,check_detail=detailed,language=locale)
            for issue in found:
                issue.update(person=role,system=panel.get("system"))
            issues.extend(found)
            if detailed:
                issues.extend(_duplicate_body(text,path+f"/report/panels/{pi}/traditional_interpretation/text",repeated_bodies,locale))
    for scope,overview in overviews.items():
        path="/overviews/"+scope
        locale=language if language is not None else locales.get("A" if scope=="pair" else scope,"zh-CN")
        if not isinstance(overview,dict):
            issues.append(_issue("invalid_reader_overview",path,"综合内容须为已校验的文字对象。")); continue
        if scope=="pair":
            rich=detailed and len(calculated.get("A",set()) & calculated.get("B",set()))>=2
        else:
            rich=detailed and len(calculated.get(scope,set()))>=2
        issues.extend(_audit(overview.get("summary"),path+"/summary",minimum_han=80,minimum_paragraphs=1,check_detail=rich,language=locale))
        themes=overview.get("themes")
        minimum_themes=1 if _focused(records,scope) else 4
        if rich and (not isinstance(themes,list) or len(themes)<minimum_themes):
            issues.append(_issue("insufficient_reader_themes",path+"/themes","综合按生活方面展开，针对性问题只围绕所问内容。",
                                 minimum=minimum_themes,actual=len(themes) if isinstance(themes,list) else 0))
        repeated_themes={}
        for section in ("themes","agreements","differences","actions"):
            entries=overview.get(section,[])
            if not isinstance(entries,list):
                issues.append(_issue("invalid_reader_section",path+"/"+section,"该处应为分开的文字条目。")); continue
            for index,entry in enumerate(entries):
                item_path=path+f"/{section}/{index}"
                if not isinstance(entry,dict):
                    issues.append(_issue("invalid_reader_entry",item_path,"条目缺少可读内容。")); continue
                issues.extend(_audit(entry.get("title"),item_path+"/title",language=locale))
                theme_detail=rich and section=="themes"
                issues.extend(_audit(entry.get("text"),item_path+"/text",minimum_han=300,minimum_paragraphs=2,check_detail=theme_detail,language=locale))
                if detailed and section=="themes":
                    issues.extend(_duplicate_body(entry.get("text"),item_path+"/text",repeated_themes,locale))
        limitations=overview.get("limitations",[])
        if not isinstance(limitations,list):
            issues.append(_issue("invalid_reader_limitations",path+"/limitations","提醒须为分开的日常话。"))
        else:
            for index,text in enumerate(limitations):
                issues.extend(_audit(text,path+f"/limitations/{index}",language=locale))
    return issues
