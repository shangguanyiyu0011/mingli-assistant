"""Offline official Tieban entry point. Reads charts; never stores personal cases."""
import argparse
from datetime import date
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
from case_lookup import load_chart
from resources import get_resources, ResourceError

PILLAR_KEYS = ('year', 'month', 'day', 'hour')
GAN = '甲乙丙丁戊己庚辛壬癸'
ZHI = '子丑寅卯辰巳午未申酉戌亥'


def normalize_gender(value):
    values = {'m': '男', 'male': '男', '男': '男', 'f': '女', 'female': '女', '女': '女'}
    if value not in values:
        raise ValueError('gender 必须明确为男/女或 m/f')
    return values[value]


def validated_pillars(values):
    if not isinstance(values, dict):
        raise ValueError('chart.pillars 必须是包含 year/month/day/hour 的对象')
    result = []
    for key in PILLAR_KEYS:
        value = values.get(key)
        if not isinstance(value, str) or len(value) != 2 or value[0] not in GAN or value[1] not in ZHI:
            raise ValueError(f'四柱 {key} 缺失或无效；时辰未知/四柱不确定时拒绝铁板起数')
        if GAN.index(value[0]) % 2 != ZHI.index(value[1]) % 2:
            raise ValueError(f'无效干支柱 {key}: {value}')
        result.append(value)
    return result


def resolve_input(args):
    chart = None
    if args.chart:
        chart = load_chart(args.chart)
        if not isinstance(chart, dict) or chart.get('schema_version') != 3:
            raise ValueError('--chart 需要 schema_version=3 的统一排盘 JSON；旧盘须核实时间口径后重新生成')
        candidates = chart.get('candidates', [])
        if not isinstance(candidates, list) or len(candidates) > 1:
            raise ValueError('统一排盘存在多个候选；请先确定出生时刻与边界口径，再作铁板起数')
        if chart.get('time_known') is False:
            raise ValueError('统一排盘未确认出生时辰，拒绝铁板起数')
        pillars = validated_pillars(chart.get('pillars'))
        for key, value in zip(PILLAR_KEYS, pillars):
            explicit = getattr(args, key)
            if explicit is not None and explicit != value:
                raise ValueError(f'--{key} 与统一排盘冲突')
        chart_input = chart.get('input') or {}
        if chart.get('convention_alternatives') and args.confirm_sect != chart_input.get('sect'):
            raise ValueError('子时存在换日口径分歧；请核实后用 --confirm-sect 确认当前排盘的 sect')
        if args.confirm_sect is not None and args.confirm_sect != chart_input.get('sect'):
            raise ValueError('--confirm-sect 与统一排盘口径冲突，请先按所选口径重新排盘')
        chart_gender = chart_input.get('gender')
        if args.gender is not None and chart_gender is not None:
            if normalize_gender(args.gender) != normalize_gender(chart_gender):
                raise ValueError('--gender 与统一排盘冲突')
        gender = normalize_gender(args.gender if args.gender is not None else chart_gender)
        solar = chart.get('solar')
        if isinstance(solar, dict):
            solar = solar.get('date') or solar.get('ymd')
        chart_birth_year = date.fromisoformat(solar).year if isinstance(solar, str) else None
        if chart_birth_year is None and chart_input.get('calendar') == 'solar':
            chart_birth_year = date.fromisoformat(chart_input['date']).year
        if args.birth_year is not None and chart_birth_year is not None and args.birth_year != chart_birth_year:
            raise ValueError('--birth-year 与统一排盘公历出生年冲突')
        birth_year = args.birth_year if args.birth_year is not None else chart_birth_year
    else:
        pillars = validated_pillars({key: getattr(args, key) for key in PILLAR_KEYS})
        gender = normalize_gender(args.gender)
        birth_year = args.birth_year
    if birth_year is None or not 1 <= birth_year <= 9999:
        raise ValueError('需要明确公历出生年 --birth-year，或由统一排盘提供 solar 日期')
    return pillars, gender, birth_year, chart


def run(args, extra):
    pillars, gender, birth_year, chart = resolve_input(args)
    if args.qiyun is not None and args.qiyun < 0:
        raise ValueError('--qiyun 必须是经过核实的非负整数')
    engine = get_resources() / 'references/upstream/tieban-shenshu-skillpack/scripts/tieban.py'
    if not engine.is_file():
        raise ValueError('打包资源缺少铁板脚本')
    command = [sys.executable, '-B', '-X', 'utf8', str(engine)]
    for key, value in zip(PILLAR_KEYS, pillars):
        command.extend(['--' + key, value])
    command.extend(['--gender', gender, '--birth-year', str(birth_year)])
    if args.qiyun is not None:
        command.extend(['--qiyun', str(args.qiyun)])
    command.extend(extra)
    command.append('--json')
    completed = subprocess.run(command, capture_output=True, encoding='utf-8', check=False)
    if completed.returncode:
        message = completed.stderr.strip() or '铁板脚本执行失败'
        try:
            message = json.loads(message)['error']['message']
        except (ValueError, KeyError, TypeError):
            pass
        raise ValueError(message)
    result = json.loads(completed.stdout)
    nested_assessment = result.get('kaoke', {}).get('assessment') if isinstance(result.get('kaoke'), dict) else None
    circuit_assessment = result.get('circuit', {}).get('assessment') if isinstance(result.get('circuit'), dict) else None
    result.setdefault('assessment', nested_assessment or circuit_assessment or {
        'stage': 'before_feedback',
        'calibration_status': 'not_calibrated',
        'score_semantics': 'heuristic_match_score_not_probability',
        'note': '反馈匹配不是独立验证；传统规则结果不代表科学预测概率。',
    })
    result['entrypoint'] = {
        'schema_version': 2,
        'input_source': 'unified_chart' if chart else 'explicit_pillars',
        'qiyun': args.qiyun,
        'qiyun_source': 'explicit_argument' if args.qiyun is not None else 'not_provided',
        'yun_policy': '统一排盘的精细起运年月日时不自动截断成铁板整数起运岁数。',
        'persistence': 'none',
        'day_convention_confirmed': args.confirm_sect,
    }
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog='其他铁板 CLI 参数直接透传，例如 --kaoke --kaoke-facts JSON、--now-year、--future。输出始终为 JSON。')
    parser.add_argument('--chart', help='统一排盘 schema_version=3 JSON 文件')
    for key in PILLAR_KEYS:
        parser.add_argument('--' + key, help='明确的两字干支柱')
    parser.add_argument('--gender', help='男/女或 m/f；可从统一排盘读取')
    parser.add_argument('--birth-year', type=int, help='公历出生年；可从统一排盘读取')
    parser.add_argument('--qiyun', type=int, help='用户核实的整数起运岁数；省略则不计算起运依赖项')
    parser.add_argument('--confirm-sect', type=int, choices=(1, 2), help='有子时换日分歧时，核实并确认统一排盘的 sect；不在此处改盘')
    parser.add_argument('--json', action='store_true', help='输出 JSON（默认）')
    args, extra = parser.parse_known_args(argv)
    try:
        print(json.dumps(run(args, extra), ensure_ascii=False, indent=2))
    except (ValueError, OSError, TypeError, KeyError, ResourceError) as exc:
        print(json.dumps({'error': {'code': 'invalid_input', 'message': str(exc)}}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == '__main__':
    main()
