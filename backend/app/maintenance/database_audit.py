"""Read-only persisted-contract audit; never emits business values or exceptions.

JSON and time validation is application-side: legacy TEXT / DOUBLE PRECISION
columns have no database JSON/time CHECK. Cross-resource run consistency likewise
has single-column foreign keys only; this audit detects that compatibility gap.
"""
import json
import math
import re
import sys
from datetime import datetime, timedelta
from sqlalchemy import inspect, CheckConstraint, DateTime, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION
from app.db.schema import metadata
from app.db.database import SCHEMA_HEAD, database_connection, get_database_config


def _finite_json_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('nonfinite JSON number')
    return number


def valid_json(value):
    try:
        json.loads(value, parse_float=_finite_json_float, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        return True
    except (ValueError, TypeError, RecursionError):
        return False


def valid_timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)', value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.utcoffset() == timedelta(0)
    except ValueError:
        return False


def valid_numeric_time(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def valid_datetime(value):
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _check_signature(value):
    # PostgreSQL rewrites IN lists to = ANY (ARRAY[]) and adds explicit casts.
    parts = re.split(r"('(?:''|[^'])*')", str(value))
    for index in range(0, len(parts), 2):
        syntax = parts[index].lower()
        syntax = re.sub(r'::(?:text|character varying|integer|bigint|double precision)', '', syntax)
        syntax = re.sub(r'=\s*any\s*\(\s*array\[', ' in (', syntax)
        parts[index] = re.sub(r'[\s()\[\]]', '', syntax)
    return ''.join(parts)


def audit_database(db):
    schema = db.config.schema
    inspector = inspect(db.raw_connection)
    issues = []
    def issue(table, kind):
        issues.append({'table': table, 'kind': kind})
    persisted_tables = set(inspector.get_table_names(schema=schema))
    if 'alembic_version' not in persisted_tables:
        issue('alembic_version', 'version')
    else:
        versions = db.execute('SELECT version_num FROM alembic_version').fetchall()
        if len(versions) != 1 or versions[0]['version_num'] != SCHEMA_HEAD:
            issue('alembic_version', 'version')
    tables = persisted_tables - {'alembic_version'}
    for table_name in sorted(tables.symmetric_difference(metadata.tables)):
        issue(table_name, 'table')
    for table in metadata.sorted_tables:
        if table.name not in tables:
            continue
        actual = {c['name']: c for c in inspector.get_columns(table.name, schema=schema)}
        expected = {c.name: c for c in table.columns}
        for name in sorted(set(actual) | set(expected)):
            if name not in actual or name not in expected:
                issue(table.name, 'column:' + name)
                continue
            a, e = actual[name], expected[name]
            expected_default = str(e.server_default.arg) if e.server_default is not None and hasattr(e.server_default, 'arg') else None
            if expected_default is not None and isinstance(e.server_default.arg, str):
                expected_default = "'" + expected_default.replace("'", "''") + "'"
            actual_default = a.get('default')
            defaults_match = (actual_default is None and expected_default is None) or (actual_default is not None and expected_default is not None and _check_signature(actual_default) == _check_signature(expected_default))
            identities_match = bool(a.get('identity')) == (e.identity is not None)
            if identities_match and e.identity is not None:
                identities_match = a['identity']['always'] == e.identity.always
            if str(a['type'].compile(dialect=db.raw_connection.dialect)) != str(e.type.compile(dialect=db.raw_connection.dialect)) or a['nullable'] != e.nullable or not defaults_match or not identities_match:
                issue(table.name, 'column:' + name)
        if inspector.get_pk_constraint(table.name, schema=schema)['constrained_columns'] != [c.name for c in table.primary_key]:
            issue(table.name, 'primary_key')
        afk = {(tuple(f['constrained_columns']), f['referred_table'], tuple(f['referred_columns']), f.get('referred_schema'), tuple(sorted(f.get('options', {}).items()))) for f in inspector.get_foreign_keys(table.name, schema=schema)}
        efk = {(tuple(c.parent.name for c in f.elements), f.elements[0].column.table.name, tuple(c.column.name for c in f.elements), schema, tuple(sorted({k: getattr(f, k) for k in ('onupdate', 'ondelete', 'deferrable', 'initially', 'match') if getattr(f, k) is not None}.items()))) for f in table.foreign_key_constraints}
        if afk != efk:
            issue(table.name, 'foreign_key')
        au = {tuple(u['column_names']) for u in inspector.get_unique_constraints(table.name, schema=schema)}
        eu = {tuple(c.name for c in u.columns) for u in table.constraints if isinstance(u, UniqueConstraint)}
        if au != eu:
            issue(table.name, 'unique')
        ac = {c['name']: _check_signature(c['sqltext']) for c in inspector.get_check_constraints(table.name, schema=schema)}
        ec = {c.name: _check_signature(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)}
        if ac != ec:
            issue(table.name, 'check')
        ai = {i['name']: i for i in inspector.get_indexes(table.name, schema=schema) if not i.get('duplicates_constraint')}
        ei = {i.name: i for i in table.indexes}
        for name in sorted(set(ai) | set(ei)):
            if name not in ai or name not in ei:
                issue(table.name, 'index:' + name)
                continue
            expressions = [str(e.compile(dialect=db.raw_connection.dialect)).split('.')[-1] for e in ei[name].expressions]
            expected_columns = [e.split()[0] for e in expressions]
            expected_sort = {e.split()[0]: ('desc',) for e in expressions if e.endswith(' DESC')}
            actual_sort = {k: tuple(v) for k, v in ai[name].get('column_sorting', {}).items()}
            actual_where = ai[name].get('dialect_options', {}).get('postgresql_where')
            expected_where = ei[name].dialect_options['postgresql'].get('where')
            where_matches = ((actual_where is None and expected_where is None) or
                             (actual_where is not None and expected_where is not None and
                              _check_signature(actual_where) == _check_signature(expected_where)))
            if ai[name]['column_names'] != expected_columns or actual_sort != expected_sort or bool(ai[name]['unique']) != ei[name].unique or not where_matches:
                issue(table.name, 'index:' + name)
    for row in db.execute('''SELECT t.relname AS table_name, i.relname AS index_name, x.indisvalid, x.indisready
        FROM pg_catalog.pg_index x JOIN pg_catalog.pg_class i ON i.oid=x.indexrelid
        JOIN pg_catalog.pg_class t ON t.oid=x.indrelid JOIN pg_catalog.pg_namespace n ON n.oid=t.relnamespace
        WHERE n.nspname=%s''', (schema,)):
        if not row['indisvalid'] or not row['indisready']:
            issue(row['table_name'], 'index_state:' + row['index_name'])
    # Matching text is insufficient: NOT VALID constraints permit invalid old rows.
    for row in db.execute('''SELECT t.relname AS table_name, c.conname AS constraint_name
        FROM pg_catalog.pg_constraint c
        JOIN pg_catalog.pg_class t ON t.oid=c.conrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=t.relnamespace
        WHERE n.nspname=%s AND c.contype IN ('f','c') AND NOT c.convalidated''', (schema,)):
        issue(row['table_name'], 'constraint_state:' + row['constraint_name'])
    checks = []
    # Index/constraint drift must not hide invalid legacy JSON/time or source chains.
    # Missing/incompatible tables and columns make the expected SELECT contract unsafe.
    if not any(i['kind'] == 'table' or i['kind'].startswith('column:') for i in issues):
        for table in metadata.sorted_tables:
            for column in table.columns:
                validator = None
                if column.name.endswith('_json') and isinstance(column.type, Text):
                    validator = valid_json
                elif isinstance(column.type, DOUBLE_PRECISION):
                    validator = valid_numeric_time
                elif isinstance(column.type, DateTime):
                    validator = valid_datetime
                elif column.name.endswith('_at'):
                    validator = valid_timestamp
                if validator:
                    invalid = total = 0
                    for row in db.execute(f'SELECT "{column.name}" AS value FROM "{table.name}"'):
                        total += 1
                        if row['value'] is not None and not validator(row['value']):
                            invalid += 1
                    checks.append({'table': table.name, 'column': column.name, 'rows': total, 'invalid': invalid})
        for table, target, key in [('explanations', 'figures', 'figure_id'), ('explanation_jobs', 'figures', 'figure_id'), ('reports', 'explanations', 'explanation_id')]:
            count = db.execute(f'''SELECT count(*) AS count FROM "{table}" r LEFT JOIN "{target}" t ON t.id=r."{key}"
                WHERE t.id IS NULL OR r.analysis_run_id IS DISTINCT FROM t.analysis_run_id''').fetchone()['count']
            checks.append({'table': table, 'column': key, 'invalid': count})
    return {'schema': schema, 'ok': not issues and not any(c['invalid'] for c in checks), 'schema_issues': issues, 'data_checks': checks,
            'compatibility': 'Legacy JSON/time validated in audit only; task JSONB/time use native types; source chains use single-column foreign keys; values preserved.'}


def main():
    try:
        config = get_database_config()
        with database_connection(config=config) as db:
            result = audit_database(db)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0 if result['ok'] else 1
    except Exception:
        print('数据库审计失败，请检查运行连接、权限和结构。', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
