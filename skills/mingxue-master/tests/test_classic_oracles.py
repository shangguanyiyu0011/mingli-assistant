"""Complete original-text indexes and explicit casting/lookup contracts."""
from collections import Counter
import copy
import hashlib
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get('MINGXUE_TEST_SKILL_ROOT') or (HERE/'package/mingxue-master' if (HERE/'package/mingxue-master').is_dir() else HERE))
sys.dont_write_bytecode = True
sys.path.insert(0,str(SKILL/'scripts'))
import classic_oracles as classic
import iching


class CompleteClassicalTextTests(unittest.TestCase):
    def test_yilin_has_all_4096_unique_nonempty_primary_texts(self):
        data,index=classic._load('yilin')
        self.assertEqual(len(data['entries']),4096)
        self.assertEqual(set(index),set(itertools.product(range(1,65),repeat=2)))
        self.assertTrue(all(len(entry['text'])>=8 for entry in data['entries']))
        self.assertEqual(index[(1,2)]['text'],'招殃來螫害我邦國病傷手足不得安息')
        self.assertEqual(index[(64,64)]['text'],'志慢未習單酒糗脯數至神前欲求所願反得大患')

    def test_lingqijing_has_all_125_count_shapes_and_zero_case(self):
        data,index=classic._load('lingqijing')
        self.assertEqual(len(data['entries']),125)
        self.assertEqual(set(index),set(itertools.product(range(5),repeat=3)))
        self.assertEqual({entry['number'] for entry in data['entries']},set(range(1,126)))
        for counts in itertools.product(range(5),repeat=3):
            result=classic.calculate('lingqijing',{'method':'counts','counts':list(counts)})
            self.assertEqual(result['status'],'calculated')
            self.assertEqual(result['figure']['counts'],list(counts))
            self.assertTrue(result['oracle']['text'])
        self.assertEqual(index[(1,1,1)]['name'],'大通')
        self.assertEqual(index[(4,4,4)]['number'],64)
        self.assertEqual(index[(0,0,0)]['number'],125)
        self.assertEqual(index[(0,0,0)]['text'],'隂鏝無兆状未形動進而有悔退保其真')

    def test_edition_anomalies_are_explicit_and_commentary_is_separate(self):
        y=classic.calculate('yilin',{'base':52,'changed':9})['oracle']
        self.assertEqual(y['source_label'],'小過')
        self.assertTrue(y['editorial_notes'])
        l=classic.calculate('lingqijing',{'counts':[0,1,0]})['oracle']
        self.assertEqual(l['number'],117)
        self.assertEqual(l['source_number'],'十七')
        self.assertTrue(l['editorial_notes'])
        corrected_boundary=classic.calculate('lingqijing',{'counts':[0,4,0]})['oracle']
        self.assertEqual(corrected_boundary['text'],'鬼氣未盛厲毒未形保慎性命門戸安寕')
        self.assertTrue(corrected_boundary['traditional_commentary'].startswith('顔日'))
        note=classic.calculate('lingqijing',{'counts':[3,0,4]})['oracle']
        self.assertIn('缺',note['commentary_notes'])

    def test_packaged_data_excludes_navigation_translations_and_source_advertising(self):
        for system in ('yilin','lingqijing'):
            text=(classic.DATA_DIR/(system+'.json')).read_text(encoding='utf-8')
            for bad in ('mw-parser-output','維基文庫','维基文库','导航','github.com','creativecommons','<script','捐款','点击关注'):
                self.assertNotIn(bad,text)
            self.assertEqual(hashlib.sha256((classic.DATA_DIR/(system+'.json')).read_bytes()).hexdigest(),classic.DATA_HASHES[system])

    def test_integrity_check_refuses_modified_data_even_after_index_cached(self):
        classic.probe()
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)
            raw=(classic.DATA_DIR/'yilin.json').read_bytes()
            (target/'yilin.json').write_bytes(raw+b' ')
            with patch.object(classic,'DATA_DIR',target), self.assertRaises(classic.OracleError):
                classic.calculate('yilin',{'base':1,'changed':1})

    def test_returned_entry_cannot_mutate_shared_text(self):
        first=classic.calculate('yilin',{'base':1,'changed':2})
        first['oracle']['text']='changed by caller'
        second=classic.calculate('yilin',{'base':1,'changed':2})
        self.assertNotEqual(first['oracle']['text'],second['oracle']['text'])


class YilinCastingTests(unittest.TestCase):
    def test_manual_pair_is_a_lookup_without_invented_coin_values(self):
        result=classic.calculate('yilin',{'method':'pair','base':1,'changed':2})
        self.assertEqual(result['hexagrams']['base']['lines_bottom_to_top'],[1]*6)
        self.assertEqual(result['hexagrams']['changed']['lines_bottom_to_top'],[0]*6)
        self.assertIsNone(result['line_values_bottom_to_top'])
        self.assertNotIn('moving_positions',result)
        self.assertNotIn('seed',result['cast_record'])

    def test_extreme_and_unchanged_six_lines_select_correct_grid_cells(self):
        for values,expected in (([9]*6,(1,2)),([6]*6,(2,1)),([7]*6,(1,1)),([8]*6,(2,2))):
            with self.subTest(values=values):
                result=classic.calculate('yilin',{'method':'lines','lines':values})
                self.assertEqual((result['oracle']['base'],result['oracle']['changed']),expected)
                self.assertEqual(result['moving_positions'],list(range(1,7)) if values[0] in (6,9) else [])

    def test_successful_iching_payload_is_recomputed_and_source_is_hashed(self):
        source=iching.build_result([9,7,8,6,7,8],question='synthetic')
        result=classic.calculate('yilin',{'method':'iching','iching_result':source})
        self.assertEqual(result['hexagrams']['base']['number'],source['hexagrams']['base']['number'])
        self.assertEqual(result['hexagrams']['changed']['number'],source['hexagrams']['changed']['number'])
        self.assertEqual(result['cast_record']['source_result_sha256'],hashlib.sha256(json.dumps(source,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest())
        corrupt=copy.deepcopy(source)
        corrupt['hexagrams']['changed']['number']=65
        with self.assertRaises(classic.OracleError):
            classic.calculate('yilin',{'method':'iching','iching_result':corrupt})
        for wrong in ({'payload':source},{'schema_version':3,'system':'bazi'},[] ):
            with self.subTest(wrong=str(wrong)[:40]),self.assertRaises(classic.OracleError):
                classic.calculate('yilin',{'method':'iching','iching_result':wrong})

    def test_versioned_coin_reproduction_vector_uses_three_coins_per_line(self):
        result=classic.calculate('yilin',{'method':'coins','seed':2026})
        self.assertEqual(result['line_values_bottom_to_top'],[9,7,7,9,7,8])
        self.assertEqual((result['oracle']['base'],result['oracle']['changed']),(43,48))
        self.assertEqual(result['cast_record']['bits_used'],18)
        self.assertEqual(result['line_values_bottom_to_top'],[6+sum(row) for row in result['cast_record']['coin_groups_bottom_to_top']])
        replay=classic.calculate('yilin',{'method':'coins','seed':'2026'})
        self.assertEqual(result['oracle'],replay['oracle'])
        self.assertEqual(result['cast_record'],replay['cast_record'])

    def test_unknown_inputs_do_not_trigger_implicit_sampling(self):
        with patch.object(classic.secrets,'randbits',side_effect=AssertionError('unexpected random cast')):
            self.assertEqual(classic.calculate('yilin',{})['status'],'needs_input')
            self.assertEqual(classic.calculate('yilin',{'method':'lines'})['status'],'needs_input')
        for params in ({'base':0,'changed':1},{'base':True,'changed':1},{'base':1,'changed':65},
                       {'method':'lines','lines':[7]*5},{'method':'lines','lines':[True]*6},
                       {'method':'pair','base':1,'changed':1,'seed':7}):
            with self.subTest(params=params),self.assertRaises(classic.OracleError):
                classic.calculate('yilin',params)


class LingqijingCastingTests(unittest.TestCase):
    def test_twelve_explicit_faces_sum_each_layer_and_preserve_positions(self):
        pieces={'upper':[1,0,1,0],'middle':[0,0,0,0],'lower':[1,1,1,1]}
        result=classic.calculate('lingqijing',{'method':'pieces','pieces':pieces})
        self.assertEqual(result['figure']['counts'],[2,0,4])
        self.assertEqual([row['faces'] for row in result['figure']['rows']],list(pieces.values()))
        self.assertFalse(result['figure']['display_is_count_layout'])
        canonical=classic.calculate('lingqijing',{'counts':[2,0,4]})
        self.assertEqual(canonical['oracle'],result['oracle'])
        self.assertTrue(canonical['figure']['display_is_count_layout'])

    def test_all_4096_microstates_have_expected_nonuniform_shape_multiplicities(self):
        distribution=Counter()
        checked=set()
        for bits in itertools.product((0,1),repeat=12):
            counts=tuple(sum(bits[i:i+4]) for i in (0,4,8))
            distribution[counts]+=1
            if counts not in checked:
                value=classic.calculate('lingqijing',{'method':'pieces','pieces':{
                    'upper':list(bits[:4]),'middle':list(bits[4:8]),'lower':list(bits[8:])}})
                self.assertEqual(tuple(value['figure']['counts']),counts)
                checked.add(counts)
        self.assertEqual(len(checked),125)
        self.assertEqual(sum(distribution.values()),4096)
        self.assertEqual(distribution[(0,0,0)],1)
        self.assertEqual(distribution[(4,4,4)],1)
        self.assertEqual(distribution[(2,2,2)],216)
        self.assertGreater(len(set(distribution.values())),1)

    def test_versioned_toss_reproduction_and_record_counts_agree(self):
        result=classic.calculate('lingqijing',{'method':'toss','seed':2026})
        self.assertEqual(result['figure']['number'],38)
        self.assertEqual(result['figure']['counts'],[3,2,2])
        self.assertEqual(result['cast_record']['binary_outcomes'],[0,1,1,1,0,1,1,0,1,0,0,1])
        for seed in range(16):
            value=classic.calculate('lingqijing',{'method':'toss','seed':seed})
            bits=value['cast_record']['binary_outcomes']
            self.assertEqual(len(bits),12)
            self.assertEqual(value['figure']['counts'],[sum(bits[i:i+4]) for i in (0,4,8)])
            self.assertEqual(value['oracle'],classic.calculate('lingqijing',{'method':'counts','counts':value['figure']['counts']})['oracle'])

    def test_recorded_generated_seed_replays_and_all_blank_is_not_recast(self):
        with patch.object(classic.secrets,'randbits',return_value=17) as generator:
            value=classic.calculate('lingqijing',{'method':'toss'})
            generator.assert_called_once_with(128)
        replay=classic.calculate('lingqijing',{'method':'toss','seed':value['cast_record']['seed']})
        self.assertEqual(value['oracle'],replay['oracle'])
        self.assertEqual(value['figure'],replay['figure'])
        self.assertEqual(value['cast_record']['seed_origin'],'generated_by_secrets')
        blank=classic.calculate('lingqijing',{'method':'pieces','pieces':{layer:[0]*4 for layer in ('upper','middle','lower')}})
        self.assertEqual(blank['figure']['number'],125)
        self.assertEqual(blank['figure']['counts'],[0,0,0])

    def test_count_and_piece_boundaries_are_strict(self):
        for params in ({'counts':[-1,0,0]},{'counts':[5,0,0]},{'counts':[True,0,0]},
                       {'counts':[1,2]},{'method':'pieces','pieces':{'upper':[0]*4}},
                       {'method':'pieces','pieces':{layer:[0,0,0,True] for layer in ('upper','middle','lower')}},
                       {'method':'counts','counts':[0,0,0],'seed':1}):
            with self.subTest(params=params),self.assertRaises(classic.OracleError):
                classic.calculate('lingqijing',params)
        self.assertEqual(classic.calculate('lingqijing',{})['status'],'needs_input')


class InterfaceTests(unittest.TestCase):
    def test_unknown_fields_seed_bounds_and_json_types_are_rejected(self):
        for seed in (-1,2**256,True,1.5,'01','-1','1e3','9'*79):
            with self.subTest(seed=seed),self.assertRaises(classic.OracleError):
                classic.calculate('lingqijing',{'method':'toss','seed':seed})
        for system,params in [('unknown',{}),('yilin',[]),('yilin',{'method':'uniform'}),
                              ('lingqijing',{'counts':[1,1,1],'birth':{}}),('yilin',{'base':1,'changed':1,'question':False})]:
            with self.subTest(system=system,params=params),self.assertRaises(classic.OracleError):
                classic.calculate(system,params)

    def test_probe_is_local_and_input_not_mutated(self):
        params={'method':'pieces','pieces':{'upper':[1,0,0,0],'middle':[1,0,0,0],'lower':[1,0,0,0]}}
        before=copy.deepcopy(params)
        with patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')):
            value=classic.probe()
            classic.calculate('lingqijing',params)
        self.assertEqual(value['systems']['yilin']['entries'],4096)
        self.assertEqual(value['systems']['lingqijing']['entries'],125)
        self.assertEqual(params,before)

    def test_cli_emits_actual_result_or_json_error_without_writing_input_files(self):
        def run(*args):
            return subprocess.run([sys.executable,'-X','utf8','-B',str(SKILL/'scripts/classic_oracles.py'),*args],
                                  text=True,encoding='utf-8',capture_output=True,timeout=30)
        process=run('yilin','--params','{"method":"pair","base":1,"changed":2}')
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertEqual(json.loads(process.stdout)['oracle']['key'],'1:2')
        self.assertEqual(run('--probe').returncode,0)
        for args in [('lingqijing','--params','{"counts":[0,0,0],"counts":[1,1,1]}'),
                     ('yilin','--params','{}'),('no-such-system',),('yilin','--params','NaN')]:
            failed=run(*args)
            self.assertEqual(failed.returncode,2)
            self.assertIn(json.loads(failed.stdout)['status'],('needs_input','invalid_input'))
            self.assertEqual(failed.stderr,'')


if __name__=='__main__':
    unittest.main()
