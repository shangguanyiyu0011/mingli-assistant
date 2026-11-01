"""Real native replanning, immutable originals and same-input result reuse."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parents[1]
SKILL=Path(os.environ.get('MINGXUE_TEST_SKILL_ROOT') or (HERE/'package/mingxue-master' if (HERE/'package/mingxue-master').is_dir() else HERE))
sys.path.insert(0,str(SKILL/"scripts"))
import agent_updates
import intake_flow
import workflow
from project_store import project_lock,read_json


def request(pair=False,systems=None):
    people=[{"person":{"name":"更正甲合成资料"},"birth":{"date":"1990-06-15","calendar":"solar","timezone":"Asia/Shanghai","time":None}}]
    if pair:
        people.append({"person":{"name":"更正乙合成资料"},"birth":{"date":"1994-09-08","calendar":"solar","timezone":"Asia/Shanghai","time":None}})
    return {"mode":"pair" if pair else "single","people":people,"preferences":{"systems":systems or ["numerology","sukuyo"],"depth":"brief","prepare_engines":False}}


def create(directory,native):
    response=intake_flow.submit(directory,native)
    if response["status"] not in ("ready","partial"):
        raise AssertionError(response)
    return directory/response["job_id"]


def current(job,role="A"):
    project=job/("project-"+role.lower())
    state=workflow.project_status(project)
    version=Path(state["report"]).parent
    return state,read_json(version/"input.json"),read_json(version/"report.json"),{
        name:read_json(project/item["file"]) for name,item in state["components"].items()}


class ActualUpdates(unittest.TestCase):
    def test_birth_correction_rederives_numeric_date_keeps_original_and_stales_reading(self):
        with tempfile.TemporaryDirectory() as temporary:
            job=create(Path(temporary)/"reports",request(systems=["numerology","sukuyo","qizheng"]))
            original=(job/"submitted-input.json").read_bytes()
            state,source,report,payloads=current(job)
            reading={"text":"此处只阅读当前生命路径归约结构。","result_sha256":state["components"]["numerology"]["sha256"],
                     "question_hash":report["question_hash"],"basis":[{"kind":"calculation","pointer":"/life_path"}]}
            workflow.run_project(job/"project-a",patch={"readings":{"numerology":reading}})
            self.assertEqual(next(x for x in current(job)[2]["panels"] if x["system"]=="numerology")["reading_status"],"applied")
            response=agent_updates.update_job(job,{"birth":{"date":"1991-06-15"}},person="A")
            self.assertTrue(response["request_committed"],response)
            _,source,report,payloads=current(job)
            self.assertEqual(source["options"]["numerology"]["date"],"1991-06-15")
            self.assertEqual(payloads["numerology"]["birth_date"],"1991-06-15")
            self.assertEqual(source["options"]["qizheng"]["params"]["date"],"1991-06-15")
            self.assertEqual(source["readings"]["numerology"],reading)
            self.assertEqual(next(x for x in report["panels"] if x["system"]=="numerology")["reading_status"],"stale")
            self.assertEqual((job/"submitted-input.json").read_bytes(),original)
            self.assertEqual(read_json(job/"current-request.json")["people"][0]["birth"]["date"],"1991-06-15")

    def test_lunar_birth_correction_replans_gregorian_numeric_and_native_mansion(self):
        incoming=request();incoming["people"][0]["birth"].update(calendar="lunar",date="1990-01-15")
        with tempfile.TemporaryDirectory() as temporary:
            job=create(Path(temporary)/"reports",incoming)
            old_numeric=current(job)[3]["numerology"]["birth_date"]
            response=agent_updates.update_job(job,{"birth":{"date":"1991-01-15"}},"A")
            self.assertTrue(response["request_committed"])
            expected=intake_flow.plan_request(read_json(job/"current-request.json"))["people"][0]["workflow_input"]
            _,source,_,payloads=current(job)
            self.assertEqual(source["options"]["numerology"]["date"],expected["options"]["numerology"]["date"])
            self.assertNotEqual(payloads["numerology"]["birth_date"],old_numeric)
            self.assertEqual(source["options"]["sukuyo"]["params"]["birth"]["year"],1991)
            self.assertEqual(source["options"]["sukuyo"],expected["options"]["sukuyo"])

    def test_unknown_to_known_removes_deferred_instead_of_merging_it_back(self):
        incoming=request(systems=["ziwei","numerology"])
        incoming["people"][0]["birth"]["gender"]="female"
        with tempfile.TemporaryDirectory() as temporary:
            job=create(Path(temporary)/"reports",incoming)
            self.assertIn("ziwei",current(job)[1]["deferred"])
            response=agent_updates.update_job(job,{"birth":{"time":"08:26"}},"A")
            self.assertTrue(response["request_committed"],response)
            state,source,_,payloads=current(job)
            self.assertNotIn("ziwei",source["deferred"])
            self.assertNotEqual(payloads["ziwei"]["status"],"needs_input")
            # Engine absence remains honest; no assertion of a fabricated ready chart.
            self.assertEqual(source["birth"]["time"],"08:26")

    def test_birth_and_question_updates_keep_independent_cast_and_cards(self):
        incoming=request(systems=["numerology","iching","tarot"])
        incoming["preferences"].update(virtual_draws=True,cast={"date":"2026-10-31","time":"18:00","timezone":"Asia/Shanghai"})
        incoming["method_options"]={"iching":{"lines":[6,7,8,9,7,8]},"tarot":{"seed":5566}}
        with tempfile.TemporaryDirectory() as temporary:
            job=create(Path(temporary)/"reports",incoming)
            old=current(job)[3]
            response=agent_updates.update_job(job,{"birth":{"date":"1991-06-15"}},"A")
            self.assertTrue(response["request_committed"])
            self.assertIn("tarot",response["revisions"]["A"]["reused"])
            response=agent_updates.update_job(job,{"preferences":{"question":"如何沟通学习安排？","answers":{"当前关注":["学习","沟通"]}}})
            self.assertTrue(response["request_committed"])
            self.assertIn("tarot",response["revisions"]["A"]["reused"])
            self.assertIn("iching",response["revisions"]["A"]["reused"])
            _,source,_,now=current(job)
            self.assertEqual(now["tarot"],old["tarot"])
            self.assertEqual(now["iching"],old["iching"])
            self.assertEqual(source["options"]["iching"]["cast_date"],"2026-10-31")
            self.assertEqual(source["birth"]["date"],"1991-06-15")
            self.assertEqual(source["questionnaire"],{"当前关注":["学习","沟通"]})
            removed=agent_updates.update_job(job,{"preferences":{"cast":None}})
            self.assertTrue(removed["request_committed"])
            _,source,_,now=current(job)
            self.assertNotIn("cast_date",source["options"]["iching"])
            self.assertNotIn("cast_timezone",source["options"]["iching"])
            self.assertEqual(now["iching"]["cast_context"]["status"],"not_supplied")

    def test_b_only_correction_does_not_advance_a_and_full_people_array_replaces(self):
        with tempfile.TemporaryDirectory() as temporary:
            job=create(Path(temporary)/"reports",request(True))
            a=current(job,"A")
            response=agent_updates.update_job(job,{"birth":{"date":"1995-09-08"}},"B")
            self.assertTrue(response["request_committed"])
            self.assertFalse(response["revisions"]["A"]["changed"])
            self.assertEqual(current(job,"A")[0]["active_revision"],a[0]["active_revision"])
            self.assertEqual(current(job,"A")[3],a[3])
            native=read_json(job/"current-request.json")
            people=copy.deepcopy(native["people"])
            people[1]["person"]={"name":"更正乙的新称呼"}
            response=agent_updates.update_job(job,{"people":people})
            self.assertTrue(response["request_committed"])
            self.assertEqual(current(job,"B")[1]["person"],{"name":"更正乙的新称呼"})
            self.assertEqual(current(job,"A")[0]["active_revision"],a[0]["active_revision"])

    def test_invalid_patch_and_lock_conflict_have_no_new_person_revision(self):
        with tempfile.TemporaryDirectory() as temporary:
            job=create(Path(temporary)/"reports",request())
            old=current(job)[0]["active_revision"]
            for change,person in (({"birth":{"date":"1991-02-30"}},"A"),({"preferences":{"question":"错层级"}},"A"),({"birth":{"time":True}},"A"),({},"B")):
                with self.subTest(change=change,person=person),self.assertRaises(ValueError):
                    agent_updates.update_job(job,change,person)
                self.assertEqual(current(job)[0]["active_revision"],old)
            with project_lock(job),self.assertRaises(ValueError):
                agent_updates.update_job(job,{"birth":{"date":"1991-06-15"}},"A")
            self.assertFalse((job/"current-request.json").exists())

    def test_private_observation_updates_use_new_files_and_leave_old_snapshot_untouched(self):
        incoming=request(systems=["palm","numerology"])
        incoming["method_options"]={"palm":{"observations":{"hand":"left","features":[{"region":"central_vertical","shape":"straight","visibility":"clear"}]}}}
        with tempfile.TemporaryDirectory() as temporary:
            job=create(Path(temporary)/"reports",incoming)
            oldfile=Path(current(job)[1]["options"]["palm"]["observations"])
            original=oldfile.read_bytes()
            response=agent_updates.update_job(job,{"method_options":{"palm":{"observations":{"hand":"right"}}}})
            self.assertTrue(response["request_committed"],response)
            _,source,_,payloads=current(job)
            self.assertNotEqual(Path(source["options"]["palm"]["observations"]),oldfile)
            self.assertEqual(oldfile.read_bytes(),original)
            self.assertEqual(payloads["palm"]["user_reported_observations"]["hand"],"right")

    def test_second_person_failure_is_partial_and_never_commits_native_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            job=create(Path(temporary)/"reports",request(True))
            original=workflow.run_project
            def fail_b(project,*args,**kwargs):
                if Path(project).name=="project-b":
                    raise OSError("synthetic interrupted second update")
                return original(project,*args,**kwargs)
            with patch.object(workflow,"run_project",side_effect=fail_b):
                response=agent_updates.update_job(job,{"preferences":{"question":"双方新问题"}})
            self.assertEqual(response["status"],"partial")
            self.assertFalse(response["request_committed"])
            self.assertIn("A",response["revisions"])
            self.assertNotIn("B",response["revisions"])
            self.assertFalse((job/"current-request.json").exists())
            self.assertNotEqual(current(job,"A")[1]["question"],current(job,"B")[1]["question"])
            recovered=agent_updates.update_job(job,{"preferences":{"question":"双方新问题"}})
            self.assertTrue(recovered["request_committed"])
            self.assertEqual(current(job,"A")[1]["question"],current(job,"B")[1]["question"])


class PathTests(unittest.TestCase):
    def test_external_absolute_job_and_private_symlink_protection(self):
        for value in (Path("relative"),SKILL,Path(sys.executable).parent):
            with self.subTest(value=value),self.assertRaises(ValueError):
                agent_updates.update_job(value,{})
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            job=create(root/"reports",request())
            source=job/"current-request.json"
            # A patched filesystem observation avoids requiring Windows symlink privileges.
            real=agent_updates._linked
            with patch.object(agent_updates,"_linked",side_effect=lambda path:path==source or real(path)),self.assertRaises(ValueError):
                agent_updates.update_job(job,{})
            self.assertEqual(current(job)[0]["active_revision"],"v000001")


if __name__=="__main__":
    unittest.main(verbosity=2)
