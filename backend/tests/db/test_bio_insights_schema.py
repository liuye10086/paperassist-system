import pytest
from sqlalchemy import CheckConstraint
from app.db.schema import metadata


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


TABLES = ('bio_resource_versions', 'bio_resource_members', 'bio_insight_plans',
          'bio_insight_plan_versions', 'bio_insight_plan_sources', 'bio_insight_runs',
          'bio_insight_result_versions', 'bio_insight_result_members')


def test_b04_has_exact_eight_scoped_tables():
    assert set(TABLES) <= set(metadata.tables), 'CR-B04 schema missing'
    for name in TABLES:
        table = metadata.tables[name]
        assert {'id', 'project_id', 'user_id', 'created_at', 'schema_version'} <= set(table.c.keys())
        assert any(set(fk.column_keys) == {'project_id', 'user_id'} for fk in table.foreign_key_constraints)


def test_b04_sources_and_public_results_have_typed_scope():
    assert set(TABLES) <= set(metadata.tables), 'CR-B04 schema missing'
    from app.db.bio_insights_schema import SOURCE_TARGETS
    sources = metadata.tables['bio_insight_plan_sources']
    assert len(SOURCE_TARGETS) == 7
    for col, target in SOURCE_TARGETS.values():
        assert any(set(fk.column_keys) == {col, 'project_id'} for fk in sources.foreign_key_constraints)
    tasks = metadata.tables['tasks']
    for col in ('result_bio_resource_version_id', 'result_bio_insight_result_version_id'):
        assert col in tasks.c
        assert any(set(fk.column_keys) == {col, 'id', 'project_id'} for fk in tasks.foreign_key_constraints)
    for name in ('research_source_bindings', 'manuscript_research_sources'):
        assert {'bio_insight_result_version_id', 'bio_insight_result_member_id'} <= set(metadata.tables[name].c.keys())


def test_b04_json_is_bounded_and_requests_use_existing_digest_contract():
    assert set(TABLES) <= set(metadata.tables), 'CR-B04 schema missing'
    for name in TABLES:
        table = metadata.tables[name]
        checks = ' '.join(str(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint))
        for col in table.c:
            if col.name.endswith('_json'):
                assert f'octet_length({col.name}::text)<=4194304' in checks
        if 'request_key' in table.c:
            assert 'request_digest' in table.c
            assert 'payload_digest' not in table.c


def test_b04_migration_is_frozen_and_adds_exact_planned_tables():
    import ast
    from pathlib import Path
    path=Path(__file__).parents[2]/'alembic'/'versions'/'0061_bio_insights.py'
    tree=ast.parse(path.read_text(encoding='utf-8'))
    assert not any(isinstance(node,ast.ImportFrom) and (node.module or '').startswith('app.') for node in ast.walk(tree))
    assignments={node.targets[0].id:ast.literal_eval(node.value) for node in tree.body
                 if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name)
                 and node.targets[0].id in ('TABLE_NAMES','CREATE_TABLE_SQL')}
    assert assignments['TABLE_NAMES']==TABLES
    assert len([sql for sql in assignments['CREATE_TABLE_SQL'] if sql.startswith('CREATE TABLE ')])==8
