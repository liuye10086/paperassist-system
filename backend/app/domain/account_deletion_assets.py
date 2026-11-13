"""Plan and remove exact local assets under the account deletion writer fence."""
from collections import defaultdict
import hashlib
from itertools import chain
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat

from app.core.exceptions import StorageError
from app.domain.bio_insights.bulk_delivery_cache import cache_pool, cache_scope, project_slot_key
from app.domain.storage_governance import service as ledger
from app.domain.storage_governance import candidates, historical


_UUID = r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'
_JOURNAL_NAME = re.compile(rf'({_UUID})(?:\.(allocation|capture|complete))?\.json')
_STAGING_NAME = re.compile(rf'(.+)\.(?:[0-9a-f]{{32}}|{_UUID})\.part')
_JOURNAL_SCOPE_FIELDS = ('namespace', 'project_id', 'owner_id', 'object_key', 'operation_key', 'kind', 'task_id')
_BULK_CACHE_KINDS = ('facts', 'word', 'archive', 'sensitivity')


def _blocked(message):
    return StorageError('account_delete_blocked', message, 409)


def _incomplete():
    return StorageError('account_delete_incomplete', '部分本地资料暂时无法读取或删除，请检查磁盘和文件占用后重试。', 503)


def _key_parts(key):
    if not isinstance(key, str):
        raise _blocked('本地资料路径无效，请核对存储记录。')
    parts = key.split('/')
    if any(part in ('', '.', '..') or part.endswith(('.', ' ')) or PureWindowsPath(part).is_reserved()
           or re.search(r'[\\:\x00-\x1f<>"|?*]', part) for part in parts):
        raise _blocked('本地资料路径无效，请核对存储记录。')
    return parts


def _file_status(root, key):
    parts = _key_parts(key)
    root = Path(root).absolute()
    path = root.joinpath(*parts)
    try:
        current = root
        info = current.lstat()
        for part in parts:
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise _blocked('本地资料路径含有链接，请核对存储记录。')
            current = current / part
            info = current.lstat()
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise _blocked('本地资料路径含有链接，请核对存储记录。')
        if ledger._key(root, path) != key or path.resolve() != path:
            raise _blocked('本地资料路径无法安全核对，请检查存储根目录和链接。')
        return path, info
    except FileNotFoundError:
        return path, None
    except StorageError as exc:
        if exc.code == 'account_delete_blocked':
            raise
        raise _blocked('本地资料路径无法安全核对，请检查存储根目录和链接。') from None
    except (OSError, RuntimeError):
        raise _incomplete() from None


def _file_identity(path, info):
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise _blocked('本地资料不是可独立删除的普通文件，请核对共享链接和存储记录。')
    try:
        return ledger._digest(path)
    except FileNotFoundError:
        return None
    except OSError:
        raise _incomplete() from None


def _directory_entries(path):
    try:
        return sorted(path.iterdir())
    except FileNotFoundError:
        return []
    except OSError:
        raise _incomplete() from None


def _reservations(db):
    return {row['id']: row for row in db.execute('SELECT * FROM storage_reservations WHERE namespace=%s', (ledger.NAMESPACE,))}


def _reservation_assets(row):
    yield row
    candidate = row.get('candidate_json') or row
    locations = candidate.get('locations', [])
    if not isinstance(locations, list):
        raise ValueError('Invalid candidate locations')
    for key in locations:
        yield {**row, 'object_key': key}
    if candidate.get('descriptor') is not None:
        yield {**row, **historical.descriptor(candidate['descriptor'])}


def _references(db, root, reservations, owned_projects):
    yield from db.execute('''SELECT o.object_key,o.size_bytes,o.sha256,r.project_id,r.owner_id,r.kind AS ref_kind
        FROM storage_objects o JOIN storage_references r ON r.object_id=o.id WHERE o.namespace=%s''', (ledger.NAMESPACE,))
    for row in reservations.values():
        try:
            yield from _reservation_assets(row)
        except (AttributeError, KeyError, TypeError, ValueError, StorageError):
            if row['project_id'] in owned_projects:
                raise _blocked('项目暂存资料的记录不完整，请核对后重试。') from None

    def invalid_history(_kind):
        raise _blocked('项目历史资料的存储记录不完整，请核对后重试。')

    yield from historical.references(db, root, invalid_history, {}, error_projects=owned_projects)


def _journals(root, reservations, owned_projects):
    directory, info = _file_status(root, '.storage-intents')
    if info is None:
        return
    if not stat.S_ISDIR(info.st_mode):
        raise _blocked('存储操作日志目录无效，请核对本地存储。')
    for entry in _directory_entries(directory):
        match = _JOURNAL_NAME.fullmatch(entry.name)
        if match is None:
            continue
        identifier, stage = match.groups()
        registered = reservations.get(identifier)
        key = '.storage-intents/' + entry.name
        journal_project = None
        try:
            path, info = _file_status(root, key)
            if info is None:
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('Unsafe journal')
            with path.open('rb') as stream:
                raw = stream.read(8193)
            if len(raw) > 8192:
                raise ValueError('Oversized journal')
            value = json.loads(raw)
            if not isinstance(value.get('project_id'), str):
                raise ValueError('Invalid journal project')
            journal_project = value['project_id']
            if (value['id'] != identifier or value['namespace'] != ledger.NAMESPACE
                    or value.get('stage') != stage or stage is not None and value.get('version') != 2):
                raise ValueError('Invalid journal identity')
            if registered and any(value[name] != registered[name] for name in _JOURNAL_SCOPE_FIELDS):
                raise ValueError('Conflicting journal identity')
            records = list(_reservation_assets(value))
            journal = {**value, 'object_key': key, 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
            yield journal, records
        except (AttributeError, KeyError, TypeError, ValueError, StorageError) as exc:
            if isinstance(exc, StorageError) and exc.code == 'account_delete_incomplete':
                raise
            if (journal_project in owned_projects or registered and registered['project_id'] in owned_projects
                    or journal_project is None and registered is None and owned_projects):
                raise _blocked('存在无法归属的存储操作日志，请核对本地存储后重试。') from None
        except OSError:
            raise _incomplete() from None


def _actor_receipts(root, user_id, owned_projects, reservations, journals):
    receipts = {}
    for row in chain(reservations.values(), (records[0] for _, records in journals)):
        operation = row.get('operation_key', '')
        if row.get('project_id') in owned_projects or not operation.startswith(('native-delivery:', 'native-delivery-retry:')):
            continue
        candidate = row.get('candidate_json') or row
        descriptor = candidate.get('descriptor') if isinstance(candidate, dict) else None
        key = f"storage-candidates/{row['id']}.json"
        if not isinstance(descriptor, dict) or descriptor.get('object_key') != key:
            continue
        try:
            _, info = _file_status(root, key)
            if info is None or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                continue
            envelope = candidates.read_descriptor(root, {'candidate_json': candidate})
            expected = dict(schema_version=1, kind='original', project_id=row['project_id'], owner_id=row['owner_id'],
                            operation_key=operation, task_id=None, source_identity=candidate['source_identity'])
            if (any(envelope.get(field) != value for field, value in expected.items())
                    or envelope['value'].get('actor_id') != user_id):
                continue
            receipt = dict(reservation_id=row['id'], project_id=row['project_id'])
            receipts[os.path.normcase(key)] = {**historical.descriptor(descriptor), 'actor_receipt': receipt}
        except (AttributeError, KeyError, TypeError, ValueError, StorageError):
            # A foreign descriptor with unproven attribution stays with its project.
            continue
    return receipts


def _assigned_upload_receipts(root, user_id, owned_projects, reservations, journals):
    actor_hash = hashlib.sha256(user_id.encode()).hexdigest()
    operation = re.compile(rf'sync-assignment:{actor_hash}:{_UUID}:[0-9a-f]{{64}}')
    known_journals = {journal['object_key']: journal for journal, _ in journals}
    receipts = {}
    for row in reservations.values():
        if (row['project_id'] in owned_projects or row.get('state') != 'settled' or row['kind'] != 'original'
                or row['task_id'] is not None or not operation.fullmatch(row['operation_key'])):
            continue
        key = f".storage-intents/{row['id']}.json"
        journal = known_journals.get(key)
        if journal is None and _file_status(root, key)[1] is not None:
            raise _blocked('代传文件的操作日志无法核对，请检查本地存储后重试。')
        record = historical.descriptor(journal) if journal else dict(object_key=key, metadata_only=True)
        record['actor_receipt'] = dict(reservation_id=row['id'], project_id=row['project_id'])
        receipts[os.path.normcase(key)] = record
    return receipts


def _remember(row, user_id, owned_projects, actor_scopes, planned, protected):
    key = row.get('object_key')
    if row.get('project_id') not in owned_projects:
        if isinstance(key, str):
            comparison = os.path.normcase(key)
            receipt = actor_scopes.get(comparison)
            if (receipt and row['project_id'] == receipt['project_id']
                    and (row.get('id') == receipt['reservation_id'] or row.get('ref_kind') == 'candidate_descriptor')):
                return
            protected.add(comparison)
        return
    if row.get('owner_id') not in (None, user_id):
        raise _blocked('项目资料的所有者与账号不一致，请核对存储记录。')
    _plan_member(row, planned)


def _plan_member(row, planned):
    key = row.get('object_key')
    _key_parts(key)
    comparison_key = os.path.normcase(key)
    entry = planned[comparison_key]
    entry['key'] = key
    if row.get('sha256') is not None:
        descriptor = historical.descriptor(dict(row))
        entry['identities'].add((descriptor['size_bytes'], descriptor['sha256']))


def _staging_files(root, planned, protected):
    """Find abandoned temporary names derived from an attributable destination."""
    owned = planned.keys() - protected
    parents = {planned[key]['key'].rpartition('/')[0] for key in owned}
    for parent in sorted(parents - {''}):
        directory, info = _file_status(root, parent)
        if info is None:
            continue
        for entry in _directory_entries(directory):
            match = _STAGING_NAME.fullmatch(entry.name)
            if match:
                destination = f'{parent}/{match[1]}'
            elif parent in ('figures', 'reports') and entry.name.endswith('.part'):
                suffix = '.png' if parent == 'figures' else '.docx'
                destination = f'{parent}/{entry.name.removesuffix(".part")}{suffix}'
            else:
                continue
            key = f'{parent}/{entry.name}'
            comparison = os.path.normcase(key)
            if os.path.normcase(destination) not in owned or comparison in planned or comparison in protected:
                continue
            path, status = _file_status(root, key)
            identity = _file_identity(path, status) if status is not None else None
            if identity is not None:
                size, digest = identity
                yield dict(object_key=key, size_bytes=size, sha256=digest)


def _path_digest(path):
    return hashlib.sha256(os.path.normcase(str(Path(path).absolute())).encode()).hexdigest()


def _scoped_files(root, key, storage_root='assets'):
    path, info = _file_status(root, key)
    if info is None:
        return
    if not stat.S_ISDIR(info.st_mode):
        raise _blocked('项目缓存目录无效，请核对本地存储。')
    scope = dict(storage_root=storage_root)
    if storage_root == 'bulk_cache':
        scope['root_sha256'] = _path_digest(root)
    pending = [key]
    while pending:
        key = pending.pop()
        path, info = _file_status(root, key)
        if info is None:
            continue
        row = dict(object_key=key, **scope)
        if stat.S_ISDIR(info.st_mode):
            pending.extend(key + '/' + child.name for child in reversed(_directory_entries(path)))
            yield dict(row, directory=True)
        else:
            identity = _file_identity(path, info)
            if identity is not None:
                size, digest = identity
                yield dict(row, size_bytes=size, sha256=digest)


def collect_account_assets(db, root, user_id, project_ids):
    """Capture verified, exclusively owned local keys before removing their metadata."""
    owned_projects = frozenset(project_ids)
    if owned_projects:
        projects = db.execute('SELECT id,owner_id FROM projects WHERE id=ANY(%s)', (list(owned_projects),))
        if {row['id'] for row in projects if row['owner_id'] == user_id} != owned_projects:
            raise _blocked('项目归属已变化，请重新确认账号删除范围。')
        for project in sorted(owned_projects):
            acquired = db.execute('SELECT pg_catalog.pg_try_advisory_xact_lock(%s) AS acquired',
                                  (project_slot_key(db.config, project),)).fetchone()['acquired']
            if not acquired:
                raise _blocked('项目正在生成 Bulk RNA-seq 交付资料，请等待任务完成后重试。')
    reservations = _reservations(db)
    journals = list(_journals(root, reservations, owned_projects))
    receipts = _actor_receipts(root, user_id, owned_projects, reservations, journals)
    receipts.update(_assigned_upload_receipts(root, user_id, owned_projects, reservations, journals))
    if not owned_projects and not receipts:
        return []
    actor_scopes = {key: row['actor_receipt'] for key, row in receipts.items()}
    receipts_by_id = {receipt['reservation_id']: receipt for receipt in actor_scopes.values()}
    actor_journals = [journal for journal, _ in journals if journal['id'] in receipts_by_id]
    actor_scopes.update({os.path.normcase(row['object_key']): receipts_by_id[row['id']] for row in actor_journals})
    planned = defaultdict(lambda: {'identities': set()})
    protected = set()
    try:
        for row in _references(db, root, reservations, owned_projects):
            _remember(row, user_id, owned_projects, actor_scopes, planned, protected)
        for journal, records in journals:
            for row in [journal, *records]:
                _remember(row, user_id, owned_projects, actor_scopes, planned, protected)
        for row in chain(receipts.values(), actor_journals):
            if not row.get('metadata_only'):
                _plan_member(row, planned)
    except StorageError as exc:
        if exc.code in ('account_delete_blocked', 'account_delete_incomplete'):
            raise
        raise _blocked('项目资料的大小或校验值无效，请核对存储记录。') from None

    if actor_scopes.keys() & protected:
        raise _blocked('交付资料的操作回执仍有共享引用，请核对后重试。')
    assets = []
    for comparison_key in sorted(planned.keys() - protected):
        entry = planned[comparison_key]
        key = entry['key']
        path, info = _file_status(root, key)
        identity = _file_identity(path, info) if info is not None else None
        receipt = receipts.get(comparison_key)
        if identity is None and receipt is None:
            continue
        if identity is None:
            identity = receipt['size_bytes'], receipt['sha256']
        if entry['identities'] != {identity}:
            raise _blocked('项目资料的实际内容与存储记录不一致，请核对后重试。')
        size, digest = identity
        row = dict(object_key=key, size_bytes=size, sha256=digest)
        if receipt is not None:
            row['actor_receipt'] = receipt['actor_receipt']
        assets.append(row)
    assets.extend(row for row in receipts.values() if row.get('metadata_only'))
    assets.extend(_staging_files(root, planned, protected))

    if owned_projects:
        pool = cache_pool(root, db.config)
        for project in sorted(owned_projects):
            if re.fullmatch(r'[A-Za-z0-9_-]{1,128}', project):
                assets.extend(_scoped_files(root, f'bio-reader-narratives/{project}'))
            for kind in _BULK_CACHE_KINDS:
                scope = cache_scope(user_id, project, kind)
                assets.extend(_scoped_files(pool, scope, 'bulk_cache'))
    return assets


def remove_account_assets(db, root, assets):
    """Remove previously captured bytes if unchanged and still unreferenced."""
    if not assets:
        return
    reservations = _reservations(db)
    protected = {os.path.normcase(row['object_key']) for row in _references(db, root, reservations, frozenset())
                 if isinstance(row.get('object_key'), str)}
    plan_keys = {os.path.normcase(row['object_key']) for row in assets if row.get('storage_root', 'assets') == 'assets'}
    for journal, records in _journals(root, reservations, frozenset()):
        key = os.path.normcase(journal['object_key'])
        if key not in plan_keys or journal['id'] in reservations:
            protected.add(key)
            protected.update(os.path.normcase(row['object_key']) for row in records if isinstance(row.get('object_key'), str))

    paths = []
    directories = []
    pool = cache_pool(root, db.config)
    pool_digest = _path_digest(pool)
    for row in assets:
        key = row['object_key']
        area = row.get('storage_root', 'assets')
        if area not in ('assets', 'bulk_cache') or area == 'bulk_cache' and row.get('root_sha256') != pool_digest:
            raise _blocked('本地缓存位置在删除前发生变化，请核对后重试。')
        is_local_asset = area == 'assets'
        comparison = os.path.normcase(key)
        if is_local_asset and comparison in protected:
            if 'actor_receipt' in row:
                raise _blocked('交付资料的操作回执仍有引用，请核对后重试。')
            continue
        base = root if is_local_asset else pool
        path, info = _file_status(base, key)
        if info is None:
            continue
        if row.get('metadata_only'):
            raise _blocked('代传文件的操作日志在删除前发生变化，请核对后重试。')
        if row.get('directory'):
            if not stat.S_ISDIR(info.st_mode):
                raise _blocked('项目缓存目录在删除前发生变化，请核对后重试。')
            prefix = comparison + os.sep
            if not is_local_asset or not any(other.startswith(prefix) for other in protected):
                directories.append((base, key))
            continue
        identity = _file_identity(path, info)
        if identity is None:
            continue
        if identity != (row['size_bytes'], row['sha256']):
            raise _blocked('项目资料在删除前发生变化，请核对本地文件后重试。')
        paths.append((base, key, info))
    for base, key, expected in paths:
        path, actual = _file_status(base, key)
        if actual is None:
            continue
        if (actual.st_dev, actual.st_ino, actual.st_nlink, actual.st_size, actual.st_mtime_ns) != (
                expected.st_dev, expected.st_ino, expected.st_nlink, expected.st_size, expected.st_mtime_ns):
            raise _blocked('项目资料在删除前发生变化，请核对本地文件后重试。')
        try:
            path.unlink(missing_ok=True)
        except OSError:
            raise _incomplete() from None
    for base, key in sorted(directories, key=lambda item: item[1].count('/'), reverse=True):
        path, info = _file_status(base, key)
        if info is None:
            continue
        try:
            path.rmdir()
        except FileNotFoundError:
            continue
        except OSError:
            raise _incomplete() from None
