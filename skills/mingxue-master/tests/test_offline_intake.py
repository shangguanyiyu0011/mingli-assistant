"""The shared standalone form preserves pending places and real photo bytes."""
import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zlib

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import offline_intake


def synthetic_png(color=18):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress((b'\0' + bytes([color, 52, 86]) * 2) * 2)) + chunk(b'IEND', b'')


class OfflineIntakeTests(unittest.TestCase):
    def test_standalone_skill_does_not_require_a_parent_plugin_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'mingxue-master'
            for name in ('ui/intake.html', 'ui/intake.css', 'ui/intake-draws.css', 'ui/intake.js', 'ui/intake-draws.js', 'ui/offline-intake.js', 'ui/i18n.js', 'ui/intake-locales.json', 'references/systems.json'):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((SKILL / name).read_bytes())
            with patch.object(offline_intake, 'ROOT', root), patch.object(offline_intake, 'art_bundle', return_value={}):
                self.assertIn('window.MINGXUE_OFFLINE=true', offline_intake.build_page())

    def test_export_uses_same_form_and_has_no_external_ui_or_private_data(self):
        with patch.object(offline_intake, 'art_bundle', return_value={}):
            page = offline_intake.build_page()
        self.assertNotIn('name="fill-mode"', page)
        self.assertNotIn('data-fill-detail', page)
        self.assertIn('data-photo-kind="${kind}"', page)
        self.assertIn('window.MINGXUE_OFFLINE=true', page)
        self.assertIn((SKILL / 'ui/intake.js').read_text(encoding='utf-8').strip(), page)
        self.assertNotRegex(page, r'<script[^>]+src=|<link[^>]+stylesheet')
        self.assertNotIn('workbench-token', page.split('<body>')[0])
        self.assertNotIn('逐字笔画', page)
        self.assertNotIn('各体系的补充说明', page)

    def test_form_behavior_checks(self):
        node = shutil.which('node')
        self.assertIsNotNone(node)
        run = subprocess.run([node, str(Path(__file__).with_name('test_intake_form.js'))], capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertGreaterEqual(json.loads(run.stdout)['passed'], 12)

    def test_actual_completed_draws_survive_offline_zip_with_photo_bytes(self):
        node = shutil.which('node')
        drawn = subprocess.run([node, str(Path(__file__).with_name('test_intake_draws.js'))], capture_output=True,
                               text=True, encoding='utf-8', timeout=30)
        self.assertEqual(drawn.returncode, 0, drawn.stderr)
        request = json.loads(drawn.stdout)['requests']['pair']
        form = subprocess.run([node, str(Path(__file__).with_name('test_intake_form.js'))], capture_output=True,
                              text=True, encoding='utf-8', timeout=20)
        self.assertEqual(form.returncode, 0, form.stderr)
        self_reports = json.loads(form.stdout)['wellbeingRequest']
        for index, person in enumerate(request['people']):
            person['person']['notes'] = self_reports['people'][index]['person']['notes']
        image = synthetic_png()
        script = r'''
const fs=require('node:fs'),vm=require('node:vm'),{webcrypto}=require('node:crypto');let saved;
const context={TextEncoder,Uint8Array,DataView,Blob,Response,crypto:webcrypto,atob,console,setTimeout,
 URL:{createObjectURL(blob){if(blob.type==='application/zip')saved=blob;return 'blob:fixture';},revokeObjectURL(){}},
 document:{body:{appendChild(){}},createElement(){return {click(){},remove(){}};}},addEventListener(){},OFFLINE_CATALOG:{systems:[]}};
context.window=context;vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),context);
(async()=>{
 const upload=await context.fetch('/api/photos',{body:JSON.stringify({person:'A',kind:'palm_left',name:'synthetic.png',mime:'image/png',data_base64:process.argv[2],include_in_report:false})});
 if(upload.status!==200)throw Error('photo failed');const photo=await upload.json();
 const request=JSON.parse(Buffer.from(process.argv[3],'base64').toString('utf8'));request.people[0].photos=[photo.ref];
 const sent=await context.fetch('/api/submit',{body:JSON.stringify(request)});if(sent.status!==200)throw Error('ZIP failed');
 console.log(JSON.stringify({request,zip:Buffer.from(await saved.arrayBuffer()).toString('base64')}));
})().catch(error=>{console.error(error);process.exitCode=1});
'''
        run = subprocess.run([node, '-e', script, str(SKILL / 'ui/offline-intake.js'),
                              base64.b64encode(image).decode('ascii'), base64.b64encode(json.dumps(request).encode()).decode('ascii')],
                             capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        saved = json.loads(run.stdout)
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(saved['zip']))) as archive:
            self.assertIsNone(archive.testzip())
            actual = json.loads(archive.read('request.json'))
            self.assertEqual(actual, saved['request'])
            self.assertEqual(actual['method_options'], request['method_options'])
            self.assertIn('本人自述（心理与近况｜综合了解）', actual['people'][0]['person']['notes'])
            self.assertIn('独处整理', actual['people'][0]['person']['notes'])
            self.assertNotIn('被理解', actual['people'][0]['person']['notes'])
            self.assertIn('被理解', actual['people'][1]['person']['notes'])
            self.assertNotIn('独处整理', actual['people'][1]['person']['notes'])
            manifest = json.loads(archive.read('photos.json'))
            self.assertEqual(archive.read(manifest['photos'][0]['relative_path']), image)
            self.assertFalse(manifest['photos'][0]['include_in_report'])

    def test_actual_form_self_reports_remain_personal_in_native_plan(self):
        import intake_flow
        import workflow
        run = subprocess.run([shutil.which('node'), str(Path(__file__).with_name('test_intake_form.js'))],
                             capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr)
        forms = json.loads(run.stdout)
        cases = [{'mode': 'pair', 'request': forms['wellbeingRequest']},
                 {'mode': 'single', 'request': forms['wellbeingSingleRequest']}, *forms['wellbeingMatrix']]
        self.assertEqual(len(forms['wellbeingMatrix']), 32)
        for case in cases:
            request = case['request']
            normalized = intake_flow.normalize_request(request, allow_unresolved_places=True)
            self.assertEqual([p['person']['notes'] for p in normalized['people']],
                             [p['person']['notes'] for p in request['people']])
            # Explicit fixture zones only: production place resolution remains unchanged.
            for person, zone, point in zip(request['people'], ('Asia/Shanghai', 'Europe/Berlin'),
                                           ((22.5431, 114.0579), (52.52, 13.405))):
                person['birth']['timezone'] = zone
                person['location'] = {'latitude': point[0], 'longitude': point[1]}
            request['preferences']['systems'] = ['numerology']
            planned = intake_flow.plan_request(request)
            self.assertEqual(len(planned['people']), len(request['people']), planned['questions'])
            for index, person in enumerate(planned['people']):
                flow = workflow.normalize_input(person['workflow_input'])
                self.assertEqual(flow['person']['notes'], request['people'][index]['person']['notes'])
                self.assertNotIn('心理与近况', json.dumps(flow['questionnaire'], ensure_ascii=False))
                self.assertLessEqual(len(flow['person']['notes']), 4000)
                self.assertIsNone(flow['birth']['time'])
            if case['mode'] == 'single':
                self.assertEqual(len(planned['people']), 1)
                self.assertNotIn('乙自己的说明', json.dumps(planned, ensure_ascii=False))
                self.assertNotIn('乙的原有补充', json.dumps(planned, ensure_ascii=False))

    def test_all_32_topic_people_combinations_keep_exact_self_reports_in_zip(self):
        node = shutil.which('node')
        form = subprocess.run([node, str(Path(__file__).with_name('test_intake_form.js'))], capture_output=True,
                              text=True, encoding='utf-8', timeout=20)
        self.assertEqual(form.returncode, 0, form.stderr)
        cases = json.loads(form.stdout)['wellbeingMatrix']
        script = r'''
const fs=require('node:fs'),vm=require('node:vm'),{webcrypto}=require('node:crypto');
const source=fs.readFileSync(process.argv[1],'utf8'),cases=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{const archives=[];for(const sample of cases){let saved;
 const context={TextEncoder,Uint8Array,DataView,Blob,Response,crypto:webcrypto,atob,console,setTimeout,
 URL:{createObjectURL(blob){if(blob.type==='application/zip')saved=blob;return 'blob:fixture';},revokeObjectURL(){}},
 document:{body:{appendChild(){}},createElement(){return {click(){},remove(){}};}},addEventListener(){},OFFLINE_CATALOG:{systems:[]}};
 context.window=context;vm.runInNewContext(source,context);
 const sent=await context.fetch('/api/submit',{body:JSON.stringify(sample.request)});if(sent.status!==200)throw Error('topic ZIP failed');
 archives.push({topic:sample.topic,mode:sample.mode,zip:Buffer.from(await saved.arrayBuffer()).toString('base64')});
 }console.log(JSON.stringify(archives));})().catch(error=>{console.error(error);process.exitCode=1});
'''
        run = subprocess.run([node, '-e', script, str(SKILL / 'ui/offline-intake.js')], input=json.dumps(cases),
                             capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        archives = json.loads(run.stdout)
        self.assertEqual(len(archives), 32)
        for sample, packed in zip(cases, archives):
            with self.subTest(topic=sample['topic'], mode=sample['mode']), zipfile.ZipFile(io.BytesIO(base64.b64decode(packed['zip']))) as archive:
                self.assertIsNone(archive.testzip())
                actual = json.loads(archive.read('request.json'))
                self.assertEqual(actual, sample['request'])
                self.assertEqual(len(actual['people']), 1 if sample['mode'] == 'single' else 2)
                if sample['mode'] == 'single':
                    self.assertNotIn('乙的原有补充', json.dumps(actual, ensure_ascii=False))

    def test_forged_five_card_lenormand_is_rejected_by_native_planner(self):
        import intake_flow
        request = {'mode': 'single', 'people': [{'person': {'name': '合成测试'},
                   'birth': {'date': '2000-08-16', 'time': None, 'calendar': 'solar', 'timezone': 'Asia/Shanghai'}}],
                   'preferences': {'systems': ['lenormand'], 'question': '怎样安排学习？', 'virtual_draws': False},
                   'method_options': {'lenormand': {'spread': 'five', 'cards': [1, 2, 3, 4, 5]}}}
        with self.assertRaises(ValueError):
            intake_flow.plan_request(request)

    def test_downloaded_zip_roundtrips_uploaded_photo_and_unresolved_place(self):
        image = synthetic_png()
        script = r'''
const fs=require('node:fs'),vm=require('node:vm'),{webcrypto}=require('node:crypto');
let saved;
const context={TextEncoder,Uint8Array,DataView,Blob,Response,crypto:webcrypto,atob,console,setTimeout,URL:{createObjectURL(blob){saved=blob;return 'blob:synthetic'},revokeObjectURL(){}},document:{body:{appendChild(){}},createElement(){return {click(){},remove(){}}}},addEventListener(){},OFFLINE_CATALOG:{systems:[]}};
context.window=context;
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),context);
(async()=>{
 const upload={person:'A',kind:'portrait',name:'synthetic.png',mime:'image/png',data_base64:process.argv[2],include_in_report:false};
 const added=await context.fetch('/api/photos',{body:JSON.stringify(upload)}),photo=await added.json();
 if(added.status!==200)throw Error(JSON.stringify(photo));
 const duplicate=await context.fetch('/api/photos',{body:JSON.stringify(upload)});
 if(duplicate.status!==400)throw Error('Duplicate photo was accepted');
 const removed=await context.fetch('/api/photos/remove',{body:JSON.stringify({id:photo.ref.id})});
 if(removed.status!==200)throw Error('Removal failed');
 const readded=await context.fetch('/api/photos',{body:JSON.stringify(upload)}),replacement=await readded.json();
 if(readded.status!==200||replacement.ref.id===photo.ref.id)throw Error('Reselect after removal failed');
 const request={mode:'single',people:[{person:{name:'合成测试'},birth:{date:'2000-08-16',calendar:'solar',time:null,shichen:'酉'},birthplace:'深圳市，广东省',photos:[replacement.ref]}],preferences:{systems:'all',cast_place:'Berlin, Germany',cast:{datetime_utc:'2026-07-01T23:30:00.123Z'}}};
 const sent=await context.fetch('/api/submit',{body:JSON.stringify(request)});
 if(sent.status!==200)throw Error('Download failed');
 const second=await context.fetch('/api/submit',{body:JSON.stringify(request)});
 if(second.status!==200)throw Error('Repeated current-state submission failed');
 console.log(Buffer.from(await saved.arrayBuffer()).toString('base64'));
})().catch(error=>{console.error(error);process.exitCode=1});
'''
        run = subprocess.run([shutil.which('node'), '-e', script, str(SKILL / 'ui/offline-intake.js'), base64.b64encode(image).decode('ascii')], capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr)
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(run.stdout))) as archive:
            self.assertIsNone(archive.testzip())
            request = json.loads(archive.read('request.json'))
            self.assertEqual(request['people'][0]['birthplace'], '深圳市，广东省')
            self.assertNotIn('timezone', request['people'][0]['birth'])
            self.assertIsNone(request['people'][0]['birth']['time'])
            self.assertEqual(request['people'][0]['birth']['shichen'], '酉')
            self.assertEqual(request['preferences']['cast']['datetime_utc'], '2026-07-01T23:30:00.123Z')
            manifest = json.loads(archive.read('photos.json'))
            photo = manifest['photos'][0]
            self.assertEqual(photo['kind'], 'portrait')
            self.assertEqual(photo['person'], 'A')
            self.assertFalse(photo['include_in_report'])
            self.assertFalse(photo['viewed'])
            self.assertEqual(photo['sha256'], hashlib.sha256(image).hexdigest())
            self.assertEqual(archive.read(photo['relative_path']), image)
            import intake_flow
            import photo_uploads
            normalized = intake_flow.normalize_request(request, allow_unresolved_places=True)
            with tempfile.TemporaryDirectory() as temporary:
                destination = Path(temporary).resolve() / manifest['owner_id']
                for name in archive.namelist():
                    self.assertFalse(Path(name).is_absolute())
                    self.assertNotIn('..', Path(name).parts)
                    target = destination / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(name))
                verified = photo_uploads.read_manifest(destination / 'photos.json', request=normalized)
                self.assertEqual(verified['photos'][0]['sha256'], photo['sha256'])

    def test_offline_recovery_concurrency_ownership_and_failed_download_retry(self):
        script = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),{webcrypto}=require('node:crypto');
let saved,failClick=true,next=0;const objects=new Map(),revoked=[];
const context={TextEncoder,Uint8Array,DataView,Blob,Response,crypto:{getRandomValues:a=>webcrypto.getRandomValues(a)},atob,console,setTimeout,
 URL:{createObjectURL(blob){const url='blob:synthetic-'+next++;objects.set(url,blob);if(blob.type==='application/zip')saved=blob;return url;},revokeObjectURL(url){revoked.push(url);}},
 document:{body:{appendChild(){}},createElement(){return {click(){if(failClick){failClick=false;throw Error('下载暂时未完成。');}},remove(){}};}},addEventListener(){},OFFLINE_CATALOG:{systems:[]}};
context.window=context;vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),context);
const send=(path,body)=>context.fetch(path,{body:JSON.stringify(body)});
(async()=>{
 const upload={person:'A',kind:'palm_left',name:'synthetic.png',mime:'image/png',data_base64:process.argv[2],include_in_report:false};
 assert.equal((await send('/api/photos',upload)).status,400);context.crypto=webcrypto;
 assert.equal((await send('/api/photos',{...upload,data_base64:'bad!'})).status,400);
 const concurrent=await Promise.all([send('/api/photos',upload),send('/api/photos',upload)]);assert.deepEqual(concurrent.map(r=>r.status).sort(),[200,400]);
 const a=await concurrent.find(r=>r.status===200).json();
 const b=await (await send('/api/photos',{...upload,person:'B',kind:'portrait',name:'other.png',data_base64:process.argv[3]})).json();
 const request={mode:'single',people:[{person:{name:'合成甲'},birth:{date:'2000-08-16',time:null,calendar:'solar'},birthplace:'深圳市，广东省',photos:[{...a.ref,include_in_report:true}]}],preferences:{systems:'all'}};
 const forged=JSON.parse(JSON.stringify(request));forged.people[0].photos=[b.ref];assert.equal((await send('/api/submit',forged)).status,400);
 assert.equal((await send('/api/submit',request)).status,400);assert.ok(context.photoUrl(a.ref.id));assert.ok(context.photoUrl(b.ref.id));
 assert.ok(revoked.some(url=>objects.get(url)?.type==='application/zip'));
 assert.equal((await send('/api/submit',request)).status,200);assert.equal((await send('/api/photos/remove',{id:a.ref.id})).status,200);assert.equal(context.photoUrl(a.ref.id),'');
 console.log(Buffer.from(await saved.arrayBuffer()).toString('base64'));
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        run = subprocess.run([shutil.which('node'), '-e', script, str(SKILL / 'ui/offline-intake.js'),
                              base64.b64encode(synthetic_png()).decode('ascii'), base64.b64encode(synthetic_png(99)).decode('ascii')],
                             capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr)
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(run.stdout))) as archive:
            self.assertIsNone(archive.testzip())
            request = json.loads(archive.read('request.json'))
            manifest = json.loads(archive.read('photos.json'))
            self.assertEqual(len(request['people']), 1)
            self.assertEqual(len(manifest['photos']), 1)
            self.assertEqual(manifest['photos'][0]['person'], 'A')
            self.assertTrue(manifest['photos'][0]['include_in_report'])
            self.assertEqual(archive.read(manifest['photos'][0]['relative_path']), synthetic_png())


if __name__ == '__main__':
    unittest.main(verbosity=2)
