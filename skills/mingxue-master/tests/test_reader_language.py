"""Reader-facing plain prose, useful detail, and real multi-method theme fusion."""
import copy
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]
SKILL=Path(os.environ["MINGXUE_TEST_SKILL_ROOT"]).resolve() if os.environ.get("MINGXUE_TEST_SKILL_ROOT") else (
    HERE if (HERE/"scripts/reader_language.py").is_file() else HERE/"package/mingxue-master")
sys.dont_write_bytecode=True
sys.path.insert(0,str(SKILL/"scripts"))
import reader_language as reader
import report_synthesis as synthesis
import test_report_synthesis as evidence


PARAS=[
    "你不必一次把生活中的每件事都安排妥当。眼前更有帮助的做法，是先分清哪些事与你自己的愿望有关，哪些只是为了让别人放心。遇到需要答应的工作、见面或学习安排，可以给自己留一点考虑时间，把能做的部分说清楚，也把暂时顾不过来的地方说出来。这样做并不意味着你不重视对方，而是让一份承诺有机会落在日常行动里。接下来一周，试着记录三次让你觉得踏实的时刻，看看它们是否都发生在你能够掌握节奏、知道下一步要做什么的时候。",
    "当你想把一件事做得更好时，可以先选一个很小、能够持续的动作，而不是马上增加很多要求。比如每天固定留出一段不被打断的时间，只处理当前最值得投入的任务；做完以后，写下哪里顺手、哪里费力、是否需要别人帮忙。记录的用处，是让你逐渐看见自己的实际习惯。偶尔停下来休息，不会抹去前面已经付出的努力。若原定的安排连续几天都让你疲惫，就把它缩小一点，再观察一周，给新的做法留下适应的余地。",
    "与别人相处时，你可以更早表达自己的需要。与其等到不舒服积累很多以后才说，不如在事情刚有变化时，用一两句具体的话说明你希望怎样安排时间、怎样分担责任。如果对方没有马上回应，先确认彼此谈的是不是同一件事，不急着把沉默当成拒绝。你也可以问问自己，真正希望获得的是陪伴、确定的答复，还是一点独处的空间。把需要说得具体，会比反复猜测更容易找到双方都愿意尝试的做法，也更有利于保护你在关系中的舒适感。",
    "做决定时，你可以把眼前的选择和稍远一点的目标放在一起看。一个看起来很诱人的机会，未必适合当前的时间和体力；一个暂时平淡的安排，也可能让你有空间慢慢积累。先写下自己最在意的两件事，再问问每个选择会带来哪些实际变化。若条件还不清楚，就给自己设一个重新考虑的日期，先把能够核实的情况问明白。你始终可以根据新的经历调整方向，不需要用一次选择定义自己，更不必因为暂时犹豫就否定已经走过的路。",
]
GOOD="\n\n".join(PARAS[:3])
OTHER="\n\n".join(PARAS[1:])


def panel(system,text=GOOD,state="ready"):
    return {"system":system,"state":state,"traditional_interpretation":{"text":text},"reading_status":"applied"}


def record(role="a",systems=("bazi","numerology")):
    return {"role":role,"report":{"panels":[panel(system,GOOD if index==0 else OTHER) for index,system in enumerate(systems)],
            "question":"全面分析；用户原话还提到输入的schema和scope。","birth_input":{"notes":"原始数据与SHA属于用户资料，不扫描"}}}


def overview(long=True):
    return {"summary":PARAS[0] if long else "你可以先把最在意的事情想清楚。",
            "themes":[{"title":title,"text":"\n\n".join([PARAS[index],PARAS[(index+1)%4],PARAS[(index+2)%4]]) if long else "先照顾自己的感受，再讨论下一步。",
                       "basis":[{"label":"schema SHA 输入字段不属于正文"}]} for index,title in enumerate(("日常节奏","行动与积累","相处中的需要","选择与余地"))] if long else [
                       {"title":"先照顾眼前","text":"先照顾自己的感受，再讨论下一步。","basis":[]}],
            "agreements":[],"differences":[],"actions":[{"title":"从一件小事开始","text":"这一周给自己留出能安静思考的时间。","basis":[]}],
            "limitations":["这些来自传统文化，不替你决定生活，也不能保证事情会怎样发展。"],
            "coverage_note":"这是机器字段的输出scope，不属于Agent正文。"}


class PlainReaderTextTests(unittest.TestCase):
    def test_clear_internal_phrases_are_blocked_without_banning_ordinary_words(self):
        for phrase in ("本模块","本算法","本方法","逐项","解释","口径","容许度","结构标记","输入","输出",
                       "payload","provider","schema","scope","SHA256","哈希","合成版式","版式演示","原始数据","未实现","当前实现","适配器",
                       "本模塊","解釋","ｓｃｈｅｍａ","JSON"):
            with self.subTest(phrase=phrase):
                issues=reader.audit_reader_text("你在这里看到"+phrase+"。")
                self.assertTrue(any(item["code"]=="internal_language" for item in issues))
        self.assertEqual(reader.audit_reader_text("你可以用自己的方法看待这些结果；盘面来自传统，生活由你来过。horoscope不是scope这个词的完整写法。" )[-1]["code"],"internal_language")
        self.assertEqual(reader.audit_reader_text("你可以用自己的方法看待这些结果；盘面来自传统，生活由你来过。horoscope是一种外文称呼。"),[])

    def test_ordinary_realizing_goals_is_allowed_but_internal_implementation_is_not(self):
        for text in ("你可以用自己的节奏实现愿望，也可以调整实现目标的时间。",
                     "你可以安排得周到，也希望参与选择，而不只是替别人实现决定。",
                     "你可以慢慢實現願望，不必急著給自己定下期限。"):
            with self.subTest(text=text):
                self.assertEqual(reader.audit_reader_text(text),[])
        for text in ("尚未实现自动排盘。","当前实现采用固定规则。","实现指纹已经改变。","具体实现需要程序支持。",
                     "尚未實現自動排盤。"):
            with self.subTest(text=text):
                self.assertIn("internal_language",{issue["code"] for issue in reader.audit_reader_text(text)})

    def test_brief_checks_language_without_demanding_a_long_body(self):
        text="你可以先听听自己的感受，再作决定。"
        self.assertEqual(reader.audit_reader_text(text,detailed=False),[])
        codes={item["code"] for item in reader.audit_reader_text(text,detailed=True)}
        self.assertIn("insufficient_reader_detail",codes)
        self.assertIn("insufficient_reader_paragraphs",codes)

    def test_natural_personal_body_passes_and_crlf_is_equivalent(self):
        self.assertEqual(reader.audit_reader_text(GOOD,True),[])
        self.assertEqual(reader.audit_reader_text(GOOD.replace("\n","\r\n"),True),[])

    def test_whitespace_repeated_sentences_and_repeated_characters_do_not_pad_detail(self):
        samples=(" \n\n"*500,("你可以慢慢想清楚再决定。"*80)+"\n\n"+("你可以慢慢想清楚再决定。"*80)+"\n\n"+"你可以慢慢想清楚再决定。"*80,
                 "你"*400+"\n\n"+"你"*400+"\n\n"+"你"*400,PARAS[0]+"\n\n"+PARAS[0]+"\n\n"+PARAS[0])
        for sample in samples:
            with self.subTest(sample=sample[:30]):
                issues=reader.audit_reader_text(sample,True)
                self.assertTrue(issues)
                self.assertTrue(any(item["code"] in ("insufficient_reader_detail","insufficient_reader_paragraphs","mechanical_reader_repetition") for item in issues))

    def test_technical_word_strings_are_not_natural_reader_paragraphs(self):
        terms=["天干","地支","五行","日主","宫位","日柱","月柱","时柱","藏干","星曜","命宫","身宫","宿曜","卦象","动爻","纳甲"]
        content=" / ".join(terms*12)
        issues=reader.audit_reader_text("\n\n".join([content]*3),True)
        self.assertIn("reader_word_sequence",{item["code"] for item in issues})
        self.assertIn("insufficient_reader_detail",{item["code"] for item in issues})
        ordinary="你想做得更稳，也想留些自由，忙时会有着急，闲时偶有犹豫，先把想法写下，再找朋友聊聊，不急着给承诺，不勉强装轻松，把时间留出来，把需要说清楚，让彼此都歇歇，再慢慢往前走。"
        self.assertFalse(reader._word_sequence(ordinary))

    def test_one_line_result_is_brief_and_cannot_pass_as_a_detailed_reading(self):
        text="本次三张牌依次为战车逆位、星币侍从逆位与权杖侍从正位。主题集中在方向、练习和探索；先定一个能完成的小目标，避免同时推进太多方向。"
        self.assertEqual(reader.audit_reader_text(text,False),[])
        issues=reader.audit_reader_text(text,True)
        self.assertIn("insufficient_reader_detail",{item["code"] for item in issues})

    def test_report_scope_filler_is_rejected_but_concrete_uncertainty_is_kept(self):
        for text in ("若只是了解当天的文化背景，可以看看。",
                     "这份日表只涉及提问当天，没有比较其他日期，也没有时辰表。",
                     "它所提供的具体信息到这一日的历表为止。",
                     "本次七政最有内容的阅读仍来自已经列出的星位和相互联系。",
                     "图中的交点与月孛保留各自位置，供你辨认这幅出生图景的不同组成。",
                     "个人的事业、收入与关系仍由各自更直接的材料展开。"):
            with self.subTest(text=text):
                self.assertIn("reader_boilerplate",{x["code"] for x in reader.audit_reader_text(text,False)})
        for text in ("出生时间接近节气交接，月柱保留两种可能。",
                     "刘海覆盖眉部，照片中仅能辨认局部眉缘。",
                     "太阳与木星对冲，个人表达与群体期待之间存在拉力。"):
            self.assertEqual(reader.audit_reader_text(text,False),[])

    def test_useful_single_passage_is_not_forced_into_three_paragraphs(self):
        self.assertEqual(reader.audit_reader_text(''.join(PARAS[:2]),True),[])

    def test_invalid_values_are_editing_issues_not_exceptions(self):
        self.assertEqual(reader.audit_reader_text(None)[0]["code"],"invalid_reader_text")
        self.assertEqual(reader.audit_reader_text(GOOD,"true")[0]["code"],"invalid_reader_option")
        self.assertEqual(reader.audit_reader_text("x"*(reader.MAX_TEXT+1))[0]["code"],"reader_text_too_large")


class ReaderReportTests(unittest.TestCase):
    def test_concise_single_results_do_not_need_scope_filler_to_pass(self):
        text="该日宜出行、移徙、入宅、安床，忌开市、破土、掘井。值日为执，日神勾陈；具体活动的宜忌与日神名称是不同分类，因此会同时出现。"
        for system in reader.SHORT_RESULT_SYSTEMS:
            item={'role':'a','report':{'panels':[panel(system,text)]}}
            self.assertEqual(reader.audit_reader_report([item],{},True),[],system)
        self.assertIn('insufficient_reader_detail',{x['code'] for x in reader.audit_reader_report([{'role':'a','report':{'panels':[panel('bazi',text)]}}],{},True)})

    def test_focused_question_keeps_one_relevant_theme(self):
        records=[record()]
        view=overview();view["themes"]=view["themes"][:1]
        for question in ("只看事业与工作，不展开其他方面。","我今年能升职吗？","下个月可以搬家吗？"):
            records[0]["report"]["question"]=question
            self.assertEqual(reader.audit_reader_report(records,{"A":view},True),[],question)
        records[0]["report"]["question"]="全面分析我的生活各方面。"
        self.assertIn("insufficient_reader_themes",{v["code"] for v in reader.audit_reader_report(records,{"A":view},True)})

    def test_full_report_is_pure_and_does_not_audit_user_or_machine_fields(self):
        records=[record()]; overviews={"A":overview()}
        records[0]["report"]["panels"].extend([panel("qimen","本模块输入schema",state="reference_only"),panel("ziwei","未实现scope",state="needs_input")])
        before=(copy.deepcopy(records),copy.deepcopy(overviews))
        with patch("builtins.open",side_effect=AssertionError("audit must not read or write files")):
            issues=reader.audit_reader_report(records,overviews,True)
        self.assertEqual(issues,[])
        self.assertEqual((records,overviews),before)

    def test_each_calculated_method_stays_detailed_even_when_it_is_the_only_one(self):
        records=[record(systems=("numerology",))]
        records[0]["report"]["panels"][0]["traditional_interpretation"]["text"]="你可以先想清楚需要什么。"
        issues=reader.audit_reader_report(records,{"A":overview(False)},True)
        self.assertTrue(any(item["code"]=="insufficient_reader_detail" and "/panels/0/" in item["path"] for item in issues))
        self.assertFalse(any(item["path"].startswith("/overviews/") for item in issues))

    def test_detailed_overview_requires_summary_and_four_substantial_themes(self):
        issues=reader.audit_reader_report([record()],{"A":overview(False)},True)
        codes={item["code"] for item in issues}
        self.assertIn("insufficient_reader_themes",codes)
        self.assertTrue(any(item["path"]=="/overviews/A/summary" and item.get("minimum")==80 for item in issues))
        self.assertTrue(any(item["path"]=="/overviews/A/themes/0/text" and item.get("minimum")==300 for item in issues))

    def test_titles_actions_and_limitations_are_reader_text_but_basis_is_not(self):
        view=overview()
        view["themes"][0]["title"]="本模块主题"
        view["actions"][0]["text"]="输入你的计划。"
        view["limitations"][0]="原始数据包含SHA。"
        issues=reader.audit_reader_report([record()],{"A":view},False)
        paths={item["path"] for item in issues if item["code"]=="internal_language"}
        self.assertIn("/overviews/A/themes/0/title",paths)
        self.assertIn("/overviews/A/actions/0/text",paths)
        self.assertIn("/overviews/A/limitations/0",paths)
        self.assertFalse(any("/basis" in item["path"] for item in issues))

    def test_brief_legacy_keeps_short_readings_and_short_overview_compatible(self):
        records=[record()]
        for panel_value in records[0]["report"]["panels"]:
            panel_value["traditional_interpretation"]["text"]="你可以留一点时间想清楚。"
        self.assertEqual(reader.audit_reader_report(records,{"A":overview(False)},False),[])
        records[0]["report"]["panels"][0]["traditional_interpretation"]["text"]="本方法解释如下。"
        self.assertTrue(reader.audit_reader_report(records,{},False))

    def test_sparse_overview_does_not_force_four_themes_or_invent_detail(self):
        self.assertEqual(reader.audit_reader_report([record(systems=("numerology",))],{"A":overview(False)},True),[])
        no_calculation={"role":"a","report":{"panels":[panel("qimen",None,"needs_input")]}}
        self.assertEqual(reader.audit_reader_report([no_calculation],{"A":overview(False)},True),[])
        records=[record("a",("numerology","tarot")),record("b",("numerology","bazi"))]
        self.assertEqual(reader.audit_reader_report(records,{"pair":overview(False)},True),[])
        issues=reader.audit_reader_report([record("a"),record("b")],{"pair":overview(False)},True)
        self.assertIn("insufficient_reader_themes",{item["code"] for item in issues})

    def test_exact_long_copy_between_methods_or_themes_is_an_editing_issue(self):
        records=[record()]
        records[0]["report"]["panels"][1]["traditional_interpretation"]["text"]=GOOD
        self.assertIn("duplicate_reader_body",{item["code"] for item in reader.audit_reader_report(records,{},True)})
        view=overview();view["themes"][1]["text"]=view["themes"][0]["text"]
        issues=reader.audit_reader_report([record()],{"A":view},True)
        self.assertTrue(any(item["code"]=="duplicate_reader_body" and item["path"]=="/overviews/A/themes/1/text" for item in issues))


class FusionEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records=[evidence.fixture("a"),evidence.fixture("b")]

    def test_each_personal_theme_requires_two_result_methods_not_only_global_coverage(self):
        value=evidence.narrative(self.records)
        value["themes"][0]["basis"]=[evidence.ref("A","bazi")]
        value["actions"][0]["basis"]=[evidence.ref("A","numerology"),evidence.ref("A","tarot")]
        with self.assertRaises(synthesis.SynthesisError):
            synthesis.validate_synthesis(value,self.records,"A")
        value["themes"][0]["basis"].append({"person":"A","system":"numerology","pointer":"/convention","label":"只说明选法"})
        with self.assertRaises(synthesis.SynthesisError):
            synthesis.validate_synthesis(value,self.records,"A")
        value["themes"][0]["basis"].append(evidence.ref("A","numerology"))
        self.assertEqual(synthesis.validate_synthesis(value,self.records,"A")["status"],"validated")

    def test_each_pair_theme_requires_both_people_and_two_real_methods(self):
        comp=evidence.comparison(self.records)
        value=evidence.narrative(self.records,"pair",comp)
        value["themes"][0]["basis"]=[evidence.ref("A","bazi"),evidence.ref("A","numerology")]
        value["actions"][0]["basis"]=[evidence.ref("B","tarot")]
        with self.assertRaises(synthesis.SynthesisError):
            synthesis.validate_synthesis(value,self.records,"pair",comparison=comp)
        value["themes"][0]["basis"]=[evidence.ref("A","numerology"),evidence.ref("B","numerology")]
        with self.assertRaises(synthesis.SynthesisError):
            synthesis.validate_synthesis(value,self.records,"pair",comparison=comp)
        value["themes"][0]["basis"].append(evidence.ref("B","bazi"))
        self.assertEqual(synthesis.validate_synthesis(value,self.records,"pair",comparison=comp)["status"],"validated")

    def test_one_calculated_method_or_one_common_pair_method_has_a_realistic_exemption(self):
        records=copy.deepcopy(self.records)
        for entry in records:
            entry["payloads"]={"numerology":entry["payloads"]["numerology"]}
            entry["packed"]["results"]=entry["payloads"]
            entry["report"]["panels"]=[item for item in entry["report"]["panels"] if item["system"]=="numerology"]
        value=evidence.narrative(records)
        self.assertEqual(synthesis.validate_synthesis(value,records,"A")["status"],"validated")
        comp=evidence.comparison(records)
        value=evidence.narrative(records,"pair",comp)
        value["themes"][0]["basis"]=[evidence.ref("A","numerology"),evidence.ref("B","numerology")]
        value["actions"][0]["basis"]=[evidence.ref("A","numerology")]
        self.assertEqual(synthesis.validate_synthesis(value,records,"pair",comparison=comp)["status"],"validated")
        value["themes"][0]["basis"]=[evidence.ref("A","numerology")]
        value["actions"][0]["basis"]=[evidence.ref("B","numerology")]
        with self.assertRaises(synthesis.SynthesisError):
            synthesis.validate_synthesis(value,records,"pair",comparison=comp)

    def test_low_level_schema_has_no_reader_length_gate(self):
        value=evidence.narrative(self.records)
        value["summary"]="你可以慢慢想。"
        value["themes"][0]["text"]="把两条线索放在一起看。"
        self.assertEqual(synthesis.validate_synthesis(value,self.records,"A")["status"],"validated")


if __name__=="__main__":
    unittest.main(verbosity=2)
