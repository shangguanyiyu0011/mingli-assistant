"""Four-language intake and reader gates; no browser or network is used."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT",Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(ROOT/"scripts"))
import agent_report
import agent_updates
import intake_flow
import reader_language as reader
import workflow
from project_store import read_json


QUESTIONS={"zh-CN":"我想了解接下来的工作方向应该如何选择？",
           "en":"How should I choose my next career direction?",
           "ja":"これからの仕事の方向をどのように選べばよいですか？",
           "ko":"앞으로 직업의 방향을 어떻게 선택하면 좋을까요?"}
PROSE={
"en": "The number in your name comes from the letters you supplied, with each letter contributing its recorded value. The total is reduced using the same rule as the other name, so you can follow each step without treating the result as a promise about your future. The original spelling remains visible beside the total, which matters when a different spelling would change the count. You may compare this symbolic reading with your own experience of using the name at work, among friends, and when introducing yourself to someone new. That comparison can give you a concrete topic to reflect on while your decisions remain grounded in the circumstances you actually know.",
"ja": "あなたが書いた名前は、そのままの表記で残しています。漢字と仮名が一緒に使われている点は、見た目の組み合わせとして確認できます。読み方が示されていない部分について、こちらで別の読み方を決めることはありません。名前を初めて伝える場面と、親しい人に呼ばれる場面では、同じ表記でも使い方が変わります。自分が普段どのように名乗っているかを思い返すと、文字の並びを身近な経験と結び付けて考えられます。仕事で署名するときの書き方や、友人に紹介してもらうときの呼ばれ方も、比べるための具体的な材料になります。別の表記を選ぶ場合には、本人が実際に使いたい綴りを先に確かめることが大切です。",
"ko": "직접 적어 주신 이름은 원래 표기 그대로 남아 있습니다. 한글로 적힌 부분과 띄어쓰기로 나뉜 부분은 글자의 구성을 살펴보는 자료가 됩니다. 따로 알려 주신 발음이 없다면 다른 발음을 정해서 붙이지 않습니다. 처음 만난 사람에게 이름을 소개하는 자리와 가까운 친구가 이름을 부르는 자리에서는 같은 이름도 다르게 쓰일 수 있습니다. 평소 어떤 형태로 자신을 소개했는지 떠올리면 글자의 배열을 실제 경험과 연결하여 생각할 수 있습니다. 직장에서 서명할 때 쓰는 표기와 지인에게 소개받을 때 듣는 호칭도 구체적으로 비교할 수 있는 자료입니다. 다른 철자를 사용하려고 한다면 본인이 실제로 쓰고 싶은 형태를 먼저 확인하는 편이 좋습니다. 이러한 관찰은 이름에 관한 대화를 시작하는 데 쓰이며 삶의 결과를 미리 정하지 않습니다."
}


def request():
    return {"mode":"single","people":[{"person":{"name":"Alex Morgan"},
        "birth":{"date":"2000-08-16","calendar":"solar","timezone":"UTC","time":None}}],
        "preferences":{"systems":["numerology"],"depth":"brief"}}


class IntakeLanguageTests(unittest.TestCase):
    def test_all_four_languages_are_normalized_and_planned(self):
        for locale,question in QUESTIONS.items():
            with self.subTest(locale=locale):
                incoming=request(); incoming["preferences"].update(ui_language="ko",language="auto",question=question)
                before=copy.deepcopy(incoming)
                plan=intake_flow.plan_request(incoming)
                self.assertEqual(plan["people"][0]["workflow_input"]["questionnaire"]["_report_language"],locale)
                self.assertEqual(incoming,before)

    def test_explicit_language_then_actual_question_then_notes_then_ui(self):
        incoming=request(); incoming["preferences"].update(language="en",ui_language="ko",question=QUESTIONS["ja"])
        self.assertEqual(reader.resolve_report_language(incoming),"en")
        incoming["preferences"]["language"]="auto"
        incoming["people"][0]["person"]["notes"]=QUESTIONS["ko"]
        self.assertEqual(reader.resolve_report_language(incoming),"ja")
        incoming["preferences"]["question"]=""
        self.assertEqual(reader.resolve_report_language(incoming),"ko")
        incoming["people"][0]["person"]["notes"]="Alex Morgan"
        incoming["preferences"]["ui_language"]="ja"
        self.assertEqual(reader.resolve_report_language(incoming),"ja")
        incoming["people"][0]["person"]["notes"]="Alex William Morgan"
        self.assertEqual(reader.resolve_report_language(incoming),"ja")
        incoming["method_options"]={"tarot":{"question":"程序生成的中文抽牌说明不能决定报告语言"}}
        self.assertEqual(reader.resolve_report_language(incoming),"ja")

    def test_language_bounds_and_reserved_field(self):
        for preferences in ({"language":"fr"},{"ui_language":"auto"},{"language":[]},{"answers":{"_report_language":"en"}}):
            incoming=request();incoming["preferences"].update(preferences)
            with self.assertRaises(ValueError):
                intake_flow.normalize_request(incoming)
        with self.assertRaises(ValueError):
            workflow.normalize_input({"systems":["numerology"],"questionnaire":{"_report_language":["en"]}})

    def test_legacy_request_canonical_shape_and_signed_job_continue(self):
        incoming=request()
        normalized=intake_flow.normalize_request(incoming)
        self.assertNotIn("language",normalized["preferences"])
        self.assertNotIn("ui_language",normalized["preferences"])
        planned=intake_flow.plan_request(incoming)["people"][0]["workflow_input"]
        self.assertNotIn("_report_language",planned["questionnaire"])
        with tempfile.TemporaryDirectory() as scratch:
            root=Path(scratch); source=root/"request.json"
            source.write_text(json.dumps(incoming),encoding="utf-8")
            started=agent_report.run(source,root/"jobs")
            job=Path(started["job_dir"])
            original=(job/"submitted-input.json").read_bytes()
            status=agent_report.describe(job)
            person=status["people"][0]; report=read_json(person["report_json"])
            reading={"text":"A short cultural reflection on your recorded birth number.",
                "result_sha256":report["panels"][0]["result_sha256"],"question_hash":report["question_hash"],
                "basis":[{"kind":"calculation","pointer":"/life_path/reduction","label":"Recorded number"}]}
            workflow.run_project(Path(person["workspace"]),patch={"readings":{"numerology":reading}})
            resumed=agent_report.describe(job)
            self.assertEqual(resumed["people"][0]["needs_readings"],[])
            updated=agent_updates.update_job(job,{"preferences":{"language":"en","ui_language":"en"}})
            self.assertTrue(updated["request_committed"])
            upgraded=agent_report.describe(job)
            latest=read_json(upgraded["people"][0]["report_json"])
            self.assertEqual(latest["questionnaire"]["_report_language"],"en")
            self.assertEqual(latest["panels"][0]["reading_status"],"stale")
            self.assertEqual((job/"submitted-input.json").read_bytes(),original)

    def test_language_correction_reuses_calculation_and_invalidates_old_reading(self):
        with tempfile.TemporaryDirectory() as scratch:
            incoming=request();incoming["preferences"].update(language="en",ui_language="en")
            flow=intake_flow.plan_request(incoming)["people"][0]["workflow_input"]
            first=workflow.run_project(Path(scratch)/"project",flow)
            report=read_json(first["report_json"])
            reading={"text":"Your recorded number is available for reflection.","result_sha256":report["panels"][0]["result_sha256"],
                "question_hash":report["question_hash"],"basis":[{"kind":"calculation","pointer":"/life_path/reduction","label":"Recorded number"}]}
            workflow.run_project(Path(scratch)/"project",patch={"readings":{"numerology":reading}})
            changed=workflow.run_project(Path(scratch)/"project",patch={"questionnaire":{"_report_language":"ja"}})
            latest=read_json(changed["report_json"])
            self.assertEqual(changed["reused"],["numerology"])
            self.assertEqual(latest["panels"][0]["reading_status"],"stale")
            self.assertNotEqual(latest["question_hash"],report["question_hash"])


class ForeignReaderTests(unittest.TestCase):
    def test_html_syntax_does_not_change_the_language_of_actual_prose(self):
        attack='</ScRiPt><img src=x onerror=alert(1)>&'
        for text in ('甲-Agent审查：真实解读文本 '+attack,'真实双人解读 '+attack):
            with self.subTest(text=text):
                self.assertNotEqual(reader.detect_prose_language(text),"en")
                self.assertEqual(reader.audit_reader_text(text,False,language="zh-CN"),[])
        for locale,text in PROSE.items():
            wrapped='<div lang="en" data-note="English attribute words">'+text+'</div>'
            self.assertEqual(reader.detect_prose_language(wrapped),locale)
            self.assertEqual(reader.audit_reader_text(wrapped,False,language=locale),[])
        self.assertIn("reader_language_mismatch",{i["code"] for i in reader.audit_reader_text('<b>'+PROSE['en']+'</b>',False,language="zh-CN")})
        chinese='你可以把当前的工作内容与下一阶段希望承担的责任放在一起比较，先确认真正愿意长期投入的方向，再决定是否转换工作。'
        self.assertIn("reader_language_mismatch",{i["code"] for i in reader.audit_reader_text('<span>'+chinese+'</span>',False,language="ja")})

    def test_natural_japanese_titles_and_short_questions_share_language_detection(self):
        titles=("職業選択と適性の分析","人間関係と仕事の傾向")
        questions=("仕事は？","転職すべき？","今後の仕事はどうなる？")
        for text in titles+questions:
            with self.subTest(text=text):
                self.assertEqual(reader.detect_prose_language(text),"ja")
                self.assertEqual(reader.audit_reader_text(text,False,language="ja"),[])
                incoming=request();incoming["preferences"].update(ui_language="en",language="auto",question=text)
                self.assertEqual(reader.resolve_report_language(incoming),"ja")
        report={"questionnaire":{"_report_language":"ja"},"panels":[]}
        overview={"summary":"", "themes":[{"title":title,"text":"仕事を選ぶ際に本人が大切にしている点を確かめます。"} for title in titles]}
        self.assertEqual(reader.audit_reader_report([{"role":"a","report":report}],{"A":overview},False),[])

    def test_japanese_detection_does_not_accept_long_chinese_or_short_names(self):
        chinese="你可以把当前的工作内容与下一阶段希望承担的责任放在一起比较，先确认真正愿意长期投入的方向，再决定是否转换工作。"
        for text in (chinese,chinese*3+"のと？"):
            with self.subTest(text=text[:20]):
                self.assertEqual(reader.detect_prose_language(text),"zh-CN")
                self.assertIn("reader_language_mismatch",{i["code"] for i in reader.audit_reader_text(text,False,language="ja")})
        self.assertIsNone(reader.detect_prose_language("山田はる"))

    def test_substantial_foreign_prose_passes_and_report_uses_bound_locale(self):
        for locale,text in PROSE.items():
            with self.subTest(locale=locale):
                self.assertEqual(reader.audit_reader_text(text,True,language=locale),[])
                report={"questionnaire":{"_report_language":locale},"panels":[{"system":"names","state":"ready","traditional_interpretation":{"text":text}}]}
                self.assertEqual(reader.audit_reader_report([{"role":"a","report":report}],{},True),[])

    def test_repeated_foreign_sentences_and_word_lists_fail(self):
        for locale,text in PROSE.items():
            sentence=text.split("." if locale in ("en","ko") else "。")[0]+("." if locale in ("en","ko") else "。")
            issues=reader.audit_reader_text((sentence+"\n\n")*40,True,language=locale)
            self.assertIn("mechanical_reader_repetition",{i["code"] for i in issues})
        issues=reader.audit_reader_text(" ".join(["work","name","day","form"]*80),True,language="en")
        self.assertIn("reader_word_sequence",{i["code"] for i in issues})

    def test_wrong_language_rejected_for_detailed_and_brief_photos(self):
        for expected in ("zh-CN","ja","ko"):
            for detailed in (True,False):
                self.assertIn("reader_language_mismatch",{i["code"] for i in reader.audit_reader_text(PROSE["en"],detailed,language=expected)})
        self.assertEqual(reader.audit_reader_text("写真では眉の一部が髪で隠れています。",False,language="ja"),[])
        self.assertEqual(reader.audit_reader_text("사진에서 눈썹 일부가 머리카락에 가려져 있습니다.",False,language="ko"),[])

    def test_foreign_metadata_filler_and_duplicates_stay_rejected(self):
        for locale in PROSE:
            self.assertIn("internal_language",{i["code"] for i in reader.audit_reader_text(PROSE[locale]+" JSON backend",False,language=locale)})
            report={"questionnaire":{"_report_language":locale},"panels":[{"system":system,"state":"ready","traditional_interpretation":{"text":PROSE[locale]}} for system in ("names","numerology")]}
            self.assertIn("duplicate_reader_body",{i["code"] for i in reader.audit_reader_report([{"role":"a","report":report}],{},True)})
        self.assertIn("reader_boilerplate",{i["code"] for i in reader.audit_reader_text("This report only covers your name.",False,language="en")})
        self.assertEqual(reader.audit_reader_text("hello",language=[])[0]["code"],"invalid_reader_language")


if __name__=="__main__":unittest.main()
