"""Run UI interaction invariants and validate exact native handoff data."""
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import unittest

HERE=Path(__file__).resolve().parents[1]
SKILL=Path(os.environ['MINGXUE_TEST_SKILL_ROOT']).resolve() if os.environ.get('MINGXUE_TEST_SKILL_ROOT') else (
    HERE if (HERE/'scripts/intake_flow.py').is_file() else HERE/'package/mingxue-master')
sys.dont_write_bytecode=True
sys.path.insert(0,str(SKILL/'scripts'))
import intake_flow
import symbolic
import oracles
import iching
import classic_oracles


class InteractiveDrawTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node=shutil.which('node')
        if not node:
            raise RuntimeError('Node is required to test the independent browser draw component')
        environment={**os.environ,'MINGXUE_TEST_SKILL_ROOT':str(SKILL)}
        process=subprocess.run([node,str(Path(__file__).with_suffix('.js'))],capture_output=True,text=True,encoding='utf-8',env=environment,timeout=30)
        if process.returncode:
            raise AssertionError(process.stderr or process.stdout)
        cls.data=json.loads(process.stdout)

    def test_ui_randomness_uniqueness_completeness_and_conflict_invariants(self):
        self.assertGreaterEqual(self.data['passed'],16)

    def test_all_78_tarot_ids_and_all_36_lenormand_cards_match_actual_native_catalogs(self):
        native=[{key:row[key] for key in ('id','name','arcana')} for row in symbolic.build_deck()]
        actual=[{key:row[key] for key in ('id','name','arcana')} for row in self.data['catalog']['tarot']]
        self.assertEqual(actual,native)
        self.assertEqual(len({row['id'] for row in actual}),78)
        self.assertEqual([{key:row[key] for key in ('id','number','name')} for row in self.data['catalog']['lenormand']],
                         [{key:row[key] for key in ('id','number','name')} for row in oracles.LENORMAND_CARDS])
        self.assertEqual({key:value[1] for key,value in self.data['catalog']['tarotSpreads'].items()},
                         {key:len(value[1]) for key,value in symbolic.SPREADS.items()})

    def test_pair_and_single_handoff_plan_as_actual_manual_data_without_seed(self):
        for mode,request in self.data['requests'].items():
            with self.subTest(mode=mode):
                plan=intake_flow.plan_request(request)
                self.assertFalse(plan['request']['preferences']['virtual_draws'])
                for person in plan['people']:
                    self.assertFalse(person['workflow_input']['deferred'])
                for options in request['method_options'].values():
                    self.assertNotIn('seed',options)
                self.assertEqual(request['method_options']['iching']['lines'],request['method_options']['yilin']['lines'])
                self.assertEqual(len(request['method_options']['lenormand']['cards']),36)
                self.assertEqual(len(set(request['method_options']['lenormand']['cards'])),36)
                self.assertLessEqual(len(request['preferences']['answers']['本次亲手抽取说明']),20)

    def test_native_manual_calculators_read_exact_card_coin_chess_and_mother_results(self):
        data=self.data['requests']['pair']['method_options']
        tarot=symbolic.tarot(data['tarot']['spread'],cards=','.join(data['tarot']['cards']),question=data['tarot']['question'])
        self.assertEqual([card['id']+':'+card['orientation'] for card in tarot['cards']],data['tarot']['cards'])
        coins=iching.build_result(data['iching']['lines'])
        self.assertEqual([row['value'] for row in coins['lines_bottom_to_top']],data['iching']['lines'])
        chess=classic_oracles.calculate('lingqijing',data['lingqijing'])
        self.assertEqual(chess['figure']['counts'],data['lingqijing']['counts'])
        oracle=classic_oracles.calculate('yilin',data['yilin'])
        self.assertEqual(oracle['hexagrams']['base']['number'],coins['hexagrams']['base']['number'])
        self.assertEqual(set(oracles.derive_shield(data['geomancy']['mothers'])),set(oracles.ROLE_IDS))

    def test_all_114_actual_image_windows_match_real_png_dimensions(self):
        self.assertEqual(len(self.data['artBindings']),114)
        seen=set()
        for binding in self.data['artBindings']:
            image=SKILL/'assets/art'/Path(binding['src']).name
            raw=image.read_bytes()[:24]
            self.assertEqual(raw[:8],b'\x89PNG\r\n\x1a\n')
            width,height=struct.unpack('>II',raw[16:24])
            self.assertEqual((width,height),(binding['assetWidth'],binding['assetHeight']))
            box=binding['box'];self.assertGreater(box['width'],0);self.assertGreater(box['height'],0)
            self.assertLessEqual(box['x']+box['width'],width+1e-7)
            self.assertLessEqual(box['y']+box['height'],height+1e-7)
            signature=(binding['src'],box['x'],box['y'],box['width'],box['height'])
            self.assertNotIn(signature,seen);seen.add(signature)


if __name__=='__main__':
    unittest.main(verbosity=2)
