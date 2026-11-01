"""Source-bound dreams and deterministic Mei Hua; no real-person fixtures."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import agent_report
import agent_updates
import fortune
import intake_flow
import new_oracles as oracle
import personal_report
import report_synthesis
import reader_language
import workbench_api
import workflow


def request(dream="梦见一条蛇游进水里。", systems="auto"):
    return {"mode":"single", "people":[{"person":{"name":"纯虚构梦境人物A"}, "birth":None, "dream":dream}],
            "preferences":{"systems":systems,"question":"这个梦中的情节有什么关联？","virtual_draws":False}}


class NewOracleTests(unittest.TestCase):
    def test_registry_and_aliases_are_distinct(self):
        self.assertEqual(len(fortune.registry()), 27)
        self.assertEqual(fortune.find_system("梅花")["id"], "meihua")
        self.assertEqual(fortune.find_system("麻衣神相")["id"], "face")
        self.assertEqual(fortune.find_system("周公解梦")["id"], "dream")
        self.assertEqual(fortune.find_system("六爻")["id"], "iching")

    def test_numbers_preserve_original_iching_algorithm(self):
        import iching
        for numbers in ([2,3], [2,3,1], [0,0]):
            result = oracle.calculate("meihua", {"numbers":numbers})
            values, method = iching.meihua_cast(numbers)
            legacy = iching.build_result(values, method_record=method)
            self.assertEqual(result["hexagrams"], legacy["hexagrams"])
            self.assertEqual(result["moving_positions"], legacy["moving_positions"])
            self.assertEqual(result["input"]["values_as_supplied"], values)
        self.assertEqual(oracle.calculate("meihua", {"numbers":[2,3,1]})["body_use"]["relation"], "target_controls_source")
        self.assertEqual(oracle.calculate("meihua", {"numbers":[2,3]})["body_use"]["body"]["name"], "离")

    def test_explicit_time_fixture_and_timezone_equivalence(self):
        china = oracle.calculate("meihua", {"date":"2026-11-01", "time":"12:00", "timezone":"Asia/Shanghai"})
        utc = oracle.calculate("meihua", {"date":"2026-11-01", "time":"04:00", "timezone":"Etc/UTC"})
        self.assertEqual(china["method"]["numbers"], [39,46,46])
        self.assertEqual(china["method"]["lunar"]["year_branch"], "午")
        self.assertEqual(china["method"]["lunar"]["month"], 9)
        self.assertEqual(china["method"]["lunar"]["day"], 23)
        self.assertEqual(china["hexagrams"], utc["hexagrams"])
        self.assertEqual(china["moving_positions"], [4])

    def test_midnight_hour_and_lunar_year_boundaries_are_recorded(self):
        a=oracle.calculate("meihua", {"date":"2026-02-16", "time":"23:59", "timezone":"Asia/Shanghai"})
        b=oracle.calculate("meihua", {"date":"2026-02-17", "time":"00:00", "timezone":"Asia/Shanghai"})
        self.assertEqual(a["method"]["lunar"]["hour_number"], 1)
        self.assertEqual(b["method"]["lunar"]["hour_number"], 1)
        self.assertEqual(a["method"]["lunar"]["year_branch"], "巳")
        self.assertEqual(b["method"]["lunar"]["year_branch"], "午")
        leap=oracle.calculate("meihua", {"date":"2025-07-25", "time":"12:00", "timezone":"Asia/Shanghai"})
        self.assertTrue(leap["method"]["lunar"]["leap"])
        self.assertEqual(leap["method"]["lunar"]["month"], 6)

    def test_invalid_and_ambiguous_clocks_never_choose_silently(self):
        for p in ({"date":"2026-03-08","time":"02:30","timezone":"America/New_York"},
                  {"date":"2026-11-01","time":"01:30","timezone":"America/New_York"},
                  {"date":"2026-11-01","timezone":"Asia/Shanghai"},
                  {"numbers":[True,2]}, {"numbers":[-1,2]}, {"numbers":[2,3],"date":"2026-11-01"}):
            with self.subTest(p=p), self.assertRaises(ValueError): oracle.calculate("meihua",p)
        p={"date":"2026-11-01","time":"01:30","timezone":"America/New_York"}
        a=oracle.calculate("meihua", {**p,"fold":0})
        b=oracle.calculate("meihua", {**p,"fold":1})
        self.assertNotEqual(a["method"]["utc"],b["method"]["utc"])
        self.assertEqual(oracle.calculate("meihua", {})["status"],"needs_input")

    def test_dream_source_and_deterministic_matching(self):
        p={"text":"梦见一条蛇游进水里。"}
        result=oracle.calculate("dream",p)
        self.assertEqual(result,oracle.calculate("dream",p))
        self.assertEqual(result["lookup_status"],"matched")
        self.assertLessEqual(len(result["matches"]),12)
        source,_=oracle._dictionary()
        actual={e["id"]:e for e in source["entries"]}
        for e in result["matches"]:
            self.assertEqual(e["text"],actual[e["id"]]["text"])
            self.assertTrue(e["matched_keywords"])
        self.assertEqual(result["source"]["revision"],7907671)
        self.assertEqual(result["input"],p)

    def test_multilingual_aliases_and_word_boundaries(self):
        for text in ("I dreamed of a snake swimming in water.", "夢の中で蛇が水の中を泳いでいました。", "꿈에서 뱀이 물속에서 헤엄치고 있었어요."):
            with self.subTest(text=text):
                result=oracle.calculate("dream",{"text":text})
                self.assertEqual(result["lookup_status"],"matched")
        result=oracle.calculate("dream",{"text":"ZXQVL-92348"})
        self.assertEqual(result["lookup_status"],"no_match")
        self.assertEqual(result["matches"],[])
        self.assertEqual(oracle.calculate("dream",{})["status"],"needs_input")
        with self.assertRaises(ValueError):oracle.calculate("dream",{"text":"x"*4001})

    def test_multi_symbol_lookup_covers_late_chapter_keywords(self):
        for text,needed in (("梦见船沿河漂过草地，一条蛇在水里。",{"船","蛇"}),
                            ("I dreamed of a boat on a river, grass and a snake in the water.",{"boat","snake"}),
                            ("夢の中で船と草を見ました。水には蛇がいました。",{"船","蛇"}),
                            ("꿈에서 배가 강에 떠 있었어요. 풀과 뱀이 물속에 있었어요.",{"배","뱀"})):
            with self.subTest(text=text):
                result=oracle.calculate("dream",{"text":text})
                keywords={word for entry in result["matches"] for word in entry["matched_keywords"]}
                self.assertTrue(needed <= keywords,keywords)
                self.assertLessEqual(len(result["matches"]),12)
                self.assertEqual(result,oracle.calculate("dream",{"text":text}))

    def test_alias_boundaries_do_not_invent_objects_from_words(self):
        for word,text,japanese in (("소","꿈속 장소가 달랐어요.",False),("물","건물 앞에서 걸었어요.",False),("말","친구가 말했다.",False),("水","水曜日に夢を見ました。",True),("木","木曜日でした。",True)):
            with self.subTest(word=word,text=text):self.assertFalse(oracle._keyword_present(word,text,japanese))
        for word,text,japanese in (("뱀","뱀이 나타났어요.",False),("거울","거울을 봤어요.",False),("물","물속에서 헤엄쳤어요.",False),("船","船で川を渡りました。",True),("水","水があふれました。",True)):
            with self.subTest(word=word,text=text):self.assertTrue(oracle._keyword_present(word,text,japanese))

    def test_actual_lookup_rejects_weekday_and_korean_compound_false_hits(self):
        for text,forbidden in (("水曜日",{"水"}),("木曜日",{"木"}),("내 소속 회사에 있었어요.",{"소"}),("소속",{"소"})):
            with self.subTest(text=text):
                result=oracle.calculate("dream",{"text":text})
                found={word for entry in result["matches"] for word in entry["matched_keywords"]}
                self.assertFalse(found & forbidden,found)
        for text,needed in (("뱀이 나타났어요.","뱀"),("거울을 봤어요.","거울"),("물속에서 헤엄쳤어요.","물"),("船で川を渡りました。","船"),("水があふれました。","水")):
            with self.subTest(text=text):
                result=oracle.calculate("dream",{"text":text})
                found={word for entry in result["matches"] for word in entry["matched_keywords"]}
                self.assertIn(needed,found)

    def test_dream_only_has_no_birth_clock_place_or_random_dependency(self):
        from intake_autofill import pending_places
        r=request(); saved=copy.deepcopy(r)
        with patch("intake_flow.build_chart",side_effect=AssertionError("birth invented")), patch("iching.coin_cast",side_effect=AssertionError("draw invented")):
            p=intake_flow.plan_request(r)
        self.assertEqual(r,saved)
        self.assertEqual(pending_places(p["request"]),[])
        flow=p["people"][0]["workflow_input"]
        self.assertIsNone(flow["birth"])
        self.assertEqual(flow["systems"],["dream"])
        self.assertFalse(flow["deferred"])
        self.assertFalse(p["warnings"])

    def test_all_retains_27_entries_but_defers_birth_and_absent_casts(self):
        flow=intake_flow.plan_request(request(systems="all"))["people"][0]["workflow_input"]
        self.assertEqual(len(flow["systems"]),27)
        self.assertEqual(set(flow["deferred"]),set(flow["systems"])-{"dream"})
        self.assertNotIn("date",flow["options"]["meihua"]["params"])
        self.assertEqual(flow["options"]["dream"]["params"]["text"],request()["people"][0]["dream"])

    def test_meihua_only_accepts_birthless_person_and_explicit_cast(self):
        r=request("",["meihua"])
        r["preferences"]["cast"]={"date":"2026-11-01","time":"12:00","timezone":"Asia/Shanghai"}
        flow=intake_flow.plan_request(r)["people"][0]["workflow_input"]
        self.assertIsNone(flow["birth"])
        self.assertEqual(flow["options"]["meihua"]["params"]["date"],"2026-11-01")
        self.assertFalse(flow["deferred"])
        with self.assertRaises(intake_flow.MissingBasics):intake_flow.plan_request(request("", "all"))

    def test_actual_dream_prose_can_select_report_language_without_ui_hint(self):
        r=request("I dreamed of a snake swimming in the water.")
        r["preferences"]["question"]=""
        flow=intake_flow.plan_request(r)["people"][0]["workflow_input"]
        self.assertEqual(flow["questionnaire"]["_report_language"],"en")

    def test_pair_dreams_are_person_scoped_and_global_text_is_rejected(self):
        r=request();r["mode"]="pair"
        r["people"].append({"person":{"name":"纯虚构梦境人物B"},"birth":None,"dream":"梦见屋里有一只白猫。"})
        p=intake_flow.plan_request(r)
        self.assertNotEqual(p["people"][0]["workflow_input"]["options"]["dream"],p["people"][1]["workflow_input"]["options"]["dream"])
        r["method_options"]={"dream":{"text":"同一个梦"}}
        with self.assertRaises(ValueError):intake_flow.normalize_request(r)

    def test_explicit_invalid_birth_is_not_silently_ignored(self):
        r=request();r["people"][0]["birth"]={"date":"2026-02-30","calendar":"solar","timezone":"Asia/Shanghai"}
        with self.assertRaises(ValueError):intake_flow.plan_request(r)

    def test_report_visual_contracts_and_reference_classification(self):
        for system,p,kind in (("dream",{"text":"梦见蛇。"},"board"),("meihua",{"numbers":"2,3,1"},"hexagrams")):
            v=workbench_api.calculate(system,p)
            self.assertEqual(v["view"]["kind"],kind)
            self.assertTrue(v["view"]["data"])
        self.assertEqual(report_synthesis._category("ready",oracle.calculate("dream",{"text":"梦见蛇。"}),"dream"),("reference",False))

    def test_real_meihua_plus_dream_does_not_require_cross_method_synthesis(self):
        r=request(systems=["meihua","dream"])
        r["method_options"]={"meihua":{"numbers":[2,3,1]}}
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)/"reports"
            result=intake_flow.submit(folder,r)
            self.assertIn(result["status"],("ready","partial"),result)
            job=folder/result["job_id"]
            description=agent_report.describe(job)
            self.assertFalse(description["synthesis_required"])
            self.assertFalse(description["people"][0]["synthesis_required"])
            self.assertEqual({v["system"] for v in description["people"][0]["needs_readings"]},{"meihua","dream"})
            _,_,records=agent_report.snapshot(job)
            self.assertEqual(reader_language._calculated(records[0]),{"meihua"})
            counts=report_synthesis.synthesis_context(records,"A")["coverage_counts"]
            self.assertEqual(counts["calculated"],1)
            self.assertEqual(counts["reference"],1)

    def test_unmatched_dream_still_requires_valid_prose_and_can_finalize(self):
        body=("你记下的梦境是一串“ZXQVL-92348”。眼前更值得补充的是，这串符号出现在什么位置，你当时是在观察它、寻找它，还是试着记住它。若它写在门牌上，可以留意梦里有没有寻找去处的情节；若它来自手机或纸张，可以回想最近是否经常接触编号、通知或需要记忆的信息。这些问题各有不同的侧重，先保留你真正记得的部分，不必为了凑成完整故事而添加细节。\n\n"
              "醒来后的感受也值得单独记下。好奇、紧张、熟悉和困惑，会让同一串符号在梦里具有不同的分量。你可以把最先浮现的一个感受写在旁边，再想起最近一次相似的体验，看看两者是否有具体联系。如果暂时没有联想，就先把这一页留下，等下一次又做了相近的梦时比较出现的场景和自己的反应，避免只凭一串字母数字替生活作决定。")
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)/"reports"
            result=intake_flow.submit(folder,request("ZXQVL-92348"))
            self.assertIn(result["status"],("ready","partial"),result)
            job=folder/result["job_id"]
            self.assertFalse(agent_report.describe(job)["synthesis_required"])
            self.assertEqual(agent_report.finalize(job)["status"],"needs_interpretation")
            _,_,records=agent_report.snapshot(job)
            record=records[0]
            self.assertEqual(record["payloads"]["dream"]["lookup_status"],"no_match")
            panel=record["report"]["panels"][0]
            binding={"result_sha256":panel["result_sha256"],"question_hash":record["report"]["question_hash"],
                     "basis":[{"kind":"calculation","pointer":"/matches","label":"本次古文检索条目"}]}
            for bad in ("", "这份日表只涉及提问当天，没有比较其他日期，也没有时辰表。"):
                with self.subTest(bad=bad):
                    if not bad:
                        with self.assertRaises(ValueError):
                            workflow.run_project(record["workspace"],patch={"readings":{"dream":{**binding,"text":bad}}})
                        continue
                    workflow.run_project(record["workspace"],patch={"readings":{"dream":{**binding,"text":bad}}})
                    self.assertIn(agent_report.finalize(job)["status"],("needs_interpretation","needs_reader_edit"))
            workflow.run_project(record["workspace"],patch={"readings":{"dream":{**binding,"text":body}}})
            _,_,after=agent_report.snapshot(job)
            self.assertEqual(after[0]["report"]["panels"][0]["reading_status"],"applied")
            self.assertEqual(reader_language.audit_reader_report(after,{},detailed=True),[])
            final=agent_report.finalize(job)
            self.assertEqual(final["status"],"exported",final)
            self.assertTrue(Path(final["files"][0]["path"]).is_file())

    def test_real_job_and_update_keep_dream_bound_to_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)/"reports"
            result=intake_flow.submit(folder,request())
            self.assertIn(result["status"],("ready","partial"),result)
            job=folder/result["job_id"]
            _,_,records=agent_report.snapshot(job)
            record=records[0];payload=record["payloads"]["dream"]
            rows=personal_report.panels(record["report"],record["payloads"])
            self.assertEqual([p["system"] for p in rows],["dream"])
            self.assertEqual(rows[0]["view"]["kind"],"board")
            self.assertEqual(agent_report.describe(job)["people"][0]["needs_readings"][0]["system"],"dream")
            context=report_synthesis.synthesis_context(records,"A")
            self.assertEqual(context["coverage_counts"]["reference"],1)
            self.assertEqual(context["coverage_counts"]["calculated"],0)
            old=record["report"]["panels"][0]["result_sha256"]
            agent_updates.update_job(job,{"dream":"梦见月亮落在院子里。"},person="A")
            _,_,after=agent_report.snapshot(job)
            self.assertNotEqual(old,after[0]["report"]["panels"][0]["result_sha256"])
            self.assertNotEqual(payload["input"],after[0]["payloads"]["dream"]["input"])


if __name__ == "__main__":
    unittest.main()
