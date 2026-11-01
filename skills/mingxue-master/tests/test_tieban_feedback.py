"""Regression checks for optional qiyun, chart boundaries and feedback audit."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if os.environ.get('MINGXUE_TEST_SKILL_ROOT'):
    SKILL_ROOT = Path(os.environ['MINGXUE_TEST_SKILL_ROOT']).resolve()
elif (ROOT / 'scripts').is_dir():
    SKILL_ROOT = ROOT
else:
    SKILL_ROOT = ROOT / 'package/mingxue-master'
SCRIPTS = SKILL_ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from resources import get_resources
RUNTIME = get_resources()
ENGINE_SCRIPTS = RUNTIME / 'references/upstream/tieban-shenshu-skillpack/scripts'
sys.path.insert(0, str(ENGINE_SCRIPTS))
from chart import build_chart
import feedback
import tieban
import tieban_run
import yansuan
import yiji_gua
import kaoke
import tiaowen_grid

PILLARS = ['庚寅', '甲申', '丙午', '甲午']


def arguments(**kw):
    values = dict(chart=None, year=PILLARS[0], month=PILLARS[1], day=PILLARS[2],
                  hour=PILLARS[3], gender='男', birth_year=1950, qiyun=None, confirm_sect=None)
    values.update(kw)
    return argparse.Namespace(**values)


class TiebanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = tieban.load_data()
        cls.n2t = {r['n']: r['t'] for r in cls.rows}

    def test_missing_qiyun_does_not_invent_age_or_block_numbering(self):
        result = tieban.build_result(self.rows, PILLARS, 'm', [])
        self.assertEqual(result['yiji']['status'], 'not_calculated')
        self.assertIsNone(result['yiji']['qiyun'])
        self.assertEqual(result['yiji']['segments'], [])
        self.assertTrue(result['sections'])
        self.assertTrue(result['yansuan']['xian_shi'])
        self.assertEqual(result['assessment']['stage'], 'before_feedback')
        self.assertIn('未计算', tieban.render_text(result))
        self.assertIsNone(yiji_gua.value_motion('乾为天', '子', 'm')['qiyun'])
        self.assertEqual(yansuan.shuchuan_liunian(PILLARS, 'm')['status'], 'not_calculated')

    def test_explicit_qiyun_is_used_including_explicit_zero(self):
        for age in (0, 6):
            with self.subTest(age=age):
                result = tieban.build_result(self.rows, PILLARS, 'm', [], qiyun=age)
                self.assertEqual(result['yiji']['status'], 'calculated')
                self.assertEqual(result['yiji']['segments'][0]['from_age'], age)
                self.assertEqual(result['yiji']['qiyun'], age)
        with self.assertRaises(ValueError):
            tieban.build_result(self.rows, PILLARS, 'm', [], qiyun=3.5)

    def test_book_number_hits_preserve_exact_database_text(self):
        result = tieban.build_result(self.rows, ['癸巳', '甲子', '丁酉', '甲辰'], 'm', [])
        row = result['yansuan']['rizhu_row']
        self.assertEqual(row['n'], 3926)
        self.assertTrue(row['hit'])
        self.assertEqual(row['text'], self.n2t[3926])
        for section in result['sections']:
            self.assertEqual(section['text'], self.n2t[section['n']])

    def test_fact_calibration_is_explicitly_after_feedback(self):
        result = tieban.build_result(self.rows, PILLARS, 'm', [], facts={1: '父羊母兔'})
        self.assertEqual(result['assessment']['stage'], 'after_feedback')
        self.assertEqual(result['assessment']['score_semantics'], 'heuristic_match_score_not_probability')
        k = tieban.kaoke.run_kaoke(PILLARS, 'm', {'brothers_n': 1})
        self.assertEqual(k['assessment']['stage'], 'after_feedback')

    def test_wrapper_runs_bundled_engine_without_writing_cases(self):
        with mock.patch.object(tieban_run, 'get_resources', return_value=RUNTIME):
            result = tieban_run.run(arguments(), ['--now-year', '1950', '--future', '0'])
        self.assertIsNone(result['entrypoint']['qiyun'])
        self.assertEqual(result['entrypoint']['persistence'], 'none')
        self.assertEqual(result['yiji']['status'], 'not_calculated')

    def test_wrapper_applies_structured_feedback_in_full_report(self):
        with mock.patch.object(tieban_run, 'get_resources', return_value=RUNTIME):
            result = tieban_run.run(arguments(qiyun=6), ['--now-year', '1950', '--future', '0',
                '--kaoke-facts', json.dumps({'brothers_n': 1})])
        self.assertEqual(result['assessment']['stage'], 'after_feedback')
        self.assertEqual(result['assessment']['calibration_status'], 'calibration_in_progress')
        self.assertEqual(result['kaoke']['facts']['brothers_n'], 1)
        self.assertEqual(result['yiji']['qiyun'], 6)

    def test_empty_or_unknown_feedback_has_no_calibration_signal(self):
        for facts in ({}, {'brothers_n': None}, {'fu_sang': '不确定', 'wife_alive': ' ', 'sons_n': '跳过'}):
            with self.subTest(facts=facts):
                result = kaoke.run_kaoke(PILLARS, 'm', facts)
                circuit = kaoke.kaoke_circuit(PILLARS, 'm', facts)
                for item in (result, circuit):
                    self.assertEqual(item['assessment']['stage'], 'before_feedback')
                    self.assertEqual(item['assessment']['calibration_status'], 'not_calibrated')
                self.assertIsNone(circuit['facts']['fu_sang'])
                self.assertFalse(circuit['done'])
        full = tieban.build_result(self.rows, PILLARS, 'm', [], facts={1: None, 2: '  ', 3: '未知'})
        self.assertEqual(full['assessment']['calibration_status'], 'not_calibrated')

    def test_wrapper_empty_objects_nulls_and_empty_fact_file_match_no_feedback(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'facts.json'
            path.write_text('{}', encoding='utf-8')
            variants = [[], ['--kaoke-facts', '{}'], ['--kaoke-facts', '{"brothers_n":null}'],
                        ['--kaoke-facts', str(path)], ['--facts', '{}'], ['--facts', '{"1":null}']]
            for variant in variants:
                with self.subTest(variant=variant):
                    result = tieban_run.run(arguments(), ['--kaoke-circuit', *variant])
                    self.assertEqual(result['assessment']['stage'], 'before_feedback')
                    self.assertEqual(result['assessment']['calibration_status'], 'not_calibrated')
                    self.assertIsNone(result['circuit']['result'])
                    self.assertFalse(result['circuit']['done'])

    def test_false_and_zero_are_valid_partial_inputs_and_completion_is_distinct(self):
        partial = {'fu_sang': False, 'brothers_n': 0, 'sons_n': '0'}
        state = kaoke.kaoke_circuit(PILLARS, 'm', partial)
        self.assertIs(state['facts']['fu_sang'], False)
        self.assertEqual(state['facts']['brothers_n'], 0)
        self.assertEqual(state['facts']['sons_n'], 0)
        self.assertEqual(state['assessment']['calibration_status'], 'calibration_in_progress')
        self.assertFalse(state['done'])
        complete = {'fu_sang': False, 'mu_sang': False, 'brothers_n': 3,
                    'wife_alive': False, 'sons_n': 0, 'daughters_n': 0}
        result = tieban_run.run(arguments(), ['--kaoke-circuit', '--kaoke-facts', json.dumps(complete)])
        self.assertTrue(result['circuit']['done'])
        self.assertEqual(len(result['circuit']['locked_ke']), 1)
        self.assertEqual(len(result['circuit']['locked_fen']), 1)
        self.assertEqual(result['assessment']['calibration_status'], 'feedback_calibrated')

    def test_ambiguous_booleans_and_invalid_counts_are_rejected_without_coercion(self):
        for key, invalid in [('brothers_n', -1), ('sons_n', 1.9), ('daughters_n', True),
                             ('sons_n', '1.9'), ('fu_sang', 'whatever'), ('mu_sang', 2),
                             ('fu_sang', []), ('brothers_n', {})]:
            with self.subTest(key=key, invalid=invalid), self.assertRaises(ValueError):
                kaoke.parse_kaoke_facts({key: invalid})
        for unknown in ('不确定', '未知', '跳过', ' ', 'unknown'):
            with self.subTest(unknown=unknown):
                state = kaoke.kaoke_circuit(PILLARS, 'm', {'fu_sang': unknown})
                self.assertIsNone(state['facts']['fu_sang'])
                self.assertTrue(any(q['key'] == ('fu_sang', 'mu_sang') for q in state['questions']))

    def test_alive_words_follow_the_field_semantics(self):
        for word in ('健在', '在世', '未丧', '存活'):
            with self.subTest(word=word):
                parsed = kaoke.parse_kaoke_facts({'fu_sang': word, 'mu_sang': word, 'wife_alive': word})
                self.assertIs(parsed['fu_sang'], False)
                self.assertIs(parsed['mu_sang'], False)
                self.assertIs(parsed['wife_alive'], True)
        for word in ('已丧', '丧', '已故', '去世', '死亡'):
            with self.subTest(word=word):
                parsed = kaoke.parse_kaoke_facts({'fu_sang': word, 'wife_alive': word})
                self.assertIs(parsed['fu_sang'], True)
                self.assertIs(parsed['wife_alive'], False)
        for value in (True, False, '是', '否', '有', '无'):
            parsed = kaoke.parse_kaoke_facts({'fu_sang': value, 'wife_alive': value})
            self.assertEqual(parsed['fu_sang'], parsed['wife_alive'])

    def test_unknown_parent_zodiac_does_not_take_the_other_parents_zodiac(self):
        grid = tiaowen_grid.build_grid(self.rows)
        father_unknown = tiaowen_grid.lookup_parents(grid, '父未知母兔')
        self.assertIsNone(father_unknown['father'])
        self.assertIsNone(father_unknown['pair'])
        self.assertEqual(father_unknown['mother'], grid['mother']['兔'])
        mother_unknown = tiaowen_grid.lookup_parents(grid, '父羊母不确定')
        self.assertIsNone(mother_unknown['mother'])
        self.assertEqual(mother_unknown['father'], grid['father']['羊'])

    def test_invalid_fact_cli_returns_json_error_and_nonzero_without_traceback(self):
        base = [sys.executable, '-B', '-X', 'utf8', str(SCRIPTS / 'tieban_run.py')]
        for key, value in zip(tieban_run.PILLAR_KEYS, PILLARS):
            base.extend(['--' + key, value])
        base.extend(['--gender', '男', '--birth-year', '1950', '--kaoke-circuit'])
        for facts in ({'brothers_n': -1}, {'sons_n': 1.9}, {'fu_sang': 'invalid'}):
            with self.subTest(facts=facts):
                result = subprocess.run(base + ['--kaoke-facts', json.dumps(facts)],
                                        capture_output=True, encoding='utf-8', check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertNotIn('Traceback', result.stderr)
                self.assertEqual(json.loads(result.stderr)['error']['code'], 'invalid_input')

    def test_unknown_hour_multiple_candidates_and_conflicting_inputs_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'chart.json'
            chart = build_chart('1950-08-16', gender='male')
            path.write_text(json.dumps(chart), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '多个候选'):
                tieban_run.resolve_input(arguments(chart=str(path)))
            unknown = dict(zip(tieban_run.PILLAR_KEYS, PILLARS))
            unknown['hour'] = None
            with self.assertRaisesRegex(ValueError, '时辰未知'):
                tieban_run.validated_pillars(unknown)
            chart = build_chart('1950-08-16', '12:00', gender='male')
            path.write_text(json.dumps(chart), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'gender'):
                tieban_run.resolve_input(arguments(chart=str(path), gender='女',
                    year=None, month=None, day=None, hour=None))
            chart['pillars']['hour'] = '乙巳'
            path.write_text(json.dumps(chart), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'modified'):
                tieban_run.resolve_input(arguments(chart=str(path)))

    def test_chart_fine_yun_never_silently_truncated_and_day_convention_confirmed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'chart.json'
            chart = build_chart('1950-08-16', '23:30', sect=2, gender='male')
            self.assertEqual(chart['yun']['status'], 'calculated')
            path.write_text(json.dumps(chart), encoding='utf-8')
            args = arguments(chart=str(path), year=None, month=None, day=None, hour=None)
            with self.assertRaisesRegex(ValueError, '换日口径'):
                tieban_run.resolve_input(args)
            args.confirm_sect = 2
            with mock.patch.object(tieban_run, 'get_resources', return_value=RUNTIME):
                result = tieban_run.run(args, ['--now-year', '1950', '--future', '0'])
            self.assertIsNone(result['entrypoint']['qiyun'])
            self.assertEqual(result['yiji']['status'], 'not_calculated')


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name) / 'archive'
        self.fact = [{'kind': 'user_fact', 'statement': '本人确认有一个弟弟', 'source': 'user'}]

    def initialize(self):
        return feedback.init_session(str(self.workspace), 'example', {'birth_year': 1950},
                                     {'assessment': {'stage': 'before_feedback'}, 'text': '初始推断'})

    def test_initial_and_revised_reports_remain_distinct_and_original_unchanged(self):
        initial = self.initialize()
        original_path = self.workspace / 'cases/example/records/000000.json'
        original = original_path.read_bytes()
        revised = feedback.revise_session(str(self.workspace), 'example',
                  {'assessment': {'stage': 'after_feedback'}, 'text': '修订推断'}, self.fact,
                  expected_head=initial['head_hash'])
        self.assertEqual(original_path.read_bytes(), original)
        self.assertEqual(revised['record_count'], 2)
        a, b = revised['records']
        self.assertEqual(a['stage'], 'before_feedback')
        self.assertEqual(b['stage'], 'after_feedback')
        self.assertEqual(a['initial_input']['content']['birth_year'], 1950)
        self.assertEqual(b['user_facts'][0]['kind'], 'user_fact')
        self.assertEqual(b['report']['kind'], 'inference')
        self.assertEqual(b['previous_hash'], a['hash'])
        self.assertIn('+00:00', b['created_at'])
        with self.assertRaises(FileExistsError):
            self.initialize()

    def test_tampered_report_and_truncated_chain_are_detected(self):
        self.initialize()
        feedback.revise_session(str(self.workspace), 'example', {'text': '修订'}, self.fact)
        last = self.workspace / 'cases/example/records/000001.json'
        last.unlink()
        with self.assertRaisesRegex(ValueError, '末端'):
            feedback.show_session(str(self.workspace), 'example')
        original = self.workspace / 'cases/example/records/000000.json'
        value = json.loads(original.read_text(encoding='utf-8'))
        value['report']['content'] = '被更改'
        original.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '完整性'):
            feedback.show_session(str(self.workspace), 'example')

    def test_path_limits_fact_provenance_and_phase_not_relabelled(self):
        with self.assertRaisesRegex(ValueError, '绝对路径'):
            feedback.paths('relative', 'example')
        for root in (feedback.SKILL_ROOT, feedback.RUNTIME_ROOT):
            with self.subTest(root=root), self.assertRaisesRegex(ValueError, '源码'):
                feedback.paths(str(root / 'cases'), 'example')
        for name in ('MINGXUE_CACHE_DIR', 'MINGXUE_RESOURCE_DIR'):
            with mock.patch.dict(os.environ, {name: str(self.workspace)}):
                with self.assertRaisesRegex(ValueError, '资源树'):
                    feedback.paths(str(self.workspace / 'records'), 'example')
        with self.assertRaisesRegex(ValueError, 'case'):
            feedback.paths(str(self.workspace), '../escape')
        with self.assertRaisesRegex(ValueError, '用户事实'):
            feedback.facts_list([{'kind': 'inference', 'statement': '模型猜测', 'source': 'model'}])
        with self.assertRaisesRegex(ValueError, '报告自带阶段'):
            feedback.init_session(str(self.workspace), 'fake', {}, {'assessment': {'stage': 'after_feedback'}})
        self.assertFalse(self.workspace.exists())

    def test_external_receipt_detects_different_head(self):
        initial = self.initialize()
        self.assertEqual(feedback.show_session(str(self.workspace), 'example', initial['head_hash'])['integrity'], 'verified')
        with self.assertRaisesRegex(ValueError, '外部'):
            feedback.show_session(str(self.workspace), 'example', '0' * 64)

    def test_cli_init_revise_show_round_trip(self):
        directory = Path(self.temp.name)
        inputs = directory / 'input.json'
        report = directory / 'report.json'
        facts = directory / 'facts.json'
        inputs.write_text(json.dumps({'birth_year': 1950}), encoding='utf-8')
        report.write_text(json.dumps({'text': '推断'}), encoding='utf-8')
        facts.write_text(json.dumps(self.fact), encoding='utf-8')
        base = [sys.executable, '-X', 'utf8', str(SCRIPTS / 'feedback.py')]
        common = ['--workspace', str(self.workspace), '--case', 'cli_example']
        commands = [base + ['init'] + common + ['--input', str(inputs), '--report', str(report)],
                    base + ['revise'] + common + ['--report', str(report), '--facts', str(facts)],
                    base + ['show'] + common]
        for index, command in enumerate(commands):
            with self.subTest(command=command[4]):
                result = subprocess.run(command, capture_output=True, encoding='utf-8', check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads(result.stdout)
                self.assertEqual(data['record_count'], 1 if index == 0 else 2)
                self.assertEqual(data['integrity'], 'verified')


if __name__ == '__main__':
    unittest.main()
