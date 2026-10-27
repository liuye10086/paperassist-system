"""Consistent backup evidence and safe read-only administrator result summaries."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
from uuid import UUID

from app.db.database import SCHEMA_HEAD
from app.maintenance.recovery_drill import DrillError, require, sha, verify_assets, rows_fingerprint

SCHEMA = re.compile(r'pa_test_[0-9a-f]{32}\Z')
HASH = re.compile(r'[0-9a-f]{64}\Z')
OPERATIONAL_TABLES = frozenset({'sessions', 'auth_login_attempts', 'operational_request_events'})


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def file_manifest(root):
    entries = []
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'symlink_not_supported')
        if path.is_file():
            entries.append(dict(path=path.relative_to(root).as_posix(), bytes=path.stat().st_size, sha256=sha(path)))
    return entries


def validate_files(root, entries):
    require(isinstance(entries, list), 'invalid_file_manifest')
    seen = set()
    for item in entries:
        path = item['path']
        require(isinstance(path, str) and path and path not in seen and '\\' not in path and ':' not in path
                and not PurePosixPath(path).is_absolute() and '..' not in PurePosixPath(path).parts
                and PurePosixPath(path).as_posix() == path, 'invalid_file_path')
        require(type(item['bytes']) is int and item['bytes'] >= 0 and HASH.fullmatch(item['sha256']), 'invalid_file_hash')
        require(not (root / path).is_symlink(), 'symlink_not_supported')
        seen.add(path)
    return verify_assets(root, entries)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def validate_backup(source, *, manifest_name='manifest.json'):
    value = read_json(source / manifest_name)
    require(value['format_version'] == 1 and value['synthetic_only'] is True
            and value['schema_revision'] == SCHEMA_HEAD and SCHEMA.fullmatch(value['source_schema']), 'invalid_backup_manifest')
    UUID(value['consistency_id'])
    require(read_json(source / 'manifest-receipt.json')['sha256'] == sha(source / manifest_name), 'manifest_hash_mismatch')
    for name, entry in value['evidence'].items():
        require(name in {'database.dump', 'asset-manifest.json', 'code-manifest.json', 'before-fingerprints.json',
                         'sequences.json', 'expected-api.json'}, 'unexpected_evidence')
        path = source / name
        require(path.is_file() and path.stat().st_size == entry['bytes'] and sha(path) == entry['sha256'], 'evidence_mismatch')
    require(set(value['evidence']) == {'database.dump', 'asset-manifest.json', 'code-manifest.json',
            'before-fingerprints.json', 'sequences.json', 'expected-api.json'}, 'missing_evidence')
    validate_files(source / 'assets', read_json(source / 'asset-manifest.json'))
    code = read_json(source / 'code-manifest.json')
    require(all(not any(part.startswith('.env') or part in {'data', 'backups', '.venv', '__pycache__', 'keys', 'private'}
                        for part in PurePosixPath(item['path']).parts) for item in code), 'unsafe_code_copy')
    validate_files(source / 'code', code)
    require(read_json(source / 'expected-api.json')['source_schema'] == value['source_schema'], 'expected_api_wrong_source')
    return value


def validate_archive(listing, schema):
    require(SCHEMA.fullmatch(schema), 'invalid_source_schema')
    schemas = re.findall(r'^\d+; \d+ \d+ SCHEMA - (\S+) ', listing, re.M)
    require(schemas == [schema], 'archive_schema_mismatch')
    # Every named namespace in a TOC entry must belong to the captured schema.
    for line in listing.splitlines():
        if not re.match(r'^\d+; ', line):
            continue
        body = re.sub(r'^\d+; \d+ \d+ ', '', line)
        match = re.match(r'(?:TABLE DATA|SEQUENCE OWNED BY|SEQUENCE SET|TABLE|SEQUENCE|INDEX|CONSTRAINT|FK CONSTRAINT|TRIGGER|FUNCTION|DEFAULT) (\S+) ', body)
        require(not match or match[1] == schema, 'archive_other_schema')


def database_fingerprints(connection, schema):
    from psycopg import sql
    from psycopg.rows import dict_row
    tables = connection.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s AND table_type='BASE TABLE' ORDER BY table_name", (schema,)).fetchall()
    result = {}
    with connection.cursor(row_factory=dict_row) as cursor:
        for (table,) in tables:
            cursor.execute(sql.SQL('SELECT * FROM {}.{}').format(sql.Identifier(schema), sql.Identifier(table)))
            rows = cursor.fetchall()
            result[table] = dict(columns=[column.name for column in cursor.description], rows=len(rows), sha256=rows_fingerprint(rows))
    return result


def business_unchanged(before, after):
    require(before.keys() == after.keys(), 'table_set_changed')
    changed = sorted(name for name in before if before[name] != after[name])
    require(set(changed) <= OPERATIONAL_TABLES, 'business_changed_after_http')
    return changed


def operational_rows(connection, schema):
    from psycopg import sql
    from psycopg.rows import dict_row
    with connection.cursor(row_factory=dict_row) as cursor:
        result = {}
        for table in OPERATIONAL_TABLES:
            cursor.execute(sql.SQL('SELECT * FROM {}.{}').format(sql.Identifier(schema), sql.Identifier(table)))
            result[table] = list(cursor.fetchall())
        return result


def verify_operational_delta(before, after, http, finished_epoch):
    """Bound permitted writes to these exact HTTP requests and login identities."""
    receipt = {}
    keys = {'sessions': 'token_hash', 'auth_login_attempts': 'id', 'operational_request_events': 'request_id'}
    for table, key in keys.items():
        old = {row[key]: row for row in before[table]}
        new = {row[key]: row for row in after[table]}
        require(all(old[identity] == new[identity] for identity in old.keys() & new.keys()), 'existing_operational_row_changed')
        removed = old.keys() - new.keys()
        added = new.keys() - old.keys()
        if table == 'auth_login_attempts':
            require(not added and all(old[identity]['attempted_at'] < finished_epoch - 900 for identity in removed), 'unexpected_login_attempt_delta')
        else:
            require(not removed, 'operational_rows_removed')
            if table == 'sessions':
                require(sorted(new[identity]['user_id'] for identity in added) == sorted(item['id'] for item in http['identities']), 'unexpected_sessions')
            else:
                expected = {item['request_id']: item for item in http['requests']}
                require(added == expected.keys(), 'request_receipt_set_mismatch')
                require(all(new[identity]['method'] == expected[identity]['method'] and new[identity]['status'] == expected[identity]['status'] for identity in added), 'request_receipt_mismatch')
        receipt[table] = dict(added=len(added), removed=len(removed), existing_rows_unchanged=True,
                             before_sha256=rows_fingerprint(before[table]), after_sha256=rows_fingerprint(after[table]))
    return receipt


def result_summary(schema):
    return dict(format_version=1, source_schema=schema, synthetic_only=True, retention='indefinite',
                backup=dict(status='unknown', consistency_id=None, finished_at=None, manifest_sha256=None, asset_count=None, table_count=None),
                restore=dict(status='unknown', finished_at=None, duration_seconds=None, verification='unknown'))


def status_summary(path, schema):
    unknown = dict(status='unavailable', **result_summary(schema))
    if not path:
        return unknown
    try:
        raw = read_json(Path(path))
        require(raw['format_version'] == 1 and raw['source_schema'] == schema
                and raw['synthetic_only'] is True and raw['retention'] == 'indefinite', 'invalid_status')
        value = result_summary(schema)
        for section in ('backup', 'restore'):
            for key in value[section]:
                item = raw[section][key]
                if key == 'status':
                    require(item in {'unknown', 'started', 'complete', 'failed'}, 'invalid_status')
                elif key == 'verification':
                    require(item in {'unknown', 'passed', 'failed'}, 'invalid_verification')
                elif item is not None:
                    if key == 'consistency_id':
                        require(str(UUID(item)) == item, 'invalid_id')
                    elif key == 'manifest_sha256':
                        require(HASH.fullmatch(item), 'invalid_hash')
                    elif key == 'finished_at':
                        require(datetime.fromisoformat(item).utcoffset().total_seconds() == 0, 'invalid_time')
                    else:
                        require(type(item) in (int, float) and math.isfinite(item) and item >= 0, 'invalid_count')
                value[section][key] = item
        require(value['restore']['status'] != 'complete' or (value['restore']['verification'] == 'passed'
                and value['restore']['finished_at'] is not None and value['restore']['duration_seconds'] is not None), 'unverified_success')
        require(value['backup']['status'] != 'complete' or all(value['backup'][key] is not None
                for key in ('consistency_id', 'finished_at', 'manifest_sha256', 'asset_count', 'table_count')), 'unverified_backup')
        return dict(status='available', **value)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, DrillError):
        # The receipt may be incomplete during an operator write; never reflect raw errors.
        return unknown
