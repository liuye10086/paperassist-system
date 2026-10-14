"""Analysis-plan persistence is additive and remains runtime writable."""
from sqlalchemy import inspect

from app.db.database import database_connection, verify_runtime_permissions
from app.db.schema import metadata


def test_analysis_plan_relations_and_constraints(postgres_schema):
    with database_connection() as db:
        inspector = inspect(db.raw_connection)
        for name in ('analysis_plan_decisions', 'confirmed_analysis_plans'):
            assert name in metadata.tables
            assert name in inspector.get_table_names()
        decision = metadata.tables['analysis_plan_decisions']
        plan = metadata.tables['confirmed_analysis_plans']
        assert set(decision.columns.keys()) == set(metadata.tables['dataset_preparation_decisions'].columns.keys())
        assert {fk.constraint.name for fk in plan.foreign_keys if fk.constraint.name} >= {'confirmed_analysis_plan_decision_fkey'}
        assert {c.name for c in plan.constraints if c.__class__.__name__ == 'UniqueConstraint'} >= {'confirmed_analysis_plans_task_key', 'confirmed_analysis_plans_decision_key', 'confirmed_analysis_plans_file_revision_key'}
        assert 'confirmed_analysis_plans_file_created' in {index.name for index in plan.indexes}
        assert {c.name for c in plan.columns} == {'id', 'file_id', 'task_id', 'decision_id', 'created_by', 'created_at', 'sha256', 'plan_json', 'setup_revision'}
        verify_runtime_permissions(db.raw_connection, postgres_schema)
