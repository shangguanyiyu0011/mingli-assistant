"""Place-only collection, real timezone resolution, and fail-closed calculation."""
import copy
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parents[1]
SKILL=Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT") or HERE)
sys.path.insert(0,str(SKILL/"scripts"))
import agent_intake
import agent_report
import intake_autofill as autofill
import intake_flow
import workbench_api


def request():
    return {"mode":"single","people":[{"person":{"name":"合成地点测试"},"birth":{"date":"2000-08-16","calendar":"solar","time":None},"birthplace":"深圳, 广东"}],
            "preferences":{"systems":["numerology"],"cast_place":"Berlin, Germany","cast":{"datetime_utc":"2026-07-01T23:30:00Z"}}}


def rows(query):
    if "Berlin" in query:
        return [{"id":2950159,"name":"柏林","admin1":"柏林","country":"德国","country_code":"DE","latitude":52.52437,"longitude":13.41053,"timezone":"Europe/Berlin"}]
    return [{"id":1795565,"name":"深圳","admin1":"广东","feature_code":"PPLA2","country":"中国","country_code":"CN","latitude":22.54554,"longitude":114.0683,"timezone":"Asia/Shanghai"}]


class AutofillTests(unittest.TestCase):
    def test_default_http_submit_resolves_places_and_keeps_files_contract(self):
        from test_agent_intake import server, http
        def worker(payload):
            output=StringIO()
            with patch("sys.stdin",StringIO(json.dumps(payload))),redirect_stdout(output):
                code=workbench_api.main()
            response=json.loads(output.getvalue())
            self.assertEqual(code,0,response)
            self.assertTrue(response["ok"],response)
            return response["value"]
        incoming=request()
        with tempfile.TemporaryDirectory() as temporary,server(Path(temporary)/"data",agent=False) as instance,patch("workbench.worker",side_effect=worker),patch.object(autofill,"_read_json",side_effect=rows):
            status,raw,_=http(instance.base,"/api/submit",data=incoming,token=instance.token)
            result=json.loads(raw)
            self.assertEqual(status,200,result)
            self.assertIn(result["status"],("ready","partial"),result)
            self.assertTrue(result["files"],result)
            job=instance.reports_root/result["job_id"]
            for item in result["files"]:
                self.assertTrue((job/item["filename"]).is_file())
                self.assertEqual(item["url"],f"/files/{result['job_id']}/{item['filename']}")
            sources=json.loads((job/"place-resolution.json").read_text(encoding="utf-8"))
            self.assertEqual(sources["original_request"],incoming)
            canonical=json.loads((job/"submitted-input.json").read_text(encoding="utf-8"))
            self.assertEqual(canonical["people"][0]["birth"]["timezone"],"Asia/Shanghai")
            self.assertTrue((instance.reports_root/".place-cache").is_dir())

    def test_default_submit_blocks_lookup_failure_and_preserves_photo_manifest(self):
        ambiguous=rows("x")+[dict(rows("x")[0],id=2,longitude=100)]
        for effect in (lambda query:ambiguous,autofill.PlaceLookupError("暂时无法联网")):
            with self.subTest(effect=effect),tempfile.TemporaryDirectory() as temporary,patch.object(autofill,"_read_json",side_effect=effect),patch("intake_flow.submit") as calculate:
                result=workbench_api.submit_request(Path(temporary)/"reports",request(),photo_manifest="trusted-photo.json")
                self.assertEqual(result["status"],"needs_input")
                self.assertFalse(result["files"])
                calculate.assert_not_called()
        with tempfile.TemporaryDirectory() as temporary,patch.object(autofill,"_read_json",side_effect=rows),patch("intake_flow.submit",return_value={"status":"needs_input"}) as calculate:
            workbench_api.submit_request(Path(temporary)/"reports",request(),photo_manifest="trusted-photo.json")
            self.assertEqual(calculate.call_args.kwargs["photo_manifest"],"trusted-photo.json")
            self.assertEqual(calculate.call_args.args[1]["people"][0]["birth"]["timezone"],"Asia/Shanghai")
        with patch.object(autofill,"_read_json") as network,self.assertRaises(intake_flow.IntakeError):
            workbench_api.submit_request(SKILL,request())
        network.assert_not_called()

    def test_collection_preserves_places_and_null_time_without_lookup_or_chart(self):
        incoming=request();before=copy.deepcopy(incoming)
        with tempfile.TemporaryDirectory() as temporary,patch.object(autofill,"_read_json",side_effect=AssertionError("no network in collection")),patch("intake_flow.build_chart",side_effect=AssertionError("no chart in collection")),patch("workflow.run_project",side_effect=AssertionError("no calculation")):
            result=agent_intake.collect_request(Path(temporary)/"collected",incoming)
            self.assertEqual(result["status"],"submitted",result)
            native=json.loads(Path(result["request_file"]).read_text(encoding="utf-8"))
            self.assertIsNone(native["people"][0]["birth"]["timezone"])
            self.assertIsNone(native["people"][0]["birth"]["time"])
            self.assertEqual(native["people"][0]["birthplace"],"深圳, 广东")
            plan=json.loads(Path(result["request_file"]).with_name("plan.json").read_text(encoding="utf-8"))
            self.assertFalse(plan["people"])
            self.assertEqual(len(plan["pending_places"]),2)
            self.assertEqual(incoming,before)

    def test_resolution_passes_real_coordinates_iana_zone_and_utc_conversion(self):
        with patch.object(autofill,"_read_json",side_effect=rows):
            result=autofill.resolve_request(request())
        self.assertFalse(result["questions"],result)
        native=result["request"]
        self.assertEqual(native["people"][0]["birth"]["timezone"],"Asia/Shanghai")
        self.assertIsNone(native["people"][0]["birth"]["time"])
        self.assertEqual(native["people"][0]["location"],{"latitude":22.54554,"longitude":114.0683})
        self.assertEqual(native["preferences"]["cast"],{"date":"2026-07-02","time":"01:30:00","timezone":"Europe/Berlin","latitude":52.52437,"longitude":13.41053})
        self.assertEqual(result["sources"][1]["matches"][0]["source"]["geonames_id"],2950159)
        self.assertTrue(intake_flow.plan_request(native)["people"])

    def test_report_resolves_before_submit_and_persists_original_and_source(self):
        incoming=request()
        with tempfile.TemporaryDirectory() as temporary,patch.object(autofill,"_read_json",side_effect=rows):
            root=Path(temporary);path=root/"request.json";path.write_text(json.dumps(incoming),encoding="utf-8")
            result=agent_report.run(path,root/"reports")
            self.assertNotIn(result["status"],("error","invalid_input","needs_input"),result)
            job=Path(result["job_dir"])
            canonical=json.loads((job/"submitted-input.json").read_text(encoding="utf-8"))
            self.assertEqual(canonical["people"][0]["birth"]["timezone"],"Asia/Shanghai")
            sources=json.loads((job/"place-resolution.json").read_text(encoding="utf-8"))
            self.assertEqual(sources["original_request"],incoming)
            self.assertEqual(len(sources["sources"]),2)

    def test_ambiguous_place_and_network_failure_never_calculate(self):
        ambiguous=rows("x")+[dict(rows("x")[0],id=2,longitude=100)]
        for side_effect in (lambda query: ambiguous,autofill.PlaceLookupError("暂时连不上地点查询服务")):
            with self.subTest(side_effect=side_effect),tempfile.TemporaryDirectory() as temporary,patch.object(autofill,"_read_json",side_effect=side_effect),patch("agent_report.submit") as submit:
                path=Path(temporary)/"request.json";path.write_text(json.dumps(request()),encoding="utf-8")
                result=agent_report.run(path,Path(temporary)/"reports")
                self.assertEqual(result["status"],"needs_input",result)
                self.assertTrue(result["questions"])
                submit.assert_not_called()
                self.assertFalse(list((Path(temporary)/"reports").glob("*/submitted-input.json")))

    def test_existing_canonical_is_unchanged_and_never_uses_network(self):
        incoming=request();person=incoming["people"][0]
        person.pop("birthplace");person["birth"]["timezone"]="Asia/Shanghai"
        person["location"]={"latitude":31.23,"longitude":121.47}
        incoming["preferences"]={"systems":["numerology"],"cast":{"date":"2026-07-02","time":"01:30","timezone":"Europe/Berlin"}}
        expected=intake_flow.normalize_request(incoming)
        with patch.object(autofill,"_read_json",side_effect=AssertionError("canonical needs no lookup")):
            result=autofill.resolve_request(incoming)
        self.assertEqual(result["request"],expected)
        self.assertFalse(result["sources"])

    def test_conflicting_explicit_timezone_is_not_overwritten(self):
        incoming=request();incoming["people"][0]["birth"]["timezone"]="Europe/London"
        with patch.object(autofill,"_read_json",side_effect=rows):
            result=autofill.resolve_request(incoming)
        self.assertTrue(result["questions"])
        self.assertEqual(result["request"]["people"][0]["birth"]["timezone"],"Europe/London")

    def test_historical_local_cast_and_place_only_are_both_supported(self):
        for cast in ({"date":"2020-02-01","time":"09:40"},None):
            with self.subTest(cast=cast),patch.object(autofill,"_read_json",side_effect=rows):
                incoming=request();incoming["preferences"]["cast"]=cast
                result=autofill.resolve_request(incoming)
                self.assertFalse(result["questions"],result)
                self.assertFalse(autofill.pending_places(result["request"]))
                if cast:
                    self.assertEqual(result["request"]["preferences"]["cast"]["timezone"],"Europe/Berlin")

    def test_cache_retains_original_retrieval_time_and_avoids_repeat_network(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(autofill,"_read_json",side_effect=rows) as network:
            first=autofill.search_places("Berlin, Germany",cache_dir=temporary)
            second=autofill.search_places("Berlin, Germany",cache_dir=temporary)
            self.assertEqual(first,second)
            self.assertEqual(network.call_count,1)

    def test_chinese_full_administration_falls_back_only_to_verified_parent(self):
        def lookup(query):
            return rows(query) if query=="深圳, 广东" else []
        with patch.object(autofill,"_read_json",side_effect=lookup):
            matches=autofill.search_places("中国广东省深圳市南山区某医院")
        self.assertEqual(len(matches),1)
        self.assertIn("深圳市",matches[0]["precision"])
        self.assertIn("未核实",matches[0]["precision"])

    def test_real_http_accepts_unresolved_places_and_originals_without_engine_work(self):
        from test_agent_intake import server, http
        with tempfile.TemporaryDirectory() as temporary,server(Path(temporary)/"data") as instance:
            status,raw,_=http(instance.base,"/api/submit",data=request(),token=instance.token)
            value=json.loads(raw)
            self.assertEqual(status,200,value)
            self.assertEqual(value["status"],"submitted",value)
            path=next((Path(temporary)/"data"/"collected").glob("*/request.json"))
            saved=json.loads(path.read_text(encoding="utf-8"))
            self.assertIsNone(saved["people"][0]["birth"]["timezone"])
            self.assertFalse(list(path.parent.rglob("*.html")))

    def test_chinese_city_province_order_and_same_named_village(self):
        shenzhen=rows("x")[0]
        village=dict(shenzhen,id=2,feature_code="PPL",admin1="其他省")
        with patch.object(autofill,"_read_json",return_value=[shenzhen,village]):
            matches=autofill.search_places("深圳市，广东省")
        self.assertEqual(len(matches),1)
        self.assertEqual(matches[0]["source"]["geonames_id"],1795565)

    def test_localized_names_keep_city_suffix_and_split_compact_province(self):
        benxi={"id":2038300,"name":"本溪市","feature_code":"PPL","admin1":"辽宁","admin2":"本溪市","country":"中国","country_code":"CN","latitude":41.28861,"longitude":123.765,"timezone":"Asia/Shanghai"}
        changzhou={"id":1815456,"name":"常州市","feature_code":"PPLA2","admin1":"江苏","admin2":"常州市","country":"中国","country_code":"CN","latitude":31.77359,"longitude":119.95401,"timezone":"Asia/Shanghai"}
        def lookup(query):
            return {"本溪市, 辽宁":[benxi],"常州市, 江苏":[changzhou]}.get(query,[])
        incoming=request();incoming["people"][0]["birthplace"]="辽宁省本溪市"
        incoming["preferences"]["cast_place"]="江苏常州"
        before=copy.deepcopy(incoming)
        with patch.object(autofill,"_read_json",side_effect=lookup) as network:
            result=autofill.resolve_request(incoming)
        self.assertFalse(result["questions"],result)
        self.assertEqual(incoming,before)
        self.assertEqual(result["request"]["people"][0]["birth"]["timezone"],"Asia/Shanghai")
        self.assertEqual(result["request"]["preferences"]["cast"]["timezone"],"Asia/Shanghai")
        self.assertEqual([s["query"] for s in result["sources"]],["辽宁省本溪市","江苏常州"])
        self.assertEqual([s["matches"][0]["source"]["geonames_id"] for s in result["sources"]],[2038300,1815456])
        self.assertEqual([c.args[0] for c in network.call_args_list],["本溪, 辽宁","本溪市, 辽宁","江苏常州","常州, 江苏","常州市, 江苏"])

    def test_compact_province_keeps_country_and_rejects_same_named_village(self):
        city={"id":1815456,"name":"常州市","feature_code":"PPLA2","admin1":"江苏","admin2":"常州市","country":"中国","latitude":31.77359,"longitude":119.95401,"timezone":"Asia/Shanghai"}
        village=dict(city,id=2,name="常州",feature_code="PPL")
        for query,results in (("江苏常州",[village]),("江苏常州，法国",[city]),("浙江常州",[city])):
            with self.subTest(query=query),patch.object(autofill,"_read_json",return_value=results):
                self.assertEqual(autofill.search_places(query),[])

    def test_province_prefix_does_not_rewrite_existing_administrative_names(self):
        cases=[
            ("河北区，天津","河北, 天津",{"id":1,"name":"河北区","admin1":"天津市","country":"中国","feature_code":"ADM3"}),
            ("河南县，青海","河南, 青海",{"id":2,"name":"河南县","admin1":"青海","country":"中国","feature_code":"ADM3"}),
            ("海南州，青海","海南州,青海",{"id":3,"name":"海南州","admin1":"青海","country":"中国","feature_code":"ADM2"}),
            ("河南市，韩国","河南, 韩国",{"id":4,"name":"河南市","admin1":"京畿道","country":"韩国","feature_code":"ADM3"}),
        ]
        for query,lookup,row in cases:
            row={**row,"latitude":36,"longitude":128,"timezone":"Asia/Seoul"}
            with self.subTest(query=query),patch.object(autofill,"_read_json",return_value=[row]) as network:
                matches=autofill.search_places(query)
                self.assertEqual(len(matches),1)
                self.assertEqual(matches[0]["source"]["geonames_id"],row["id"])
                network.assert_called_once_with(lookup)
        for query in ("河北区，天津","河南县，青海","海南州，青海","河南市，韩国"):
            self.assertFalse(any("省" in lookup for lookup,_ in autofill._queries(query)))

    def test_autonomous_names_are_not_treated_as_province_prefixes(self):
        for query,lookup,name,feature in (
            ("海南藏族自治州，青海","海南藏族自治州,青海","海南藏族自治州","ADM2"),
            ("河南蒙古族自治县，青海","河南蒙古族自治, 青海","河南蒙古族自治县","ADM3"),
        ):
            row={"id":1,"name":name,"admin1":"青海","country":"中国","feature_code":feature,"latitude":35,"longitude":101,"timezone":"Asia/Shanghai"}
            with self.subTest(query=query),patch.object(autofill,"_read_json",return_value=[row]) as network:
                matches=autofill.search_places(query)
                self.assertEqual(len(matches),1)
                network.assert_called_once_with(lookup)
            self.assertFalse(any("省" in lookup for lookup,_ in autofill._queries(query)))

    def test_autonomous_region_uses_admin1_not_district_or_arbitrary_label(self):
        nanning={"id":1799869,"name":"南宁","feature_code":"PPLA","admin1":"广西","admin2":"南宁市","country":"中国","latitude":22.81667,"longitude":108.31667,"timezone":"Asia/Shanghai"}
        for query in ("广西壮族自治区南宁市","南宁市，广西壮族自治区"):
            with self.subTest(query=query),patch.object(autofill,"_read_json",return_value=[nanning]) as lookup:
                matches=autofill.search_places(query)
                self.assertEqual(len(matches),1)
                self.assertEqual(matches[0]["source"]["geonames_id"],1799869)
                lookup.assert_called_once_with("南宁, 广西")
        misleading=dict(nanning,admin1="广东",admin3="广西")
        with patch.object(autofill,"_read_json",return_value=[misleading]):
            self.assertEqual(autofill.search_places("广西壮族自治区南宁市"),[])

    def test_district_never_becomes_same_named_village_in_same_prefecture(self):
        village={"id":8368567,"name":"西湖","feature_code":"PPL","admin1":"浙江","admin2":"杭州市","country":"中国","latitude":29.61998,"longitude":118.84041,"timezone":"Asia/Shanghai"}
        city={"id":1808926,"name":"杭州","feature_code":"PPLA","admin1":"浙江","country":"中国","latitude":30.29365,"longitude":120.16142,"timezone":"Asia/Shanghai"}
        with patch.object(autofill,"_read_json",side_effect=lambda query:[village] if query.startswith("西湖") else [city]):
            matches=autofill.search_places("杭州市西湖区，浙江省")
        self.assertEqual(matches[0]["source"]["geonames_id"],1808926)
        self.assertIn("杭州市",matches[0]["precision"])
        self.assertIn("未核实",matches[0]["precision"])

    def test_same_named_city_cannot_claim_to_be_a_county(self):
        city={"id":1,"name":"长沙","feature_code":"PPLA","admin1":"湖南","admin2":"长沙市","country":"中国","latitude":28.2,"longitude":113,"timezone":"Asia/Shanghai"}
        with patch.object(autofill,"_read_json",return_value=[city]):
            matches=autofill.search_places("湖南省长沙县")
        self.assertEqual(matches,[])

    def test_explicit_country_is_not_discarded_when_chinese_city_is_split(self):
        with patch.object(autofill,"_read_json",return_value=[]) as lookup:
            self.assertFalse(autofill.search_places("深圳市，法国"))
        self.assertEqual([c.args[0] for c in lookup.call_args_list],["深圳, 法国","深圳市, 法国"])
        with patch.object(autofill,"_read_json",side_effect=rows):
            self.assertFalse(autofill.search_places("广东省深圳市，法国"))

    def test_cache_is_external_even_when_request_is_read_from_plugin_tree(self):
        with tempfile.TemporaryDirectory() as temporary,patch("agent_report.read_json",return_value=request()),patch.object(autofill,"_read_json",side_effect=rows),patch("agent_report.submit",return_value={"status":"needs_input"}):
            root=Path(temporary)/"reports"
            agent_report.run(SKILL/"readonly-example.json",root)
            self.assertEqual(len(list((root/".place-cache").glob("*.json"))),2)
        with patch("agent_report.read_json",return_value=request()),patch.object(autofill,"_read_json") as network:
            result=agent_report.run(SKILL/"readonly-example.json",SKILL)
            self.assertEqual(result["status"],"invalid_input")
            network.assert_not_called()

    def test_utc_cast_in_a_dst_repeat_is_blocked_instead_of_losing_its_fold(self):
        incoming=request();incoming["preferences"]["cast"]["datetime_utc"]="2026-10-25T01:30:00Z"
        with patch.object(autofill,"_read_json",side_effect=rows):
            result=autofill.resolve_request(incoming)
        self.assertTrue(result["questions"])
        self.assertIn("夏令时",result["questions"][0]["question"])

    def test_strict_normalizer_still_rejects_unresolved_timezone_and_bad_utc(self):
        with self.assertRaises(intake_flow.MissingBasics):
            intake_flow.normalize_request(request())
        for value in ("2026-07-01T09:30:00","2026-07-01T09:30:00+08:00",3):
            incoming=request();incoming["preferences"]["cast"]["datetime_utc"]=value
            with self.subTest(value=value),self.assertRaises(intake_flow.IntakeError):
                intake_flow.normalize_request(incoming,allow_unresolved_places=True)


if __name__=="__main__":
    unittest.main()
