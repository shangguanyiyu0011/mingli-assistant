"""Offline personal-report security and person/questionnaire binding checks."""
import copy
import base64
import binascii
from contextlib import contextmanager
from html.parser import HTMLParser
import http.client
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid

HERE = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get('MINGXUE_TEST_SKILL_ROOT') or (HERE/'package/mingxue-master' if (HERE/'package/mingxue-master').is_dir() else HERE))
sys.path.insert(0,str(SKILL/'scripts'))
import personal_report
import workflow
import pair_report
import intake_flow
from workbench import Records, Server

EVIDENCE = Path(os.environ['MINGXUE_REVIEW_EVIDENCE_DIR']) if os.environ.get('MINGXUE_REVIEW_EVIDENCE_DIR') else None
if EVIDENCE: EVIDENCE.mkdir(parents=True,exist_ok=True)
ATTACK = '</ScRiPt><img src=x onerror=alert(1)><script>alert(2)</script><!--&\u2028\u2029'

def inline_image(value):
    """Only the packaged/upload-supported raster formats are reader images."""
    match=re.fullmatch(r'data:image/(png|jpeg);base64,([A-Za-z0-9+/]+={0,2})',value or '')
    if not match:return False
    try:raw=base64.b64decode(match[2],validate=True)
    except (binascii.Error,ValueError):return False
    return raw.startswith(b'\x89PNG\r\n\x1a\n') if match[1]=='png' else raw.startswith(b'\xff\xd8\xff')

class Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.scripts=[]; self.script=None; self.resources=[]; self.dangerous=[]; self.csp=''
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='script': self.script={'attrs':attrs,'text':''}
        if tag in ('iframe','object','embed'): self.dangerous.append(tag)
        if tag=='img' and (not inline_image(attrs.get('src')) or attrs.get('srcset')):
            self.dangerous.append('img')
        for key,value in attrs.items():
            if key.startswith('on'): self.dangerous.append(key)
            if key in ('src','href','poster','action','srcset') and value and not value.startswith(('#','data:','blob:')):
                self.resources.append((tag,key,value))
        if tag=='meta' and attrs.get('http-equiv','').lower()=='content-security-policy': self.csp=attrs.get('content','')
    def handle_data(self,data):
        if self.script is not None: self.script['text']+=data
    def handle_endtag(self,tag):
        if tag=='script' and self.script is not None:
            self.scripts.append(self.script);self.script=None
    def data(self):
        return json.loads(next(s['text'] for s in self.scripts if s['attrs'].get('id')=='report-data'))

def sample_data():
    return {'schema_version':1,'kind':'personal','title':ATTACK,'people':[{'name':ATTACK,'birth':{'date':'1990-05-02','time':None}}],
        'meta':{'topic':ATTACK,'question':ATTACK,'revision':'v000001'},
        'panels':[{'id':'numerology','system':'numerology','title':ATTACK,'state':'ready','reading':ATTACK,
                   'interpretation':{'text':ATTACK,'basis':[{'label':ATTACK}]},'facts':[{'label':ATTACK,'value':ATTACK}],
                   'limits':[ATTACK],'view':{'kind':'reference','title':ATTACK,'data':{'text':ATTACK}},'raw':{'value':ATTACK}}]}

@contextmanager
def project_folder():
    if EVIDENCE:
        root=EVIDENCE/('personal-fixture-'+uuid.uuid4().hex[:10]);root.mkdir();yield root
    else:
        with tempfile.TemporaryDirectory(prefix='personal-report-review-') as directory: yield Path(directory)

def load(path): return json.loads(Path(path).read_text(encoding='utf-8'))

def first_input(name='甲-安全测试'):
    return {'person':{'name':name,'notes':'原履历'},'birth':{'date':'1990-05-02','time':None,'timezone':'Asia/Shanghai'},
            'topic':'事业','question':'同一出生输入，区分自述与计算。','systems':['numerology'],
            'questionnaire':{'关注':'研发'}}

def with_reading(root):
    first=workflow.run_project(root,first_input())
    report=load(first['report_json']);panel=report['panels'][0]
    reading={'text':'甲-安全测试：依据原履历讨论研发侧重点。','result_sha256':panel['result_sha256'],
             'question_hash':report['question_hash'],'basis':[{'kind':'calculation','pointer':'/life_path/reduction','label':'真实归约'}]}
    second=workflow.run_project(root,patch={'readings':{'numerology':reading}})
    return second,reading

class PersonalReportSecurityTests(unittest.TestCase):
    def test_json_script_closure_and_inline_resources(self):
        document=personal_report.document(sample_data());parsed=Document();parsed.feed(document)
        self.assertEqual(len(parsed.scripts),3)
        self.assertEqual(parsed.resources,[])
        self.assertEqual(parsed.dangerous,[])
        self.assertIn("connect-src 'none'",parsed.csp)
        self.assertEqual(parsed.data()['people'][0]['name'],ATTACK)
        self.assertEqual(parsed.data()['panels'][0]['raw']['value'],ATTACK)
        for script in parsed.scripts:
            self.assertNotIn('src',script['attrs'])
        # Allowing packaged images must not relax the attack detector into
        # accepting external, relative, SVG, event-bearing or srcset images.
        safe='data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode('ascii')
        image=Document();image.feed('<img src="'+safe+'" alt="装饰">');self.assertEqual(image.dangerous,[])
        for value in ('<img src=x>','<img src="https://invalid.example/x.png">','<img src="data:image/svg+xml,&lt;svg/&gt;">',
                      '<img src="'+safe+'" onerror="alert(1)">','<img src="'+safe+'" srcset="https://invalid.example/x.png 2x">'):
            rejected=Document();rejected.feed(value);self.assertTrue(rejected.dangerous)
        if EVIDENCE: (EVIDENCE/'hostile-personal-report.html').write_text(document,encoding='utf-8')

    @unittest.skipUnless(shutil.which('node'),'Node.js is needed to execute the inline report scripts')
    def test_actual_inline_scripts_do_not_request_or_create_injected_tags(self):
        parsed=Document();parsed.feed(personal_report.document(sample_data()))
        job={'data':parsed.scripts[0]['text'],'scripts':[s['text'] for s in parsed.scripts[1:]]}
        runner=r"""const vm=require('node:vm'),fs=require('node:fs');let q=JSON.parse(fs.readFileSync(0,'utf8'));let requests=0;const nodes=new Map();function node(id){const n={id,textContent:'',_html:'',addEventListener(){},querySelectorAll(){return []},click(){}};Object.defineProperty(n,'innerHTML',{get(){return this._html},set(v){this._html=v;for(const m of v.matchAll(/\bid="([^"]+)"/g))if(!nodes.has(m[1]))nodes.set(m[1],node(m[1]));}});return n;}nodes.set('report-app',node('report-app'));nodes.set('report-data',{textContent:q.data});let doc={getElementById:id=>nodes.get(id)||null,createElement:()=>node('new')};const deny=()=>{requests++;throw Error('unexpected network')};let win={addEventListener(){},print(){}};let c={window:win,document:doc,fetch:deny,XMLHttpRequest:deny,WebSocket:deny,navigator:{sendBeacon:deny},URL:{createObjectURL:()=> 'blob:review-local',revokeObjectURL(){}},Blob:globalThis.Blob,setTimeout(){}};vm.createContext(c);for(const s of q.scripts)vm.runInContext(s,c,{timeout:1000});process.stdout.write(JSON.stringify({requests,html:[...nodes.values()].map(n=>n._html||'').join('\n')}));"""
        run=subprocess.run([shutil.which('node'),'-e',runner],input=json.dumps(job,ensure_ascii=False),text=True,encoding='utf-8',capture_output=True,timeout=10)
        self.assertEqual(run.returncode,0,run.stderr)
        value=json.loads(run.stdout);p=Document();p.feed(value['html'])
        self.assertEqual(value['requests'],0)
        self.assertEqual(p.dangerous,[])
        self.assertEqual(p.resources,[])

    def test_questionnaire_changes_only_interpretation_context(self):
        with project_folder() as directory:
            root=directory/'project';before,_=with_reading(root)
            before_input=load(Path(before['report']).with_name('input.json'))
            after=workflow.run_project(root,patch={'questionnaire':{'关注':'产品设计；出生日期仍是1990-05-02'}})
            after_report=load(after['report_json']);after_input=load(Path(after['report']).with_name('input.json'))
            self.assertEqual(after_input['birth'],before_input['birth'])
            self.assertNotEqual(after_report['question_hash'],before['question_hash'])
            self.assertEqual(after_report['panels'][0]['reading_status'],'stale')
            self.assertIsNone(after_report['panels'][0]['traditional_interpretation'])
            self.assertEqual(after_report['panels'][0]['result_sha256'],load(before['report_json'])['panels'][0]['result_sha256'])

    def test_person_context_change_invalidates_prior_person_reading(self):
        with project_folder() as directory:
            root=directory/'project';before,_=with_reading(root)
            after=workflow.run_project(root,patch={'person':{'name':'乙-安全测试','notes':'另一条明确履历'}})
            report=load(after['report_json'])
            evidence={'project':str(root),'before_person':load(before['report_json'])['person'],'after_person':report['person'],
                      'same_question_hash':before['question_hash']==after['question_hash'],
                      'reading_status':report['panels'][0]['reading_status'],
                      'interpretation':report['panels'][0]['traditional_interpretation'],
                      'same_result_sha256':load(before['report_json'])['panels'][0]['result_sha256']==report['panels'][0]['result_sha256']}
            if EVIDENCE: (EVIDENCE/'person-binding-observed.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
            self.assertEqual(report['panels'][0]['reading_status'],'stale')
            self.assertIsNone(report['panels'][0]['traditional_interpretation'])

    def test_pair_export_keeps_each_project_person_birth_and_payload(self):
        with project_folder() as directory:
            a=first_input('甲-双人独立测试')
            b=first_input('乙-双人独立测试');b['birth']['date']='1992-06-13';b['person']['notes']='另一人履历'
            aroot,broot=directory/'a',directory/'b'
            ar=workflow.run_project(aroot,a);br=workflow.run_project(broot,b)
            target=directory/'pair.html'
            pair_report.export_pair(aroot,broot,target,'同事')
            parsed=Document();parsed.feed(target.read_text(encoding='utf-8'));data=parsed.data()
            self.assertEqual(parsed.resources,[])
            self.assertEqual(len(parsed.scripts),3)
            self.assertEqual([p['name'] for p in data['people']],[a['person']['name'],b['person']['name']])
            self.assertEqual([p['birth']['date'] for p in data['people']],[a['birth']['date'],b['birth']['date']])
            self.assertEqual([p['person_index'] for p in data['panels']],[0,1])
            self.assertEqual([p['raw']['birth_date'] for p in data['panels']],[a['birth']['date'],b['birth']['date']])
            self.assertEqual(data['panels'][0]['evidence']['result_sha256'],load(ar['report_json'])['panels'][0]['result_sha256'])
            self.assertEqual(data['panels'][1]['evidence']['result_sha256'],load(br['report_json'])['panels'][0]['result_sha256'])
            self.assertNotEqual(data['panels'][0]['evidence']['result_sha256'],data['panels'][1]['evidence']['result_sha256'])
            # Reader data omits the machine comparison. Its real A/B identity
            # and result evidence must still agree with the separate projects.
            self.assertIsNone(data['comparison'])
            self.assertEqual([p['person'] for p in data['people']],[a['person'],b['person']])
            self.assertTrue(all(p['birth']['time'] is None for p in data['people']))
            self.assertEqual([p['system'] for p in data['panels']],['numerology','numerology'])
            if EVIDENCE:
                (EVIDENCE/'pair-binding-observed.json').write_text(json.dumps({'report':str(target),'people':[p['name'] for p in data['people']],
                    'birth_dates':[p['birth']['date'] for p in data['people']],
                    'panels':[{'person_index':p['person_index'],'system':p['system'],'birth_date':p['raw']['birth_date'],
                        'result_sha256':p['evidence']['result_sha256']} for p in data['panels']],
                    'machine_comparison_omitted_from_reader':data['comparison'] is None,'offline_dependencies':parsed.resources,
                    'times_not_invented':all(p['birth']['time'] is None for p in data['people'])},ensure_ascii=False,indent=2),encoding='utf-8')

    def test_pair_export_rejects_same_project_and_protected_output(self):
        with project_folder() as directory:
            root=directory/'project';workflow.run_project(root,first_input())
            with self.assertRaises(ValueError): pair_report.export_pair(root,root,directory/'same.html')
            with self.assertRaises(ValueError): pair_report.export_pair(root,directory/'other',SKILL/'review-should-never-write.html')
            self.assertFalse((SKILL/'review-should-never-write.html').exists())

    def test_missing_birth_conditions_remain_deferred_without_fabricated_charts(self):
        with project_folder() as directory:
            request={'mode':'single','people':[{'person':{'name':'缺条件审查'},
                'birth':{'date':'1990-05-02','time':None,'calendar':'solar','timezone':'Asia/Shanghai'},'location':{}}],
                'preferences':{'systems':['numerology','astrology','ziwei'],'topic':'事业','relationship':'个人研习',
                    'answers':{'文本答案':'这里写2000-01-01 12:00不能变成生辰'},'prepare_engines':False}}
            result=intake_flow.submit(directory/'reports',request)
            self.assertEqual(result['status'],'partial')
            self.assertEqual(len(result['files']),1)
            target=directory/'reports'/result['job_id']/'personal-a.html'
            parsed=Document();parsed.feed(target.read_text(encoding='utf-8'));data=parsed.data()
            self.assertEqual(data['people'][0]['birth']['date'],'1990-05-02')
            self.assertIsNone(data['people'][0]['birth']['time'])
            rows={p['system']:p for p in data['panels']}
            self.assertEqual(rows['numerology']['raw']['birth_date'],'1990-05-02')
            self.assertEqual(set(rows),{'numerology'})
            project=directory/'reports'/result['job_id']/'project-a'
            state=workflow.project_status(project)
            private_report=load(Path(state['report']).with_name('report.json'))
            private_rows={p['system']:p for p in private_report['panels']}
            for system in ('astrology','ziwei'):
                self.assertNotIn(system,rows)
                self.assertIn(private_rows[system]['state'],('deferred','needs_input'))
                payload=load(project/state['components'][system]['file'])
                self.assertFalse(payload.get('chart'))
                self.assertFalse(payload.get('candidates'))
                self.assertFalse(payload.get('planets'))
            self.assertEqual({q['system'] for q in result['questions']},{'astrology','ziwei'})
            if EVIDENCE:
                (EVIDENCE/'missing-birth-conditions-observed.json').write_text(json.dumps({'status':result['status'],
                    'report':str(target),'actual_birth':data['people'][0]['birth'],
                    'rows':{s:{'state':p['state'],'raw_keys':sorted(p['raw'])} for s,p in rows.items()},
                    'private_missing_states':{s:private_rows[s]['state'] for s in ('astrology','ziwei')},
                    'questions':result['questions'],'external_dependencies':parsed.resources},ensure_ascii=False,indent=2),encoding='utf-8')


class ReportFileHTTPBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='report-http-review-',dir=EVIDENCE)
        cls.server=Server(('127.0.0.1',0),Records(cls.temp.name))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        job=cls.server.reports_root/('a'*32);job.mkdir(parents=True)
        cls.path='/files/'+('a'*32)+'/personal-a.html'
        cls.document=personal_report.document(sample_data()).encode('utf-8')
        (job/'personal-a.html').write_bytes(cls.document)
        (job/'submitted-input.json').write_text('{"private":true}',encoding='utf-8')
        code,headers,raw=cls.request('/intake',auth=False)
        if code!=200: raise RuntimeError('Own local intake fixture is unavailable')
        # Neither the cookie/header value nor the token-containing intake bytes are persisted.
        cookie=SimpleCookie(headers.get('Set-Cookie',''));entry=cookie.get('mingli_session')
        if not entry: raise RuntimeError('Own local intake did not set its session cookie')
        cls.cookie=entry.output(header='').strip().split(';',1)[0]
        cls.cookie_flags={k:bool(entry[k]) for k in ('httponly','samesite')}
        cls.cookie_samesite=entry['samesite'];cls.cookie_path=entry['path']
        cls.observed=[]

    @classmethod
    def tearDownClass(cls):
        if EVIDENCE:
            (EVIDENCE/'report-file-http-observed.json').write_text(json.dumps({'bind':cls.server.server_address[0],
                'cookie_flags':cls.cookie_flags,'cookie_samesite':cls.cookie_samesite,'cookie_path':cls.cookie_path,
                'cases':cls.observed},ensure_ascii=False,indent=2),encoding='utf-8')
        cls.server.shutdown();cls.thread.join(timeout=5);cls.server.server_close();cls.temp.cleanup()

    @classmethod
    def request(cls,path,auth=True,headers=None):
        chosen={'Host':'127.0.0.1:'+str(cls.server.server_port)}
        if auth: chosen['Authorization']='Bearer '+cls.server.token
        chosen.update(headers or {})
        connection=http.client.HTTPConnection('127.0.0.1',cls.server.server_port,timeout=5)
        try:
            connection.request('GET',path,headers=chosen);response=connection.getresponse()
            return response.status,dict(response.getheaders()),response.read()
        finally: connection.close()

    def expect(self,label,path,status,*,auth=True,headers=None):
        code,_,_=self.request(path,auth=auth,headers=headers)
        self.observed.append({'case':label,'status':code,'expected':status})
        self.assertEqual(code,status,label)

    def test_files_require_bearer_or_cookie_and_never_query_credentials(self):
        self.expect('no_auth',self.path,401,auth=False)
        self.expect('wrong_cookie',self.path,401,auth=False,headers={'Cookie':'mingli_session=invalid'})
        self.expect('query_credential_not_accepted',self.path+'?token='+self.server.token,401,auth=False)
        self.expect('bearer',self.path,200)
        self.expect('http_only_cookie_navigation',self.path,200,auth=False,headers={'Cookie':self.cookie})
        self.assertTrue(self.cookie_flags['httponly'])
        self.assertEqual(self.cookie_samesite,'Strict')
        self.assertEqual(self.cookie_path,'/')

    def test_cookie_is_limited_to_files_and_host_origin_remain_checked(self):
        self.expect('history_does_not_accept_cookie','/api/history',401,auth=False,headers={'Cookie':self.cookie})
        self.expect('foreign_host',self.path,403,auth=False,headers={'Cookie':self.cookie,'Host':'evil.invalid'})
        self.expect('foreign_origin',self.path,403,auth=False,headers={'Cookie':self.cookie,'Origin':'https://evil.invalid'})
        self.expect('opaque_origin',self.path,403,auth=False,headers={'Cookie':self.cookie,'Origin':'null'})

    def test_private_paths_and_traversal_are_not_served(self):
        prefix='/files/'+('a'*32)+'/'
        for label,path in (
            ('private_input',prefix+'submitted-input.json'),('nested_project',prefix+'project-a/versions/v000001/report.html'),
            ('parent',prefix+'../personal-a.html'),('encoded_parent',prefix+'%2e%2e/personal-a.html'),
            ('backslash',prefix+'..\\personal-a.html'),('encoded_separator',prefix+'%2fpersonal-a.html'),
            ('wrong_job','/files/'+('A'*32)+'/personal-a.html')):
            with self.subTest(case=label):self.expect(label,path,404)

    def test_report_response_contains_no_session_credentials_and_blocks_connections(self):
        code,headers,raw=self.request(self.path,auth=False,headers={'Cookie':self.cookie})
        self.assertEqual(code,200)
        self.assertEqual(raw,self.document)
        self.assertFalse(self.server.token.encode('ascii') in raw)
        self.assertNotIn('Set-Cookie',headers)
        self.assertIn("connect-src 'none'",headers['Content-Security-Policy'])
        self.assertEqual(headers['Referrer-Policy'],'no-referrer')
        self.observed.append({'case':'offline_response','status':code,'exact_document':raw==self.document,
            'credential_absent':self.server.token.encode('ascii') not in raw,'connect_none':"connect-src 'none'" in headers['Content-Security-Policy']})

if __name__=='__main__': unittest.main()
