"""Reader omissions and real birth-time alternatives remain faithful to inputs."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

HERE=Path(__file__).resolve().parents[1]
SKILL=Path(os.environ.get('MINGXUE_TEST_SKILL_ROOT') or (HERE/'package/mingxue-master' if (HERE/'package/mingxue-master').is_dir() else HERE))
sys.path.insert(0,str(SKILL/'scripts'))
import reader_art
from reader_language import audit_reader_text
from reader_projection import available,unknown_bazi_view,overview_for_reader,reader_view,report_locale,report_translator


class ReaderProjectionTests(unittest.TestCase):
    def test_partial_name_pronunciation_does_not_hide_completed_grid_arithmetic(self):
        payload={'status':'needs_input','calculation_status':'calculated','name':'测试名',
                 'strokes':[{'character':'测','count':9},{'character':'试','count':8},{'character':'名','count':6}],
                 'five_grids':{'天格':{'number':10,'element':'水','yin_yang':'阴'},'人格':{'number':17,'element':'金','yin_yang':'阳'}},
                 'three_talents':{'label':'水金火'},'sound_form_meaning':{'pronunciation':None}}
        before=copy.deepcopy(payload)
        view=reader_view({'kind':'reference','data':{'text':'依赖未就绪'}},'names',payload)
        self.assertEqual(view['kind'],'numbers')
        self.assertEqual([row['value'] for row in view['data']['items']],[10,17])
        self.assertEqual(view['metrics'][1]['value'],'测 9 · 试 8 · 名 6')
        self.assertEqual(payload,before);self.assertIsNone(payload['sound_form_meaning']['pronunciation'])
        for patch in ({'five_grids':{}},{'five_grids':None},{'calculation_status':'needs_input'}):
            result=reader_view({'kind':'reference','data':{'text':'实际待补内容'}},'names',{**payload,**patch})
            self.assertEqual(result['kind'],'reference')

    def test_international_names_use_actual_writing_and_existing_expression_not_chinese_grids(self):
        payload={'mode':'international','status':'calculated','full_name':'Alex Kim','writing':{'scripts':{'Latin':7,'Hangul':0},'letter_count':7,'word_parts':['Alex','Kim']},
                 'latin_numerology':{'sum':30,'reduction':{'number':3,'trace':[30,3]}} ,'five_grids':None,'three_talents':None}
        before=copy.deepcopy(payload);view=reader_view({},'names',payload)
        self.assertEqual(view['kind'],'numbers');self.assertEqual(view['data']['items'][0]['value'],'Alex Kim')
        self.assertEqual(view['data']['items'][-1]['value'],3)
        self.assertNotIn('天格',json.dumps(view,ensure_ascii=False));self.assertEqual(payload,before)

    def test_report_language_comes_from_saved_questionnaire_with_legacy_fallback(self):
        for language in ('zh-CN','en','ja','ko'):
            self.assertEqual(report_locale({'questionnaire':{'_report_language':language}}),language)
        for report in ({},{'questionnaire':None},{'questionnaire':{'_report_language':'auto'}}):
            self.assertEqual(report_locale(report),'zh-CN')
    def test_unknown_time_retains_real_month_and_day_alternatives(self):
        result=unknown_bazi_view({'candidates':[{'pillars':{'year':'丁丑','month':'丁未','day':'辛巳','hour':'癸巳'}},
            {'pillars':{'year':'丁丑','month':'戊申','day':'壬午','hour':'甲午'}}]})
        cols={c['key']:c for c in result['data']['columns']}
        self.assertEqual(cols['year']['values'],['丁丑'])
        self.assertTrue(cols['year']['certain'])
        self.assertEqual(set(cols['month']['values']),{'丁未','戊申'})
        self.assertEqual(set(cols['day']['values']),{'辛巳','壬午'})
        self.assertEqual(cols['hour']['values'],[])
        self.assertFalse(cols['month']['certain'])

    def test_unfilled_and_unviewed_observation_never_becomes_a_page(self):
        for state in ('needs_input','reference_only','intake_only','error'):
            self.assertFalse(available({'system':'palm','state':state,'reading_status':'applied'},{}))
        panel={'system':'face','state':'intake_only','reading_status':'applied'}
        payload={'observation_status':'user_reported','photo_refs':[{'id':'a'}],'user_reported_observations':{'features':['可见轮廓']}}
        self.assertFalse(available(panel,payload))
        payload['observation_status']='agent_observed'
        self.assertTrue(available(panel,payload))
        payload['user_reported_observations']['features']=[]
        self.assertFalse(available(panel,payload))

    def test_omission_removes_coverage_and_counts_without_mutating_private_data(self):
        private={'coverage':[{'person':'A','system':'numerology'},{'person':'A','system':'palm'}],
                 'highlights':[{'person':'A','system':'palm'}],'coverage_counts':{'total':25},
                 'limitations':['手相没有提供','这是文化阅读。']}
        before=copy.deepcopy(private)
        public=overview_for_reader(private,{('A','numerology')})
        self.assertEqual([x['system'] for x in public['coverage']],['numerology'])
        self.assertEqual(public['highlights'],[])
        self.assertNotIn('coverage_counts',public)
        self.assertEqual(public['limitations'],['这是文化阅读。'])
        self.assertEqual(private,before)

    def test_developer_words_require_rewriting_but_daily_realization_is_allowed(self):
        for term in ('权限','接口','缓存','前端','后端','调用','端点','JSON','API','backend'):
            self.assertTrue(any(x['code']=='internal_language' for x in audit_reader_text('这里有'+term+'。')))
        self.assertEqual(audit_reader_text('你可以实现愿望，也可以调整目标。'),[])


class ReaderArtTests(unittest.TestCase):
    def fixture(self,root):
        (root/'assets/art').mkdir(parents=True);(root/'ui').mkdir()
        raw=b'\x89PNG\r\n\x1a\nillustration-test'
        (root/'assets/art/hero.png').write_bytes(raw)
        record={'key':'hero','path':'assets/art/hero.png','format':'png','width':2,'height':2,
            'sha256':hashlib.sha256(raw).hexdigest(),'prompt':'PRIVATE PRODUCTION PROMPT','alt':'山水'}
        (root/'assets/art-manifest.json').write_text(json.dumps({'schema_version':1,'assets':[record]}),encoding='utf-8')
        return record

    def test_offline_bundle_keeps_no_paths_prompts_or_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.fixture(root)
            with mock.patch.object(reader_art,'ROOT',root):bundle=reader_art.art_bundle([])
            self.assertTrue(bundle['hero']['src'].startswith('data:image/png;base64,'))
            self.assertEqual(set(bundle['hero']),{'src','width','height','alt'})

    def test_intake_uses_only_packaged_same_origin_image_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.fixture(root)
            with mock.patch.object(reader_art,'ROOT',root):path=reader_art.write_intake_bundle()
            text=path.read_text(encoding='utf-8')
            self.assertIn('/art/hero.png',text)
            self.assertNotIn('base64',text)
            self.assertNotIn('PRIVATE PRODUCTION',text)

    def test_modified_or_escaping_art_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);record=self.fixture(root)
            with mock.patch.object(reader_art,'ROOT',root):
                (root/'assets/art/hero.png').write_bytes(b'changed')
                with self.assertRaises(ValueError):reader_art.art_bundle()
                record['path']='../../outside.png'
                (root/'assets/art-manifest.json').write_text(json.dumps({'schema_version':1,'assets':[record]}),encoding='utf-8')
                with self.assertRaises(ValueError):reader_art.art_bundle()


class ReaderLocaleTests(unittest.TestCase):
    def test_personal_pair_and_noscript_keep_requested_locale_and_agent_text(self):
        import personal_report
        from test_report_illustrations import record
        dictionary_path=SKILL/'ui/report-locales.json'
        self.assertTrue(dictionary_path.is_file(),'The report shares one shipped locale dictionary')
        for language,text in [('zh-CN','这是正文，保留事业一词。'),('en','Keep this original prose: 事业.'),('ja','この文章の「事业」をそのまま残す。'),('ko','이 원문에서 事业 표기를 유지합니다.')]:
            with self.subTest(language=language):
                records=[record('A','palm'),record('B','face')]
                translate=report_translator(language)
                for r in records:
                    r['report']['questionnaire']={'_report_language':language}
                    r['report']['panels'][0]['traditional_interpretation']={'text':text}
                overview={'scope':'A','subjects':[{'person':'A','name':'A'}],'summary':text,'themes':[{'title':'Agent title: 事业','text':text}],
                          'actions':[{'title':'Agent action','text':text}]}
                personal=personal_report.personal_html(records[0]['report'],records[0]['payloads'],overview=overview)
                pair=personal_report.pair_html(records[0]['report'],records[0]['payloads'],records[1]['report'],records[1]['payloads'],{'interpretation':{'text':text}},overview=overview)
                for output in (personal,pair):
                    self.assertIn(f'<html lang="{language}">',output)
                    from test_personal_report_security import Document
                    parsed=Document();parsed.feed(output);data=parsed.data()
                    self.assertEqual(data['language'],language)
                    fallback=output.split('</noscript>')[0]
                    self.assertIn(text,fallback);self.assertIn('Agent title: 事业',fallback)
                    self.assertIn(translate('行动建议'),fallback)
                    self.assertEqual(data['panels'][0]['title'],translate('手相'))
                    self.assertEqual(parsed.resources,[]);self.assertEqual(parsed.dangerous,[])

class AnswerCorrectionTests(unittest.TestCase):
    def test_delete_only_requested_answer_without_filling_unknown_birth_time(self):
        from agent_updates import update_job
        from intake_flow import submit
        from agent_report import snapshot
        with tempfile.TemporaryDirectory() as directory:
            parent=Path(directory)/'reports'
            request={'mode':'single','people':[{'person':{'name':'合成资料'},'birth':{'date':'1990-05-17','calendar':'solar','timezone':'Asia/Shanghai','time':None}}],
                     'preferences':{'systems':['numerology'],'depth':'brief','answers':{'旧关注':'旧文字','保留':'生活'}}}
            created=submit(parent,request)
            self.assertIn(created['status'],('ready','partial'))
            job=parent/created['job_id']
            result=update_job(job,{'preferences':{'answers':{'旧关注':None,'新关注':'相处'}}})
            self.assertTrue(result['request_committed'])
            _,current,_=snapshot(job)
            self.assertEqual(current['preferences']['answers'],{'保留':'生活','新关注':'相处'})
            self.assertIsNone(current['people'][0]['birth']['time'])


if __name__=='__main__':unittest.main()
