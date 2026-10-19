"""Private, immutable task input with separately published model suggestions."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def define_literature_assistance_tables(metadata):
    requests = sa.Table('literature_assistance_requests', metadata,
        sa.Column('task_id', sa.Text, primary_key=True),
        sa.Column('project_id', sa.Text, nullable=False),
        sa.Column('user_id', sa.Text, nullable=False),
        sa.Column('kind', sa.Text, nullable=False),
        sa.Column('result_json', JSONB(none_as_null=True)),
        sa.Column('model_call_id', sa.Text, sa.ForeignKey('model_calls.id')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['task_id','project_id','user_id'], ['tasks.id','tasks.project_id','tasks.user_id'], name='literature_assistance_requests_task_fkey'),
        sa.ForeignKeyConstraint(['project_id','user_id'], ['projects.id','projects.owner_id'], name='literature_assistance_requests_owner_fkey'),
        sa.CheckConstraint("kind IN ('search_plan','evidence_review','evidence_comparison')", name='literature_assistance_requests_kind_check'),
        sa.CheckConstraint("((result_json IS NULL AND model_call_id IS NULL) OR (jsonb_typeof(result_json)='object' AND model_call_id IS NOT NULL)) IS TRUE", name='literature_assistance_requests_result_check'),
        sa.CheckConstraint('updated_at>=created_at', name='literature_assistance_requests_time_check'))
    sa.Index('literature_assistance_requests_project_created', requests.c.project_id, requests.c.created_at.desc(), requests.c.task_id)
    return (requests,)
