"""Offline local administration of evidenced actual costs, without provider calls."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import sys

from app.auth.service import normalize_email
from app.core.exceptions import StorageError
from app.db.database import database_connection, get_database_config
from app.domain.model_usage.contracts import MAX_ACCOUNTED_MICRO_USD


RECORD_FIELDS = frozenset({
    'event_key', 'expected_revision', 'component', 'amount_usd', 'evidence_kind',
    'evidence_reference', 'provider_object_id', 'evidence_file',
})
RECEIPT_FIELDS = (
    'call_id', 'revision', 'component', 'actual_micro_usd', 'reconciliation_status',
    'accounted_before_micro_usd', 'accounted_after_micro_usd', 'delta_micro_usd',
    'reserved_after_micro_usd',
)
REQUEST_FIELDS = (
    'event_key', 'expected_revision', 'component', 'amount_micro_usd', 'evidence_kind',
    'evidence_reference', 'evidence_sha256', 'provider_object_id', 'operator',
)
MAX_RECORD_BYTES = 1_048_576
MAX_EVIDENCE_BYTES = 64 * 1_048_576


def parse_usd(value: str) -> int:
    """Convert decimal text exactly, using the ledger BIGINT rather than budget limit."""
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,6})?', value):
        raise ValueError('金额须为非负普通十进制文本，最多6位小数。')
    whole, _, fraction = value.partition('.')
    whole = whole.lstrip('0') or '0'
    if len(whole) > 13:
        raise ValueError('金额超过微美元存储范围。')
    amount = int(whole) * 1_000_000 + int(fraction.ljust(6, '0'))
    if amount > MAX_ACCOUNTED_MICRO_USD:
        raise ValueError('金额超过微美元存储范围。')
    return amount


def _local_path(value):
    """Reject UNC/device paths and mapped network drives before reading a file."""
    raw = os.fspath(value)
    if not isinstance(raw, str) or '\x00' in raw or raw.startswith(('\\\\', '//')):
        raise ValueError('只接受本机文件。')
    if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', raw):
        raise ValueError('只接受本机文件。')
    path = Path(os.path.abspath(raw))
    if os.name == 'nt':
        import ctypes
        if ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) == 4:
            raise ValueError('只接受本机文件。')
    resolved = path.resolve(strict=True)
    if str(resolved).startswith(('\\\\', '//')):
        raise ValueError('只接受本机文件。')
    if os.name == 'nt':
        if ctypes.windll.kernel32.GetDriveTypeW(str(resolved.anchor)) == 4:
            raise ValueError('只接受本机文件。')
    return resolved


def _read_regular(path, maximum, *, digest=False):
    with path.open('rb') as source:
        details = os.fstat(source.fileno())
        if not stat.S_ISREG(details.st_mode) or details.st_size > maximum:
            raise ValueError('文件不是允许大小的普通文件。')
        if not digest:
            content = source.read(maximum + 1)
            if len(content) > maximum:
                raise ValueError('文件过大。')
            return content
        checksum = hashlib.sha256()
        total = 0
        while block := source.read(65_536):
            total += len(block)
            if total > maximum:
                raise ValueError('文件过大。')
            checksum.update(block)
        if total == 0:
            raise ValueError('凭证原件不能为空。')
        return checksum.hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('记录不能包含重复字段。')
        result[key] = value
    return result


def load_record(record_file):
    """Hash local original bytes and construct the strict internal evidence request."""
    from app.domain.model_usage.reconciliation_contracts import ReconciliationRequest

    record_path = _local_path(record_file)
    data = json.loads(_read_regular(record_path, MAX_RECORD_BYTES).decode('utf-8'),
                      object_pairs_hook=_unique_object)
    if not isinstance(data, dict) or set(data) != RECORD_FIELDS:
        raise ValueError('记录必须包含且仅包含规定的八个字段。')
    evidence_name = data['evidence_file']
    if (not isinstance(evidence_name, str) or not evidence_name
            or Path(evidence_name).is_absolute() or PureWindowsPath(evidence_name).drive
            or PureWindowsPath(evidence_name).root
            or re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', evidence_name)):
        raise ValueError('凭证原件须为记录目录内的相对文件。')
    evidence_path = _local_path(record_path.parent / evidence_name)
    if not evidence_path.is_relative_to(record_path.parent):
        raise ValueError('凭证原件须为记录目录内的相对文件。')
    evidence_sha256 = _read_regular(evidence_path, MAX_EVIDENCE_BYTES, digest=True)
    request = {key: data[key] for key in RECORD_FIELDS - {'amount_usd', 'evidence_file'}}
    request.update(amount_micro_usd=parse_usd(data['amount_usd']),
        evidence_sha256=evidence_sha256, operator=getpass.getuser())
    return ReconciliationRequest.model_validate(request)


def _pick(value, fields):
    return {key: value[key] for key in fields if key in value}


def _show_result(result):
    """Only admin accounting/audit fields may leave the process on stdout."""
    shown = _pick(result, (
        'call_id', 'status', 'provider_response_id', 'estimated_cost_micro_usd',
        'usage_status', 'reconciliation_revision',
    ))
    shown['container_id'] = (result.get('provider_state') or {}).get('container_id')
    shown['reconciliation'] = _pick(result.get('reconciliation') or {}, (
        'status', 'token_micro_usd', 'tool_micro_usd', 'tool_applicable',
        'actual_micro_usd', 'reconciled_at',
    ))
    shown['history'] = []
    for item in result.get('history', []):
        event = _pick(item, ('event_key', 'created_at'))
        payload = item.get('reconciliation') or {}
        event['reconciliation'] = _pick(payload, (
            'operator', 'revision', 'previous_actual_micro_usd', 'actual_micro_usd',
            'accounted_before_micro_usd', 'accounted_after_micro_usd', 'delta_micro_usd',
            'reserved_after_micro_usd',
        ))
        if 'request' in payload:
            event['reconciliation']['request'] = _pick(payload['request'], REQUEST_FIELDS)
        if 'receipt' in payload:
            event['reconciliation']['receipt'] = _pick(payload['receipt'], RECEIPT_FIELDS)
        shown['history'].append(event)
    return shown


def _json_date(value):
    from datetime import datetime
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError('Unsupported administration output.')


class _SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default includes arbitrary input values and source paths.
        self.exit(2, '命令参数无效；请用 --help 查看 show/preview/apply 的参数。\n')


def main(argv=None):
    parser = _SafeParser(description='PaperAssist 本机实际费用核对（离线凭证，USD）')
    parser.add_argument('command', choices=['show', 'preview', 'apply'])
    parser.add_argument('--user-email', required=True)
    parser.add_argument('--call-id', required=True)
    parser.add_argument('--record-file')
    args = parser.parse_args(argv)
    if (args.command == 'show') == (args.record_file is not None):
        parser.error('show 不接受记录文件，preview/apply 必须提供记录文件。')
    try:
        from app.domain.model_usage.reconciliation import ModelReconciliationService

        request = load_record(args.record_file) if args.command != 'show' else None
        email = normalize_email(args.user_email)
        config = get_database_config()
        with database_connection(config=config) as db:
            user = db.execute('SELECT id FROM users WHERE email=%s AND active', (email,)).fetchone()
        if user is None:
            print('未找到启用的目标账号。', file=sys.stderr)
            return 1
        service = ModelReconciliationService(user['id'], config)
        if args.command == 'show':
            result = _show_result(service.inspect(args.call_id))
        elif args.command == 'preview':
            result = _pick(service.preview(args.call_id, request), RECEIPT_FIELDS)
        else:
            result = _pick(service.reconcile(args.call_id, request), RECEIPT_FIELDS)
        print(json.dumps(result, ensure_ascii=False, default=_json_date, allow_nan=False))
        return 0
    except StorageError as exc:
        safe_code = exc.code if re.fullmatch(r'[a-z_]{1,80}', exc.code or '') else 'model_reconciliation_operation_failed'
        print(f'实际费用核对未完成（{safe_code}），请核对调用、凭证和当前修订号。', file=sys.stderr)
    except Exception:
        print('实际费用核对未完成，请核对本机记录、凭证和运行连接；不输出原件或连接信息。', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
