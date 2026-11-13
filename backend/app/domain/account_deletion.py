"""Erase account records, then finish the local file cleanup before removing the account."""

from psycopg.types.json import Jsonb
from sqlalchemy.exc import IntegrityError

from app.core.config import get_data_dir
from app.core.exceptions import StorageError
from app.db.database import database_connection


DELETED_ACTOR_ID = 'deleted-account'
DELETION_PENDING = 'EXISTS (SELECT 1 FROM account_deletions WHERE user_id=users.id)'
DELETABLE_ROLES = frozenset({'customer', 'analyst'})
ERRORS = {
    'permission_denied': ('仅有效管理员可以删除账号。', 403),
    'admin_user_not_found': ('账号不存在。', 404),
    'admin_revision_conflict': ('账号版本已变化，请刷新后重试。', 409),
    'account_delete_protected': ('账号管理支持永久删除客户和分析员账号。', 409),
    'account_delete_blocked': ('账号关联任务仍在运行或相关记录暂时无法清理。', 409),
    'account_delete_incomplete': ('本机清理未完成，请重试删除。', 503),
}


def _error(code):
    message, status = ERRORS[code]
    return StorageError(code, message, status)


def _target(db, user_id, expected_revision):
    row = db.execute('SELECT role,admin_revision FROM users WHERE id=%s AND id<>%s',
                     (user_id, DELETED_ACTOR_ID)).fetchone()
    if not row:
        raise _error('admin_user_not_found')
    if row['role'] not in DELETABLE_ROLES:
        raise _error('account_delete_protected')
    if row['admin_revision'] != expected_revision:
        raise _error('admin_revision_conflict')


def _erase_records(db, operator, target, revision, plan):
    result = db.execute('SELECT erase_account_records(%s,%s,%s,%s) AS error',
                        (operator, target, revision, Jsonb(plan) if plan is not None else None)).fetchone()
    if result['error']:
        raise _error(result['error'])


def _cleanup_storage_ledger(db, object_ids, assets):
    for asset in assets:
        receipt = asset.get('actor_receipt')
        if receipt is None:
            continue
        reservation = db.execute('''DELETE FROM storage_reservations WHERE id=%s AND project_id=%s
            RETURNING namespace''', (receipt['reservation_id'], receipt['project_id'])).fetchone()
        if not reservation:
            continue
        rows = db.execute('''DELETE FROM storage_references r USING storage_objects o
            WHERE r.project_id=%s AND r.object_id=o.id AND r.kind='candidate_descriptor'
              AND o.namespace=%s AND o.object_key=%s RETURNING o.id''',
            (receipt['project_id'], reservation['namespace'], asset['object_key'])).fetchall()
        object_ids.extend(row['id'] for row in rows)
    db.execute('''DELETE FROM storage_objects o WHERE o.id=ANY(%s)
        AND NOT EXISTS (SELECT 1 FROM storage_references r WHERE r.object_id=o.id)
        AND NOT EXISTS (SELECT 1 FROM storage_reservations s WHERE (s.namespace,s.object_key)=(o.namespace,o.object_key))''',
        (object_ids,))


def delete_account(operator, target, expected_revision):
    from app.domain.account_deletion_assets import collect_account_assets, remove_account_assets
    from app.domain.admin_operations import require_identity
    from app.domain.storage_governance.service import NAMESPACE

    root = get_data_dir()
    try:
        with database_connection(write=True) as db:
            require_identity(db, operator)
            _target(db, target, expected_revision)
            pending = db.execute('SELECT 1 FROM account_deletions WHERE user_id=%s', (target,)).fetchone()
            if not pending:
                projects = [r['id'] for r in db.execute('SELECT id FROM projects WHERE owner_id=%s', (target,))]
                assets = collect_account_assets(db, root, target, projects)
                local_keys = [asset['object_key'] for asset in assets
                              if not asset.get('storage_root') and not asset.get('directory')]
                object_ids = [r['id'] for r in db.execute('''SELECT o.id FROM storage_objects o
                    WHERE EXISTS (SELECT 1 FROM storage_references r WHERE r.object_id=o.id AND r.project_id=ANY(%s))
                       OR EXISTS (SELECT 1 FROM storage_reservations s WHERE (s.namespace,s.object_key)=(o.namespace,o.object_key)
                                  AND s.project_id=ANY(%s))
                       OR (o.namespace=%s AND o.object_key=ANY(%s))''', (projects, projects, NAMESPACE, local_keys))]
                _erase_records(db, operator, target, expected_revision, {'root': str(root), 'files': assets})
                _cleanup_storage_ledger(db, object_ids, assets)
    except IntegrityError as exc:
        raise _error('account_delete_blocked') from exc

    # Commit the cleanup plan before touching files. A failed unlink can then be
    # retried using the same revision and the original list of owned assets.
    try:
        with database_connection(write=True) as db:
            require_identity(db, operator)
            _target(db, target, expected_revision)
            plan = db.execute('SELECT assets FROM account_deletions WHERE user_id=%s',
                              (target,)).fetchone()['assets']
            if plan['root'] != str(root):
                raise _error('account_delete_incomplete')
            try:
                remove_account_assets(db, root, plan['files'])
            except StorageError as exc:
                if exc.code == 'account_delete_blocked':
                    raise StorageError('account_delete_incomplete', exc.message, 503) from exc
                raise
            _erase_records(db, operator, target, expected_revision, None)
    except IntegrityError as exc:
        raise _error('account_delete_incomplete') from exc
    return {'id': target, 'deleted': True}
