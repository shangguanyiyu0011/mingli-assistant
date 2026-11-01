"""Actual form -> real interactive state -> repeated offline ZIP -> native intake."""
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

SKILL=Path(os.environ.get('MINGXUE_TEST_SKILL_ROOT',Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(SKILL/'scripts'))
import intake_flow
import photo_uploads
import symbolic
import iching


class RepeatedExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run=subprocess.run([shutil.which('node'),str(Path(__file__).with_suffix('.js'))],capture_output=True,text=True,encoding='utf-8',timeout=30)
        if run.returncode:raise AssertionError(run.stderr)
        cls.data=json.loads(run.stdout)

    def test_all_four_language_current_snapshots_keep_first_zip_immutable(self):
        self.assertEqual(self.data['passed'],6)
        self.assertEqual({row['language'] for row in self.data['matrix']},{'zh-CN','en','ja','ko'})
        for row in self.data['matrix']:
            with self.subTest(language=row['language']):
                first=base64.b64decode(row['first_zip']);current=base64.b64decode(row['current_zip'])
                self.assertEqual(hashlib.sha256(first).hexdigest(),row['first_sha256'])
                self.assertEqual(hashlib.sha256(current).hexdigest(),row['current_sha256'])
                self.assertNotEqual(first,current)
                with zipfile.ZipFile(io.BytesIO(first)) as archive:
                    self.assertIsNone(archive.testzip());self.assertEqual(archive.namelist(),['request.json'])
                    self.assertEqual(json.loads(archive.read('request.json')),row['first'])
                with zipfile.ZipFile(io.BytesIO(current)) as archive:
                    self.assertIsNone(archive.testzip());self.assertEqual(json.loads(archive.read('request.json')),row['current'])
                self.assertTrue(row['random_unchanged'])
                self.assertEqual(row['cleared']['method_options'],row['current']['method_options'])
                self.assertNotIn('photos',row['cleared']['people'][0])
                self.assertNotIn('notes',row['cleared']['people'][0]['person'])

    def test_actual_photo_bytes_and_owner_manifest_survive_second_download(self):
        for row in self.data['matrix']:
            request=row['current'];normalized=intake_flow.normalize_request(request,allow_unresolved_places=True)
            with self.subTest(language=row['language']),zipfile.ZipFile(io.BytesIO(base64.b64decode(row['current_zip']))) as archive,tempfile.TemporaryDirectory() as temporary:
                manifest=json.loads(archive.read('photos.json'));destination=Path(temporary).resolve()/manifest['owner_id'];destination.mkdir()
                for filename in archive.namelist():
                    self.assertFalse(Path(filename).is_absolute());self.assertNotIn('..',Path(filename).parts)
                    target=destination/filename;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(filename))
                actual=photo_uploads.read_manifest(destination/'photos.json',request=normalized)
                self.assertEqual(len(actual['photos']),1);photo=actual['photos'][0]
                self.assertEqual(photo['person'],'A');self.assertFalse(photo['include_in_report'])
                self.assertEqual(hashlib.sha256(archive.read(photo['relative_path'])).hexdigest(),photo['sha256'])

    def test_manual_results_and_self_report_route_through_native_planner_without_redraw(self):
        for row in self.data['matrix']:
            with self.subTest(language=row['language']):
                request=copy.deepcopy(row['current']);manual=request['method_options']
                self.assertEqual(len(manual['tarot']['cards']),3);self.assertEqual(len(manual['iching']['lines']),6)
                self.assertEqual(manual['iching']['lines'],manual['yilin']['lines'])
                result=symbolic.tarot(manual['tarot']['spread'],cards=','.join(manual['tarot']['cards']),question=manual['tarot']['question'])
                self.assertEqual([c['id']+':'+c['orientation'] for c in result['cards']],manual['tarot']['cards'])
                lines=iching.build_result(manual['iching']['lines'])
                self.assertEqual([line['value'] for line in lines['lines_bottom_to_top']],manual['iching']['lines'])
                request['people'][0]['birth']['timezone']='Asia/Shanghai';request['people'][0]['location']={'latitude':22.5431,'longitude':114.0579}
                request['preferences'].pop('cast_place',None)
                request['preferences']['cast']={'date':'2026-11-01','time':'08:00','timezone':'Asia/Shanghai','latitude':22.5431,'longitude':114.0579}
                planned=intake_flow.plan_request(request)
                self.assertEqual(len(planned['people']),1,planned['questions'])
                flow=planned['people'][0]['workflow_input']
                self.assertEqual(flow['person']['notes'],row['current']['people'][0]['person']['notes'])
                normalized_manual=copy.deepcopy(manual);normalized_manual['tarot']['cards']=','.join(manual['tarot']['cards'])
                self.assertEqual(planned['request']['method_options'],normalized_manual)
                self.assertTrue(planned['request']['preferences']['virtual_draws'])


if __name__=='__main__':unittest.main()
