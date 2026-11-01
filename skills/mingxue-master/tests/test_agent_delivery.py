"""Actual immutable HTML delivery; PDF calls are mocked, no browser is started."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT",Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(ROOT/"scripts"))
import agent_report
import report_pdf
from test_agent_report_review import run_job,apply_readings,make_pair_reading


def exported(source,target):
    # Deliberately a structural PDF fixture, never a real user deliverable.
    raw=b"%PDF-1.4\n"+b"fixture\n"*150+b"%%EOF\n"
    with Path(target).open("xb") as stream:stream.write(raw)
    return {"status":"exported","path":str(target),"sha256":hashlib.sha256(raw).hexdigest(),"size_bytes":len(raw)}


class AgentDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.job,_=run_job(self.root)
        apply_readings(self.job)
        self.pair,_=make_pair_reading(self.job,self.root/"pair.json")

    def deliver(self,**kwargs):
        return agent_report.deliver(self.job,self.root/"out",pair_reading_file=self.pair,**kwargs)

    def test_complete_delivery_records_real_pdf_bytes_and_preserves_html_manifest(self):
        with mock.patch.object(report_pdf,"export_pdf",side_effect=exported) as export:
            first=self.deliver();second=self.deliver()
        self.assertEqual(first["status"],"exported");self.assertEqual(export.call_count,6)
        self.assertEqual(json.loads(Path(first["delivery_manifest"]).read_text(encoding="utf-8")),first)
        for file in first["files"]:
            html=Path(file["delivery_path"]);self.assertEqual(hashlib.sha256(html.read_bytes()).hexdigest(),file["sha256"])
            pdf=file["pdf"];self.assertEqual(Path(pdf["path"]),html.with_suffix(".pdf"))
            self.assertEqual(hashlib.sha256(Path(pdf["path"]).read_bytes()).hexdigest(),pdf["sha256"])
            original=json.loads((Path(file["path"]).parent/"manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(all("pdf" not in row for row in original["files"]))
        self.assertTrue({f["pdf"]["path"] for f in first["files"]}.isdisjoint(f["pdf"]["path"] for f in second["files"]))

    def test_partial_pdf_failure_keeps_all_html_and_successful_pdf(self):
        calls=0
        def export(source,target):
            nonlocal calls
            calls+=1
            return {"status":"needs_browser","code":"browser_not_found","message":"没有可用导出器。"} if calls==2 else exported(source,target)
        with mock.patch.object(report_pdf,"export_pdf",side_effect=export):result=self.deliver()
        self.assertEqual(result["status"],"needs_pdf_export")
        self.assertEqual([f["pdf"]["status"] for f in result["files"]],["exported","needs_browser","exported"])
        self.assertTrue(all(Path(f["delivery_path"]).is_file() for f in result["files"]))
        self.assertFalse(Path(result["files"][1]["delivery_path"]).with_suffix(".pdf").exists())

    def test_exporter_success_without_actual_pdf_is_not_success(self):
        with mock.patch.object(report_pdf,"export_pdf",return_value={"status":"exported","path":"missing","sha256":"a"*64,"size_bytes":1234}):result=self.deliver()
        self.assertEqual(result["status"],"needs_pdf_export")
        self.assertTrue(all(f["pdf"]["code"]=="invalid_pdf_export" for f in result["files"]))

    def test_existing_pdf_is_not_overwritten(self):
        previous=b"existing user PDF"
        def export(source,target):
            target.write_bytes(previous)
            return {"status":"error","code":"output_exists","message":"目标已存在。"}
        with mock.patch.object(report_pdf,"export_pdf",side_effect=export):result=self.deliver()
        self.assertEqual(result["status"],"needs_pdf_export")
        self.assertTrue(all(Path(f["delivery_path"]).with_suffix(".pdf").read_bytes()==previous for f in result["files"]))

    def test_no_output_directory_uses_immutable_html_siblings_and_finalize_stays_html_only(self):
        with mock.patch.object(report_pdf,"export_pdf",side_effect=exported) as export:
            html=agent_report.finalize(self.job,pair_reading_file=self.pair);self.assertEqual(export.call_count,0)
            result=agent_report.deliver(self.job,pair_reading_file=self.pair)
        self.assertEqual(result["status"],"exported")
        self.assertTrue(all(Path(f["pdf"]["path"])==Path(f["path"]).with_suffix(".pdf") for f in result["files"]))
        self.assertTrue(all("pdf" not in f for f in html["files"]))

    def test_pending_reading_does_not_attempt_pdf_and_cli_returns_incomplete_code(self):
        pending={"status":"needs_interpretation","files":[]}
        with mock.patch.object(agent_report,"finalize",return_value=pending),mock.patch.object(report_pdf,"export_pdf") as export:
            self.assertEqual(agent_report.deliver(self.job),pending);export.assert_not_called()
        with mock.patch.object(agent_report,"deliver",return_value={"status":"needs_pdf_export","files":[]}) as deliver,contextlib.redirect_stdout(io.StringIO()):
            code=agent_report.main(["deliver","--job",str(self.job),"--illustrations",str(self.root/"diagrams.json")])
        self.assertEqual(code,3);self.assertEqual(deliver.call_args.kwargs["illustrations_file"],str(self.root/"diagrams.json"))


if __name__=="__main__":unittest.main()
