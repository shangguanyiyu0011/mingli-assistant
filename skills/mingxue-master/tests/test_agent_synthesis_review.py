"""Independent incremental review of real Agent synthesis and final report gates."""
import copy
from contextlib import contextmanager
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import uuid

HERE=Path(__file__).resolve().parents[1]
SKILL=Path(os.environ.get('MINGXUE_TEST_SKILL_ROOT') or (HERE/'package/mingxue-master' if (HERE/'package/mingxue-master').is_dir() else HERE))
sys.path.insert(0,str(SKILL/'scripts'))
import agent_report
from agent_updates import update_job
import intake_flow
from pair_analysis import compare_people
import personal_report
import report_synthesis as synthesis
import workflow
from test_personal_report_security import inline_image

EVIDENCE=Path(os.environ['MINGXUE_SYNTHESIS_REVIEW_DIR']) if os.environ.get('MINGXUE_SYNTHESIS_REVIEW_DIR') else None
ATTACK='</ScRiPt><img src=x onerror=alert(1)><script>alert(2)</script>&\u2028\u2029'
POINTERS={'numerology':'/life_path/reduction','sukuyo':'/birth_mansion','bazi':'/pillars'}
# A source checkout can exercise its bound real ALL25 evidence without an old
# external v6 path. Portable packages legitimately omit the research directory.
_LOCAL_ALL25_JOB=HERE/'research/comprehensive-demo/jobs/a4e40c9e285a44fb1e340ab6a10dba35'
_LOCAL_ALL25_SUMMARIES=HERE/'research/rewrite/bound'
ALL25_JOB=Path(os.environ['MINGXUE_ALL25_REVIEW_JOB']) if os.environ.get('MINGXUE_ALL25_REVIEW_JOB') else (
    _LOCAL_ALL25_JOB if _LOCAL_ALL25_JOB.is_dir() and all((_LOCAL_ALL25_SUMMARIES/('synthesis-'+s+'.json')).is_file() for s in ('a','b','pair')) else None)


def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str).encode('utf-8')).hexdigest()
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');return Path(path)
def evidence(name,value):
    if EVIDENCE:write(EVIDENCE/name,value)


def request(systems=None,mode='pair'):
    people=[{'person':{'name':'综合审查甲','notes':'合成测试的甲履历'},'birth':{'date':'1990-05-02','time':None,'calendar':'solar','timezone':'Asia/Shanghai'},'location':{}},
            {'person':{'name':'综合审查乙','notes':'合成测试的乙履历'},'birth':{'date':'1992-06-13','time':None,'calendar':'solar','timezone':'Asia/Shanghai'},'location':{}}]
    return {'mode':mode,'people':people if mode=='pair' else people[:1],
        'preferences':{'systems':systems or ['numerology','sukuyo'],'topic':'事业','question':'如何据实际资料讨论工作安排？',
            # Short native fixtures target context/owner/XSS boundaries. The
            # dedicated reader tests retain the detailed prose requirements.
            'relationship':'同事' if mode=='pair' else '个人研习','answers':{'关注':'实际经验与资料限制'},'depth':'brief',
            'virtual_draws':False,'prepare_engines':False}}


def fill_readings(job,suffix=''):
    state=agent_report.describe(job)
    for person in state['people']:
        report=load(person['report_json']);readings={}
        for panel in report['panels']:
            if panel['state'] not in ('ready','partial'):continue
            pointer=POINTERS.get(panel['system'])
            if pointer is None:raise AssertionError('This small fixture unexpectedly calculated '+panel['system'])
            readings[panel['system']]={'text':person['name']+'：本次仅按实际'+panel['system']+'结构讨论提纲，现实工作需核对经验与意愿。'+suffix,
                'result_sha256':panel['result_sha256'],'question_hash':report['question_hash'],
                'basis':[{'kind':'calculation','pointer':pointer,'label':'本次真实结构'}]}
        workflow.run_project(Path(person['workspace']),patch={'readings':readings})
    return agent_report.describe(job)


def comparison(records,relationship='同事'):
    value=compare_people(records[0]['packed'],records[1]['packed'],relationship)
    value['reading_context']={r['role'].upper():r['report']['question_hash'] for r in records}
    return value


def ref(person,system,pointer=None):
    return {'person':person,'system':system,'pointer':pointer or POINTERS[system],'label':'当前本人实际结果'}


def summary(records,scope,comp=None):
    context=synthesis.synthesis_context(records,scope,comparison=comp)
    required=context['required_systems'] if scope!='pair' else [c for c in context['coverage'] if c['calculated']]
    assert required,'Small fixture must have an actual calculation'
    # Every theme is a genuine cross-method reading. A pair theme carries both
    # owners locally, including the supported one-common-method compatibility case.
    details=[]
    for item in required:
        payload=next(r['payloads'][item['system']] for r in records if r['role'].upper()==item['person'])
        if item['system']=='numerology':detail='生命路径数为'+str(payload['life_path']['reduction']['number'])
        elif item['system']=='sukuyo':detail='本命宿为'+payload['birth_mansion']['label']
        else:detail='四柱为'+'、'.join(v for v in payload['pillars'].values() if v)
        details.append(item['person']+'的'+detail+'。')
    linked=('生日归约关注长期的选择，宿曜关注本命与当天的对应。两者放在一起，可以先说自己想尝试什么，再问今天愿意投入多少。'
            if any(x['system']=='sukuyo' for x in required) else '生日归约可用来思考自己的选择与愿望，先听清各自的需要，再决定怎样参与。')
    themes=[{'title':'把变化的愿望与当下的节奏一起照顾',
        'text':''.join(details)+linked+'彼此都可以表达自己的需要，不由符号替对方作决定。',
        'basis':[ref(item['person'],item['system']) for item in required]}]
    value={'context_sha256':context['context_sha256'],'summary':'把自己的探索意愿与每天能承担的分量一起照顾；彼此说清需要，再由真实相处决定下一步。',
        'themes':themes,'agreements':[],'differences':[],
        'actions':[{'title':'核对现实条件','text':'分别核实经验、意愿和工作条件，再讨论具体安排。','basis':copy.deepcopy(themes[0]['basis'])}],
        'limitations':['方法共享出生资料，引用关系不构成独立验证；传统符号不保证现实结果。']}
    if scope=='pair':
        methods={item['system'] for item in required}
        if len(methods)>=2:
            a=next(item for item in required if item['person']=='A')
            b=next(item for item in required if item['person']=='B' and item['system']!=a['system'])
            bases=[ref('A',a['system']),ref('B',b['system'])]
            value['agreements']=[{'title':'愿望和当下都值得被听见','text':'生日归约与宿表分别提供选择和节奏的联想；双方都可以说出愿望，也照顾今天能承担的分量。','basis':bases}]
            value['differences']=[{'title':'符号空间不同','text':'整数归约与宿表位置按各自规则并列，不能相加为合作评分。','basis':copy.deepcopy(bases)}]
    return value


def files_for(directory,records):
    comp=comparison(records,records[0]['relationship'])
    values={scope:summary(records,scope,comp if scope=='pair' else None) for scope in (['A','B','pair'] if len(records)==2 else ['A'])}
    return {scope:write(directory/(scope+'-synthesis.json'),value) for scope,value in values.items()}


def arguments(files):return {dict(A='synthesis_a_file',B='synthesis_b_file',pair='synthesis_pair_file')[scope]:path for scope,path in files.items()}


class Page(HTMLParser):
    def __init__(self):super().__init__();self.scripts=[];self.active=None;self.controls=[];self.resources=[];self.injected=[];self.images=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='script':self.active={'attrs':attrs,'text':''}
        if tag in ('form','input','select','textarea'):self.controls.append(tag)
        if tag in ('iframe','object','embed') or any(k.startswith('on') for k in attrs):self.injected.append(tag)
        if tag=='img':
            # Real offline illustrations are permitted only as validated inline
            # PNG/JPEG containers; an injected src=x or SVG remains hostile.
            if not inline_image(attrs.get('src')) or attrs.get('srcset'):self.injected.append(tag)
            else:self.images.append(attrs['src'])
        for key,value in attrs.items():
            if key in ('src','href','action','srcset','poster') and value and not value.startswith(('#','data:','blob:')):self.resources.append((tag,key,value))
    def handle_data(self,text):
        if self.active is not None:self.active['text']+=text
    def handle_endtag(self,tag):
        if tag=='script' and self.active is not None:self.scripts.append(self.active);self.active=None
    def data(self):return json.loads(next(x['text'] for x in self.scripts if x['attrs'].get('id')=='report-data'))


class AgentSynthesisIncrementalReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary=None
        if EVIDENCE:
            EVIDENCE.mkdir(parents=True,exist_ok=True);cls.root=EVIDENCE/('run-'+uuid.uuid4().hex[:10]);cls.root.mkdir()
        else:
            cls.temporary=tempfile.TemporaryDirectory(prefix='agent-synthesis-review-');cls.root=Path(cls.temporary.name)
        source=write(cls.root/'request.json',request())
        start=agent_report.run(source,cls.root/'seed')
        cls.job=Path(start['job_dir']);fill_readings(cls.job)
        _,_,cls.records=agent_report.snapshot(cls.job);cls.comp=comparison(cls.records)
        evidence('real-two-method-fixture.json',{'job':str(cls.job),'records':[{'role':r['role'],'name':r['packed']['person']['name'],
            'birth':r['packed']['birth'],'methods':[{k:p[k] for k in ('system','state','reading_status','result_sha256')} for p in r['report']['panels']]} for r in cls.records]})

    @classmethod
    def tearDownClass(cls):
        if cls.temporary:cls.temporary.cleanup()

    @contextmanager
    def clone(self):
        directory=self.root/('case-'+uuid.uuid4().hex[:10]);directory.mkdir()
        job=directory/self.job.name;shutil.copytree(self.job,job)
        yield directory,job

    def test_01_all25_and_auto_plan_preserve_real_inputs_and_no_draw_authorization(self):
        value=request('all');plan=intake_flow.plan_request(value)
        from fortune import registry
        ids={x['id'] for x in registry()}
        self.assertEqual(len(ids),25)
        for item in plan['people']:
            flow=item['workflow_input'];self.assertEqual(set(flow['systems']),ids)
            self.assertIsNone(flow['birth']['time'])
            for method in ('tarot','lenormand','geomancy'):self.assertIn(method,flow['deferred'])
            self.assertEqual(flow['questionnaire']['_relationship_context'],'同事')
        auto=intake_flow.plan_request(request('auto'))
        self.assertEqual(auto['people'][0]['workflow_input']['systems'],['bazi','numerology','sukuyo'])
        value=request();value['preferences']['answers']['_relationship_context']='冒填'
        with self.assertRaises(ValueError):intake_flow.normalize_request(value)
        evidence('all25-plan-observed.json',{'methods':sorted(ids),'plans':[{k:p['workflow_input'][k] for k in ('systems','birth','deferred')} for p in plan['people']],
            'auto_systems':auto['people'][0]['workflow_input']['systems']})

    def test_02_required_scope_gates_and_missing_files_create_no_outputs(self):
        with self.clone() as (directory,job):
            first=agent_report.finalize(job,directory/'final')
            self.assertEqual(first['status'],'needs_synthesis');self.assertEqual(first['files'],[])
            self.assertEqual({x['scope'] for x in first['pending']},{'A','B','pair'})
            self.assertFalse((job/'deliveries').exists());self.assertFalse((directory/'final').exists())
            _,_,records=agent_report.snapshot(job);files=files_for(directory,records)
            second=agent_report.finalize(job,directory/'final',synthesis_a_file=files['A'])
            self.assertEqual(second['status'],'needs_synthesis')
            self.assertEqual({x['scope'] for x in second['pending']},{'B','pair'})
            bad={**files,'B':directory/'missing.json'}
            with self.assertRaises((OSError,ValueError)):agent_report.finalize(job,directory/'final',**arguments(bad))
            self.assertFalse((job/'deliveries').exists());self.assertFalse((directory/'final').exists())
            evidence('synthesis-gates-observed.json',{'job':str(job),'first':first['status'],'pending':[x['scope'] for x in first['pending']],
                'partial_files':second['status'],'missing_file_rejected':True,'no_output_created':True})

    def test_03_real_multimethod_homepage_export_preserves_all_method_and_person_bindings(self):
        with self.clone() as (directory,job):
            _,_,records=agent_report.snapshot(job);files=files_for(directory,records)
            result=agent_report.finalize(job,directory/'final',**arguments(files))
            self.assertEqual(result['status'],'exported');self.assertEqual(set(result['synthesis_contexts']),{'A','B','pair'})
            prior={Path(f[k]):sha(f[k]) for f in result['files'] for k in ('path','delivery_path')}
            checked=[]
            for file in result['files']:
                p=Page();p.feed(Path(file['delivery_path']).read_text(encoding='utf-8'));data=p.data()
                self.assertEqual(p.controls,[]);self.assertEqual(p.resources,[]);self.assertEqual(len(p.scripts),3)
                self.assertEqual(data['overview']['status'],'validated')
                # Reader data keeps the real visible methods while omitting
                # machine completion counters and the full comparison payload.
                self.assertNotIn('coverage_counts',data['overview'])
                expected=[(who,system) for who in (('A','B') if file['role']=='pair' else ('A' if file['role']=='personal_a' else 'B',))
                          for system in ('numerology','sukuyo')]
                self.assertCountEqual([(c['person'],c['system']) for c in data['overview']['coverage']],expected)
                if file['role']=='pair':
                    self.assertEqual([o['scope'] for o in data['personal_overviews']],['A','B'])
                    self.assertEqual([p['person_index'] for p in data['panels']],[0,0,1,1])
                    self.assertIsNone(data['comparison'])
                checked.append({'role':file['role'],'path':file['delivery_path'],'scope':data['overview']['scope'],
                    'coverage':data['overview']['coverage'],'overview_context':data['overview']['context_sha256']})
            again=agent_report.finalize(job,directory/'final',**arguments(files))
            self.assertEqual(again['status'],'exported');self.assertTrue(all(sha(p)==v for p,v in prior.items()))
            evidence('real-synthesis-export-observed.json',{'job':str(job),'files':checked,'original_exports_unchanged':True})

    def test_04_legacy_one_canonical_method_and_new_mode_mutual_exclusion(self):
        with self.clone() as (directory,job):
            update_job(job,{'preferences':{'systems':['numerology']}})
            status=agent_report.describe(job);self.assertFalse(status['synthesis_required'])
            legacy={'comparison_sha256':status['pair_comparison_sha256'],'text':'保留双方已知数值，不换算评分。',
                'basis':[ref('A','numerology')]}
            legacy_file=write(directory/'legacy.json',legacy)
            old=agent_report.finalize(job,pair_reading_file=legacy_file);self.assertEqual(old['status'],'exported')
            _,_,records=agent_report.snapshot(job);files=files_for(directory,records)
            with self.assertRaises(ValueError):agent_report.finalize(job,pair_reading_file=legacy_file,synthesis_a_file=files['A'])
            pending=agent_report.finalize(job,synthesis_a_file=files['A']);self.assertEqual(pending['status'],'needs_synthesis')
            modern=agent_report.finalize(job,**arguments(files));self.assertEqual(modern['status'],'exported')
        source=write(self.root/('single-'+uuid.uuid4().hex+'.json'),request(['numerology'],'single'))
        result=agent_report.run(source,self.root/'single-jobs');fill_readings(Path(result['job_dir']))
        single=agent_report.finalize(result['job_dir']);self.assertEqual(single['status'],'exported')
        with self.assertRaises(ValueError):agent_report.finalize(result['job_dir'],synthesis_b_file=self.root/'no-B.json')

    def test_05_scope_hash_separates_even_identical_people(self):
        records=[copy.deepcopy(self.records[0]),copy.deepcopy(self.records[0])];records[1]['role']='b'
        a=synthesis.synthesis_context(records,'A');b=synthesis.synthesis_context(records,'B')
        self.assertNotEqual(a['context_sha256'],b['context_sha256'])
        with self.assertRaises(ValueError):synthesis.validate_synthesis(summary(records,'A'),records,'B')

    def test_06_narrative_basis_must_cover_every_ready_or_partial_method(self):
        bad=summary(self.records,'A')
        for field in ('themes','actions'):
            for item in bad[field]:item['basis']=[b for b in item['basis'] if b['system']!='sukuyo']
        with self.assertRaises(ValueError):synthesis.validate_synthesis(bad,self.records,'A')
        context=synthesis.synthesis_context(self.records,'A')
        for field in ('coverage','highlights'):
            forged=copy.deepcopy(bad);forged[field]=context[field]
            with self.assertRaises(ValueError):synthesis.validate_synthesis(forged,self.records,'A')
        records=copy.deepcopy(self.records);records[0]['report']['panels'][1]['state']='partial'
        bad['context_sha256']=synthesis.synthesis_context(records,'A')['context_sha256']
        with self.assertRaises(ValueError):synthesis.validate_synthesis(bad,records,'A')
        for pointers in ({'numerology':'/system','sukuyo':'/system'},
                         {'numerology':'/convention','sukuyo':'/rules'}):
            named_only=summary(self.records,'A')
            for field in ('themes','actions'):
                for item in named_only[field]:
                    for basis in item['basis']:basis['pointer']=pointers[basis['system']]
            with self.subTest(pointers=pointers),self.assertRaises(ValueError):
                synthesis.validate_synthesis(named_only,self.records,'A')

    def test_07_pair_claims_require_local_A_B_and_two_distinct_canonical_methods(self):
        base=summary(self.records,'pair',self.comp)
        for refs in ([ref('A','numerology'),ref('B','numerology')],
                     [ref('A','numerology'),ref('A','sukuyo')],
                     [ref('A','numerology'),ref('A','numerology')]):
            value=copy.deepcopy(base);value['agreements'][0]['basis']=refs
            with self.subTest(refs=refs),self.assertRaises(ValueError):synthesis.validate_synthesis(value,self.records,'pair',comparison=self.comp)
        value=copy.deepcopy(base);value['agreements'][0]['basis'][0]['system']='数秘'
        with self.assertRaises(ValueError):synthesis.validate_synthesis(value,self.records,'pair',comparison=self.comp)
        value=copy.deepcopy(base)
        value['agreements'][0]['basis']=[ref('A','numerology','/convention'),ref('B','sukuyo','/rules')]
        with self.assertRaises(ValueError):synthesis.validate_synthesis(value,self.records,'pair',comparison=self.comp)

    def test_08_deferred_methods_null_fields_and_invalid_pointers_cannot_supply_proof(self):
        with self.clone() as (directory,job):
            update_job(job,{'preferences':{'systems':['numerology','sukuyo','astrology']}})
            _,_,records=agent_report.snapshot(job)
            value=summary(records,'A')
            value['themes'].append({'title':'不能假造星盘','text':'此方法还缺时辰和地点。','basis':[ref('A','astrology','/system')]})
            with self.assertRaises(ValueError):synthesis.validate_synthesis(value,records,'A')
        for pointer in ('/name_expression','/missing','/life_path/reduction/trace/-1','/life_path/reduction/trace/01','/bad~2escape'):
            value=summary(self.records,'A');value['actions'][0]['basis'][0]['pointer']=pointer
            with self.subTest(pointer=pointer),self.assertRaises(ValueError):synthesis.validate_synthesis(value,self.records,'A')

    def test_09_coverage_and_highlights_are_actual_and_inputs_are_not_mutated(self):
        before=digest([self.records,self.comp]);value=summary(self.records,'pair',self.comp);original=digest(value)
        output=synthesis.validate_synthesis(value,self.records,'pair',comparison=self.comp)
        self.assertEqual(digest([self.records,self.comp]),before);self.assertEqual(digest(value),original)
        for h in output['highlights']:
            if h['system']=='numerology':
                record=next(r for r in self.records if r['role'].upper()==h['person'])
                self.assertEqual(h['value'],record['payloads']['numerology']['life_path']['reduction']['number'])
        for field,item in (('coverage',[{'person':'A','system':'astrology','state':'ready'}]),('highlights',[{'value':99}])):
            forged=summary(self.records,'A');forged[field]=item
            with self.assertRaises(ValueError):synthesis.validate_synthesis(forged,self.records,'A')

    def test_10_any_fact_applied_reading_or_result_change_invalidates_context(self):
        old=summary(self.records,'A');baseline=old['context_sha256']
        def identity(records):records[0]['packed']['person']['notes']='更正履历';records[0]['report']['person']['notes']='更正履历'
        def birth(records):records[0]['packed']['birth']['date']='1991-05-02';records[0]['report']['birth_input']['date']='1991-05-02'
        def location(records):records[0]['report']['location_input']={'latitude':31.23,'longitude':121.47}
        def relationship(records):records[0]['relationship']='朋友'
        def question(records):
            records[0]['report']['question_hash']='f'*64
            for p in records[0]['report']['panels']:p['traditional_interpretation']['question_hash']='f'*64
        def reading(records):records[0]['report']['panels'][0]['traditional_interpretation']['text']+='修订解读'
        def basis(records):records[0]['report']['panels'][0]['traditional_interpretation']['basis'][0]['label']='修订实际依据'
        def result(records):records[0]['payloads']['numerology']['life_path']['reduction']['number']=9
        for change in (identity,birth,location,relationship,question,reading,basis,result):
            records=copy.deepcopy(self.records);change(records)
            with self.subTest(change=change.__name__):
                self.assertNotEqual(synthesis.synthesis_context(records,'A')['context_sha256'],baseline)
                with self.assertRaises(ValueError):synthesis.validate_synthesis(old,records,'A')
        records=copy.deepcopy(self.records);records[1]['report']['panels'][0]['traditional_interpretation']['text']+='只改B'
        self.assertEqual(synthesis.synthesis_context(records,'A')['context_sha256'],baseline)

    def test_11_native_relationship_change_stales_personal_and_pair_summary(self):
        with self.clone() as (directory,job):
            _,_,records=agent_report.snapshot(job);files=files_for(directory,records)
            old_question=[r['report']['question_hash'] for r in records]
            self.assertTrue(update_job(job,{'preferences':{'relationship':'朋友'}})['request_committed'])
            state=agent_report.describe(job);self.assertTrue(all(p['needs_readings'] for p in state['people']))
            self.assertNotEqual(old_question,[load(p['report_json'])['question_hash'] for p in state['people']])
            fill_readings(job)
            with self.assertRaises(ValueError):agent_report.finalize(job,**arguments(files))
            self.assertFalse((job/'deliveries').exists())
            evidence('synthesis-relationship-update-observed.json',{'job':str(job),'old_personal_readings_stale':True,'old_summaries_rejected':True,'no_final_output':True})

    def test_12_revision_and_workspace_only_changes_do_not_invalidate_summary(self):
        with self.clone() as (directory,job):
            _,_,before=agent_report.snapshot(job);old=summary(before,'A');original=before[0]['report']['revision']
            readings={p['system']:p['traditional_interpretation'] for p in before[0]['report']['panels']}
            workflow.run_project(job/'project-a',patch={'readings':readings})
            _,_,after=agent_report.snapshot(job)
            self.assertNotEqual(original,after[0]['report']['revision'])
            self.assertEqual(synthesis.synthesis_context(after,'A')['context_sha256'],old['context_sha256'])
            self.assertEqual(synthesis.validate_synthesis(old,after,'A')['status'],'validated')

    def test_13_finalization_uses_one_consistent_snapshot_during_real_update(self):
        with self.clone() as (directory,job):
            _,_,records=agent_report.snapshot(job);files=files_for(directory,records);initial=[r['report']['revision'] for r in records]
            original_validate=synthesis.validate_synthesis;called=False
            def validate(value,actual,scope,**kwargs):
                nonlocal called
                if not called:
                    called=True;update_job(job,{'preferences':{'question':'验证中途到来的新问题'}})
                return original_validate(value,actual,scope,**kwargs)
            with mock.patch.object(synthesis,'validate_synthesis',side_effect=validate),mock.patch.object(agent_report,'snapshot',wraps=agent_report.snapshot) as snapshots:
                result=agent_report.finalize(job,**arguments(files))
            self.assertEqual(snapshots.call_count,1);self.assertTrue(called);self.assertEqual(result['status'],'exported')
            self.assertEqual([result['revisions'][r] for r in ('a','b')],initial)
            pair=Page();pair.feed(Path(result['files'][2]['path']).read_text(encoding='utf-8'))
            self.assertEqual(pair.data()['overview']['context_sha256'],load(files['pair'])['context_sha256'])
            self.assertTrue(all(p['needs_readings'] for p in agent_report.describe(job)['people']))
            evidence('synthesis-snapshot-interleave-observed.json',{'job':str(job),'snapshots':snapshots.call_count,
                'exported_revisions':result['revisions'],'export_remained_same_snapshot':True,'new_question_requires_new_readings':True})

    @unittest.skipUnless(shutil.which('node'),'Actual renderer execution requires Node.js')
    def test_14_hostile_overview_executes_offline_without_injection_or_forms(self):
        value=summary(self.records,'pair',self.comp);value['summary']=ATTACK;value['limitations']=[ATTACK]
        for field in ('themes','agreements','differences','actions'):
            for item in value[field]:
                item['title']=ATTACK;item['text']=ATTACK
                for basis in item['basis']:basis['label']=ATTACK
        overview=synthesis.validate_synthesis(value,self.records,'pair',comparison=self.comp)
        raw=personal_report.pair_html(self.records[0]['report'],self.records[0]['payloads'],self.records[1]['report'],self.records[1]['payloads'],self.comp,
            '同事',overview=overview)
        p=Page();p.feed(raw);self.assertEqual(len(p.scripts),3);self.assertEqual(p.controls+p.resources+p.injected,[])
        runner=r"""const vm=require('node:vm'),fs=require('node:fs');let q=JSON.parse(fs.readFileSync(0,'utf8')),requests=0;const nodes=new Map();function node(id){const n={id,textContent:'',_html:'',addEventListener(){},querySelectorAll(){return []},click(){}};Object.defineProperty(n,'innerHTML',{get(){return this._html},set(v){this._html=v;for(const m of v.matchAll(/\bid="([^"]+)"/g))if(!nodes.has(m[1]))nodes.set(m[1],node(m[1]));}});return n;}nodes.set('report-app',node('report-app'));nodes.set('report-data',{textContent:q.data});let doc={getElementById:id=>nodes.get(id)||null,createElement:()=>node('new')};const deny=()=>{requests++;throw Error('unexpected network')};let c={window:{addEventListener(){},print(){}},document:doc,fetch:deny,XMLHttpRequest:deny,WebSocket:deny,navigator:{sendBeacon:deny},URL:{createObjectURL:()=> 'blob:local-review',revokeObjectURL(){}},Blob:globalThis.Blob,setTimeout(){}};vm.createContext(c);for(const s of q.scripts)vm.runInContext(s,c,{timeout:2000});process.stdout.write(JSON.stringify({requests,html:[...nodes.values()].map(n=>n._html||'').join('\n')}));"""
        run=subprocess.run([shutil.which('node'),'-e',runner],input=json.dumps({'data':p.scripts[0]['text'],'scripts':[s['text'] for s in p.scripts[1:]]},ensure_ascii=False),
            text=True,encoding='utf-8',capture_output=True,timeout=15)
        self.assertEqual(run.returncode,0,run.stderr);output=json.loads(run.stdout)
        rendered=Page();rendered.feed(output['html']);self.assertEqual(output['requests'],0)
        self.assertEqual(rendered.controls+rendered.resources+rendered.injected,[])
        self.assertTrue(rendered.images,'The packaged hero must still render during the hostile-text check')
        self.assertIn(p.data()['art']['hero']['src'],rendered.images)
        hostile=Page();hostile.feed(ATTACK);self.assertTrue(hostile.injected,'The parser must detect an unescaped hostile image')
        self.assertIn('&lt;',output['html'])
        if EVIDENCE:(EVIDENCE/'hostile-synthesis-report.html').write_text(raw,encoding='utf-8')
        evidence('synthesis-xss-observed.json',{'scripts':3,'requests':output['requests'],'forms':rendered.controls,'injected_tags':rendered.injected,'external_resources':rendered.resources})

    @unittest.skipUnless(ALL25_JOB,'Portable package has no independently prepared real ALL25 research sample')
    def test_15_existing_real_all25_sample_has_truthful_coverage_and_narrative_use(self):
        job=ALL25_JOB;_,native,records=agent_report.snapshot(job)
        folder=_LOCAL_ALL25_SUMMARIES if job==_LOCAL_ALL25_JOB else job.parent.parent
        comp=comparison(records,native['preferences']['relationship']);checked={};basis_table=[]
        for record in records:
            scope=record['role'].upper();context=synthesis.synthesis_context(records,scope)
            self.assertEqual(context['coverage_counts']['selected'],25)
            self.assertEqual(context['coverage_counts']['calculated'],19)
            self.assertEqual(context['coverage_counts']['calculated'],sum(c['calculated'] for c in context['coverage']))
            self.assertTrue(all(c['kind'] not in ('reference','observation','needs_input','unavailable') for c in context['coverage'] if c['calculated']))
            self.assertTrue(all(c['reading_status']=='applied' for c in context['coverage'] if c['calculated']))
        for scope in ('A','B','pair'):
            filename=Path(os.environ.get('MINGXUE_ALL25_SYNTHESIS_'+scope.upper(),str(folder/('synthesis-'+scope.lower()+'.json'))))
            value=load(filename)
            checked[scope]=synthesis.validate_synthesis(value,records,scope,comparison=comp if scope=='pair' else None)
            for field in ('themes','agreements','differences','actions'):
                for item in value[field]:
                    refs=[]
                    for basis in item['basis']:
                        payload=next(r['payloads'][basis['system']] for r in records if r['role'].upper()==basis['person'])
                        actual=payload
                        for key in basis['pointer'].split('/')[1:]:
                            key=key.replace('~1','/').replace('~0','~')
                            actual=actual[int(key)] if isinstance(actual,list) else actual[key]
                        self.assertIsNotNone(actual)
                        refs.append({**basis,'actual_value':actual})
                    basis_table.append({'scope':scope,'section':field,'title':item['title'],'text':item['text'],'basis':refs})
        if EVIDENCE:
            a,b=copy.deepcopy(records[0]['report']),copy.deepcopy(records[1]['report'])
            a['delivery_stage']=b['delivery_stage']='interpreted'
            documents={'personal-a':personal_report.personal_html(a,records[0]['payloads'],overview=checked['A']),
                'personal-b':personal_report.personal_html(b,records[1]['payloads'],overview=checked['B']),
                'pair':personal_report.pair_html(a,records[0]['payloads'],b,records[1]['payloads'],comp,native['preferences']['relationship'],
                    overview=checked['pair'],personal_overviews=[checked['A'],checked['B']])}
            paths={}
            for key,html in documents.items():
                parser=Page();parser.feed(html);self.assertEqual(parser.controls+parser.resources+parser.injected,[])
                path=EVIDENCE/('actual-all25-'+key+'-reviewed.html');path.write_text(html,encoding='utf-8');paths[key]=str(path)
            evidence('real-all25-basis-table.json',basis_table)
            evidence('real-all25-context-observed.json',{'job':str(job),'people':[synthesis.synthesis_context(records,r['role'].upper()) for r in records],
                'validated_contexts':{scope:value['context_sha256'] for scope,value in checked.items()},'reviewed_html':paths,
                'claim_items_with_resolved_actual_basis':len(basis_table)})


if __name__=='__main__':unittest.main()
