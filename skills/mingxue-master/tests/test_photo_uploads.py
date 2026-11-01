"""Private upload/ownership, actual HTTP and no-view/no-calculation regressions."""
import base64
import copy
from contextlib import contextmanager
import hashlib
import http.client as http_client
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
import zlib

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get('MINGXUE_TEST_SKILL_ROOT') or HERE/'package/mingxue-master')
sys.path.insert(0,str(ROOT/'scripts'))
import agent_intake
import intake_flow
import photo_uploads as photos
import workbench


def png(color=0):
    def chunk(name,data):return struct.pack('>I',len(data))+name+data+struct.pack('>I',zlib.crc32(name+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',2,2,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\x00'+bytes([color,0,0])*2+b'\x00'+bytes([color,0,0])*2))+chunk(b'IEND',b'')


def upload(data=None,person='A',kind='palm_unknown'):
    return {'person':person,'kind':kind,'name':'合成测试.png','mime':'image/png','data_base64':base64.b64encode(data or png()).decode('ascii'),'include_in_report':False}


def request(pair=False):
    a={'person':{'name':'合成甲'},'birth':{'date':'2000-08-16','time':None,'calendar':'solar','timezone':'Asia/Shanghai'}}
    b={'person':{'name':'合成乙'},'birth':{'date':'2001-06-02','time':'09:00','calendar':'solar','timezone':'Asia/Shanghai'}}
    return {'mode':'pair' if pair else 'single','people':[a,b] if pair else [a],'preferences':{'systems':['bazi','names','palm','face'],'prepare_engines':False},'method_options':{}}


def http(base,path='/',data=None,token=None,headers=None):
    url=urlsplit(base);conn=http_client.HTTPConnection(url.hostname,url.port,timeout=20)
    h={'Origin':base}
    if token:h['Authorization']='Bearer '+token
    if data is not None:h['Content-Type']='application/json';data=json.dumps(data,ensure_ascii=False).encode('utf-8')
    h.update(headers or {})
    try:
        conn.request('POST' if data is not None else 'GET',path,body=data,headers=h)
        r=conn.getresponse();return r.status,r.read(),dict(r.getheaders())
    finally:conn.close()


@contextmanager
def server(directory):
    instance=workbench.Server(('127.0.0.1',0),workbench.Records(directory,agent_mode=True),agent_mode=True)
    t=threading.Thread(target=instance.serve_forever,kwargs={'poll_interval':0.02},daemon=True);t.start()
    try:yield instance
    finally:
        instance.collection_cancel.set();instance.shutdown();t.join(timeout=3);instance.server_close()


class PhotoSessionTests(unittest.TestCase):
    def test_actual_container_metadata_not_viewing(self):
        with tempfile.TemporaryDirectory() as t:
            session=photos.PhotoSession(Path(t)/'.photo-sessions')
            value=session.upload(upload())
            item=value['photo'];self.assertRegex(item['id'],r'^[a-f0-9]{32}$')
            self.assertEqual(item['sha256'],hashlib.sha256(png()).hexdigest())
            self.assertEqual((item['width'],item['height']),(2,2))
            self.assertFalse(item['viewed']);self.assertFalse(item['pixel_decode_performed'])
            self.assertNotIn('relative_path',item)
            self.assertEqual(session.preview(item['id']),(png(),'image/png'))
            session.cleanup();self.assertFalse(session.root.exists())

    def test_forged_mime_svg_bad_crc_and_paths_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            session=photos.PhotoSession(Path(t)/'.photo-sessions')
            cases=[{**upload(), 'mime':'image/jpeg'},upload(b'<svg/>'),upload(png()[:-1]+b'x'),{**upload(),'path':'C:/secret'}, {**upload(),'name':'../x.png'}, {**upload(),'data_base64':'!'}, {**upload(),'name':chr(0xd800)+'.png'}]
            for case in cases:
                with self.subTest(case=list(case)):
                    with self.assertRaises(ValueError):session.upload(case)
                    self.assertFalse(session.entries)
            session.cleanup()

    def test_limits_duplicate_and_removal_release_quota(self):
        with tempfile.TemporaryDirectory() as t:
            session=photos.PhotoSession(Path(t)/'.photo-sessions');value=session.upload(upload())
            with self.assertRaises(ValueError):session.upload(upload(person='B'))
            with patch.object(photos,'MAX_PHOTOS',1):
                with self.assertRaises(ValueError):session.upload(upload(png(2)))
            with patch.object(photos,'MAX_TOTAL_BYTES',len(png())+len(png(2))-1):
                with self.assertRaises(ValueError):session.upload(upload(png(2)))
            with self.assertRaises(ValueError):session.upload({**upload(),'data_base64':'A'*(4*((photos.MAX_PHOTO_BYTES+2)//3)+4)})
            session.remove(value['photo']['id'])
            with self.assertRaises(ValueError):session.preview(value['photo']['id'])
            new=session.upload(upload());self.assertNotEqual(value['photo']['id'],new['photo']['id'])
            session.cleanup()

    def test_cross_person_cross_session_old_id_and_duplicate_refs(self):
        with tempfile.TemporaryDirectory() as t:
            first=photos.PhotoSession(Path(t)/'.photo-sessions');second=photos.PhotoSession(Path(t)/'.photo-sessions')
            value=first.upload(upload());native=request(True)
            native['people'][1]['photos']=[value['ref']]
            with self.assertRaises(ValueError):first.snapshot(native)
            native['people'][1].pop('photos');native['people'][0]['photos']=[value['ref']]
            with self.assertRaises(ValueError):second.snapshot(native)
            wrong=copy.deepcopy(native);wrong['people'][0]['photos'][0]['sha256']='0'*64
            with self.assertRaises(ValueError):first.snapshot(wrong)
            dup=copy.deepcopy(native);dup['people'][1]['photos']=[value['ref']]
            with self.assertRaises(ValueError):intake_flow.normalize_request(dup)
            first.remove(value['photo']['id'])
            with self.assertRaises(ValueError):first.snapshot(native)
            first.cleanup();second.cleanup()

    def test_collect_persists_hash_bound_copy_without_blob_or_public_paths(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);session=photos.PhotoSession(root/'.photo-sessions');item=session.upload(upload())
            native=request();native['people'][0]['photos']=[{**item['ref'],'include_in_report':True}]
            snap=session.snapshot(native)
            with patch('workflow.run_project',side_effect=AssertionError('no calculation')):
                result=agent_intake.collect_request(root/'collected',native,photo_session=snap)
            self.assertEqual(result['status'],'submitted',result)
            path=Path(result['photo_manifest']);manifest=photos.read_manifest(path,native)
            self.assertTrue(manifest['photos'][0]['include_in_report'])
            self.assertEqual(path.parent,Path(result['request_file']).parent)
            saved=json.loads(Path(result['request_file']).read_text(encoding='utf-8'))
            self.assertNotIn('data_base64',json.dumps(saved));self.assertNotIn(str(root),json.dumps(saved))
            handoff=photos.photo_handoff(path,native);file=Path(handoff['photos'][0]['file'])
            session.cleanup();self.assertEqual(file.read_bytes(),png())
            file.write_bytes(png(3))
            with self.assertRaises(ValueError):photos.read_manifest(path,native)

    def test_missing_photo_and_path_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);session=photos.PhotoSession(root/'.photo-sessions');item=session.upload(upload());native=request();native['people'][0]['photos']=[item['ref']]
            result=agent_intake.collect_request(root/'collected',native,photo_session=session.snapshot(native));path=Path(result['photo_manifest'])
            raw=json.loads(path.read_text(encoding='utf-8'));original=copy.deepcopy(raw);raw['photos'][0]['relative_path']='../escape.png';path.write_text(json.dumps(raw),encoding='utf-8')
            with self.assertRaises(ValueError):photos.read_manifest(path,native)
            path.write_text(json.dumps(original),encoding='utf-8');(path.parent/original['photos'][0]['relative_path']).unlink()
            with self.assertRaises(ValueError):photos.read_manifest(path,native)
            session.cleanup()

    def test_trusted_actual_update_keeps_A_palm_and_B_face_independent(self):
        import agent_updates
        import workflow
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);session=photos.PhotoSession(root/'.photo-sessions');a=session.upload(upload());b=session.upload(upload(png(2),'B','portrait'))
            native=request(True);native['preferences']['systems']=['bazi','palm','face']
            native['people'][0]['photos']=[a['ref']];native['people'][1]['photos']=[b['ref']]
            collected=agent_intake.collect_request(root/'collected',native,photo_session=session.snapshot(native))
            created=intake_flow.submit(root/'reports',native,photo_manifest=collected['photo_manifest']);self.assertIn(created['status'],('ready','partial'),created)
            job=root/'reports'/created['job_id'];original=(job/'submitted-input.json').read_bytes()
            palm={'schema_version':2,'source':'agent_viewed','photo_refs':[{'id':a['ref']['id'],'sha256':a['ref']['sha256']}],'observations':{'hand':'unknown','features':[{'region':'palm_outline','shape':'curved','visibility':'clear'}]},'note':'只使用自造图验证数据归属'}
            response=agent_updates.update_job(str(job),{'observations':{'palm':palm}},person='A');self.assertTrue(response['request_committed'],response)
            face={'schema_version':2,'source':'user_reported','photo_refs':[{'id':b['ref']['id'],'sha256':b['ref']['sha256']}],'observations':{'features':[{'region':'face_outline','shape':'angular','visibility':'clear'}]}}
            response=agent_updates.update_job(str(job),{'observations':{'face':face}},person='B');self.assertTrue(response['request_committed'],response)
            def payload(role,system):
                project=job/('project-'+role);state=workflow.project_status(project);return json.loads((project/state['components'][system]['file']).read_text(encoding='utf-8'))
            pa=payload('a','palm');fb=payload('b','face')
            self.assertEqual(pa['status'],'intake_only');self.assertEqual(pa['observation_status'],'agent_observed');self.assertEqual(pa['photo_refs'][0]['id'],a['ref']['id'])
            self.assertEqual(fb['observation_status'],'user_reported');self.assertEqual(fb['photo_refs'][0]['id'],b['ref']['id'])
            self.assertEqual((job/'submitted-input.json').read_bytes(),original)
            bad=copy.deepcopy(palm);bad['photo_refs']=[{'id':b['ref']['id'],'sha256':b['ref']['sha256']}]
            with self.assertRaises(ValueError):agent_updates.update_job(str(job),{'observations':{'palm':bad}},person='A')
            self.assertEqual(payload('a','palm')['photo_refs'][0]['id'],a['ref']['id'])
            session.cleanup()

    def test_per_person_observations_require_trusted_view_and_matching_kind(self):
        with tempfile.TemporaryDirectory() as t:
            session=photos.PhotoSession(Path(t)/'.photo-sessions');a=session.upload(upload());b=session.upload(upload(png(2),'B','portrait'))
            native=request(True)
            obs={'schema_version':2,'source':'agent_viewed','photo_refs':[{'id':a['ref']['id'],'sha256':a['ref']['sha256']}],'observations':{'hand':'unknown','features':[{'region':'palm_outline','shape':'curved','visibility':'clear'}]},'note':'合成图测试描述，不推断人物'}
            native['people'][0].update(photos=[a['ref']],observations={'palm':obs});native['people'][1]['photos']=[b['ref']]
            with self.assertRaises(ValueError):intake_flow.normalize_request(native)
            normalized=intake_flow.normalize_request(native,allow_agent_observations=True)
            plan=intake_flow.plan_request(normalized,allow_agent_observations=True)
            self.assertEqual(plan['people'][0]['inline_observations']['palm']['source'],'agent_viewed')
            self.assertFalse(plan['people'][1]['inline_observations'])
            self.assertIn('face',plan['people'][1]['workflow_input']['deferred'])
            wrong=copy.deepcopy(native);wrong['people'][1]['observations']={'face':obs}
            with self.assertRaises(ValueError):intake_flow.normalize_request(wrong,allow_agent_observations=True)
            global_obs=copy.deepcopy(native);global_obs['method_options']={'palm':{'observations':{'features':[]}}}
            with self.assertRaises(ValueError):intake_flow.normalize_request(global_obs,allow_agent_observations=True)
            session.cleanup()

    def test_no_name_no_photo_unknown_time_only_deferred_and_no_noon(self):
        native=request();normalized=intake_flow.normalize_request(native);plan=intake_flow.plan_request(native)
        self.assertNotIn('name',normalized['people'][0]);self.assertNotIn('photos',normalized['people'][0])
        flow=plan['people'][0]['workflow_input'];self.assertIsNone(flow['birth']['time']);self.assertIn('bazi',flow['systems']);self.assertNotIn('bazi',flow['deferred'])
        self.assertEqual(set(flow['deferred']),{'names','palm','face'})


class PhotoHTTPTests(unittest.TestCase):
    def test_all_server_modes_reject_non_loopback_bind(self):
        with tempfile.TemporaryDirectory() as t:
            for agent in (True,False):
                with self.assertRaises(ValueError):workbench.Server(('0.0.0.0',0),workbench.Records(Path(t)/('a' if agent else 'b'),agent_mode=agent),agent_mode=agent)

    def test_actual_http_auth_preview_ownership_submit_private_handoff(self):
        with tempfile.TemporaryDirectory() as t,server(Path(t)/'data') as s:
            status,raw,headers=http(s.base);self.assertEqual(status,200)
            token=re.search(rb'workbench-token" content="([^"]+)',raw)[1].decode()
            cookie=headers['Set-Cookie'].split(';')[0]
            self.assertEqual(http(s.base,'/api/photos',upload())[0],401)
            self.assertEqual(http(s.base,'/api/photos',upload(),token,{'Origin':'https://invalid.example'})[0],403)
            self.assertEqual(http(s.base,'/api/photos',upload(),token,{'Host':'invalid.example'})[0],403)
            status,raw,_=http(s.base,'/api/photos',upload(),token);self.assertEqual(status,200,raw)
            value=json.loads(raw);self.assertNotIn(str(Path(t)),raw.decode())
            preview=value['photo']['preview_url']
            self.assertEqual(http(s.base,preview)[0],401)
            self.assertEqual(http(s.base,preview,headers={'Cookie':cookie})[:2],(200,png()))
            self.assertEqual(http(s.base,preview,headers={'Cookie':cookie,'Origin':'https://invalid.example'})[0],403)
            self.assertEqual(http(s.base,'/files/'+value['photo']['id']+'/photo.png',token=token)[0],404)
            native=request(True);native['people'][1]['photos']=[value['ref']]
            self.assertEqual(http(s.base,'/api/submit',native,token)[0],400)
            self.assertFalse(s.submission_event.is_set())
            native['people'][1].pop('photos');native['people'][0]['photos']=[value['ref']]
            status,raw,_=http(s.base,'/api/submit',native,token);self.assertEqual(status,200,raw)
            public=json.loads(raw);self.assertEqual(public['status'],'submitted');self.assertNotIn('request_file',public);self.assertNotIn('photo_manifest',public)
            self.assertNotIn(str(Path(t)),raw.decode())
            self.assertTrue(s.submission_event.wait(3))
            self.assertIsNotNone(s.submission_payload['photo_manifest']);self.assertFalse(s.photos.root.exists())
            self.assertEqual(http(s.base,preview,headers={'Cookie':cookie})[0],410)

    def test_upload_body_above_native_request_limit_and_malformed_ref(self):
        def chunk(name,data):return struct.pack('>I',len(data))+name+data+struct.pack('>I',zlib.crc32(name+data)&0xffffffff)
        base=png();large=base[:33]+chunk(b'tEXt',b'note\0'+b'x'*300000)+base[33:]
        with tempfile.TemporaryDirectory() as t,server(Path(t)/'data') as s:
            status,raw,_=http(s.base,'/api/photos',upload(large),s.token);self.assertEqual(status,200,raw);item=json.loads(raw)
            self.assertEqual(item['photo']['bytes'],len(large))
            native=request();native['people'][0]['photos']=[{**item['ref'],'kind':[]}]
            self.assertEqual(http(s.base,'/api/submit',native,s.token)[0],400)
            self.assertFalse(s.submission_event.is_set())

    def test_real_cli_success_has_trusted_manifest_stdout_only(self):
        with tempfile.TemporaryDirectory() as t:
            cmd=[sys.executable,'-X','utf8','-B',str(ROOT/'scripts/agent_intake.py'),'--data-dir',str(Path(t)/'data'),'--timeout','20']
            child=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
            try:
                ready=json.loads(child.stdout.readline());_,raw,_=http(ready['url']);token=re.search(rb'workbench-token" content="([^"]+)',raw)[1].decode()
                items=[]
                for value in (upload(),upload(png(4),'B','portrait')):
                    status,raw,_=http(ready['url'],'/api/photos',value,token);self.assertEqual(status,200,raw);items.append(json.loads(raw))
                native=request(True)
                for person,item in zip(native['people'],items):person['photos']=[item['ref']]
                code,raw,_=http(ready['url'],'/api/submit',native,token);self.assertEqual(code,200,raw);self.assertNotIn(b'photo_manifest',raw)
                stdout,stderr=child.communicate(timeout=10);result=json.loads(stdout.strip());self.assertEqual(child.returncode,0,(stdout,stderr))
                path=Path(result['photo_manifest']);self.assertTrue(path.is_absolute());self.assertTrue(path.is_file())
                manifest=photos.read_manifest(path,native);self.assertEqual([p['person'] for p in manifest['photos']],['A','B'])
                self.assertFalse(list((Path(t)/'data/.photo-sessions').iterdir()))
            finally:
                if child.poll() is None:child.kill();child.communicate()

    def test_actual_remove_and_cancel_clean_only_this_session(self):
        with tempfile.TemporaryDirectory() as t:
            directory=Path(t)/'data';other=directory/'.photo-sessions'/'other-task';other.mkdir(parents=True);keep=other/'keep';keep.write_text('keep')
            with server(directory) as s:
                _,raw,_=http(s.base,'/api/photos',upload(),s.token);item=json.loads(raw)
                self.assertEqual(http(s.base,'/api/photos/remove',{'id':item['photo']['id']},s.token)[0],200)
                self.assertEqual(http(s.base,item['photo']['preview_url'],token=s.token)[0],404)
                _,raw,_=http(s.base,'/api/photos',upload(png(4)),s.token);item=json.loads(raw)
                self.assertEqual(http(s.base,'/api/cancel',{},s.token)[0],200)
                self.assertTrue(s.submission_event.wait(3))
                self.assertFalse(s.photos.root.exists());self.assertEqual(keep.read_text(),'keep')
                self.assertFalse(list((directory/'collected').glob('*')) if (directory/'collected').exists() else [])
            self.assertEqual(keep.read_text(),'keep')

    def test_real_cli_timeout_removes_staged_files(self):
        with tempfile.TemporaryDirectory() as t:
            cmd=[sys.executable,'-X','utf8','-B',str(ROOT/'scripts/agent_intake.py'),'--data-dir',str(Path(t)/'data'),'--timeout','2']
            child=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
            try:
                ready=json.loads(child.stdout.readline());_,raw,_=http(ready['url']);token=re.search(rb'workbench-token" content="([^"]+)',raw)[1].decode()
                self.assertEqual(http(ready['url'],'/api/photos',upload(),token)[0],200)
                stdout,stderr=child.communicate(timeout=10);result=json.loads(stdout.strip());self.assertEqual(result['status'],'timeout',(stdout,stderr))
                self.assertEqual(child.returncode,3)
                sessions=Path(t)/'data/.photo-sessions';self.assertFalse(list(sessions.iterdir()))
            finally:
                if child.poll() is None:child.kill();child.communicate()

    def test_reserved_collector_rollback_preserves_other_task(self):
        with tempfile.TemporaryDirectory() as t:
            owner='a'*32;root=Path(t)/'collected';reserved=photos.reserve_collection(root,owner)
            other=root/('b'*32);other.mkdir();(other/'request.json').write_text('original')
            (reserved/'private-photos').mkdir();(reserved/'private-photos'/('c'*32+'.png')).write_bytes(png())
            (reserved/'request.json').write_text('partial')
            photos.discard_reserved(reserved,owner);self.assertFalse(reserved.exists());self.assertEqual((other/'request.json').read_text(),'original')


if __name__=='__main__':unittest.main()
