"""Trusted local administration of cumulative budgets; no defaults or paid calls."""
import argparse
from decimal import Decimal
import json
import re
import sys

from app.auth.service import normalize_email
from app.core.exceptions import StorageError
from app.db.database import database_connection, get_database_config
from app.domain.model_usage.contracts import MAX_MICRO_USD
from app.domain.model_usage.service import ModelUsageService


def parse_usd(value: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,7}(?:\.[0-9]{1,6})?', value):
        raise ValueError('美元金额须为非负普通十进制数，最多6位小数。')
    amount = int(Decimal(value) * 1_000_000)
    if amount > MAX_MICRO_USD:
        raise ValueError('美元金额超过允许的配置范围。')
    return amount


def main(argv=None):
    parser = argparse.ArgumentParser(description='PaperAssist 本机累计模型预算管理（美元，不自动重置）')
    parser.add_argument('command', choices=['show', 'set'])
    parser.add_argument('--user-email', required=True)
    parser.add_argument('--scope', choices=['user', 'project', 'task'], required=True)
    parser.add_argument('--scope-id')
    parser.add_argument('--limit-usd')
    parser.add_argument('--expected-revision', type=int)
    args = parser.parse_args(argv)
    if args.scope == 'user' and args.scope_id is not None:
        parser.error('用户范围由邮箱确定，不接受 --scope-id。')
    if args.scope != 'user' and not args.scope_id:
        parser.error('项目或任务范围需要 --scope-id。')
    if args.command == 'set' and (args.limit_usd is None or args.expected_revision is None):
        parser.error('set 需要 --limit-usd 和 --expected-revision（首次为0）。')
    if args.command == 'show' and (args.limit_usd is not None or args.expected_revision is not None):
        parser.error('show 只读，不接受金额或期望修订号。')
    try:
        amount = parse_usd(args.limit_usd) if args.command == 'set' else None
        email = normalize_email(args.user_email)
        config = get_database_config()
        with database_connection(config=config) as db:
            user = db.execute('SELECT id FROM users WHERE email=%s AND active', (email,)).fetchone()
        if user is None:
            print('未找到启用的目标账号。', file=sys.stderr)
            return 1
        service = ModelUsageService(user['id'], config)
        scope_key = user['id'] if args.scope == 'user' else args.scope_id
        if args.command == 'set':
            result = service.set_budget(args.scope, scope_key, amount, args.expected_revision)
        else:
            result = service.get_budget(args.scope, scope_key)
        print(json.dumps({'currency': 'USD', 'period': 'cumulative', **result}, ensure_ascii=False))
        return 0
    except StorageError as exc:
        # Codes are controlled by our domain; messages can originate at database boundaries.
        safe_code = exc.code if re.fullmatch(r'[a-z_]{1,80}', exc.code or '') else 'model_budget_operation_failed'
        print(f'预算操作未完成（{safe_code}），请核对目标、当前版本和数据库状态。', file=sys.stderr)
    except Exception:
        print('预算操作未完成，请核对参数、运行连接和数据库状态；不输出连接信息。', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
