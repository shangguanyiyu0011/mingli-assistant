"""Explicit local feedback archive with immutable reports and a verifiable hash chain.

No archive is created until init is requested with --workspace. Local hashes detect
accidental or partial edits; use --expected-head from a separately kept receipt to
detect a complete rewrite. Hashes are not a digital signature or scientific proof.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import uuid

sys.dont_write_bytecode = True
SKILL_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = SKILL_ROOT.parents[1] / 'runtime'
CASE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _bounded(root, path):
    if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
        raise ValueError('档案路径不得使用符号链接或目录联接')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('档案路径超出显式工作目录')
    return path


def paths(workspace, case_id):
    raw = Path(workspace).expanduser()
    if not raw.is_absolute():
        raise ValueError('--workspace 必须是显式绝对路径')
    root = raw.resolve()
    forbidden_roots = [SKILL_ROOT.resolve(), RUNTIME_ROOT.resolve(),
                       (Path(tempfile.gettempdir()) / 'mingxue-master-cache').resolve()]
    forbidden_roots.extend(Path(os.environ[key]).expanduser().resolve()
                           for key in ('MINGXUE_CACHE_DIR', 'MINGXUE_RESOURCE_DIR') if os.environ.get(key))
    from output_paths import protected_output_roots
    forbidden_roots.extend(protected_output_roots())
    for forbidden in forbidden_roots:
        if root == forbidden or root.is_relative_to(forbidden):
            raise ValueError('个人命例不得写入技能源码、资源树或其缓存')
    if any(p.name.startswith('mingxue-resources-') or p.name == 'mingxue-master-cache'
           for p in (root, *root.parents)):
        raise ValueError('个人命例不得写入打包资源缓存')
    if not isinstance(case_id, str) or not CASE_ID.fullmatch(case_id):
        raise ValueError('--case 只允许 1–80 位英文字母、数字、下划线及短横线，且首位为字母或数字')
    cases = _bounded(root, root / 'cases')
    case = _bounded(root, cases / case_id)
    _bounded(root, case / 'records')
    return root, case


def facts_list(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError('facts 必须是列表，每项含 kind=user_fact、statement 和 source=user')
    result = []
    for fact in value:
        if not isinstance(fact, dict) or fact.get('kind') != 'user_fact' or fact.get('source') != 'user':
            raise ValueError('用户事实必须显式标记 kind=user_fact、source=user；不能将模型推断写为用户事实')
        if not isinstance(fact.get('statement'), str) or not fact['statement'].strip():
            raise ValueError('用户事实 statement 不得为空')
        result.append(json.loads(canonical(fact)))
    return result


def _read(root, path):
    return json.loads(_bounded(root, path).read_text(encoding='utf-8-sig'))


def _write_new(root, path, value):
    _bounded(root, path)
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n')


@contextmanager
def _lock(root, case):
    path = _bounded(root, case / '.lock')
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError('档案正在写入，或存在中断后的 .lock；请检查后重试') from None
    try:
        os.close(fd)
        yield
    finally:
        path.unlink()


def _set_head(root, case, record):
    value = {'schema_version': 1, 'sequence': record['sequence'], 'hash': record['hash'],
             'updated_at': record['created_at']}
    path = _bounded(root, case / 'head.json')
    tmp = _bounded(root, case / ('.head-' + uuid.uuid4().hex + '.tmp'))
    try:
        _write_new(root, tmp, value)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _record(sequence, stage, report, user_facts, previous_hash, input_data=None, note=None):
    declared_stage = report.get('assessment', {}).get('stage') if isinstance(report, dict) else None
    if declared_stage is not None and declared_stage != stage:
        raise ValueError('报告自带阶段与存档阶段不符，不能把反馈后报告重标为反馈前结论')
    record = {'schema_version': 1, 'sequence': sequence, 'stage': stage,
              'created_at': _now(), 'previous_hash': previous_hash,
              'user_facts': facts_list(user_facts),
              'report': {'kind': 'inference', 'content': report},
              'score_semantics': 'heuristic_match_score_not_probability'}
    if sequence == 0:
        record['initial_input'] = {'kind': 'user_input', 'content': input_data}
    if note is not None:
        record['revision_note'] = {'kind': 'inference', 'content': note}
    record['hash'] = _digest(record)
    return record


def show_session(workspace, case_id, expected_head=None):
    root, case = paths(workspace, case_id)
    manifest = _read(root, case / 'session.json')
    head = _read(root, case / 'head.json')
    records_dir = _bounded(root, case / 'records')
    files = sorted(records_dir.iterdir())
    if not files or any(not re.fullmatch(r'\d{6}\.json', f.name) for f in files):
        raise ValueError('档案记录缺失或存在未知文件')
    records = []
    previous_hash = None
    for index, path in enumerate(files):
        if path.name != f'{index:06d}.json':
            raise ValueError('档案记录序号断裂')
        record = _read(root, path)
        actual_hash = record.get('hash')
        payload = {k: v for k, v in record.items() if k != 'hash'}
        if record.get('sequence') != index or record.get('previous_hash') != previous_hash or _digest(payload) != actual_hash:
            raise ValueError(f'档案完整性校验失败（记录 {index}）')
        expected_stage = 'before_feedback' if index == 0 else 'after_feedback'
        if record.get('stage') != expected_stage or record.get('report', {}).get('kind') != 'inference':
            raise ValueError('档案阶段或事实/推断分类无效')
        facts_list(record.get('user_facts'))
        previous_hash = actual_hash
        records.append(record)
    if manifest.get('case_id') != case_id or manifest.get('initial_hash') != records[0]['hash']:
        raise ValueError('初始输入及反馈前报告校验失败')
    if head.get('sequence') != len(records) - 1 or head.get('hash') != previous_hash:
        raise ValueError('档案末端校验失败，可能有缺失记录或未完成的写入')
    if expected_head is not None and expected_head != previous_hash:
        raise ValueError('档案 hash 与外部保存的回执不一致')
    return {'case_id': case_id, 'workspace': str(root), 'integrity': 'verified',
            'audit_scope': 'local_hash_chain; external_expected_head_detects_complete_rewrite',
            'head_hash': previous_hash, 'record_count': len(records), 'records': records}


def init_session(workspace, case_id, input_data, report, user_facts=None):
    root, case = paths(workspace, case_id)
    record = _record(0, 'before_feedback', report, user_facts, None, input_data=input_data)
    root.mkdir(parents=True, exist_ok=True)
    case.parent.mkdir(exist_ok=True)
    case.mkdir(exist_ok=False)
    with _lock(root, case):
        records = case / 'records'
        records.mkdir()
        _write_new(root, records / '000000.json', record)
        _write_new(root, case / 'session.json', {'schema_version': 1, 'case_id': case_id,
                   'created_at': record['created_at'], 'initial_hash': record['hash']})
        _set_head(root, case, record)
    return show_session(workspace, case_id)


def revise_session(workspace, case_id, report, user_facts, note=None, expected_head=None):
    facts = facts_list(user_facts)
    if not facts:
        raise ValueError('反馈后修订需要至少一条用户明确提供的事实')
    root, case = paths(workspace, case_id)
    if not case.is_dir():
        raise ValueError('请先 init 保存初始输入及反馈前报告')
    with _lock(root, case):
        previous = show_session(workspace, case_id, expected_head)
        record = _record(previous['record_count'], 'after_feedback', report, facts,
                         previous['head_hash'], note=note)
        _write_new(root, case / 'records' / f"{record['sequence']:06d}.json", record)
        _set_head(root, case, record)
    return show_session(workspace, case_id)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)
    for name in ('init', 'revise', 'show'):
        sub = subparsers.add_parser(name)
        sub.add_argument('--workspace', required=True, help='档案工作目录绝对路径；不得是技能源码目录')
        sub.add_argument('--case', required=True, help='档案标识，仅字母数字、下划线及短横线')
        if name != 'show':
            sub.add_argument('--report', required=True, help='JSON 报告文件，明确作为推断存储')
            sub.add_argument('--facts', required=name == 'revise', help='JSON 用户事实列表，见 facts_list 格式')
        if name == 'init':
            sub.add_argument('--input', required=True, help='初始输入 JSON 文件')
        else:
            sub.add_argument('--expected-head', help='另存回执中的 hash，用于核对完整档案未被替换')
        if name == 'revise':
            sub.add_argument('--note', help='本次修订说明；按推断/分析备注保存')
    args = parser.parse_args(argv)
    try:
        def read_json(path):
            return json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if args.command == 'show':
            result = show_session(args.workspace, args.case, args.expected_head)
        elif args.command == 'init':
            result = init_session(args.workspace, args.case, read_json(args.input), read_json(args.report),
                                  read_json(args.facts) if args.facts else None)
        else:
            result = revise_session(args.workspace, args.case, read_json(args.report), read_json(args.facts),
                                    args.note, args.expected_head)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, TypeError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
