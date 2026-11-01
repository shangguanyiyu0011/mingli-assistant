"""Original international names reuse existing expression arithmetic without transliteration."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT",Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(ROOT/"scripts"))
import agent_report
import intake_flow
import name_analysis
import pair_analysis
import report_pdf
import report_synthesis
import symbolic
import workflow
from project_store import read_json
from test_language import request, QUESTIONS


class InternationalNamesTests(unittest.TestCase):
    def test_synthesis_recognizes_derived_name_results_but_not_supplied_name_or_reading(self):
        for pointer,value in (("/latin_numerology/reduction",{"number":4}), ("/writing/letter_count",4)):
            self.assertEqual(report_synthesis._basis_kind("names",pointer,value),"result")
        for pointer,value in (("/full_name","Alex Morgan"),("/pronunciation","user supplied"),("/latin_numerology/input","Alex Morgan")):
            self.assertEqual(report_synthesis._basis_kind("names",pointer,value),"context")

    def test_ascii_name_reuses_existing_calculation_exactly(self):
        result=name_analysis.analyze_international_name("Alex Morgan")
        expected=symbolic.numerology("2000-08-16",latin_name="Alex Morgan")["name_expression"]
        self.assertEqual(result["latin_numerology"],expected)
        self.assertEqual(result["writing"]["scripts"],{"Latin":10})
        self.assertEqual(result["latin_name_source"],"original_ascii_name")
        self.assertIsNone(result["five_grids"])

    def test_original_japanese_korean_and_accents_are_not_transliterated(self):
        for name in ("山田はる","김하늘","Élodie Martin"):
            result=name_analysis.analyze_international_name(name)
            self.assertEqual(result["full_name"],name)
            self.assertIsNone(result["latin_numerology"])
            self.assertEqual(result["pronunciation_source"],"not_provided")
        result=name_analysis.analyze_international_name("김하늘",latin_name="Kim Haneul",pronunciation="김하늘")
        self.assertEqual(result["latin_numerology"]["input"],"Kim Haneul")
        self.assertEqual(result["writing"]["scripts"],{"Hangul":3})

    def test_bounds_and_mixed_chinese_fields_are_rejected(self):
        for name in ("",123,"1234","A\nB","A\u202eB","a"*161,"a"+" "*160):
            with self.assertRaises(ValueError):name_analysis.analyze_international_name(name)
        for latin in ("Élodie","山田", "--"):
            with self.assertRaises(ValueError):name_analysis.analyze_international_name("山田はる",latin_name=latin)
        for extra in ({"surname":"山"},{"strokes":[3]},{"dictionary_dir":"C:/private"}):
            with self.assertRaises(ValueError):workflow.normalize_input({"name":{"mode":"international","full_name":"Alex Morgan",**extra}})

    def test_cli_and_intake_use_same_contract(self):
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream):
            code=name_analysis.main(["--mode","international","--full-name","山田はる","--latin-name","Yamada Haru"])
        self.assertEqual(code,0)
        self.assertEqual(json.loads(stream.getvalue())["latin_numerology"]["input"],"Yamada Haru")
        incoming=request();incoming["preferences"]["systems"]=["names"]
        incoming["people"][0]["name"]={"mode":"international","full_name":"山田はる"}
        flow=intake_flow.plan_request(incoming)["people"][0]["workflow_input"]
        self.assertEqual(flow["name"],incoming["people"][0]["name"])
        with patch.object(workflow,"dispatch",side_effect=AssertionError("international mode needs no dictionary")):
            self.assertIsNone(workflow._engine_probe("names",flow))
            self.assertEqual(workflow._prepare(["names"],flow),[])

    def test_native_run_reading_finalize_preserves_actual_international_result(self):
        incoming=request();incoming["preferences"].update(systems=["names"],ui_language="en",language="en")
        incoming["people"][0]["name"]={"mode":"international","full_name":"Alex Morgan"}
        with tempfile.TemporaryDirectory() as scratch:
            root=Path(scratch);source=root/"request.json";source.write_text(json.dumps(incoming),encoding="utf-8")
            started=agent_report.run(source,root/"jobs")
            job=Path(started["job_dir"]);status=agent_report.describe(job);person=status["people"][0]
            report=read_json(person["report_json"]);panel=report["panels"][0]
            self.assertEqual(panel["state"],"ready")
            reading={"text":"Your name has ten letters in the supplied spelling. Its letter sum is retained beside the reduction for a cultural reading.",
                "result_sha256":panel["result_sha256"],"question_hash":report["question_hash"],
                "basis":[{"kind":"calculation","pointer":"/latin_numerology/reduction","label":"Name letter reduction"}]}
            workflow.run_project(Path(person["workspace"]),patch={"readings":{"names":reading}})
            final=agent_report.finalize(job,root/"delivery")
            self.assertEqual(final["status"],"exported")
            markup=Path(final["files"][0]["path"]).read_text(encoding="utf-8")
            self.assertIn("Alex Morgan",markup)

    def test_four_language_native_delivery_reaches_pdf_stage_without_browser(self):
        names={"zh-CN":"林光","en":"Alex Morgan","ja":"山田はる","ko":"김하늘"}
        readings={"zh-CN":"姓名保留本人填写的原文，书写组成按照实际文字统计。未提供拉丁拼写时不自动转写，也不采用汉字笔画计算。",
            "en":"The original name remains in the spelling you supplied. Its written composition is counted directly, with no automatic change of spelling.",
            "ja":"お名前は記入した表記のまま残っています。文字の組み合わせをそのまま確認し、示されていない読み方を勝手に決めることはありません。",
            "ko":"이름은 직접 적어 주신 표기 그대로 남아 있습니다. 실제 글자의 구성을 확인하며 알려 주시지 않은 발음을 임의로 정하지 않습니다."}
        for locale,name in names.items():
            with self.subTest(locale=locale), tempfile.TemporaryDirectory() as scratch:
                incoming=request();incoming["preferences"].update(systems=["names"],ui_language=locale,language="auto",question=QUESTIONS[locale])
                incoming["people"][0]["name"]={"mode":"international","full_name":name}
                root=Path(scratch);source=root/"request.json";source.write_text(json.dumps(incoming),encoding="utf-8")
                started=agent_report.run(source,root/"jobs");job=Path(started["job_dir"])
                person=agent_report.describe(job)["people"][0];report=read_json(person["report_json"]);panel=report["panels"][0]
                self.assertEqual(report["questionnaire"]["_report_language"],locale)
                reading={"text":readings[locale],"result_sha256":panel["result_sha256"],"question_hash":report["question_hash"],
                    "basis":[{"kind":"calculation","pointer":"/writing/letter_count","label":"Written composition"}]}
                workflow.run_project(Path(person["workspace"]),patch={"readings":{"names":reading}})
                with patch.object(report_pdf,"export_pdf",return_value={"status":"needs_browser","code":"test_no_browser","message":"No browser in unit checks"}) as export:
                    final=agent_report.deliver(job,root/"delivery")
                self.assertEqual(final["status"],"needs_pdf_export")
                export.assert_called_once()
                self.assertIn(readings[locale],Path(final["files"][0]["path"]).read_text(encoding="utf-8"))

    def test_pair_and_mixed_name_methods_preserve_their_original_results(self):
        a=name_analysis.analyze_international_name("Alex Morgan")
        for b in (name_analysis.analyze_international_name("김하늘"),name_analysis.analyze_name("林","光",[8,6])):
            people=[{"person":{"name":"Person "+str(i)},"results":{"names":value}} for i,value in enumerate((a,b))]
            result=pair_analysis.compare_people(*people)
            panel=next(p for p in result["panels"] if p["id"]=="names")
            self.assertEqual(panel["data"]["A"]["latin_numerology"],a["latin_numerology"])
            if b.get("mode")=="international":
                self.assertEqual(panel["data"]["B"]["writing"],b["writing"])
            else:
                self.assertEqual(panel["data"]["B"]["five_grids"],b["five_grids"])

    def test_native_single_and_multi_method_synthesis_reaches_delivery(self):
        for systems,name,pointer in ((["names"],"山田はる","/writing/letter_count"),
                                     (["names","numerology"],"Alex Morgan","/latin_numerology/reduction")):
            with self.subTest(systems=systems),tempfile.TemporaryDirectory() as scratch:
                incoming=request();incoming["preferences"].update(systems=systems,ui_language="en",language="en")
                incoming["people"][0]["name"]={"mode":"international","full_name":name,"pronunciation":"Explicit user reading"}
                root=Path(scratch);source=root/"request.json";source.write_text(json.dumps(incoming),encoding="utf-8")
                started=agent_report.run(source,root/"jobs");job=Path(started["job_dir"])
                person=agent_report.describe(job)["people"][0];report=read_json(person["report_json"])
                pointers={"names":pointer,"numerology":"/life_path/reduction"}
                readings={panel["system"]:{"text":"Your recorded "+panel["system"]+" result is retained with its actual calculation for a cultural reading.",
                    "result_sha256":panel["result_sha256"],"question_hash":report["question_hash"],
                    "basis":[{"kind":"calculation","pointer":pointers[panel["system"]],"label":"Actual recorded calculation"}]}
                    for panel in report["panels"]}
                workflow.run_project(Path(person["workspace"]),patch={"readings":readings})
                _,_,records=agent_report.snapshot(job)
                refs=[{"person":"A","system":system,"pointer":pointers[system],"label":"Actual "+system+" result"} for system in systems]
                value={"context_sha256":report_synthesis.synthesis_context(records,"A")["context_sha256"],
                    "summary":"The written name and the recorded numbers provide concrete material for this cultural reflection.",
                    "themes":[{"title":"Names and choices","text":"The letter or character count belongs to the supplied spelling. Any birth number follows its own reduction rule; the two remain separate when discussing your choices.","basis":refs}],
                    "agreements":[],"differences":[],
                    "actions":[{"title":"Consider the actual name","text":"Check which spelling you use in daily life before comparing another written form.","basis":[refs[0]]}],
                    "limitations":["These cultural readings do not determine real life outcomes."]}
                self.assertEqual(report_synthesis.validate_synthesis(value,records,"A")["status"],"validated")
                for context_pointer in ("/full_name","/pronunciation"):
                    bad=copy.deepcopy(value);bad["themes"][0]["basis"][0]["pointer"]=context_pointer
                    with self.assertRaises(report_synthesis.SynthesisError):report_synthesis.validate_synthesis(bad,records,"A")
                synthesis_file=root/"synthesis.json";synthesis_file.write_text(json.dumps(value),encoding="utf-8")
                with patch.object(report_pdf,"export_pdf",return_value={"status":"needs_browser","code":"test_no_browser","message":"No browser in unit checks"}) as export:
                    final=agent_report.deliver(job,root/"delivery",synthesis_a_file=synthesis_file)
                self.assertEqual(final["status"],"needs_pdf_export")
                export.assert_called_once()
                markup=Path(final["files"][0]["path"]).read_text(encoding="utf-8")
                self.assertIn(value["summary"],markup)
                self.assertIn(value["themes"][0]["text"],markup)


if __name__=="__main__":unittest.main()
