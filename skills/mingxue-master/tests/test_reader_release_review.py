"""Independent reader-gate unit checks; release-flow checks follow source freeze.

The prose below is a synthetic editorial fixture, not a personal report or an
assertion that length checks establish interpretation quality.
"""
import copy
import base64
from contextlib import contextmanager
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import struct
import sys
import tempfile
import unittest
from unittest import mock
import uuid
import zlib

HERE=Path(__file__).resolve().parents[1]
SKILL=Path(os.environ.get('MINGXUE_TEST_SKILL_ROOT') or (HERE/'package/mingxue-master' if (HERE/'package/mingxue-master').is_dir() else HERE))
sys.path.insert(0,str(SKILL/'scripts'))


BODY_PARAGRAPHS=[
    '你面对一件尚未有清楚终点的事情时，可能很快注意到责任和回报是否相称。这样的敏锐能够帮助你守住边界，也可能让你在还没听完对方的想法之前，先把自己的承诺收紧。值得留心的不是你肯不肯付出，而是你有没有把担心讲清楚。若你真正担心的是长期没有回应，就先承认这份需要，不必把它包装成对每个细节都要掌握。',
    '当别人肯定你的能力，你可能会更愿意承担难处；但被需要的感觉也容易让你把一个人的期待变成自己的义务。亲近与负责可以同时存在，却不必用无限承担来证明。你可以观察自己在答应以后是踏实还是紧绷：踏实往往表示这件事合乎你的意愿，紧绷则提醒你重新看待界限。这种分别来自你的真实感受，而不是别人给你的角色。',
    '你的坚持未必总是外显的强硬。有时它表现为先忍住不说，等失望积累后再一次撤回。这样做能够暂时避免冲突，却使对方不容易知道你为何改变。若你看见自己有这样的倾向，可以把不舒服说在它还很小的时候，既不急于判定对方，也不否定自己的感受。温和地坚持需要，比突然切断来往更能保留彼此重新理解的余地。',
    '真正适合你的稳定，应当让你仍能选择，而不是只能持续证明自己可靠。你愿意投入的地方，需要同时容得下休息、不同意见和偶尔改变主意。判断一段联系是否值得继续，可以看你是否越来越能够坦率表达，是否仍能保有自己的节奏。若这些条件逐渐具备，你的力量就不必只用在防守，也能用来创造你真正重视的生活。'
]
THEME_PARAGRAPHS=[
    '你在意承诺能否兑现，也在意自己是否被认真看见。前一种需要让你愿意守住已经答应的事情，后一种需要则会催促你寻求更鲜明的回应；两者并不冲突，却可能在等待时相互拉扯。当对方反应平淡，你可能误以为继续坚持便等于压抑自己。其实你需要辨认的是，眼前缺少的是时间、表达，还是双方根本不同的期待。',
    '如果你能把这几种可能分开，稳定就不再等于忍耐，变化也不再等于推翻全部。你可以保留自己重视的那部分承诺，同时承认某些期待尚未得到满足。这使你的选择更接近真实感受：既不会为了证明可靠而持续消耗，也不会因为一时失落便否定整段经历。真正的踏实，是你知道自己为何留下，也知道什么时候可以调整。',
    '你可能很会察觉气氛的变化，却未必愿意立即说出自己的需要。敏感使你看到细节，克制又让你希望给彼此留余地；当两者失去平衡，你容易把猜到的意思当成对方已经说过的话。这样的时刻最值得留心：你是在回应一件发生过的事，还是在回应自己担心将要发生的事。分清这一点，情绪才不必独自承担全部判断。',
    '表达真实需要并不意味着必须强烈或立即得到答案。你可以先承认自己希望被怎样对待，再给对方了解你的机会。如果回应仍然有限，也不必把原因全部归在自己身上。你需要的是一种可以容纳差异的联系，而不是每次都依靠猜测维持和气。能逐渐减少猜测，通常比表面上从不争执更值得珍惜。',
    '你有时希望靠近，有时又需要退回自己的空间。靠近让你感到被理解，独处使你重新找到节奏；真正的困难常常不在这两种需要本身，而在于你是否允许它们同时存在。如果每次想独处都伴随着愧疚，你就可能把亲近变成必须持续回应的负担，最后反而更想远离。承认自己的限度，是维持联系的一部分。',
    '对方也可能有不同的靠近方式，这并不自动表示谁更重视这段关系。你可以留意怎样的相处让自己既自在又愿意回来，而不是只看联系是否频繁。边界清楚时，你更容易把关心表达出来，也更容易接受别人暂时不同步。这样形成的亲近，不需要任何一方放弃全部习惯，仍然能够在共同重视的地方相遇。',
    '新的机会可能唤起你的好奇，已经拥有的秩序又使你不愿轻易改变。好奇让你看见尚未尝试的方向，秩序则帮助你保存已经积累的东西；若你只选其中一边，另一边的需要便可能以焦虑出现。因此，重要的并不是立即决定要不要改变，而是看清你希望保留什么，又愿意为哪些新的可能承担代价。',
    '当你能说清这些，变化就不必被想成一次孤注一掷。你可以允许某个部分先向前走，另一个部分仍然维持原来的安排。这样的节奏并非犹豫，而是给真实感受留下跟上选择的时间。最终值得依靠的，不是外界对勇敢或稳重的评价，而是你是否越来越能分辨自己的愿望，并愿意为这份愿望负责。'
]


def body():return '\n\n'.join(BODY_PARAGRAPHS)
def overview():
    return {'summary':BODY_PARAGRAPHS[0]+BODY_PARAGRAPHS[1],
        'themes':[{'title':title,'text':'\n\n'.join(THEME_PARAGRAPHS[(index+offset)%len(THEME_PARAGRAPHS)] for offset in range(3)),'basis':[]} for title,index in
                  [('承诺与被看见',0),('敏感与表达',2),('靠近与边界',4),('好奇与秩序',6)]],
        'agreements':[],'differences':[],'actions':[],'limitations':[]}
def record(bodies=None):
    return {'role':'a','report':{'question':'这是用户自己的JSON问题说明','person':{'notes':'用户自己写的本模块字样'},
        'panels':[{'system':system,'state':state,'traditional_interpretation':{'text':text}} for system,state,text in
                  (bodies or [('numerology','ready',body())])]}}


class ReaderGateIndependentReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import reader_language
        cls.gate=reader_language

    def test_clean_brief_keeps_a_genuine_short_request_short(self):
        self.assertEqual(self.gate.audit_reader_text('你可以保留自己的节奏，也认真听见对方的需要。',detailed=False),[])

    def test_detailed_single_method_is_not_exempted_by_method_count(self):
        issues=self.gate.audit_reader_report([record([('numerology','ready','你可以多留意自己的感受。')])],{},detailed=True)
        self.assertTrue(any(x['code']=='insufficient_reader_detail' for x in issues))

    def test_partial_real_method_still_needs_detailed_personal_prose(self):
        issues=self.gate.audit_reader_report([record([('qizheng','partial','仍有一部分资料待补。')])],{},detailed=True)
        self.assertTrue(any(x['code']=='insufficient_reader_detail' for x in issues))

    def test_missing_data_is_not_filled_with_a_fake_long_article(self):
        item=record();item['report']['panels'].append({'system':'palm','state':'needs_input','traditional_interpretation':None})
        self.assertEqual(self.gate.audit_reader_report([item],{},detailed=True),[])

    def test_internal_language_rejected_in_both_modes(self):
        for term in ('本模块','逐项','解释','输入','输出','哈希','权限','接口','缓存','PAYLOAD','ＪＳＯＮ'):
            for detailed in (False,True):
                with self.subTest(term=term,detailed=detailed):
                    issues=self.gate.audit_reader_text(body()+'\n\n'+term,detailed=detailed)
                    self.assertTrue(any(x['code']=='internal_language' for x in issues))

    def test_user_fields_and_machine_evidence_are_not_rewritten_or_audited_as_prose(self):
        item=record();item['report']['panels'][0]['traditional_interpretation']['basis']=[{'pointer':'/payload/schema','label':'内部JSON标签'}]
        before=copy.deepcopy(item)
        self.assertEqual(self.gate.audit_reader_report([item],{},detailed=True),[])
        self.assertEqual(item,before)

    def test_detailed_results_do_not_require_paragraph_padding(self):
        self.assertEqual(self.gate.audit_reader_text(body(),detailed=True),[])
        self.assertEqual(self.gate.audit_reader_text(''.join(BODY_PARAGRAPHS),detailed=True),[])

    def test_whitespace_latin_tokens_and_exact_repetition_cannot_pad_detail(self):
        cases=['\n\n'.join([' '+(' ' * 4000)]*4),
               '\n\n'.join(['alpha beta gamma delta '*150]*4),
               '\n\n'.join([BODY_PARAGRAPHS[0]]*6)]
        for text in cases:
            with self.subTest(kind=text[:20]):
                self.assertTrue(self.gate.audit_reader_text(text,detailed=True))

    def test_multimethod_overview_has_substantive_theme_paragraphs(self):
        item=record([('numerology','ready',body()),('sukuyo','ready','\n\n'.join(THEME_PARAGRAPHS[:4]))])
        value=overview()
        self.assertEqual(self.gate.audit_reader_report([item],{'A':value},detailed=True),[])
        value['themes'][0]['text']='你需要认识自己。'
        issues=self.gate.audit_reader_report([item],{'A':value},detailed=True)
        self.assertTrue(any(x['code']=='insufficient_reader_detail' and '/themes/0/text' in x['path'] for x in issues))

    def test_boolean_mode_is_explicit_and_gate_is_pure(self):
        item=record();value=overview();before=copy.deepcopy([item,value])
        self.gate.audit_reader_report([item],{'A':value},detailed=True)
        self.assertEqual([item,value],before)
        self.assertTrue(any(x['code']=='invalid_reader_option' for x in self.gate.audit_reader_text(body(),detailed='false')))


EVIDENCE=Path(os.environ['MINGXUE_READER_REVIEW_DIR']) if os.environ.get('MINGXUE_READER_REVIEW_DIR') else None
POINTERS={'numerology':'/life_path/reduction','sukuyo':'/birth_mansion','bazi':'/pillars','palm':'/user_reported_observations','face':'/user_reported_observations'}


def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def write(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');return Path(path)
def file_sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def evidence(name,value):
    if EVIDENCE:write(EVIDENCE/name,value)


def native_request(systems=None,mode='pair',depth=None):
    people=[{'person':{'name':'读者审查甲','notes':'虚构技术测试人物甲'},'birth':{'date':'1990-05-02','time':None,'calendar':'solar','timezone':'Asia/Shanghai'}},
            {'person':{'name':'读者审查乙','notes':'虚构技术测试人物乙'},'birth':{'date':'1992-06-13','time':None,'calendar':'solar','timezone':'Asia/Shanghai'}}]
    pref={'systems':systems or ['numerology','sukuyo'],'topic':'个人特点与合作相处',
          'question':'相处和合作时，各自擅长什么，容易在哪些地方有分歧，怎样更合拍？',
          'relationship':'合作伙伴' if mode=='pair' else '个人研习','virtual_draws':False,'prepare_engines':False}
    if depth is not None:pref['depth']=depth
    return {'mode':mode,'people':people if mode=='pair' else people[:1],'preferences':pref}


def fill_actual_readings(job,*,short=False,overrides=None):
    import agent_report,workflow
    state=agent_report.describe(job)
    for person in state['people']:
        report=load(person['report_json']);readings={}
        for index,panel in enumerate(report['panels']):
            if panel['state'] not in ('ready','partial') and not (panel['state']=='intake_only' and panel['system'] in ('palm','face')):continue
            if panel['system'] not in POINTERS:raise AssertionError('Unexpected fixture method '+panel['system'])
            text='你可以保留自己的节奏，也认真听见对方的需要。' if short else '\n\n'.join(BODY_PARAGRAPHS if index%2==0 else THEME_PARAGRAPHS[:4])
            text=(overrides or {}).get((person['role'].upper(),panel['system']),text)
            readings[panel['system']]={'text':text,'result_sha256':panel['result_sha256'],'question_hash':report['question_hash'],
                'basis':[{'kind':'calculation','pointer':POINTERS[panel['system']],'label':'当前本人的实际结果'}]}
        workflow.run_project(Path(person['workspace']),patch={'readings':readings})
    return agent_report.describe(job)


def comparison(records):
    from pair_analysis import compare_people
    value=compare_people(records[0]['packed'],records[1]['packed'],records[0]['relationship'])
    value['reading_context']={r['role'].upper():r['report']['question_hash'] for r in records}
    return value


def synthesis_value(records,scope,comp=None):
    import report_synthesis
    context=report_synthesis.synthesis_context(records,scope,comparison=comp)
    refs=[{'person':row['person'],'system':row['system'],'pointer':POINTERS[row['system']],'label':'本人当次实际结果'}
          for row in context['coverage'] if row['calculated']]
    value=overview();value['context_sha256']=context['context_sha256']
    for item in value['themes']:item['basis']=copy.deepcopy(refs)
    value['actions']=[{'title':'留意真实的相处感受','text':'让愿望与承担都有位置，听见对方真实的需要。','basis':copy.deepcopy(refs)}]
    value['limitations']=['这些传统符号不代替真实生活与双方表达，也不保证未来。']
    return value


def synthesis_files(directory,records):
    comp=comparison(records) if len(records)==2 else None
    scopes=['A','B','pair'] if comp else ['A']
    return {scope:write(Path(directory)/(scope+'-synthesis.json'),synthesis_value(records,scope,comp if scope=='pair' else None)) for scope in scopes}


def synthesis_arguments(files):
    return {dict(A='synthesis_a_file',B='synthesis_b_file',pair='synthesis_pair_file')[scope]:path for scope,path in files.items()}


def bound_photo_fixture(directory):
    """Two artificial colour tiles; their labels exercise API trust, not vision."""
    import agent_intake,agent_report,photo_uploads
    from agent_updates import update_job
    def png(color):
        def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',2,2,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\x00'+bytes([color,0,0])*2+b'\x00'+bytes([color,0,0])*2))+chunk(b'IEND',b'')
    session=photo_uploads.PhotoSession(directory/'.photo-sessions')
    try:
        native=native_request(['numerology','palm'])
        refs=[]
        for role,color in (('A',20),('B',40)):
            uploaded=session.upload({'person':role,'kind':'palm_unknown','name':role+'技术色块.png','mime':'image/png',
                'data_base64':base64.b64encode(png(color)).decode('ascii'),'include_in_report':False})
            refs.append(uploaded['ref'])
        for person,ref in zip(native['people'],refs):person['photos']=[ref]
        submitted=agent_intake.collect_request(directory/'collected',native,photo_session=session.snapshot(native))
        state=agent_report.run(submitted['request_file'],directory/'jobs');job=Path(state['job_dir'])
        for role,ref,shape in zip(('A','B'),refs,('curved','angular')):
            wrapper={'schema_version':2,'source':'agent_viewed','photo_refs':[{'id':ref['id'],'sha256':ref['sha256']}],
                'observations':{'hand':'unknown','features':[{'region':'palm_outline','shape':shape,'visibility':'clear'}]},
                'note':'人工合成分类，测试资料绑定，不是实际看图结论。'}
            result=update_job(job,{'observations':{'palm':wrapper}},person=role)
            if not result['request_committed']:raise AssertionError(result)
        return job
    finally:session.cleanup()


class Page(HTMLParser):
    def __init__(self):
        super().__init__();self.scripts=[];self.active=None;self.tags=[];self.resources=[];self.text=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs);self.tags.append((tag,attrs))
        if tag=='script':self.active={'attrs':attrs,'text':''}
        if tag in ('script','style'):self.skip+=1
        for key,value in attrs.items():
            if key in ('src','href','action','srcset','poster','data') and value and not value.startswith(('#','data:','blob:')):
                self.resources.append((tag,key,value))
    def handle_endtag(self,tag):
        if tag=='script' and self.active is not None:self.scripts.append(self.active);self.active=None
        if tag in ('script','style'):self.skip=max(0,self.skip-1)
    def handle_data(self,value):
        if self.active is not None:self.active['text']+=value
        if not self.skip:self.text.append(value)
    def data(self):return json.loads(next(s['text'] for s in self.scripts if s['attrs'].get('id')=='report-data'))


def rendered_markup(page):
    """Execute the actual pure renderer in an isolated VM, not a browser mockup.

    This checks generated markup and scripts. Layout/390px/PDF still require the
    separate real-browser evidence; a DOM stub does not establish those facts.
    """
    node=shutil.which('node')
    if not node:raise unittest.SkipTest('Node is unavailable for the markup execution check')
    program=r'''
const vm=require('vm'),fs=require('fs'),items=JSON.parse(fs.readFileSync(0,'utf8')),holders={};
const element=id=>holders[id]||(holders[id]={innerHTML:'',addEventListener(){},querySelectorAll(){return []},classList:{toggle(){}}});
const source=items.find(s=>s.attrs.id==='report-data').text;
const document={getElementById(id){return id==='report-data'?{textContent:source}:element(id)}};
const events={},window={addEventListener(name,fn){events[name]=fn},print(){}};
const sandbox={window,document,console,fetch(){throw new Error('network must not be used')}};
vm.createContext(sandbox);
for(const s of items)if(s.attrs.type!=='application/json')vm.runInContext(s.text,sandbox,{timeout:5000});
if(events.beforeprint)events.beforeprint();
process.stdout.write(JSON.stringify({root:element('report-app').innerHTML,views:Object.fromEntries(Object.entries(holders).filter(([k])=>k.startsWith('view-')).map(([k,v])=>[k,v.innerHTML]))}));
'''
    completed=subprocess.run([node,'-e',program],input=json.dumps(page.scripts,ensure_ascii=False),text=True,encoding='utf-8',capture_output=True,timeout=20)
    if completed.returncode:raise AssertionError('Reader script failed: '+completed.stderr[:1200])
    return json.loads(completed.stdout)


class ReaderReleaseIntegrationReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import agent_report
        cls.temp=None
        if EVIDENCE:
            EVIDENCE.mkdir(parents=True,exist_ok=True);cls.root=EVIDENCE/('run-'+uuid.uuid4().hex[:10]);cls.root.mkdir()
        else:
            cls.temp=tempfile.TemporaryDirectory(prefix='reader-release-review-');cls.root=Path(cls.temp.name)
        result=agent_report.run(write(cls.root/'request.json',native_request()),cls.root/'seed')
        cls.job=Path(result['job_dir']);fill_actual_readings(cls.job)
        _,_,cls.records=agent_report.snapshot(cls.job)
        evidence('two-method-snapshot.json',{'job':str(cls.job),'people':[{'role':r['role'],'name':r['packed']['person']['name'],
            'methods':[{key:p[key] for key in ('system','state','reading_status','result_sha256')} for p in r['report']['panels']]} for r in cls.records]})
    @classmethod
    def tearDownClass(cls):
        if cls.temp:cls.temp.cleanup()
    @contextmanager
    def clone(self):
        directory=self.root/('case-'+uuid.uuid4().hex[:10]);directory.mkdir();job=directory/self.job.name;shutil.copytree(self.job,job)
        yield directory,job
    def new_single(self,directory,systems,depth=None):
        import agent_report
        result=agent_report.run(write(directory/'request.json',native_request(systems,'single',depth)),directory/'jobs')
        return Path(result['job_dir'])
    def assert_no_outputs(self,job,destination):
        self.assertFalse((job/'deliveries').exists());self.assertFalse(destination.exists())

    def test_11_default_detailed_single_method_cannot_export_an_unwritten_short_article(self):
        import agent_report
        directory=self.root/('single-'+uuid.uuid4().hex[:8]);directory.mkdir();job=self.new_single(directory,['numerology'])
        fill_actual_readings(job,short=True)
        result=agent_report.finalize(job,directory/'final')
        self.assertEqual(result['status'],'needs_reader_edit');self.assertEqual(result['files'],[])
        self.assertTrue(any(i['code']=='insufficient_reader_detail' for i in result['issues']))
        self.assert_no_outputs(job,directory/'final')
        fill_actual_readings(job)
        self.assertEqual(agent_report.finalize(job,directory/'final')['status'],'exported')
        evidence('default-detail-gate.json',{'initial':result,'corrected_exported':True})

    def test_12_bad_late_scope_has_no_half_delivery_and_keeps_previous_reports(self):
        import agent_report
        for bad_scope in ('B','pair'):
            with self.subTest(scope=bad_scope),self.clone() as (directory,job):
                _,_,records=agent_report.snapshot(job);files=synthesis_files(directory,records)
                first=agent_report.finalize(job,directory/'original',**synthesis_arguments(files))
                self.assertEqual(first['status'],'exported')
                prior={f[k]:file_sha(f[k]) for f in first['files'] for k in ('path','delivery_path')}
                exports={p.name for p in (job/'deliveries').iterdir()}
                value=load(files[bad_scope]);value['themes'][2]['text']='你可以先照顾自己的感受。';write(files[bad_scope],value)
                result=agent_report.finalize(job,directory/'failed',**synthesis_arguments(files))
                self.assertEqual(result['status'],'needs_reader_edit');self.assertEqual(result['files'],[])
                self.assertFalse((directory/'failed').exists());self.assertEqual({p.name for p in (job/'deliveries').iterdir()},exports)
                self.assertTrue(all(file_sha(p)==sha for p,sha in prior.items()))
                evidence('late-'+bad_scope+'-gate.json',{'result':result,'old_products_unchanged':True,'no_new_revision':True})

    def test_13_explicit_brief_allows_short_prose_but_still_rejects_internal_language(self):
        import agent_report,workflow
        directory=self.root/('brief-'+uuid.uuid4().hex[:8]);directory.mkdir();job=self.new_single(directory,['numerology'],'brief')
        fill_actual_readings(job,short=True)
        self.assertEqual(agent_report.finalize(job)['status'],'exported')
        status=agent_report.describe(job);person=status['people'][0];report=load(person['report_json']);panel=report['panels'][0]
        workflow.run_project(Path(person['workspace']),patch={'readings':{'numerology':{'text':'本模块解释你的特点。',
            'result_sha256':panel['result_sha256'],'question_hash':report['question_hash'],
            'basis':[{'kind':'calculation','pointer':POINTERS['numerology'],'label':'实际数字'}]}}})
        result=agent_report.finalize(job,directory/'failed')
        self.assertEqual(result['status'],'needs_reader_edit');self.assertEqual(result['files'],[]);self.assertFalse((directory/'failed').exists())

    def test_14_actual_pair_reader_markup_keeps_paragraphs_people_and_offline_boundaries(self):
        import agent_report,reader_language
        with self.clone() as (directory,job):
            _,_,records=agent_report.snapshot(job);files=synthesis_files(directory,records)
            result=agent_report.finalize(job,directory/'final',**synthesis_arguments(files));self.assertEqual(result['status'],'exported')
            checked=[]
            for file in result['files']:
                page=Page();page.feed(Path(file['delivery_path']).read_text(encoding='utf-8'));data=page.data()
                self.assertEqual(page.resources,[]);self.assertEqual(len(page.scripts),3)
                self.assertFalse(any(tag in ('form','input','select','textarea','pre') for tag,_ in page.tags))
                rendered=rendered_markup(page);markup=Page();markup.feed(rendered['root']+''.join(rendered['views'].values()))
                self.assertFalse(any(tag in ('form','input','select','textarea','pre') for tag,_ in markup.tags));self.assertEqual(markup.resources,[])
                self.assertFalse(any(key.lower().startswith('on') for _,attrs in markup.tags for key in attrs))
                self.assertEqual(reader_language.audit_reader_text('\n'.join(markup.text),detailed=False),[])
                for panel in data['panels']:
                    self.assertIn('raw',panel);self.assertEqual(len(panel['interpretation']['text'].split('\n\n')),4)
                if file['role']=='pair':
                    self.assertEqual([p['person_index'] for p in data['panels']],[0,0,1,1])
                    self.assertEqual([p['name'] for p in data['people']],['读者审查甲','读者审查乙'])
                checked.append({'role':file['role'],'path':file['delivery_path'],'panels':len(data['panels']),
                    'paragraph_nodes':sum(tag=='p' for tag,_ in markup.tags),'machine_tree_not_mounted':True})
            evidence('actual-reader-markup.json',{'files':checked,'check_type':'Actual JS-generated markup in a VM. Browser layout/PDF checked separately.'})

    def test_15_changed_person_or_birthday_cannot_reuse_old_readings_and_summary(self):
        import agent_report
        from agent_updates import update_job
        for patch in ({'person':{'name':'已更正的新人物'}},{'birth':{'date':'1991-05-02'}}):
            with self.subTest(patch=patch),self.clone() as (directory,job):
                _,_,records=agent_report.snapshot(job);files=synthesis_files(directory,records)
                response=update_job(job,patch,person='A');self.assertTrue(response['request_committed'],response)
                result=agent_report.finalize(job,directory/'final',**synthesis_arguments(files))
                self.assertEqual(result['status'],'needs_interpretation');self.assertEqual(result['files'],[])
                self.assert_no_outputs(job,directory/'final')

    def test_16_each_theme_requires_substantive_methods_and_both_pair_people(self):
        import report_synthesis
        good=synthesis_value(self.records,'A');bad=copy.deepcopy(good)
        bad['themes'][0]['basis']=[{'person':'A','system':'numerology','pointer':POINTERS['numerology'],'label':'实际数值'},
            {'person':'A','system':'sukuyo','pointer':'/rules','label':'仅传统规则'}]
        with self.assertRaises(ValueError):report_synthesis.validate_synthesis(bad,self.records,'A')
        comp=comparison(self.records);bad=synthesis_value(self.records,'pair',comp)
        bad['themes'][0]['basis']=[r for r in bad['themes'][0]['basis'] if r['person']=='A']
        with self.assertRaises(ValueError):report_synthesis.validate_synthesis(bad,self.records,'pair',comparison=comp)

    def test_17_unknown_birth_time_has_an_empty_hour_column_and_missing_methods_are_absent(self):
        import agent_report
        directory=self.root/('unknown-'+uuid.uuid4().hex[:8]);directory.mkdir();job=self.new_single(directory,['bazi','names','palm','face'])
        fill_actual_readings(job)
        result=agent_report.finalize(job,directory/'final');self.assertEqual(result['status'],'exported',result)
        page=Page();page.feed(Path(result['files'][0]['delivery_path']).read_text(encoding='utf-8'));data=page.data()
        self.assertEqual([p['system'] for p in data['panels']],['bazi'])
        panel=data['panels'][0];self.assertFalse(panel['raw']['time_known']);self.assertEqual(panel['view']['kind'],'bazi_unknown')
        hour=next(c for c in panel['view']['data']['columns'] if c['key']=='hour');self.assertEqual(hour['values'],[])
        self.assertIsNone(data['people'][0]['birth']['time'])
        markup=rendered_markup(page);p=Page();p.feed(markup['root']+''.join(markup['views'].values()))
        visible='\n'.join(p.text);self.assertNotIn('面相',visible);self.assertNotIn('手相',visible);self.assertNotIn('姓名学',visible)
        self.assertNotIn('12:00',visible)
        evidence('unknown-time-and-missing-methods.json',{'file':result['files'][0]['delivery_path'],'hour_column':hour,
            'visible_methods':['bazi'],'no_synthetic_noon':True})

    def test_18_script_closure_in_user_fields_remains_data_in_html_and_real_markup(self):
        import agent_report
        attack='</ScRiPt><img src=x onerror=alert(1)><script>alert(2)</script>&\u2028\u2029'
        directory=self.root/('xss-'+uuid.uuid4().hex[:8]);directory.mkdir();request=native_request(['numerology'],'single')
        request['people'][0]['person']['name']='审查'+attack
        result=agent_report.run(write(directory/'request.json',request),directory/'jobs');job=Path(result['job_dir']);fill_actual_readings(job)
        final=agent_report.finalize(job,directory/'final');self.assertEqual(final['status'],'exported')
        page=Page();page.feed(Path(final['files'][0]['delivery_path']).read_text(encoding='utf-8'))
        self.assertEqual(len(page.scripts),3);self.assertEqual(page.data()['people'][0]['name'],'审查'+attack)
        rendered=rendered_markup(page);markup=Page();markup.feed(rendered['root']+''.join(rendered['views'].values()))
        self.assertFalse(any(tag=='script' for tag,_ in markup.tags));self.assertEqual(markup.resources,[])
        self.assertFalse(any(k.startswith('on') for _,attrs in markup.tags for k in attrs))

    def test_19_pdf_invalid_targets_do_not_launch_or_overwrite(self):
        import report_pdf
        directory=self.root/('pdf-'+uuid.uuid4().hex[:8]);directory.mkdir();source=directory/'original.html';source.write_text('<!doctype html><p>本地报告</p>',encoding='utf-8')
        original=file_sha(source);existing=directory/'keep.pdf';existing.write_bytes(b'original-pdf')
        with mock.patch.object(report_pdf,'_render',side_effect=AssertionError('should not launch')):
            for target in (existing,SKILL/'ui/reviewer-forbidden.pdf'):
                result=report_pdf.export_pdf(source,target);self.assertEqual(result['status'],'error')
        self.assertEqual(existing.read_bytes(),b'original-pdf');self.assertEqual(file_sha(source),original)
        with mock.patch.object(report_pdf,'find_browser',return_value=None):
            result=report_pdf.export_pdf(source,directory/'new.pdf');self.assertEqual(result['status'],'needs_browser')
        self.assertFalse((directory/'new.pdf').exists());self.assertFalse((SKILL/'ui/reviewer-forbidden.pdf').exists())

    def test_20_photo_upload_is_not_visual_analysis_and_trusted_observation_remains_person_bound(self):
        """Synthetic colour tiles exercise binding only, never real palm findings."""
        import agent_intake,agent_report
        from agent_updates import update_job
        import photo_uploads
        def png(color):
            def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
            return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',2,2,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\x00'+bytes([color,0,0])*2+b'\x00'+bytes([color,0,0])*2))+chunk(b'IEND',b'')
        directory=self.root/('photos-'+uuid.uuid4().hex[:8]);directory.mkdir()
        session=photo_uploads.PhotoSession(directory/'.photo-sessions')
        try:
            tile=png(30)
            upload=session.upload({'person':'A','kind':'palm_unknown','name':'技术色块.png','mime':'image/png',
                'data_base64':base64.b64encode(tile).decode('ascii'),'include_in_report':False})
            self.assertIs(upload['photo']['viewed'],False);self.assertIs(upload['photo']['pixel_decode_performed'],False)
            native=native_request(['palm','face'],'single');native['people'][0]['photos']=[upload['ref']]
            submitted=agent_intake.collect_request(directory/'collected',native,photo_session=session.snapshot(native))
            state=agent_report.run(submitted['request_file'],directory/'jobs');job=Path(state['job_dir']);fill_actual_readings(job)
            _,_,unobserved=agent_report.snapshot(job)
            from personal_report import panels as reader_panels
            self.assertEqual(reader_panels(unobserved[0]['report'],unobserved[0]['payloads']),[])
            before=agent_report.finalize(job,directory/'too-soon')
            self.assertEqual(before['status'],'needs_photo_review');self.assertEqual(before['files'],[])
            self.assert_no_outputs(job,directory/'too-soon')
            wrapper={'schema_version':2,'source':'agent_viewed','photo_refs':[{'id':upload['ref']['id'],'sha256':upload['ref']['sha256']}],
                'observations':{'hand':'unknown','features':[{'region':'palm_outline','shape':'curved','visibility':'clear'}]},
                'note':'人工合成分类，仅测试可信更正和照片归属；不表示色块是真人手掌。'}
            response=update_job(job,{'observations':{'palm':wrapper}},person='A');self.assertTrue(response['request_committed'],response)
            fill_actual_readings(job,short=True)
            short_observation=agent_report.finalize(job,directory/'short')
            self.assertEqual(short_observation['status'],'exported',short_observation)
            short_page=Page();short_page.feed(Path(short_observation['files'][0]['delivery_path']).read_text(encoding='utf-8'))
            self.assertIsNone(short_page.data()['panels'][0]['view'])
            # The following prose is an editorial pipeline fixture. No real user
            # or image-content assertion is used as release evidence here.
            fill_actual_readings(job)
            final=agent_report.finalize(job,directory/'final');self.assertEqual(final['status'],'exported',final)
            source=Path(final['files'][0]['delivery_path']);original=file_sha(source)
            page=Page();page.feed(source.read_text(encoding='utf-8'));data=page.data()
            self.assertEqual({p['system'] for p in data['panels']},{'palm'})
            palm=next(p for p in data['panels'] if p['system']=='palm')
            self.assertEqual(palm['raw']['observation_status'],'agent_observed');self.assertIs(palm['raw']['image_content_analysis'],False)
            self.assertEqual(palm['raw']['photo_refs'],wrapper['photo_refs']);self.assertEqual(palm['raw']['image']['sha256'],hashlib.sha256(tile).hexdigest())
            self.assertNotIn(base64.b64encode(tile).decode('ascii'),source.read_text(encoding='utf-8'))
            _,native,records=agent_report.snapshot(job)
            from report_synthesis import synthesis_context
            coverage=synthesis_context(records,'A')['coverage'];observed=next(c for c in coverage if c['system']=='palm')
            self.assertFalse(observed['calculated']);self.assertEqual(observed['kind'],'observation')
            # Optional attachment changes display consent, not the findings.
            native['people'][0]['photos'][0]['include_in_report']=True
            update=update_job(job,{'photos':native['people'][0]['photos']},person='A');self.assertTrue(update['request_committed'],update)
            next_final=agent_report.finalize(job,directory/'attached');self.assertEqual(next_final['status'],'exported',next_final)
            attached=Path(next_final['files'][0]['delivery_path']).read_text(encoding='utf-8')
            self.assertIn('data:image/png;base64,'+base64.b64encode(tile).decode('ascii'),attached)
            self.assertEqual(file_sha(source),original)
            # A matching container is still tied to its immutable content hash.
            selected=photo_uploads.photo_handoff(job/'photos.json',native)['photos'][0]
            Path(selected['file']).write_bytes(png(31))
            with self.assertRaises(ValueError):agent_report.finalize(job,directory/'tampered')
            self.assertFalse((directory/'tampered').exists());self.assertEqual(file_sha(source),original)
            evidence('photo-reader-boundaries.json',{'pending_before_review':before['status'],'trusted_fixture_export':str(source),
                'scope':'Synthetic tile/classification verifies API binding only, not actual content recognition.',
                'not_calculated':True,'short_observation_allowed':short_observation['status'],'unobserved_panel_absent':True,
                'initial_attachment':False,'explicit_attachment':True,'old_file_unchanged':True,'tampered_hash_rejected':True})
        finally:session.cleanup()

    def test_21_direct_workflow_cannot_replace_A_observation_or_image_with_B(self):
        import agent_report,workflow
        directory=self.root/('cross-photo-'+uuid.uuid4().hex[:8]);directory.mkdir();job=bound_photo_fixture(directory)
        _,_,records=agent_report.snapshot(job)
        def source(record):return load(record['workspace']/'versions'/record['report']['revision']/'input.json')
        a,b=records;original=source(a)['options']['palm'];foreign=source(b)['options']['palm']
        self.assertNotEqual(file_sha(original['image']),file_sha(foreign['image']))
        observed=[]
        for description,replacement in (('B wrapper and image',foreign),('B image with native A wrapper',{**original,'image':foreign['image']})):
            workflow.run_project(a['workspace'],patch={'options':{'palm':replacement}})
            with self.assertRaises(ValueError):agent_report.snapshot(job)
            with self.assertRaises(ValueError):agent_report.finalize(job,directory/'rejected')
            self.assert_no_outputs(job,directory/'rejected')
            observed.append(description)
            workflow.run_project(a['workspace'],patch={'options':{'palm':original}})
            agent_report.snapshot(job)
        evidence('direct-workflow-cross-photo.json',{'job':str(job),'rejected_cases':observed,'no_exports':True})

    def test_22_restoring_observation_file_cannot_hide_a_different_committed_payload(self):
        import agent_report,workflow
        directory=self.root/('restored-photo-'+uuid.uuid4().hex[:8]);directory.mkdir();job=bound_photo_fixture(directory)
        fill_actual_readings(job)
        _,_,records=agent_report.snapshot(job);a=records[0]
        source=load(a['workspace']/'versions'/a['report']['revision']/'input.json')
        observed_file=Path(source['options']['palm']['observations']);original=observed_file.read_bytes()
        changed=load(observed_file);changed['observations']['features'][0]['shape']='angular'
        try:
            write(observed_file,changed)
            # The workflow captures external observations as checksummed
            # revision artifacts. A changed artifact must be rejected before
            # it can be recalculated, rebound, or published as a new product.
            with self.assertRaises(ValueError):workflow.run_project(a['workspace'],patch={})
            with self.assertRaises(ValueError):agent_report.snapshot(job)
            with self.assertRaises(ValueError):agent_report.finalize(job,directory/'rejected')
            self.assert_no_outputs(job,directory/'rejected')
        finally:observed_file.write_bytes(original)
        _,_,accepted=agent_report.snapshot(job)
        self.assertEqual(accepted[0]['payloads']['palm']['user_reported_observations']['features'],load(observed_file)['observations']['features'])
        evidence('restored-observation-closed.json',{'job':str(job),'immutable_observation_artifact_tamper_rejected':True,
            'restored_original_coherent':True,'no_exports':True})

    def test_23_clearing_an_answer_invalidates_old_prose_and_preserves_unknown_clock(self):
        import agent_report
        from agent_updates import update_job
        directory=self.root/('clear-answer-'+uuid.uuid4().hex[:8]);directory.mkdir()
        request=native_request(['numerology'],'single','brief')
        request['preferences']['answers']={'原关注':'旧内容','保留':'生活'}
        initial=agent_report.run(write(directory/'request.json',request),directory/'jobs')
        self.assertIn('job_dir',initial,initial);job=Path(initial['job_dir'])
        fill_actual_readings(job,short=True)
        old=agent_report.finalize(job,directory/'original');self.assertEqual(old['status'],'exported')
        old_file=Path(old['files'][0]['delivery_path']);old_sha=file_sha(old_file);submitted_sha=file_sha(job/'submitted-input.json')
        _,_,before=agent_report.snapshot(job);before_hash=before[0]['report']['question_hash']
        result=update_job(job,{'preferences':{'answers':{'原关注':None,'新关注':'相处'}}});self.assertTrue(result['request_committed'],result)
        _,native,after=agent_report.snapshot(job)
        self.assertEqual(native['preferences']['answers'],{'保留':'生活','新关注':'相处'})
        self.assertIsNone(native['people'][0]['birth']['time'])
        self.assertNotEqual(after[0]['report']['question_hash'],before_hash)
        self.assertEqual(after[0]['report']['panels'][0]['reading_status'],'stale')
        blocked=agent_report.finalize(job,directory/'not-yet')
        self.assertEqual(blocked['status'],'needs_interpretation');self.assertEqual(blocked['files'],[])
        self.assertFalse((directory/'not-yet').exists());self.assertEqual(file_sha(old_file),old_sha)
        self.assertEqual(file_sha(job/'submitted-input.json'),submitted_sha)
        fill_actual_readings(job,short=True)
        final=agent_report.finalize(job,directory/'updated');self.assertEqual(final['status'],'exported')
        evidence('answer-deletion-context.json',{'job':str(job),'answers':native['preferences']['answers'],'birth_time':None,
            'old_reading_stale':True,'premature_export':blocked['status'],'fresh_export':final['status'],
            'old_product_and_original_submit_unchanged':True})


if __name__=='__main__':unittest.main()
