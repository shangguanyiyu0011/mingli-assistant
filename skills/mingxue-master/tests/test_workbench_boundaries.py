"""Workbench boundary checks; live loopback requests require explicit opt-in."""
import copy
from html.parser import HTMLParser
import http.client
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get('MINGXUE_TEST_SKILL_ROOT') or (HERE / 'package/mingxue-master' if (HERE / 'package/mingxue-master').is_dir() else HERE))
sys.path.insert(0, str(SKILL / 'scripts'))
from workbench import Records
from workbench_api import calculate
from workbench_catalog import catalog

EVIDENCE = Path(os.environ['MINGXUE_REVIEW_EVIDENCE_DIR']) if os.environ.get('MINGXUE_REVIEW_EVIDENCE_DIR') else None
if EVIDENCE:
    EVIDENCE.mkdir(parents=True, exist_ok=True)

def fixture():
    return calculate('numerology', {'date':'1990-05-02','year':2026,'question':'[边界审查] 自有测试记录'})

class _Markup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.dangerous = []
    def handle_starttag(self, tag, attrs):
        if tag in ('script','iframe','object','embed','img'):
            self.dangerous.append(tag)
        for key,value in attrs:
            if key.startswith('on') or (key in ('href','src','xlink:href') and (value or '').lower().startswith(('javascript:','data:text/html'))):
                self.dangerous.append(key)

class RecordBoundaryTests(unittest.TestCase):
    def test_valid_result_roundtrip(self):
        with tempfile.TemporaryDirectory(dir=EVIDENCE) as directory:
            store = Records(directory)
            record = store.save(fixture())
            self.assertEqual(store.read(record['id']), record)

    def test_modified_record_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=EVIDENCE) as directory:
            store = Records(directory)
            record = store.save(fixture())
            altered = copy.deepcopy(record)
            altered['result']['system'] = 'iching'
            altered['view']['title'] = '周易六爻'
            (Path(directory)/(record['id']+'.json')).write_text(json.dumps(altered,ensure_ascii=False),encoding='utf-8')
            with self.assertRaises((ValueError,OSError)):
                store.read(record['id'])

    def test_cross_system_save_is_rejected(self):
        value = fixture()
        value['result']['system'] = 'iching'
        with tempfile.TemporaryDirectory(dir=EVIDENCE) as directory:
            with self.assertRaises(ValueError):
                Records(directory).save(value)

    def test_catalog_has_no_personal_fact_defaults(self):
        personal = {'date','time','gender','latitude','longitude','surname','given','birth_date','birth_time'}
        for spec in catalog()['systems']:
            for field in spec['fields']:
                if field['key'] in personal:
                    self.assertIn(field.get('default'), (None,''), (spec['id'],field['key']))

    @unittest.skipUnless(shutil.which('node'), 'Node.js is needed to execute the actual renderer')
    def test_html_and_svg_values_are_escaped(self):
        attack = '\"\'><img src=x onerror=alert(1)><script>alert(2)</script>&'
        views = {
            'reference':{'text':attack},
            'verse':{'title':attack,'text':attack,'source':attack},
            'numbers':{'items':[{'label':attack,'value':attack,'detail':attack}]},
            'cards':{'cards':[{'label':attack,'position':attack,'icon':attack,'orientation':attack,'keywords':[attack]}]},
            'hexagrams':{'hexagrams':[{'title':attack,'name':attack,'number':1,'lines':[{'yang':False,'moving':True,'label':attack,'detail':attack}]}]},
            'wheel':{'points':[{'label':attack,'longitude':0,'speed':1,'type':attack}],'cusps':[0],'ascendant':0},
            'palaces':{'palaces':[{'index':0,'name':attack,'branch':attack,'major':[attack],'minor':[attack],'tags':[attack]}],'center':[attack]},
            'shield':{'figures':[{'col':0,'row':0,'name':attack,'points':[1,2,1,2],'parents':[attack]}]},
            'board':{'cells':[{'label':attack,'value':attack,'items':[attack]}]},
            'pillars':{'columns':[{'label':attack,'stem':attack,'branch':attack,'element':attack,'hidden':[attack],'tags':[attack]}]},
            'sixpalaces':{'cells':[{'name':attack,'element':attack,'row':0,'col':0,'index':0,'active':True}],
                          'steps':[{'label':attack,'count':attack,'start_palace':attack,'end_palace':attack}]},
            'fourpositions':{'rows':[{'label':attack,'stem':attack,'branch':attack,'name':attack,'element':attack}],
                             'general_ring':[{'earth_branch':attack,'general_branch':attack,'general_name':attack}],
                             'noble_ring':[{'earth_branch':attack,'noble_name':attack,'noble_branch':attack}]},
            'mansion':{'nodes':[{'label':attack,'is_birth':True,'relation_from_birth':attack}],'relations':[attack]}
        }
        source = "const fs=require('node:fs'),vm=require('node:vm');let c={window:{}};vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),c);let q=JSON.parse(fs.readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(Object.fromEntries(Object.entries(q.views).map(([kind,data])=>[kind,c.window.MingRenderer.render({kind,data,title:q.attack,subtitle:q.attack,notes:[q.attack],metrics:[{label:q.attack,value:q.attack}]})]))));"
        run = subprocess.run([shutil.which('node'),'-e',source,str(SKILL/'ui/renderer.js')],
            input=json.dumps({'attack':attack,'views':views},ensure_ascii=False),text=True,encoding='utf-8',capture_output=True,timeout=30)
        self.assertEqual(run.returncode,0,run.stderr)
        outputs = json.loads(run.stdout)
        for name,value in outputs.items():
            parser = _Markup()
            parser.feed(value)
            self.assertEqual(parser.dangerous,[],name)
            self.assertIn('&lt;',value,name)
        if EVIDENCE:
            (EVIDENCE/'renderer-escape-verified.json').write_text(json.dumps({'passed':True,'kinds':list(outputs)},indent=2),encoding='utf-8')

class _Token(HTMLParser):
    def __init__(self): super().__init__(); self.value=None
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='meta' and attrs.get('name')=='workbench-token': self.value=attrs.get('content')

@unittest.skipUnless(os.environ.get('MINGXUE_REVIEW_LIVE_WORKBENCH')=='1', 'Live service checks are opt-in')
class LiveWorkbenchBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.token = None
        cls.observed = []
        status,headers,data = cls.request('/',auth=False)
        if status != 200: raise RuntimeError('Local workbench is unavailable')
        parser=_Token();parser.feed(data.decode('utf-8'))
        if not parser.value: raise RuntimeError('Local workbench did not provide its session token')
        cls.token=parser.value

    @classmethod
    def request(cls,path,*,method='GET',value=None,raw=None,auth=True,headers=None):
        chosen={'Host':'127.0.0.1:2544'}
        if auth: chosen['Authorization']='Bearer '+cls.token
        if value is not None: raw=json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8')
        if raw is not None: chosen['Content-Type']='application/json'
        chosen.update(headers or {})
        conn=http.client.HTTPConnection('127.0.0.1',2544,timeout=90)
        try:
            conn.request(method,path,body=raw,headers=chosen)
            response=conn.getresponse();data=response.read(13_000_000)
            return response.status,dict(response.getheaders()),data
        finally: conn.close()

    @classmethod
    def tearDownClass(cls):
        # Deliberately exclude homepage bytes and all request headers/tokens.
        if EVIDENCE:
            (EVIDENCE/'live-boundaries-observed.json').write_text(json.dumps({'cases':cls.observed},ensure_ascii=False,indent=2),encoding='utf-8')

    def test_host_origin_and_token(self):
        cases=[
            ('missing_token',{},False,401),
            ('wrong_token',{'Authorization':'Bearer review-invalid'},True,401),
            ('foreign_host',{'Host':'review.invalid:2544'},True,403),
            ('localhost_alias',{'Host':'localhost:2544'},True,403),
            ('wrong_port',{'Host':'127.0.0.1:2545'},True,403),
            ('foreign_origin',{'Origin':'http://review.invalid'},True,403),
            ('null_origin',{'Origin':'null'},True,403),
            ('same_origin',{'Origin':'http://127.0.0.1:2544'},True,200),
            ('local_nonbrowser',{},True,200)
        ]
        for name,headers,auth,expected in cases:
            with self.subTest(name=name):
                code,reply,data=self.request('/api/history',auth=auth,headers=headers)
                self.observed.append({'case':name,'status':code,'expected':expected})
                self.assertEqual(code,expected)
                self.assertNotIn('Access-Control-Allow-Origin',reply)

    def test_static_and_history_paths(self):
        cases=[('/../scripts/workbench.py',404),('/%2e%2e/scripts/workbench.py',404),('/scripts/workbench.py',404),
               ('/api/history/../outside',400),('/api/history/%2e%2e%2foutside',400),('/api/history/'+'z'*32,400)]
        for path,expected in cases:
            with self.subTest(path=path):
                code,headers,data=self.request(path)
                self.observed.append({'case':'contained_path','path':path,'status':code,'expected':expected})
                self.assertEqual(code,expected)

    def test_strict_json_and_no_unknown_output_option(self):
        cases=[('duplicate_key',b'{"system":"tarot","system":"iching","params":{}}',{},400),
               ('nonfinite',b'{"system":"tarot","params":{"seed":NaN}}',{},400),
               ('wrong_content_type',b'{}',{'Content-Type':'text/plain'},415),
               ('transfer_encoding',b'{}',{'Transfer-Encoding':'chunked'},415),
               ('oversize_declared',b'{}',{'Content-Length':'65537'},413),
               ('unknown_system',b'{"system":"__proto__","params":{}}',{},400)]
        for name,raw,headers,expected in cases:
            with self.subTest(name=name):
                code,reply,data=self.request('/api/calculate',method='POST',raw=raw,headers=headers)
                self.observed.append({'case':name,'status':code,'expected':expected})
                self.assertEqual(code,expected)
        output=str((EVIDENCE or Path(tempfile.gettempdir()))/'review-no-output.json')
        code,reply,data=self.request('/api/calculate',method='POST',value={'system':'numerology','params':{'date':'1990-05-02','output':output}})
        self.observed.append({'case':'unknown_output_option','status':code,'expected':400})
        self.assertEqual(code,400)
        self.assertFalse(Path(output).exists())

    def test_authenticated_record_roundtrip_and_actual_view(self):
        code,headers,raw=self.request('/api/calculate',method='POST',value={'system':'iching','params':{'method':'manual','lines':'6,7,8,9,7,8','najia':False,'question':'[边界审查] 实际互卦与历史回读'}})
        self.assertEqual(code,200)
        record=json.loads(raw)
        expected=[bool(int(c)) for c in record['result']['hexagrams']['nuclear']['bits_bottom_to_top']]
        actual=[line['yang'] for line in record['view']['data']['hexagrams'][2]['lines']]
        self.assertEqual(actual,expected)
        status,reply,loaded=self.request('/api/history/'+record['id'])
        self.assertEqual(status,200)
        self.assertEqual(json.loads(loaded),record)
        self.observed.append({'case':'real_iching_history_roundtrip','status':status,'native_nuclear_bits':record['result']['hexagrams']['nuclear']['bits_bottom_to_top'],'view_yang':actual})
        if EVIDENCE:
            (EVIDENCE/'real-iching-record.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__': unittest.main()
