"""Actual one-use HTTP/CLI collection and no-computation invariants."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import copy
import http.client as http_client
import json
import os
from pathlib import Path
import queue
import re
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parents[1]
SKILL=Path(os.environ.get('MINGXUE_TEST_SKILL_ROOT') or (HERE/'package/mingxue-master' if (HERE/'package/mingxue-master').is_dir() else HERE))
sys.path.insert(0,str(SKILL/"scripts"))
import agent_intake
import intake_flow
import workbench


def sample():
    return {"mode":"single","people":[{"person":{"name":"合成收集示例"},
            "birth":{"date":"2000-08-16","time":None,"calendar":"solar","timezone":"Asia/Shanghai"}}],
            "preferences":{"systems":["bazi","yilin","tarot"],"virtual_draws":True,"prepare_engines":True,
                           "answers":{"当前关注":["学习","沟通"]}},
            "method_options":{"yilin":{"method":"coins","seed":100},"tarot":{"seed":200}}}


def http(url,path="/",data=None,token=None,extra=None):
    address=urlsplit(url)
    connection=http_client.HTTPConnection(address.hostname,address.port,timeout=15)
    headers={"Origin":url}
    if token:
        headers["Authorization"]="Bearer "+token
    if data is not None:
        headers["Content-Type"]="application/json"
        data=json.dumps(data,ensure_ascii=False).encode("utf-8")
    headers.update(extra or {})
    try:
        connection.request("POST" if data is not None else "GET",path,data,headers)
        response=connection.getresponse()
        raw=response.read()
        return response.status,raw,dict(response.getheaders())
    finally:
        connection.close()


@contextmanager
def server(directory,agent=True):
    instance=workbench.Server(("127.0.0.1",0),workbench.Records(directory,agent_mode=agent),agent_mode=agent)
    thread=threading.Thread(target=instance.serve_forever,kwargs={"poll_interval":0.02},daemon=True)
    thread.start()
    try:
        yield instance
    finally:
        instance.collection_cancel.set()
        instance.shutdown()
        thread.join(timeout=3)
        instance.server_close()


class CollectionTests(unittest.TestCase):
    def test_native_request_roundtrip_and_no_compute_prepare_or_draw(self):
        incoming=sample(); saved=copy.deepcopy(incoming)
        with tempfile.TemporaryDirectory() as temporary, \
             patch("workflow.run_project",side_effect=AssertionError("calculation forbidden")), \
             patch("workbench_api.calculate",side_effect=AssertionError("adapter forbidden")), \
             patch("workbench_api.prepare",side_effect=AssertionError("prepare forbidden")), \
             patch("iching.coin_cast",side_effect=AssertionError("draw forbidden")), \
             patch("classic_oracles._sample_bits",side_effect=AssertionError("draw forbidden")), \
             patch("symbolic.tarot",side_effect=AssertionError("draw forbidden")):
            result=agent_intake.collect_request(Path(temporary)/"collected",incoming)
            self.assertEqual(result["status"],"submitted",result)
            request_file=Path(result["request_file"])
            native=json.loads(request_file.read_text(encoding="utf-8"))
            self.assertEqual(intake_flow.normalize_request(native),native)
            self.assertEqual(set(native),{"mode","people","preferences","method_options"})
            self.assertEqual(incoming,saved)
            self.assertEqual(json.loads(request_file.with_name("original-request.json").read_text(encoding="utf-8")),incoming)
            self.assertTrue(request_file.with_name("plan.json").is_file())
            self.assertFalse(list(request_file.parent.rglob("*.html")))
            metadata=json.loads(request_file.with_name("metadata.json").read_text(encoding="utf-8"))
            self.assertFalse(metadata["calculated"])
            self.assertFalse(metadata["engines_prepared"])
            self.assertFalse(metadata["drawn"])

    def test_invalid_input_is_write_free_and_has_no_path_or_credential_fields(self):
        incoming=sample(); incoming["method_options"]["tarot"]["engine_dir"]="/untrusted"
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)/"not-created"
            result=agent_intake.collect_request(directory,incoming)
            self.assertEqual(result["status"],"invalid_input")
            self.assertFalse(directory.exists())
            self.assertNotIn("request_file",result)
            self.assertNotIn("/untrusted",json.dumps(result))

    def test_protected_roots_reject_both_directions_and_relative_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            protected=Path(temporary)/"protected"
            with patch("output_paths.protected_output_roots",return_value=(protected,)):
                for directory in (protected,protected/"child",protected.parent,Path("relative")):
                    with self.subTest(directory=directory),self.assertRaises(ValueError):
                        agent_intake.guard_data_directory(directory)
                self.assertFalse(protected.exists())
            with self.assertRaises(ValueError):
                agent_intake.guard_data_directory(SKILL)
            with self.assertRaises(ValueError):
                agent_intake.guard_data_directory(SKILL.parent)
            with self.assertRaises(ValueError):
                agent_intake.guard_data_directory(Path(sys.executable).parent)

    def test_real_http_invalid_retry_then_submit_is_private_and_duplicate_409(self):
        with tempfile.TemporaryDirectory() as temporary,server(Path(temporary)/"data") as instance:
            status,page,headers=http(instance.base)
            self.assertEqual(status,200)
            self.assertIn(b'name="mingli-intake-mode" content="agent"',page)
            self.assertIn("HttpOnly",headers["Set-Cookie"])
            token=instance.token
            incoming=sample(); incoming["people"][0]["birth"]["date"]="2000-02-31"
            status,raw,_=http(instance.base,"/api/submit",incoming,token)
            self.assertEqual(status,400)
            self.assertEqual(json.loads(raw)["status"],"invalid_input")
            self.assertFalse(instance.submission_event.is_set())
            self.assertFalse((instance.records.root/"collected").exists())
            status,raw,_=http(instance.base,"/api/submit",sample(),token)
            self.assertEqual(status,200,raw)
            response=json.loads(raw)
            self.assertEqual(response["status"],"submitted")
            self.assertEqual(response["files"],[])
            self.assertNotIn("request_file",response)
            self.assertNotIn(str(instance.records.root),raw.decode())
            self.assertTrue(instance.submission_event.wait(2))
            native=Path(instance.submission_payload["request_file"])
            for path in native.parent.glob("*.json"):
                self.assertNotIn(token,path.read_text(encoding="utf-8"))
            self.assertEqual(http(instance.base,"/api/submit",sample(),token)[0],409)
            self.assertEqual(len(list((instance.records.root/"collected").iterdir())),1)
            self.assertEqual(http(instance.base,"/files/"+response["job_id"]+"/request.json",token=token)[0],404)

    def test_concurrent_submit_accepts_first_only_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temporary,server(Path(temporary)/"data") as instance:
            entered=threading.Event(); release=threading.Event(); original=workbench.worker
            def held(request,**kwargs):
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("test rendezvous timed out")
                return original(request,**kwargs)
            with patch.object(workbench,"worker",side_effect=held),ThreadPoolExecutor(max_workers=2) as pool:
                first=pool.submit(http,instance.base,"/api/submit",sample(),instance.token)
                self.assertTrue(entered.wait(5))
                second=http(instance.base,"/api/submit",sample(),instance.token)
                self.assertEqual(second[0],409)
                release.set()
                self.assertEqual(first.result(timeout=15)[0],200)
            self.assertEqual(len(list((instance.records.root/"collected").iterdir())),1)

    def test_agent_security_and_explicit_cancel(self):
        with tempfile.TemporaryDirectory() as temporary,server(Path(temporary)/"data") as instance:
            self.assertEqual(http(instance.base,"/api/submit",sample())[0],401)
            self.assertEqual(http(instance.base,"/",extra={"Host":"evil.invalid"})[0],403)
            self.assertEqual(http(instance.base,"/api/submit",sample(),instance.token,{"Origin":"https://evil.invalid"})[0],403)
            self.assertEqual(http(instance.base,"/api/calculate",{"system":"bazi"},instance.token)[0],403)
            self.assertEqual(http(instance.base,"/api/prepare",{"system":"astrology"},instance.token)[0],403)
            credential=sample(); credential["people"][0]["person"]["notes"]=instance.token
            self.assertEqual(http(instance.base,"/api/submit",credential,instance.token)[0],400)
            status,raw,_=http(instance.base,"/api/cancel",{},instance.token)
            self.assertEqual(status,200)
            self.assertEqual(json.loads(raw)["status"],"cancelled")
            self.assertTrue(instance.submission_event.wait(2))
            self.assertEqual(http(instance.base,"/api/submit",sample(),instance.token)[0],409)
            self.assertFalse((instance.records.root/"collected").exists())

    def test_default_server_preserves_calculation_adapter_path(self):
        value={"system":"numerology","name":"数秘","params":{"date":"2000-08-16"},
               "result":{"system":"numerology","status":"ok"},"view":{"kind":"numbers"}}
        with tempfile.TemporaryDirectory() as temporary,server(Path(temporary)/"data",False) as instance:
            self.assertNotIn(b'name="mingli-intake-mode"',http(instance.base)[1])
            with patch.object(workbench,"worker",return_value=value) as worker:
                status,raw,_=http(instance.base,"/api/calculate",{"system":"numerology","params":{"date":"2000-08-16"}},instance.token)
            self.assertEqual(status,200,raw)
            self.assertEqual(worker.call_args.args[0]["operation"],"calculate")
            self.assertRegex(json.loads(raw)["id"],r"^[a-f0-9]{32}$")

    def test_default_server_keeps_report_submit_operation(self):
        response={"status":"partial","job_id":"a"*32,"files":[{"filename":"personal-a.html","url":"/files/"+"a"*32+"/personal-a.html"}],"warnings":[]}
        with tempfile.TemporaryDirectory() as temporary,server(Path(temporary)/"data",False) as instance:
            with patch.object(workbench,"worker",return_value=response) as worker:
                status,raw,_=http(instance.base,"/api/submit",sample(),instance.token)
            self.assertEqual(status,200)
            self.assertEqual(json.loads(raw),response)
            self.assertEqual(worker.call_args.args[0]["operation"],"submit")
            self.assertEqual(worker.call_args.args[0]["reports_dir"],str(instance.reports_root))
            self.assertFalse(instance.submission_event.is_set())

    def test_actual_default_worker_still_returns_calculated_numeric_result(self):
        response=workbench.worker({"operation":"calculate","system":"numerology","params":{"date":"2000-08-16"}})
        self.assertEqual(response["system"],"numerology")
        self.assertIn("life_path",response["result"])
        self.assertEqual(response["view"]["kind"],"numbers")

    def test_cancellation_reaps_only_the_collector_child_started_by_this_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); (root/"scripts").mkdir()
            (root/"scripts/workbench_api.py").write_text("import time\ntime.sleep(30)\n",encoding="utf-8")
            started=threading.Event(); cancelled=threading.Event(); processes=[]
            original=subprocess.Popen
            def launch(*args,**kwargs):
                child=original(*args,**kwargs)
                processes.append(child); started.set()
                return child
            with patch.object(workbench,"ROOT",root),patch.object(subprocess,"Popen",side_effect=launch),ThreadPoolExecutor(max_workers=1) as pool:
                pending=pool.submit(workbench.worker,{"operation":"collect","request":{}},cancel_event=cancelled)
                self.assertTrue(started.wait(3))
                cancelled.set()
                with self.assertRaises(subprocess.TimeoutExpired):
                    pending.result(timeout=5)
            self.assertEqual(len(processes),1)
            self.assertIsNotNone(processes[0].poll())


class ActualCLITests(unittest.TestCase):
    def launch(self,directory,timeout=20,ready_file=None):
        command=[sys.executable,"-X","utf8","-B",str(SKILL/"scripts/agent_intake.py"),"--data-dir",str(directory),"--timeout",str(timeout)]
        if ready_file:
            command.extend(["--ready-file",str(ready_file)])
        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8")
        def cleanup():
            if process.poll() is None:
                process.kill()
            process.communicate()
        self.addCleanup(cleanup)
        results=queue.Queue()
        threading.Thread(target=lambda:results.put(process.stdout.readline()),daemon=True).start()
        first=results.get(timeout=15)
        return process,json.loads(first)

    def test_http_submit_cli_result_then_process_and_port_close(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)/"data"; ready_file=Path(temporary)/"ready.json"
            process,first=self.launch(directory,ready_file=ready_file)
            self.assertEqual(first["status"],"collecting")
            self.assertNotIn("token",json.dumps(first).lower())
            self.assertEqual(json.loads(ready_file.read_text(encoding="utf-8")),first)
            status,page,_=http(first["url"])
            token=re.search(rb'name="workbench-token" content="([^"]+)"',page).group(1).decode()
            status,body,_=http(first["url"],"/api/submit",sample(),token)
            self.assertEqual(status,200,body)
            self.assertNotIn("request_file",json.loads(body))
            output,errors=process.communicate(timeout=10)
            self.assertEqual(process.returncode,0,errors)
            final=json.loads(output)
            self.assertEqual(final["status"],"submitted")
            self.assertTrue(Path(final["request_file"]).is_absolute())
            self.assertTrue(Path(final["request_file"]).is_file())
            self.assertEqual(final["job_id"],json.loads(body)["job_id"])
            self.assertNotIn("2000-08-16",output)
            self.assertNotIn(token,output)
            with self.assertRaises((OSError,http_client.HTTPException)):
                http(first["url"],"/api/submit",sample(),token)

    def test_timeout_returns_no_completed_request_and_stops_only_this_service(self):
        with tempfile.TemporaryDirectory() as temporary,server(Path(temporary)/"other") as unrelated:
            process,first=self.launch(Path(temporary)/"data",timeout=0.2)
            output,errors=process.communicate(timeout=10)
            self.assertEqual(process.returncode,3,errors)
            final=json.loads(output)
            self.assertEqual(final["status"],"timeout")
            self.assertNotIn("request_file",final)
            self.assertIsNone(final["job_id"])
            self.assertFalse((Path(temporary)/"data/collected").exists())
            with self.assertRaises((OSError,http_client.HTTPException)):
                http(first["url"])
            self.assertEqual(http(unrelated.base)[0],200)

    def test_http_cancel_closes_cli_without_saving_a_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)/"data"
            process,first=self.launch(directory)
            page=http(first["url"])[1]
            token=re.search(rb'name="workbench-token" content="([^"]+)"',page).group(1).decode()
            status,raw,_=http(first["url"],"/api/cancel",{},token)
            self.assertEqual(status,200)
            output,errors=process.communicate(timeout=10)
            self.assertEqual(process.returncode,130,errors)
            self.assertEqual(json.loads(output)["status"],"cancelled")
            self.assertNotIn("request_file",json.loads(output))
            self.assertFalse((directory/"collected").exists())
            with self.assertRaises((OSError,http_client.HTTPException)):
                http(first["url"])


if __name__=="__main__":
    unittest.main(verbosity=2)
