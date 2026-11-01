"""Real calculation-to-visual contracts and historical-record regression checks."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]
ROOT=HERE/'package/mingxue-master' if (HERE/'package/mingxue-master').is_dir() else HERE
sys.path.insert(0,str(ROOT/'scripts'))
from workbench_catalog import catalog
from workbench_api import calculate, safe_params
from workbench import Records


class VisualContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.specs={s['id']:s for s in catalog()['systems']}
        cls.results={k:calculate(k,v['example']) for k,v in cls.specs.items()}

    def test_all_twenty_five_examples_have_method_specific_fields(self):
        self.assertEqual(25,len(self.specs))
        for spec in self.specs.values():
            self.assertTrue(spec['fields'])
            safe_params(spec['id'],spec['example'])

    def test_nineteen_active_methods_have_actual_visual_data(self):
        references={'palm','face','fengshui','qimen','liuren','human_design'}
        for key,r in self.results.items():
            if key in references:
                self.assertEqual('reference',r['view']['kind'])
            else:
                self.assertNotEqual('reference',r['view']['kind'],key)
                self.assertTrue(r['view']['data'],key)
                self.assertNotIn(r['result'].get('status'),('error','needs_input','invalid_input','engine_unavailable'))

    def test_hidden_stems_and_zero_bits_survive_display_adapter(self):
        self.assertTrue(self.results['bazi']['view']['data']['columns'][0]['hidden'][0].startswith('丁'))
        r=self.results['iching']
        nuclear=r['result']['hexagrams']['nuclear']['bits_bottom_to_top']
        self.assertEqual([bool(int(x)) for x in nuclear], [line['yang'] for line in r['view']['data']['hexagrams'][2]['lines']])

    def test_numerology_shows_final_number_and_trace(self):
        item=self.results['numerology']['view']['data']['items'][0]
        self.assertEqual('5',item['value'])
        self.assertEqual('32 → 5',item['detail'])

    def test_unknown_birth_time_retains_each_candidate(self):
        r=calculate('bazi',{'date':'1990-05-17','timezone':'Asia/Shanghai'})
        self.assertEqual(13,len(r['view']['variants']))
        self.assertNotIn('variant_mode',r['view'])
        self.assertEqual('?',r['view']['data']['columns'][3]['stem'])

    def test_ambiguous_astrology_clocks_keep_both_wheels(self):
        r=calculate('astrology',{'date':'2021-11-07','time':'01:30','timezone':'America/New_York','latitude':40.71,'longitude':-74.0})
        self.assertEqual(2,len(r['view']['variants']))
        self.assertNotEqual(r['view']['variants'][0]['label'],r['view']['variants'][1]['label'])

    def test_actual_ziwei_flows_have_distinct_labels_and_layer_stars(self):
        r=calculate('ziwei',{**self.specs['ziwei']['example'],'scope':'daily','target_date':'2026-03-24','target_time':'12:30'})
        views=r['view']['variants']
        self.assertEqual(['本命盘','流年','流月','流日'],[v['label'] for v in views])
        self.assertEqual('views',r['view']['variant_mode'])
        self.assertEqual(12,len(views[-1]['view']['data']['palaces']))
        self.assertTrue(any(any(t.startswith('本命') for t in p['tags']) for p in views[-1]['view']['data']['palaces']))

    def test_classics_display_real_verses_and_counts(self):
        self.assertEqual('乾',self.results['yilin']['view']['data']['hexagrams'][0]['name'])
        self.assertTrue(self.results['yilin']['view']['data']['text'])
        self.assertEqual([1,1,1],self.results['lingqijing']['view']['data']['counts'])

    def test_qizheng_missing_calibration_is_visible(self):
        r=self.results['qizheng']
        self.assertEqual('partial',r['result']['status'])
        self.assertEqual(10,len(r['view']['data']['points']))
        self.assertTrue(any('紫气' in n for n in r['view']['notes']))

    def test_ziqi_explicit_reference_gets_separate_point_style(self):
        r=calculate('qizheng',{**self.specs['qizheng']['example'],'ziqi_model':'mean_cycle',
            'ziqi_epoch_utc':'2000-01-01T12:00:00Z','ziqi_epoch_longitude':0,'ziqi_period_days':10227,
            'ziqi_reference_label':'测试均速参考，非古历校准'})
        point=next(p for p in r['view']['data']['points'] if p['label']=='紫气')
        self.assertEqual('conventional_point',point['type'])
        self.assertEqual('dashed',point['plot_style'])

    def test_taiyi_zero_bureau_is_not_a_fabricated_board(self):
        r=calculate('taiyi',{'date':'2026-03-24','time':'10:30','mode':'hour','method':1})
        self.assertEqual('unsupported_boundary',r['result']['status'])
        self.assertEqual('reference',r['view']['kind'])

    def test_grand_tableau_columns_match_selected_layout(self):
        for layout,n in [('9x4',9),('8x4+4',8)]:
            r=calculate('lenormand',{'spread':'grand','layout':layout,'seed':42})
            self.assertEqual(n,r['view']['data']['columns'])
            self.assertEqual(36,len(r['view']['data']['cards']))

    def test_lenormand_has_no_fabricated_orientation_but_tarot_keeps_it(self):
        result=calculate('lenormand',{'spread':'three','cards':'1,27,35'})
        self.assertEqual([card['id'] for card in result['view']['data']['cards']],[1,27,35])
        self.assertTrue(all('orientation' not in card for card in result['view']['data']['cards']))
        self.assertTrue(all(card.get('orientation') in ('upright','reversed') for card in self.results['tarot']['view']['data']['cards']))

    def test_geomancy_views_are_views_and_court_is_centered(self):
        r=self.results['geomancy']['view']
        self.assertEqual('views',r['variant_mode'])
        figures=r['data']['figures']
        judge=next(f for f in figures if f['id']=='J')
        self.assertEqual(3.5,judge['col'])
        self.assertEqual(12,len(r['variants'][1]['view']['data']['cells']))

    def test_user_question_does_not_change_lunar_calculation(self):
        original=self.results['xiaoliuren']
        amended=calculate('xiaoliuren',{**self.specs['xiaoliuren']['example'],'question':'<script>untrusted</script>'})
        self.assertEqual(original['result'],amended['result'])
        self.assertEqual('<script>untrusted</script>',amended['params']['question'])

    def test_unknown_output_paths_and_implicit_gender_are_rejected(self):
        for system,p in [('bazi',{'date':'1990-01-01','output':'C:/bad.json'}),
                         ('ziwei',{'date':'1990-01-01','time':'12:30','timezone':'Asia/Shanghai'}),
                         ('horary',{**self.specs['horary']['example'],'question':''})]:
            with self.assertRaises(ValueError): calculate(system,p)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='mingli-history-tests-')
        self.store=Records(self.tmp.name)
        self.sample=calculate('numerology',{'date':'1990-05-17'})

    def tearDown(self): self.tmp.cleanup()

    def test_roundtrip_and_tampering_with_same_id(self):
        record=self.store.save(self.sample)
        self.assertEqual(record,self.store.read(record['id']))
        record['params']['date']='2000-01-01'
        path=Path(self.tmp.name)/(record['id']+'.json')
        path.write_text(json.dumps(record),encoding='utf-8')
        with self.assertRaises(ValueError): self.store.read(record['id'])
        self.assertEqual([],self.store.list()['items'])

    def test_conflicting_native_method_cannot_be_saved(self):
        data=copy.deepcopy(self.sample)
        data['result']['system']='iching'
        with self.assertRaises(ValueError): self.store.save(data)

    def test_paths_cannot_escape_history_or_write_into_plugin(self):
        for id_ in ('../other','0'*32+'.json','/etc/passwd'):
            with self.assertRaises(ValueError): self.store.read(id_)
        with self.assertRaises(ValueError): Records(ROOT/'history')


if __name__=='__main__': unittest.main()
