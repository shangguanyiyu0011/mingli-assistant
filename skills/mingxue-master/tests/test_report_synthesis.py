"""Current-context binding, real pointers, complete coverage and all-method planning."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parents[1]
SKILL=Path(os.environ["MINGXUE_TEST_SKILL_ROOT"]).resolve() if os.environ.get("MINGXUE_TEST_SKILL_ROOT") else (
    HERE if (HERE/"scripts/intake_flow.py").is_file() else HERE/"package/mingxue-master")
sys.path.insert(0,str(SKILL/"scripts"))
import report_synthesis as synthesis
from chart import build_chart
from symbolic import numerology,tarot
from pair_analysis import compare_people
import intake_flow
import workflow
from project_store import read_json


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def fixture(role="a",extra=False):
    date="2000-08-16" if role=="a" else "1997-03-24"
    person={"name":"合成甲" if role=="a" else "合成乙","notes":"本人合成说明"}
    birth={"date":date,"time":"08:26","calendar":"solar","timezone":"Asia/Shanghai"}
    payloads={"bazi":build_chart(date,"08:26",timezone="Asia/Shanghai"),"numerology":numerology(date),
              "tarot":tarot("three",seed=123 if role=="a" else 234)}
    states={key:"ready" for key in payloads}
    if extra:
        payloads.update(qimen={"system":"qimen","status":"reference_only","reference_text":"资料入口"},
                        palm={"system":"palm","status":"intake_only","user_reported_observations":{}},
                        ziwei={"system":"ziwei","status":"needs_input","required_inputs":["time"]})
        states.update(qimen="reference_only",palm="intake_only",ziwei="needs_input")
    question_hash=digest({"person":person,"question":"怎样安排学习？"})
    panels=[]
    for system,payload in payloads.items():
        sha=digest(payload)
        reading={"text":"只按本次符号结构作有限阅读。","result_sha256":sha,"question_hash":question_hash,
                 "basis":[{"kind":"calculation","pointer":"/schema_version"}]}
        applied=states[system] in ("ready","partial")
        panels.append({"system":system,"title":system,"state":states[system],"result_sha256":sha,
                       "result_file":"versions/v000001/results/"+system+".json","reading_status":"applied" if applied else "not_provided",
                       "traditional_interpretation":reading if applied else None})
    return {"role":role,"packed":{"person":person,"birth":birth,"results":payloads},"payloads":payloads,
            "report":{"person":person,"birth_input":birth,"location_input":{"latitude":31,"longitude":121},
                      "revision":"v000001","question_hash":question_hash,"panels":panels},
            "workspace":Path("/irrelevant/path"),"relationship":"合作伙伴"}


POINTERS={"bazi":"/details/day_master","numerology":"/life_path","tarot":"/cards"}
def ref(person,system):
    return {"person":person,"system":system,"pointer":POINTERS[system],"label":"实际"+system+"字段"}


def comparison(records):
    value=compare_people(records[0]["packed"],records[1]["packed"],records[0].get("relationship","合作伙伴"))
    value["reading_context"]={record["role"].upper():record["report"]["question_hash"] for record in records}
    return value


def narrative(records,scope="A",comp=None):
    context=synthesis.synthesis_context(records,scope,comparison=comp)
    refs=[ref(item["person"],item["system"]) for item in context["required_systems"]]
    if scope=="pair":
        refs=[ref("A","bazi"),ref("B","numerology")]
    return {"context_sha256":context["context_sha256"],"summary":"本次综合把已算结构按主题联系起来阅读，并明确保留缺条件和不同口径的边界。",
            "themes":[{"title":"学习与安排","text":"把实际符号及数字归约放在同一关注点下阅读，不据此保证现实结果。","basis":refs}],
            "agreements":[],"differences":[],
            "actions":[{"title":"具体下一步","text":"记录自己的安排，再补充必要资料；行动不依赖运势保证。","basis":[refs[0]] if refs else []}],
            "limitations":["这些是传统符号对照，不是独立验证或命运概率。"]}


class BindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base=[fixture("a",True),fixture("b")]

    def test_context_has_ui_role_contract_true_coverage_and_no_new_scores(self):
        records=copy.deepcopy(self.base)
        before=copy.deepcopy(records)
        context=synthesis.synthesis_context(records,"A")
        self.assertEqual(records,before)
        self.assertEqual(context["subjects"][0]["person"],"A")
        self.assertEqual(context["subjects"][0]["name"],"合成甲")
        self.assertIsInstance(context["coverage"],list)
        self.assertEqual(context["coverage_counts"],{"selected":6,"ready":3,"partial":0,"calculated":3,"needs_input":1,"reference":1,"observation":1,"unavailable":0})
        self.assertEqual({item["system"] for item in context["required_systems"]},{"bazi","numerology","tarot"})
        for highlight in context["highlights"]:
            self.assertEqual(highlight["value"],synthesis._pointer(records[0]["payloads"][highlight["system"]],highlight["pointer"]))
        self.assertNotIn("compatibility_score",context)
        self.assertNotIn("probability",context)
        self.assertNotRegex(json.dumps(context,ensure_ascii=False),r"[0-9]+\s*[%％]")

    def test_revision_and_file_paths_do_not_change_context(self):
        records=copy.deepcopy(self.base)
        before=synthesis.synthesis_context(records,"A")["context_sha256"]
        records[0]["report"]["revision"]="v009999"
        records[0]["workspace"]=Path("/new/workspace")
        for panel in records[0]["report"]["panels"]:
            panel["result_file"]="versions/v009999/results/"+panel["system"]+".json"
            panel["reused_from"]="v000001"
        self.assertEqual(synthesis.synthesis_context(records,"A")["context_sha256"],before)

    def test_birth_location_name_question_relationship_and_applied_reading_invalidate(self):
        value=narrative(self.base)
        mutations=[lambda r:r[0]["packed"]["birth"].update(date="2001-08-16"),
                   lambda r:r[0]["report"]["location_input"].update(longitude=122),
                   lambda r:r[0]["packed"]["person"].update(name="新称呼"),
                   lambda r:r[0].update(relationship="同事"),
                   lambda r:r[0]["report"]["panels"][0]["traditional_interpretation"].update(text="改写后的当前阅读。"),
                   lambda r:r[0]["report"]["panels"][0]["traditional_interpretation"]["basis"][0].update(label="新依据说明")]
        for mutate in mutations:
            records=copy.deepcopy(self.base);mutate(records)
            with self.subTest(mutate=mutate),self.assertRaises(synthesis.SynthesisError):
                synthesis.validate_synthesis(value,records,"A")
        records=copy.deepcopy(self.base)
        records[0]["report"]["question_hash"]="9"*64
        for panel in records[0]["report"]["panels"]:
            if panel["reading_status"]=="applied":
                panel["traditional_interpretation"]["question_hash"]="9"*64
        with self.assertRaises(synthesis.SynthesisError):
            synthesis.validate_synthesis(value,records,"A")

    def test_payload_content_and_state_are_bound_even_if_claimed_sha_is_kept(self):
        value=narrative(self.base)
        records=copy.deepcopy(self.base)
        records[0]["payloads"]["numerology"]["life_path"]["reduction"]["number"]=9
        with self.assertRaises(synthesis.SynthesisError):
            synthesis.validate_synthesis(value,records,"A")
        records=copy.deepcopy(self.base)
        records[0]["report"]["panels"][1]["state"]="partial"
        with self.assertRaises(synthesis.SynthesisError):
            synthesis.validate_synthesis(value,records,"A")

    def test_scope_a_is_independent_of_b_but_pair_binds_actual_comparison(self):
        original=synthesis.synthesis_context(self.base,"A")["context_sha256"]
        changed=copy.deepcopy(self.base)
        changed[1]["packed"]["person"]["name"]="乙的新称呼"
        self.assertEqual(synthesis.synthesis_context(changed,"A")["context_sha256"],original)
        comp=comparison(self.base)
        old=narrative(self.base,"pair",comp)
        altered=copy.deepcopy(comp);altered["limits"].append("新的实际合参限制说明。")
        with self.assertRaises(synthesis.SynthesisError):
            synthesis.validate_synthesis(old,self.base,"pair",comparison=altered)
        with self.assertRaises(synthesis.SynthesisError):
            synthesis.synthesis_context(self.base,"pair")
        stale=copy.deepcopy(comp);stale["evidence"]["people"]["B"]["package_sha256"]="0"*64
        with self.assertRaises(synthesis.SynthesisError):
            synthesis.synthesis_context(self.base,"pair",comparison=stale)


class NarrativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records=[fixture("a",True),fixture("b")]

    def test_valid_personal_covers_every_calculated_method_and_is_pure(self):
        value=narrative(self.records)
        before=copy.deepcopy(self.records)
        validated=synthesis.validate_synthesis(value,self.records,"A")
        self.assertEqual(validated["status"],"validated")
        self.assertEqual(self.records,before)
        self.assertEqual(validated["summary"],value["summary"])
        self.assertTrue(validated["highlights"])

    def test_coverage_and_highlight_names_cannot_replace_narrative_evidence(self):
        value=narrative(self.records)
        value["themes"][0]["basis"]=[ref("A","bazi")]
        self.assertEqual(len(synthesis.synthesis_context(self.records,"A")["required_systems"]),3)
        with self.assertRaisesRegex(synthesis.SynthesisError,"遗漏"):
            synthesis.validate_synthesis(value,self.records,"A")
        for extra in ("coverage","highlights","coverage_counts","probability","compatibility_score"):
            value=narrative(self.records);value[extra]=[]
            with self.subTest(extra=extra),self.assertRaises(synthesis.SynthesisError):
                synthesis.validate_synthesis(value,self.records,"A")

    def test_focused_synthesis_can_select_relevant_calculated_methods(self):
        value=narrative(self.records)
        value["themes"][0]["basis"]=[ref("A","bazi"),ref("A","numerology")]
        value["actions"][0]["basis"]=[ref("A","bazi")]
        self.assertEqual(synthesis.validate_synthesis(value,self.records,"A")["status"],"validated")

    def test_cross_person_uncomputed_reference_observation_and_bad_pointer_reject(self):
        bad=[{"person":"B","system":"numerology","pointer":"/life_path","label":"跨人"},
             {"person":"A","system":"qimen","pointer":"/reference_text","label":"资料不是实算"},
             {"person":"A","system":"palm","pointer":"/user_reported_observations","label":"观察不是实算"},
             {"person":"A","system":"ziwei","pointer":"/required_inputs","label":"尚未计算"},
             {"person":"A","system":"numerology","pointer":"/personal_year","label":"未给年份"},
             {"person":"A","system":"bazi","pointer":"/candidates/-1","label":"负索引"},
             {"person":"A","system":"bazi","pointer":"/details/~2bad","label":"错误转义"},
             {"person":"A","system":"bazi","pointer":"/missing","label":"不存在字段"}]
        for ref_value in bad:
            value=narrative(self.records);value["actions"][0]["basis"]=[ref_value]
            with self.subTest(ref=ref_value),self.assertRaises(synthesis.SynthesisError):
                synthesis.validate_synthesis(value,self.records,"A")

    def test_identity_status_metadata_cannot_be_used_as_result_evidence(self):
        for system,pointer in (("numerology","/system"),("numerology","/schema_version"),("numerology","/status"),
                               ("tarot","/deck_id")):
            value=narrative(self.records)
            value["actions"][0]["basis"]=[{"person":"A","system":system,"pointer":pointer,"label":"纯元字段"}]
            with self.subTest(pointer=pointer),self.assertRaisesRegex(synthesis.SynthesisError,"元字段"):
                synthesis.validate_synthesis(value,self.records,"A")
        for pointer in ("/life_path/system","/life_path/status","/life_path/schemaVersion","/life_path/inputHash"):
            with self.subTest(pointer=pointer),self.assertRaisesRegex(synthesis.SynthesisError,"元字段"):
                synthesis._basis_kind("numerology",pointer,"technical identity")
        self.assertEqual(synthesis._basis_kind("numerology","/life_path",{"system":"numerology","status":"calculated"}),"context")
        self.assertEqual(synthesis._basis_kind("names","/sound_form_meaning",{"pronunciation":"user supplied","meaning_note":"user supplied"}),"context")
        self.assertEqual(synthesis._basis_kind("ziwei","/horoscope/scope","yearly"),"context")

    def test_input_convention_and_seed_protocol_do_not_count_as_method_coverage(self):
        value=narrative(self.records)
        refs=[{"person":"A","system":system,"pointer":pointer,"label":"只说明输入或口径"}
              for system,pointer in (("bazi","/input"),("numerology","/convention"),("tarot","/randomness"))]
        value["themes"][0]["basis"]=refs
        value["actions"][0]["basis"]=[refs[0]]
        with self.assertRaisesRegex(synthesis.SynthesisError,"遗漏"):
            synthesis.validate_synthesis(value,self.records,"A")
        # Protocol references remain useful alongside actual output references.
        value=narrative(self.records)
        value["themes"][0]["basis"].extend(refs)
        self.assertEqual(synthesis.validate_synthesis(value,self.records,"A")["status"],"validated")

    def test_pair_people_and_distinct_method_gates_use_only_result_refs(self):
        comp=comparison(self.records)
        context_ref={"person":"B","system":"numerology","pointer":"/convention","label":"只说明B口径"}
        value=narrative(self.records,"pair",comp)
        value["themes"][0]["basis"]=[ref("A","bazi"),context_ref]
        with self.assertRaisesRegex(synthesis.SynthesisError,"双方"):
            synthesis.validate_synthesis(value,self.records,"pair",comparison=comp)
        for refs in ([ref("A","bazi"),context_ref],
                     [ref("A","bazi"),ref("A","numerology"),context_ref]):
            value=narrative(self.records,"pair",comp)
            value["agreements"]=[{"title":"不得靠口径凑跨法与双方","text":"这条不能借输入或协议字段凑齐门槛。","basis":refs}]
            with self.subTest(refs=refs),self.assertRaises(synthesis.SynthesisError):
                synthesis.validate_synthesis(value,self.records,"pair",comparison=comp)

    def test_pair_requires_both_people_and_each_cross_system_claim_has_two_methods(self):
        comp=comparison(self.records)
        value=narrative(self.records,"pair",comp)
        before=copy.deepcopy(comp)
        validated=synthesis.validate_synthesis(value,self.records,"pair",comparison=comp)
        self.assertEqual(validated["scope"],"pair")
        self.assertEqual(comp,before)
        self.assertEqual(validated["required_systems"],[])  # Pair selects supported evidence, not all personal methods.
        for refs in ([ref("A","numerology"),ref("B","numerology")],
                     [ref("A","numerology"),ref("A","bazi")]):
            value=narrative(self.records,"pair",comp)
            value["agreements"]=[{"title":"跨体系主题对照","text":"仅作主题对照，不作投票。","basis":refs}]
            with self.subTest(refs=refs),self.assertRaises(synthesis.SynthesisError):
                synthesis.validate_synthesis(value,self.records,"pair",comparison=comp)
        value=narrative(self.records,"pair",comp)
        value["themes"][0]["basis"]=[ref("A","numerology")]
        with self.assertRaises(synthesis.SynthesisError):
            synthesis.validate_synthesis(value,self.records,"pair",comparison=comp)
        value=narrative(self.records,"pair",comp)
        value["differences"]=[{"title":"口径有别","text":"双方两个实际方法的输入和符号口径分别阅读。","basis":[ref("A","bazi"),ref("B","numerology")]}]
        self.assertEqual(synthesis.validate_synthesis(value,self.records,"pair",comparison=comp)["status"],"validated")

    def test_single_method_does_not_force_agreements_or_differences_and_text_is_not_html(self):
        records=copy.deepcopy(self.records)
        for record in records:
            record["payloads"]={"numerology":record["payloads"]["numerology"]}
            record["packed"]["results"]=record["payloads"]
            record["report"]["panels"]=[item for item in record["report"]["panels"] if item["system"]=="numerology"]
        value=narrative(records)
        value["summary"]="保留 <em>用户原文</em> 字符，渲染层仍须escape；此处不输出HTML。"
        result=synthesis.validate_synthesis(value,records,"A")
        self.assertEqual(result["agreements"],[])
        self.assertEqual(result["differences"],[])
        self.assertIn("<em>",result["summary"])

    def test_schema_bounds_and_unsupported_fate_score_are_rejected(self):
        for change in ({"themes":[]},{"actions":[]},{"summary":"x"*12001},{"summary":" "*12001+"x"},
                       {"summary":"x"+" "*12001},{"summary":" "*100},{"limitations":"非数组"},{"summary":"匹配度：95%"}):
            value=narrative(self.records);value.update(change)
            with self.subTest(change=list(change)),self.assertRaises(synthesis.SynthesisError):
                synthesis.validate_synthesis(value,self.records,"A")
        value=narrative(self.records);value["summary"]="已算几何值可按原字段说明；数值120.5°或引用中的25%不自动变成命运评分。"
        self.assertEqual(synthesis.validate_synthesis(value,self.records,"A")["status"],"validated")


class PlanningAndActualTests(unittest.TestCase):
    def request(self,pair=False):
        person={"person":{"name":"综合甲合成示例"},"birth":{"date":"2000-08-16","time":None,"calendar":"solar","timezone":"Asia/Shanghai"}}
        return {"mode":"pair" if pair else "single","people":[person,copy.deepcopy(person)] if pair else [person],"preferences":{"systems":"all","depth":"brief"}}

    def test_all_25_expands_without_unauthorized_randomness_and_auto_stays_compatible(self):
        incoming=self.request()
        with patch("workflow.run_project",side_effect=AssertionError("no workflow")),patch("iching.coin_cast",side_effect=AssertionError("no draw")),patch("classic_oracles._sample_bits",side_effect=AssertionError("no draw")),patch("symbolic.tarot",side_effect=AssertionError("no draw")):
            plan=intake_flow.plan_request(incoming)
        flow=plan["people"][0]["workflow_input"]
        self.assertEqual(len(flow["systems"]),25)
        self.assertEqual(len(set(flow["systems"])),25)
        self.assertEqual(len(flow["deferred"]),22)
        self.assertFalse(plan["request"]["preferences"]["virtual_draws"])
        for system in ("iching","tarot","yilin","lingqijing","lenormand","geomancy"):
            self.assertIn(system,flow["deferred"])
        del incoming["preferences"]["systems"]
        self.assertEqual(intake_flow.plan_request(incoming)["people"][0]["workflow_input"]["systems"],["bazi","numerology","sukuyo"])

    def test_cast_location_only_is_preserved_and_never_invents_a_clock(self):
        incoming=self.request()
        incoming["preferences"].update(question="独立问题",cast={"latitude":30,"longitude":120})
        plan=intake_flow.plan_request(incoming)
        self.assertEqual(plan["request"]["preferences"]["cast"],{"latitude":30,"longitude":120})
        flow=plan["people"][0]["workflow_input"]
        self.assertIn("horary",flow["deferred"])
        self.assertEqual(flow["options"]["horary"]["params"]["latitude"],30)
        self.assertNotIn("date",flow["options"]["horary"]["params"])
        for cast in ({"latitude":30,"longitude":120,"date":"2026-10-31"},
                     {"date":"2026-10-31","timezone":"Asia/Shanghai"},
                     {"date":"2026-10-31","time":None,"timezone":"Asia/Shanghai"}):
            incoming["preferences"]["cast"]=cast
            with self.subTest(cast=cast),self.assertRaises(ValueError):
                intake_flow.plan_request(incoming)

    def test_real_snapshot_context_and_relationship_correction_stales_personal_reading(self):
        from agent_updates import update_job
        from agent_report import snapshot
        incoming=self.request(True)
        incoming["people"][1]["person"]["name"]="综合乙合成示例"
        incoming["preferences"].update(systems=["numerology"],relationship="伴侣",answers={"关注":"沟通"})
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/"reports"
            result=intake_flow.submit(root,incoming)
            self.assertIn(result["status"],("ready","partial"),result)
            job=root/result["job_id"]
            _,_,records=snapshot(job)
            panel=records[0]["report"]["panels"][0]
            reading={"text":"当前以伴侣背景阅读数字结构。","result_sha256":panel["result_sha256"],"question_hash":records[0]["report"]["question_hash"],
                     "basis":[{"kind":"calculation","pointer":"/life_path"}]}
            workflow.run_project(job/"project-a",patch={"readings":{"numerology":reading}})
            _,_,records=snapshot(job)
            context=synthesis.synthesis_context(records,"A")
            corrected=update_job(job,{"preferences":{"relationship":"同事"}})
            self.assertTrue(corrected["request_committed"],corrected)
            _,native,now=snapshot(job)
            self.assertEqual(native["preferences"]["answers"],{"关注":"沟通"})
            self.assertEqual(now[0]["report"]["panels"][0]["reading_status"],"stale")
            self.assertNotEqual(synthesis.synthesis_context(now,"A")["context_sha256"],context["context_sha256"])
        incoming["preferences"]["answers"]["_relationship_context"]="伪造"
        with self.assertRaises(ValueError):
            intake_flow.normalize_request(incoming)

    def test_actual_numeric_and_mansion_cannot_pass_with_only_system_names(self):
        from agent_report import snapshot
        incoming=self.request();incoming["preferences"]["systems"]=["numerology","sukuyo"]
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/"reports"
            response=intake_flow.submit(root,incoming)
            self.assertIn(response["status"],("ready","partial"),response)
            _,_,records=snapshot(root/response["job_id"])
            context=synthesis.synthesis_context(records,"A")
            refs=[{"person":"A","system":system,"pointer":"/system","label":"方法身份"} for system in ("numerology","sukuyo")]
            value={"context_sha256":context["context_sha256"],"summary":"这是实际两个方法的综合测试。",
                   "themes":[{"title":"不得挂名覆盖","text":"系统名不能充当结论依据。","basis":refs}],"agreements":[],"differences":[],
                   "actions":[{"title":"需实际字段","text":"应引用本次真实结果。","basis":[refs[0]]}],"limitations":[]}
            with self.assertRaisesRegex(synthesis.SynthesisError,"元字段"):
                synthesis.validate_synthesis(value,records,"A")
            value["themes"][0]["basis"]=[{"person":"A","system":"numerology","pointer":"/life_path","label":"实际归约"},
                                            {"person":"A","system":"sukuyo","pointer":"/birth_mansion","label":"实际本命宿"}]
            value["actions"][0]["basis"]=[value["themes"][0]["basis"][0]]
            self.assertEqual(synthesis.validate_synthesis(value,records,"A")["status"],"validated")


if __name__=="__main__":
    unittest.main(verbosity=2)
