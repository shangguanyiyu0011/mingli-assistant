"""Independent Agent calculation/interpretation/export boundary checks."""
import copy
from contextlib import contextmanager
import hashlib
from html.parser import HTMLParser
import http.client
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import unittest
from unittest import mock
import uuid

HERE=Path(__file__).resolve().parents[1]
SKILL=Path(os.environ.get('MINGXUE_TEST_SKILL_ROOT') or (HERE/'package/mingxue-master' if (HERE/'package/mingxue-master').is_dir() else HERE))
sys.path.insert(0,str(SKILL/'scripts'))
import agent_report
import workflow
from test_personal_report_security import Document

EVIDENCE=Path(os.environ['MINGXUE_AGENT_REVIEW_EVIDENCE_DIR']) if os.environ.get('MINGXUE_AGENT_REVIEW_EVIDENCE_DIR') else None
if EVIDENCE:EVIDENCE.mkdir(parents=True,exist_ok=True)
ATTACK='</ScRiPt><img src=x onerror=alert(1)>&'


def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    return Path(path)


def request():
    return {'mode':'pair','people':[
        {'person':{'name':'甲-Agent审查','notes':'甲的独立履历'},
         'birth':{'date':'1990-05-02','time':None,'calendar':'solar','timezone':'Asia/Shanghai'},'location':{}},
        {'person':{'name':'乙-Agent审查','notes':'乙的独立履历'},
         'birth':{'date':'1992-06-13','time':None,'calendar':'solar','timezone':'Asia/Shanghai'},'location':{}}],
        # These intentionally short readings exercise binding and export safety;
        # detailed reader prose is covered by the dedicated editorial gate tests.
        'preferences':{'systems':['numerology'],'topic':'事业','question':'如何讨论合作方式？','depth':'brief',
            'relationship':'同事','answers':{'关注':'职责分工'},'prepare_engines':False,'virtual_draws':False}}


@contextmanager
def fixture():
    if EVIDENCE:
        root=EVIDENCE/('agent-fixture-'+uuid.uuid4().hex[:12]);root.mkdir();yield root
    else:
        with tempfile.TemporaryDirectory(prefix='agent-review-') as value:yield Path(value)


def run_job(directory,source=None):
    path=write(directory/'request.json',source or request())
    result=agent_report.run(path,directory/'jobs')
    return Path(result['job_dir']),result


def apply_readings(job,*,text='按本人已算生日结构讨论职责，不推断结果。'):
    status=agent_report.describe(job)
    for person in status['people']:
        report=load(person['report_json'])
        panel=report['panels'][0]
        reading={'text':person['name']+'：'+text,'result_sha256':panel['result_sha256'],
                 'question_hash':report['question_hash'],
                 'basis':[{'kind':'calculation','pointer':'/life_path/reduction','label':'本人的实际归约过程'}]}
        workflow.run_project(Path(person['workspace']),patch={'readings':{'numerology':reading}})
    return agent_report.describe(job)


def make_pair_reading(job,path,text='本次双方的数值并列阅读，不作关系评分。'):
    status=agent_report.describe(job)
    reading=copy.deepcopy(status['pair_reading_schema'])
    reading['text']=text
    reading['basis']=[{'person':who,'system':'numerology','pointer':'/life_path/reduction',
                       'label':'本人的实际生日归约'} for who in ('A','B')]
    write(path,reading)
    return path,status


class Controls(HTMLParser):
    def __init__(self):super().__init__();self.controls=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('form','input','select','textarea'):self.controls.append(tag)


class SessionMeta(HTMLParser):
    def __init__(self):super().__init__();self.token=None
    def handle_starttag(self,tag,attrs):
        props=dict(attrs)
        if tag=='meta' and props.get('name')=='workbench-token':self.token=props.get('content')


@contextmanager
def once_process(directory,timeout=20):
    ready=directory/'ready.json'
    command=[sys.executable,'-X','utf8','-B',str(SKILL/'scripts/workbench.py'),'--agent','--port','0',
        '--data-dir',str(directory/'collection'),'--ready-file',str(ready),'--timeout',str(timeout)]
    process=subprocess.Popen(command,cwd=directory,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
    try:
        deadline=time.monotonic()+10
        information=None
        while time.monotonic()<deadline:
            if ready.exists():
                try:information=load(ready);break
                except json.JSONDecodeError:pass
            if process.poll() is not None:break
            time.sleep(0.02)
        if information is None:raise RuntimeError('Reviewer-owned collector did not become ready')
        yield process,information
    finally:
        if process.poll() is None:process.kill()
        process.communicate(timeout=5)


def local_http(ready,path,*,token=None,value=None,headers=None):
    from urllib.parse import urlsplit
    parsed=urlsplit(ready['url']);chosen={'Host':parsed.netloc}
    if token:chosen['Authorization']='Bearer '+token
    raw=None
    if value is not None:raw=json.dumps(value,ensure_ascii=False).encode('utf-8');chosen['Content-Type']='application/json'
    chosen.update(headers or {})
    connection=http.client.HTTPConnection('127.0.0.1',parsed.port,timeout=10)
    try:
        connection.request('POST' if value is not None else 'GET',path,body=raw,headers=chosen)
        response=connection.getresponse();return response.status,dict(response.getheaders()),response.read()
    finally:connection.close()


class AgentReportReviewTests(unittest.TestCase):
    def test_real_agent_requires_readings_then_exports_immutable_offline_reports(self):
        with fixture() as directory:
            job,start=run_job(directory)
            self.assertEqual(start['status'],'needs_interpretation')
            self.assertEqual(start['calculation_status'],'ready')
            self.assertTrue(all(len(p['needs_readings'])==1 for p in start['people']))
            blocked=agent_report.finalize(job,directory/'final')
            self.assertEqual(blocked['status'],'needs_interpretation');self.assertEqual(blocked['files'],[])
            ready=apply_readings(job,text='真实解读文本 '+ATTACK)
            self.assertTrue(all(not p['needs_readings'] for p in ready['people']))
            pair_pending=agent_report.finalize(job,directory/'final')
            self.assertEqual(pair_pending['status'],'needs_pair_interpretation')
            pair_file,_=make_pair_reading(job,directory/'pair-reading.json',text='真实双人解读 '+ATTACK)
            first=agent_report.finalize(job,directory/'final',pair_reading_file=pair_file)
            self.assertEqual(first['status'],'exported');self.assertEqual(first['stage'],'interpreted')
            self.assertEqual(len(first['files']),3)
            prior={Path(f[key]):sha(f[key]) for f in first['files'] for key in ('path','delivery_path')}
            for file in first['files']:
                path=Path(file['path']);parsed=Document();parsed.feed(path.read_text(encoding='utf-8'));data=parsed.data()
                controls=Controls();controls.feed(path.read_text(encoding='utf-8'))
                self.assertEqual(controls.controls,[])
                self.assertEqual(parsed.resources,[]);self.assertEqual(parsed.dangerous,[])
                self.assertEqual(len(parsed.scripts),3)
                self.assertEqual(data['meta']['delivery_stage'],'interpreted')
                self.assertTrue(all(p['interpretation'] is not None for p in data['panels']))
                self.assertTrue(all(p['birth']['time'] is None for p in data['people']))
                if file['role']=='pair':
                    self.assertEqual([p['person_index'] for p in data['panels']],[0,1])
                    self.assertEqual([p['raw']['birth_date'] for p in data['panels']],['1990-05-02','1992-06-13'])
                    self.assertEqual(data['comparison']['interpretation']['text'],'真实双人解读 '+ATTACK)
            second=agent_report.finalize(job,directory/'final',pair_reading_file=pair_file)
            self.assertEqual(second['status'],'exported')
            self.assertTrue(all(sha(path)==digest for path,digest in prior.items()))
            self.assertTrue({f['delivery_path'] for f in first['files']}.isdisjoint(f['delivery_path'] for f in second['files']))
            if EVIDENCE:write(EVIDENCE/'agent-valid-journey.json',{'job':str(job),'start_status':start['status'],
                'blocked_status':blocked['status'],'pair_pending':pair_pending['status'],'first':first,'second':second,
                'original_files_unchanged':all(sha(path)==digest for path,digest in prior.items())})

    def test_old_pair_reading_is_rejected_after_person_or_birth_change(self):
        for label,patch in (('person',{'person':{'name':'丙-Agent审查','notes':'换人后履历'}}),
                            ('birth',{'birth':{'date':'1991-05-02'},'options':{'numerology':{'date':'1991-05-02'}}})):
            with self.subTest(case=label),fixture() as directory:
                job,_=run_job(directory);apply_readings(job)
                pair_file,before=make_pair_reading(job,directory/'old-pair.json')
                workflow.run_project(Path(before['people'][0]['workspace']),patch=patch)
                try:pending=agent_report.describe(job)
                except ValueError:
                    # Current Agent contract requires native facts to be
                    # replanned through Agent update; rejecting is safe too.
                    with self.assertRaises(ValueError):agent_report.finalize(job,pair_reading_file=pair_file)
                    continue
                self.assertTrue(pending['people'][0]['needs_readings'])
                apply_readings(job)
                with self.assertRaises(ValueError):agent_report.finalize(job,pair_reading_file=pair_file)

    def test_old_pair_reading_is_rejected_after_questionnaire_or_question_change(self):
        with fixture() as directory:
            job,_=run_job(directory);apply_readings(job)
            pair_file,before=make_pair_reading(job,directory/'old-question-pair.json','只讨论原问题的双方文字。')
            before_hash=before['pair_comparison_sha256']
            for person in before['people']:
                workflow.run_project(Path(person['workspace']),patch={'topic':'亲密关系','question':'新的关系沟通问题',
                    'questionnaire':{'关注':'新的问答条件'}})
            try:updated=apply_readings(job)
            except ValueError as exc:
                with self.assertRaises(ValueError):agent_report.finalize(job,pair_reading_file=pair_file)
                if EVIDENCE:write(EVIDENCE/'pair-question-context-observed.json',{'job':str(job),'safe_rejection':str(exc),
                    'finalize_rejected':True,'reason':'Direct workflow fact/context changes must first pass native Agent replanning.'})
                return
            error=None;exported=None
            try:exported=agent_report.finalize(job,pair_reading_file=pair_file)
            except ValueError as exc:error=str(exc)
            observation={'job':str(job),'pair_hash_before':before_hash,'pair_hash_after':updated['pair_comparison_sha256'],
                'individual_question_hashes_before':[load(p['report_json'])['question_hash'] for p in before['people']],
                'individual_question_hashes_after':[load(p['report_json'])['question_hash'] for p in updated['people']],
                'rejection':error,'export':exported}
            if EVIDENCE:write(EVIDENCE/'pair-question-context-observed.json',observation)
            self.assertIsNotNone(error,'Old pair interpretation was exported for a changed question/context')

    def test_birth_only_update_does_not_keep_prior_birth_result_and_reading(self):
        with fixture() as directory:
            job,_=run_job(directory);before=apply_readings(job)
            person=before['people'][0]
            workflow.run_project(Path(person['workspace']),patch={'birth':{'date':'1991-05-02'}})
            try:current=agent_report.describe(job)
            except ValueError as exc:
                with self.assertRaises(ValueError):agent_report.finalize(job)
                if EVIDENCE:write(EVIDENCE/'birth-only-update-observed.json',{'job':str(job),'safe_rejection':str(exc),
                    'finalize_rejected':True,'reason':'Native birth change needs Agent replanning; mismatched existing component cannot be delivered.'})
                return
            report=load(current['people'][0]['report_json'])
            _,_,records=agent_report.snapshot(job)
            original=records[0]['payloads']['numerology']
            observation={'job':str(job),'declared_birth':report['birth_input']['date'],
                'result_birth_date':original['birth_date'],'reading_status':report['panels'][0]['reading_status'],
                'needs_readings':current['people'][0]['needs_readings']}
            if EVIDENCE:write(EVIDENCE/'birth-only-update-observed.json',observation)
            self.assertEqual(original['birth_date'],report['birth_input']['date'],'Report changed the person birthday but retained the old birthday result')
            self.assertTrue(current['people'][0]['needs_readings'])

    def test_invalid_or_protected_output_does_not_overwrite_sources(self):
        with fixture() as directory:
            job,_=run_job(directory);apply_readings(job)
            pair_file,_=make_pair_reading(job,directory/'pair.json')
            inputs={p:sha(p) for p in job.rglob('input.json')}
            for output in (SKILL/'review-agent-never-write',job/'project-a'/'output'):
                with self.subTest(output=str(output)):
                    with self.assertRaises(ValueError):agent_report.finalize(job,output,pair_reading_file=pair_file)
            self.assertTrue(all(sha(p)==value for p,value in inputs.items()))
            self.assertFalse((SKILL/'review-agent-never-write').exists())

    def test_absent_birth_facts_never_create_calculated_job(self):
        with fixture() as directory:
            value=request();value['people'][0]['birth']['date']=''
            result=agent_report.run(write(directory/'missing.json',value),directory/'jobs')
            self.assertIn(result['status'],('needs_input','invalid_input'))
            self.assertEqual(result['files'],[])
            self.assertFalse((directory/'jobs').exists())

    def test_structural_export_is_only_explicit_and_labeled(self):
        with fixture() as directory:
            job,_=run_job(directory)
            result=agent_report.finalize(job,allow_structural_only=True)
            self.assertEqual(result['stage'],'structure_only')
            for file in result['files']:
                parsed=Document();parsed.feed(Path(file['path']).read_text(encoding='utf-8'))
                self.assertEqual(parsed.data()['meta']['delivery_stage'],'structure_only')
                self.assertTrue(all(p['interpretation'] is None for p in parsed.data()['panels']))

    def test_finalize_cannot_check_new_revision_then_export_unread_old_snapshot(self):
        with fixture() as directory:
            value=request();value['mode']='single';value['people']=value['people'][:1]
            job,_=run_job(directory,value)
            original_describe=agent_report.describe
            hook_used=False
            def interleaved(current_job):
                nonlocal hook_used
                hook_used=True
                # Deterministically schedule a real workflow commit between
                # finalize's initial snapshot and its second status snapshot.
                status=original_describe(current_job)
                for person in status['people']:
                    report=load(person['report_json']);panel=report['panels'][0]
                    reading={'text':'并发提交后才新增的真实解读','result_sha256':panel['result_sha256'],
                        'question_hash':report['question_hash'],
                        'basis':[{'kind':'calculation','pointer':'/life_path/reduction','label':'实际归约'}]}
                    workflow.run_project(Path(person['workspace']),patch={'readings':{'numerology':reading}})
                return original_describe(current_job)
            with mock.patch.object(agent_report,'describe',interleaved):result=agent_report.finalize(job)
            rows=[]
            for file in result.get('files',[]):
                parsed=Document();parsed.feed(Path(file['path']).read_text(encoding='utf-8'))
                data=parsed.data();rows.append({'revision':data['meta']['revision'],'stage':data['meta']['delivery_stage'],
                    'readings_present':[p['interpretation'] is not None for p in data['panels']]})
            if EVIDENCE:write(EVIDENCE/'finalize-snapshot-interleave-observed.json',{'job':str(job),'result':result,'exported_rows':rows,
                'second_describe_hook_used':hook_used})
            self.assertTrue(result.get('status')!='exported' or all(all(r['readings_present']) for r in rows),
                'Finalize checked the new ready revision but exported an older unread report as interpreted')


class AgentIntakeIndependentTests(unittest.TestCase):
    def test_real_one_use_cli_collects_only_native_data_then_exits(self):
        with fixture() as directory,once_process(directory) as (process,ready):
            self.assertEqual(ready['network_scope'],'loopback_only')
            self.assertEqual(ready['mode'],'agent')
            code,_,home=local_http(ready,'/intake');self.assertEqual(code,200)
            meta=SessionMeta();meta.feed(home.decode('utf-8'));self.assertTrue(bool(meta.token))
            observed=[]
            for label,path,token,body,headers,expected in (
                ('no_session','/api/submit',None,request(),None,401),
                ('foreign_origin','/api/submit',meta.token,request(),{'Origin':'https://evil.invalid'},403),
                ('foreign_host','/api/submit',meta.token,request(),{'Host':'evil.invalid'},403),
                ('calculate_forbidden','/api/calculate',meta.token,{'system':'numerology','params':{'date':'1990-05-02'}},None,403),
                ('prepare_forbidden','/api/prepare',meta.token,{'system':'astrology'},None,403),
                ('private_request','/collected/request.json',meta.token,None,None,404)):
                status,_,_=local_http(ready,path,token=token,value=body,headers=headers)
                observed.append({'case':label,'status':status,'expected':expected})
                self.assertEqual(status,expected,label)
            source=request();source['preferences']['answers']['独立文字']='出生钟点若写12:00也不能补成时辰'
            code,_,raw=local_http(ready,'/api/submit',token=meta.token,value=source)
            self.assertEqual(code,200)
            public=json.loads(raw);self.assertEqual(public['status'],'submitted');self.assertEqual(public['files'],[])
            self.assertNotIn('request_file',public)
            self.assertNotIn('photo_manifest',public)
            stdout,stderr=process.communicate(timeout=15)
            self.assertEqual(process.returncode,0)
            self.assertFalse(meta.token in stdout or meta.token in stderr or meta.token in raw.decode('utf-8'))
            terminal=json.loads(stdout.strip().splitlines()[-1]);self.assertEqual(terminal['status'],'submitted')
            self.assertIsNone(terminal['photo_manifest'])
            saved=Path(terminal['request_file']);self.assertTrue(saved.is_file())
            stored=load(saved)
            self.assertEqual(load(saved.with_name('original-request.json')),source)
            for original,normalized in zip(source['people'],stored['people']):
                self.assertEqual(normalized['person'],original['person'])
                self.assertEqual(normalized['location'],original['location'])
                for key,value in original['birth'].items():self.assertEqual(normalized['birth'][key],value)
                self.assertIsNone(normalized['birth']['gender'])
            self.assertTrue(all(p['birth']['time'] is None for p in stored['people']))
            metadata=load(saved.with_name('metadata.json'))
            for flag in ('calculated','engines_prepared','drawn'):self.assertFalse(metadata[flag])
            files=sorted(p.name for p in saved.parent.iterdir())
            self.assertEqual(files,['collection-owner.json','metadata.json','original-request.json','plan.json','request.json'])
            # The collection is now reserved before the worker starts. Its
            # private owner marker is allowed, but is not a submitted user fact.
            owner=load(saved.with_name('collection-owner.json'))
            self.assertEqual(set(owner),{'photo_session'})
            self.assertRegex(owner['photo_session'],r'^[a-f0-9]{32}$')
            self.assertEqual(saved.parent.parent,directory/'collection'/'collected')
            self.assertEqual(saved.parent.name,terminal['job_id'])
            self.assertTrue(all(meta.token.encode('ascii') not in p.read_bytes() for p in saved.parent.iterdir()))
            if EVIDENCE:write(EVIDENCE/'agent-once-http-observed.json',{'directory':str(directory),'cli_exit':process.returncode,
                'final_status':terminal['status'],'request_file':str(saved),'original_request_unchanged':load(saved.with_name('original-request.json'))==source,
                'unknown_times_preserved':all(p['birth']['time'] is None for p in stored['people']),
                'saved_files':files,'metadata':metadata,'cases':observed,'session_not_persisted':True})

    def test_real_one_use_timeout_exits_without_a_submission(self):
        with fixture() as directory,once_process(directory,0.3) as (process,ready):
            stdout,_=process.communicate(timeout=8)
            self.assertEqual(process.returncode,3)
            result=json.loads(stdout.strip().splitlines()[-1]);self.assertEqual(result['status'],'timeout')
            self.assertIsNone(result['job_id']);self.assertEqual(result['files'],[])
            self.assertFalse(list((directory/'collection').rglob('request.json')))


    def test_real_one_use_cancel_exits_without_a_submission(self):
        with fixture() as directory,once_process(directory) as (process,ready):
            code,_,home=local_http(ready,'/');self.assertEqual(code,200)
            meta=SessionMeta();meta.feed(home.decode('utf-8'))
            code,_,raw=local_http(ready,'/api/cancel',token=meta.token,value={});self.assertEqual(code,200)
            self.assertEqual(json.loads(raw)['status'],'cancelled')
            stdout,stderr=process.communicate(timeout=8)
            self.assertEqual(process.returncode,130)
            self.assertFalse(meta.token in stdout or meta.token in stderr)
            self.assertEqual(json.loads(stdout.strip().splitlines()[-1])['status'],'cancelled')
            self.assertFalse(list((directory/'collection').rglob('request.json')))


class AgentNativeUpdateReviewTests(unittest.TestCase):
    def test_cli_native_birth_update_rederives_result_invalidates_readings_and_preserves_old_exports(self):
        with fixture() as directory:
            job,_=run_job(directory);apply_readings(job)
            old_pair,before=make_pair_reading(job,directory/'old-pair.json')
            first=agent_report.finalize(job,directory/'final',pair_reading_file=old_pair)
            originals={Path(f[k]):sha(f[k]) for f in first['files'] for k in ('path','delivery_path')}
            submitted=sha(job/'submitted-input.json')
            b_hash=load(before['people'][1]['report_json'])['panels'][0]['result_sha256']
            patch=write(directory/'native-birth-patch.json',{'person':{'name':'丙-Agent更新审查'},'birth':{'date':'1991-05-02'}})
            run=subprocess.run([sys.executable,'-X','utf8','-B',str(SKILL/'scripts/agent_report.py'),'update',
                '--job',str(job),'--person','A','--patch',str(patch)],cwd=directory,text=True,encoding='utf-8',capture_output=True,timeout=45)
            self.assertEqual(run.returncode,0,run.stderr)
            result=json.loads(run.stdout);self.assertTrue(result['request_committed'])
            self.assertEqual(result['status'],'updated')
            current=agent_report.describe(job);_,native,records=agent_report.snapshot(job)
            self.assertEqual(records[0]['packed']['person']['name'],'丙-Agent更新审查')
            self.assertEqual(records[0]['report']['birth_input']['date'],'1991-05-02')
            self.assertEqual(records[0]['payloads']['numerology']['birth_date'],'1991-05-02')
            self.assertTrue(current['people'][0]['needs_readings'])
            self.assertFalse(current['people'][1]['needs_readings'])
            self.assertEqual(records[1]['report']['panels'][0]['result_sha256'],b_hash)
            self.assertEqual(sha(job/'submitted-input.json'),submitted)
            self.assertEqual(native['people'][0]['birth']['date'],'1991-05-02')
            apply_readings(job)
            with self.assertRaises(ValueError):agent_report.finalize(job,pair_reading_file=old_pair)
            fresh_pair,after=make_pair_reading(job,directory/'new-pair.json')
            self.assertNotEqual(before['pair_comparison_sha256'],after['pair_comparison_sha256'])
            exported=agent_report.finalize(job,directory/'final',pair_reading_file=fresh_pair)
            self.assertEqual(exported['status'],'exported')
            self.assertTrue(all(sha(path)==value for path,value in originals.items()))
            if EVIDENCE:write(EVIDENCE/'native-birth-update-observed.json',{'job':str(job),'update':result,
                'person_name':records[0]['packed']['person']['name'],'declared_birth':records[0]['report']['birth_input']['date'],
                'result_birth_date':records[0]['payloads']['numerology']['birth_date'],
                'a_reading_invalidated':bool(current['people'][0]['needs_readings']),'b_reading_preserved':not current['people'][1]['needs_readings'],
                'original_submit_unchanged':sha(job/'submitted-input.json')==submitted,
                'old_exports_unchanged':all(sha(path)==value for path,value in originals.items()),'old_pair_rejected':True,'fresh_export':exported})

    def test_native_question_update_changes_pair_binding_with_same_numeric_results(self):
        from agent_updates import update_job
        with fixture() as directory:
            job,_=run_job(directory);apply_readings(job)
            old_pair,before=make_pair_reading(job,directory/'old-question-pair.json')
            original_hashes=[load(p['report_json'])['panels'][0]['result_sha256'] for p in before['people']]
            result=update_job(job,{'preferences':{'topic':'新的合作主题','question':'新的明确问题',
                'answers':{'关注':'更正后的问答背景'}}})
            self.assertTrue(result['request_committed'])
            current=agent_report.describe(job)
            self.assertTrue(all(p['needs_readings'] for p in current['people']))
            self.assertEqual([load(p['report_json'])['panels'][0]['result_sha256'] for p in current['people']],original_hashes)
            self.assertNotEqual(current['pair_comparison_sha256'],before['pair_comparison_sha256'])
            apply_readings(job)
            with self.assertRaises(ValueError):agent_report.finalize(job,pair_reading_file=old_pair)
            if EVIDENCE:write(EVIDENCE/'native-question-update-observed.json',{'job':str(job),'request_committed':True,
                'numeric_hashes_unchanged':True,'personal_readings_invalidated':True,'old_pair_rejected':True,
                'pair_hash_before':before['pair_comparison_sha256'],'pair_hash_after':current['pair_comparison_sha256']})

    def test_native_location_update_reassesses_deferred_method_without_assuming_birth_time(self):
        from agent_updates import update_job
        with fixture() as directory:
            value=request();value['mode']='single';value['people']=value['people'][:1]
            value['preferences']['systems']=['numerology','bazi'];value['method_options']={'bazi':{'true_solar':True}}
            job,_=run_job(directory,value)
            _,_,before=agent_report.snapshot(job)
            self.assertEqual(next(p for p in before[0]['report']['panels'] if p['system']=='bazi')['state'],'needs_input')
            result=update_job(job,{'location':{'latitude':31.23,'longitude':121.47}},person='A')
            self.assertTrue(result['request_committed'])
            _,_,after=agent_report.snapshot(job)
            report=after[0]['report'];bazi=next(p for p in report['panels'] if p['system']=='bazi')
            self.assertIn(bazi['state'],('ready','partial'))
            self.assertIsNone(report['birth_input']['time'])
            self.assertNotIn('bazi',load(job/'project-a'/'versions'/report['revision']/'input.json')['deferred'])
            if EVIDENCE:write(EVIDENCE/'native-deferred-update-observed.json',{'job':str(job),'request_committed':True,
                'bazi_state_before':'needs_input','bazi_state_after':bazi['state'],'time_preserved_unknown':report['birth_input']['time'] is None})

    def test_partial_update_does_not_publish_mixed_request_and_can_retry(self):
        from agent_updates import update_job
        from project_store import project_lock
        with fixture() as directory:
            job,_=run_job(directory)
            patch={'preferences':{'question':'并发锁释放后重试的同一问题'}}
            submitted=sha(job/'submitted-input.json')
            with project_lock(job/'project-b'):
                partial=update_job(job,patch)
            self.assertEqual(partial['status'],'partial');self.assertFalse(partial['request_committed'])
            self.assertFalse((job/'current-request.json').exists())
            with self.assertRaises(ValueError):agent_report.finalize(job)
            retry=update_job(job,patch)
            self.assertTrue(retry['request_committed'])
            self.assertEqual(retry['status'],'updated')
            current=agent_report.describe(job)
            self.assertEqual(len(current['people']),2)
            self.assertEqual(sha(job/'submitted-input.json'),submitted)
            if EVIDENCE:write(EVIDENCE/'native-update-retry-observed.json',{'job':str(job),'partial':partial,'retry':retry,
                'mixed_export_rejected':True,'original_submit_unchanged':sha(job/'submitted-input.json')==submitted})

if __name__=='__main__':unittest.main()
