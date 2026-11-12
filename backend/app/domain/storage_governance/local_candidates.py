"""Local immutable artifacts with a metered business envelope on the v2 ledger.

Callers own the writer and must validate current typed source and authorization.
This module has no provider, connection ownership, or task transition authority.
"""
import json
from pathlib import Path

from . import service as s
from . import candidates as c


def encode(value):
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                     separators=(',', ':')).encode('utf-8')
    if len(raw) > c.DESCRIPTOR_LIMIT:
        raise s.invalid()
    return raw


def lookup(db, root, project_id, operation, *, kind, task_id=None, include_released=False):
    if s.reconcile_intents(db, root):
        raise s.invalid()
    row = db.execute('SELECT * FROM storage_reservations WHERE namespace=%s AND project_id=%s AND operation_key=%s',
        (s.NAMESPACE, project_id, operation)).fetchone()
    if row is None:
        return None
    row = dict(row)
    if (row['owner_id'] != s._project(db, project_id)['owner_id'] or row['kind'] != kind
            or row['task_id'] != task_id or row['capacity_bytes'] is None
            or (row['state'] == 'released' and not include_released)):
        raise s.invalid()
    return row


def release_empty(db, root, row):
    """Release only an unpublished local hold whose exact paths are absent."""
    metadata = row['candidate_json']
    if row['state'] not in s.ACTIVE or metadata.get('descriptor_complete'):
        return False
    keys = {row['object_key'], f"storage-candidates/{row['id']}.json", *metadata.get('locations', ())}
    if metadata.get('descriptor'):
        keys.add(metadata['descriptor']['object_key'])
    for key in keys | {f".storage-intents/{row['id']}.complete.json"}:
        try:
            c._path(root, key).lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise s.invalid() from exc
        return False
    if db.execute('SELECT 1 FROM storage_objects WHERE namespace=%s AND object_key=ANY(%s)',
                  (s.NAMESPACE, list(keys))).fetchone():
        return False
    s.release(db, row['id'])
    return True


def read(root, row, source_identity):
    if row['candidate_json']['source_identity'] != source_identity:
        raise s.invalid()
    envelope = c.read_descriptor(root, row)
    paths = c._present(root, row)
    if len(paths) != 1 or not c._descriptor_completed(root, row):
        raise s.invalid()
    expected = dict(schema_version=1, kind=row['kind'], project_id=row['project_id'],
                    owner_id=row['owner_id'], operation_key=row['operation_key'],
                    task_id=row['task_id'], source_identity=source_identity)
    if any(envelope.get(k) != v for k, v in expected.items()):
        raise s.invalid()
    return envelope['value'], paths[0].read_bytes()


def capture(db, root, project_id, operation, target, content, value, *, source_identity, kind, task_id=None, staged=None, progress=None):
    owner = s._project(db, project_id)['owner_id']
    envelope = encode(dict(schema_version=1, kind=kind, project_id=project_id, owner_id=owner,
        operation_key=operation, task_id=task_id, source_identity=source_identity, value=value))
    row = s.admit_candidate(db, root, project_id, operation, target, max(1, len(content)+len(envelope)),
        task_id=task_id, source_identity=source_identity, kind=kind, progress=progress)
    descriptor = Path(root)/'storage-candidates'/(row['id']+'.json')
    return s.capture_candidate(db, root, row['id'], content, [staged or target, target],
        source_identity=source_identity, descriptor=envelope, descriptor_path=descriptor,
        write_path=staged or target)
