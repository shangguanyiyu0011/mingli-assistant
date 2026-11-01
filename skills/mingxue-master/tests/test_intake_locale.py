"""Four-locale UI requests, native intake and ZIP handoff; no browser/server."""
import base64
import copy
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

SKILL=Path(os.environ.get('MINGXUE_TEST_SKILL_ROOT',Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(SKILL/'scripts'))
import intake_flow
import offline_intake
import workflow
import workbench


class IntakeLocaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result=subprocess.run([shutil.which('node'),str(SKILL/'tests/test_intake_i18n.js')],capture_output=True,text=True,encoding='utf-8',timeout=30)
        if result.returncode:raise AssertionError(result.stderr)
        cls.ui=json.loads(result.stdout)
        cls.dictionary=json.loads((SKILL/'ui/intake-locales.json').read_text(encoding='utf-8'))

    def test_all_four_language_native_requests_and_international_names(self):
        self.assertEqual(self.ui['passed'],5)
        self.assertEqual(len(self.ui['requests']),67)
        for sample in self.ui['requests']:
            with self.subTest(language=sample['language'],topic=sample['topic']):
                request=copy.deepcopy(sample['request'])
                normalized=intake_flow.normalize_request(request,allow_unresolved_places=True)
                self.assertEqual(normalized['preferences']['ui_language'],sample['language'])
                self.assertEqual(normalized['preferences']['language'],'auto')
                self.assertEqual(normalized['people'][0]['person'],request['people'][0]['person'])
                self.assertIsNone(normalized['people'][0]['birth']['time'])
                request['people'][0]['birth']['timezone']='Asia/Shanghai'
                request['people'][0]['location']={'latitude':22.5431,'longitude':114.0579}
                request['preferences']['systems']=['numerology']
                if request['preferences'].get('cast'):
                    request['preferences'].pop('cast_place',None)
                    request['preferences']['cast']={'date':'2026-11-01','time':'08:00','timezone':'Asia/Shanghai','latitude':22.5431,'longitude':114.0579}
                plan=intake_flow.plan_request(request)
                self.assertEqual(len(plan['people']),1,plan['questions'])
                flow=workflow.normalize_input(plan['people'][0]['workflow_input'])
                self.assertEqual(flow['questionnaire']['_report_language'],sample['language'])
                self.assertEqual(flow['person'],request['people'][0]['person'])
                if sample['topic']=='international-name':
                    self.assertEqual(request['people'][0]['name']['mode'],'international')
                    self.assertEqual(flow['name']['full_name'],request['people'][0]['name']['full_name'])

    def test_exact_localized_requests_survive_offline_zip(self):
        script=r'''
const fs=require('node:fs'),vm=require('node:vm'),{webcrypto}=require('node:crypto');
const source=fs.readFileSync(process.argv[1],'utf8'),cases=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{const out=[];for(const sample of cases){let saved;
 const context={TextEncoder,Uint8Array,DataView,Blob,Response,crypto:webcrypto,atob,setTimeout,
 URL:{createObjectURL(blob){saved=blob;return 'blob:fixture';},revokeObjectURL(){}},document:{body:{appendChild(){}},createElement(){return {click(){},remove(){}};}},addEventListener(){},OFFLINE_CATALOG:{systems:[]}};
 context.window=context;vm.runInNewContext(source,context);const sent=await context.fetch('/api/submit',{body:JSON.stringify(sample.request)});
 if(sent.status!==200)throw Error('localized ZIP failed');out.push(Buffer.from(await saved.arrayBuffer()).toString('base64'));
 }console.log(JSON.stringify(out));})().catch(error=>{console.error(error);process.exitCode=1});
'''
        run=subprocess.run([shutil.which('node'),'-e',script,str(SKILL/'ui/offline-intake.js')],input=json.dumps(self.ui['requests']),capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(run.returncode,0,run.stderr)
        for sample,encoded in zip(self.ui['requests'],json.loads(run.stdout)):
            with self.subTest(language=sample['language'],topic=sample['topic']),zipfile.ZipFile(io.BytesIO(base64.b64decode(encoded))) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(json.loads(archive.read('request.json')),sample['request'])

    def test_complete_offline_html_inlines_every_dictionary_and_runtime(self):
        with patch.object(offline_intake,'art_bundle',return_value={}):page=offline_intake.build_page()
        self.assertNotRegex(page,r'<script[^>]+src=|<link[^>]+stylesheet')
        match=re.search(r'<script id="intake-locales" type="application/json">([\s\S]*?)</script>',page)
        self.assertIsNotNone(match)
        self.assertEqual(json.loads(match[1]),self.dictionary)
        self.assertIn((SKILL/'ui/i18n.js').read_text(encoding='utf-8').strip(),page)
        for label in ('中文','English','日本語','한국어'):self.assertIn(label,page)

    def test_live_static_language_routes_without_starting_a_server(self):
        class Capture:
            server=SimpleNamespace(agent_mode=True,token='synthetic-token')
            def trusted(self,*args,**kwargs):return True
            def respond(self,code,raw,mime=None,**kwargs):self.result=(code,raw,mime)
            def error(self,code,message):raise AssertionError((code,message))
        for path in ('/intake','/i18n.js'):
            handler=Capture();handler.path=path;workbench.Handler.do_GET(handler)
            self.assertEqual(handler.result[0],200)
            if path=='/intake':
                page=handler.result[1].decode('utf-8');match=re.search(r'<script id="intake-locales" type="application/json">([\s\S]*?)</script>',page)
                self.assertEqual(json.loads(match[1]),self.dictionary)
            else:self.assertEqual(handler.result[1],(SKILL/'ui/i18n.js').read_bytes())


if __name__=='__main__':unittest.main()
