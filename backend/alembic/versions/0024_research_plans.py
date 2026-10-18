"""Extend existing waiting and checkpoint checks without rewriting business rows."""
from alembic import op

revision = '0024_research_plans'
down_revision = '0023_file_lifecycle'
branch_labels = None
depends_on = None

CHECKS = (
    ('task_waits', 'task_waits_kind_check', 'kind',
     "'budget_confirmation','submission_unknown','unsupported_input','unsupported_confirmation','dataset_preparation_confirmation','ocr_review_confirmation','analysis_plan_confirmation'",
     'analysis_plan_input'),
    ('task_checkpoints', 'task_checkpoints_node_check', 'node',
     "'prepare_preview','check','await_confirmation','approve','revise','publish','done'", 'await_input'),
    ('task_checkpoints', 'task_checkpoints_next_check', 'next_node',
     "'prepare_preview','check','await_confirmation','publish','done'", 'await_input'),
)


def replace_checks(include_research):
    for table, name, column, old, addition in CHECKS:
        op.drop_constraint(name, table, type_='check')
        values = old + (",'" + addition + "'" if include_research else '')
        op.create_check_constraint(name, table, column + ' IN (' + values + ')')


def upgrade():
    replace_checks(True)


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM tasks WHERE workflow_version='analysis_plan_v2')
        OR EXISTS (SELECT 1 FROM task_waits WHERE kind='analysis_plan_input')
        OR EXISTS (SELECT 1 FROM task_checkpoints WHERE node='await_input' OR next_node='await_input')
        OR EXISTS (SELECT 1 FROM confirmed_analysis_plans WHERE plan_json->>'schema_version'='2')
        THEN RAISE EXCEPTION 'research plan history requires preservation before downgrade'; END IF; END $$""")
    replace_checks(False)
