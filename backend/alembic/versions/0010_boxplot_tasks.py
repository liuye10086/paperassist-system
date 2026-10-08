"""Add durable plot side effects and recoverable PNG publication metadata."""
from alembic import op
from sqlalchemy import Column, Text
from sqlalchemy.dialects.postgresql import JSONB

revision = '0010_boxplot_tasks'
down_revision = '0009_explanation_tasks'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tasks', Column('result_figure_id', Text, nullable=True))
    op.add_column('tasks', Column('figure_candidate', JSONB(none_as_null=True), nullable=True))
    op.create_foreign_key('tasks_result_figure_id_fkey', 'tasks', 'figures', ['result_figure_id'], ['id'])
    op.create_check_constraint('tasks_figure_candidate_check', 'tasks',
                               "figure_candidate IS NULL OR jsonb_typeof(figure_candidate) = 'object'")
    op.add_column('model_calls', Column('provider_state', JSONB(none_as_null=True), nullable=True))
    op.create_check_constraint('model_calls_provider_state_check', 'model_calls',
                               "provider_state IS NULL OR jsonb_typeof(provider_state) = 'object'")


def downgrade():
    # Downgrades are explicit maintenance actions, never performed by application startup.
    op.drop_constraint('model_calls_provider_state_check', 'model_calls', type_='check')
    op.drop_column('model_calls', 'provider_state')
    op.drop_constraint('tasks_figure_candidate_check', 'tasks', type_='check')
    op.drop_constraint('tasks_result_figure_id_fkey', 'tasks', type_='foreignkey')
    op.drop_column('tasks', 'figure_candidate')
    op.drop_column('tasks', 'result_figure_id')
