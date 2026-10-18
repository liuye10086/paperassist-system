"""Add bounded failure evidence and a recommendation task; preserve every old row."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0025_correlation_planning'
down_revision = '0024_research_plans'
branch_labels = None
depends_on = None
OLD_TYPES = "'boxplot','explanation','word_report','parse_file','extract_dataset','prepare_dataset','review_ocr','analysis_plan'"


def upgrade():
    op.drop_constraint('tasks_type_check', 'tasks', type_='check')
    op.create_check_constraint('tasks_type_check', 'tasks', "task_type IN ("+OLD_TYPES+",'analysis_recommendation')")
    op.add_column('tasks', sa.Column('verification_failure', JSONB(none_as_null=True), nullable=True))
    op.create_check_constraint('tasks_verification_failure_check', 'tasks',
        "verification_failure IS NULL OR jsonb_typeof(verification_failure)='object'")


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM tasks WHERE task_type='analysis_recommendation'
        OR verification_failure IS NOT NULL OR workflow_version='analysis_plan_v3')
        OR EXISTS (SELECT 1 FROM analysis_runs WHERE engine_version='correlation_statistics_dataset_v1')
        THEN RAISE EXCEPTION 'correlation planning history requires preservation before downgrade'; END IF; END $$""")
    op.drop_constraint('tasks_verification_failure_check', 'tasks', type_='check')
    op.drop_column('tasks', 'verification_failure')
    op.drop_constraint('tasks_type_check', 'tasks', type_='check')
    op.create_check_constraint('tasks_type_check', 'tasks', 'task_type IN ('+OLD_TYPES+')')
