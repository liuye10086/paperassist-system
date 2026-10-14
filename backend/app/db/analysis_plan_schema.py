"""Append-only analysis-plan decisions and confirmed plan publications."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def define_analysis_plan_tables(metadata):
    decisions = sa.Table('analysis_plan_decisions', metadata,
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('task_id', sa.Text, sa.ForeignKey('tasks.id'), nullable=False),
        sa.Column('user_id', sa.Text, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('project_id', sa.Text, sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('wait_id', sa.Text, nullable=False),
        sa.Column('checkpoint_id', sa.Text, nullable=False),
        sa.Column('idempotency_key', sa.Text, nullable=False),
        sa.Column('request_digest', sa.Text, nullable=False),
        sa.Column('operation', sa.Text, nullable=False),
        sa.Column('request_json', JSONB, nullable=False),
        sa.Column('response_json', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id', 'task_id', 'idempotency_key', name='analysis_plan_decisions_request_key'),
        sa.UniqueConstraint('task_id', 'wait_id', name='analysis_plan_decisions_wait_key'),
        sa.UniqueConstraint('task_id', 'id', name='analysis_plan_decisions_identity_key'),
        sa.ForeignKeyConstraint(['task_id', 'wait_id'], ['task_waits.task_id', 'task_waits.id'], name='analysis_plan_decisions_wait_fkey'),
        sa.ForeignKeyConstraint(['task_id', 'checkpoint_id'], ['task_checkpoints.task_id', 'task_checkpoints.id'], name='analysis_plan_decisions_checkpoint_fkey'),
        sa.CheckConstraint("operation IN ('approve','revise')", name='analysis_plan_decisions_operation_check'),
        sa.CheckConstraint("idempotency_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$'", name='analysis_plan_decisions_request_check'),
        sa.CheckConstraint("jsonb_typeof(request_json)='object' AND jsonb_typeof(response_json)='object'", name='analysis_plan_decisions_json_check'))
    plans = sa.Table('confirmed_analysis_plans', metadata,
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('file_id', sa.Text, sa.ForeignKey('files.id'), nullable=False),
        sa.Column('task_id', sa.Text, sa.ForeignKey('tasks.id'), nullable=False),
        sa.Column('decision_id', sa.Text, nullable=False),
        sa.Column('created_by', sa.Text, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sha256', sa.Text, nullable=False),
        sa.Column('plan_json', JSONB, nullable=False),
        sa.Column('setup_revision', sa.Integer, nullable=False),
        sa.UniqueConstraint('task_id', name='confirmed_analysis_plans_task_key'),
        sa.UniqueConstraint('decision_id', name='confirmed_analysis_plans_decision_key'),
        sa.UniqueConstraint('file_id', 'setup_revision', name='confirmed_analysis_plans_file_revision_key'),
        sa.ForeignKeyConstraint(['task_id', 'decision_id'], ['analysis_plan_decisions.task_id', 'analysis_plan_decisions.id'], name='confirmed_analysis_plan_decision_fkey'),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name='confirmed_analysis_plans_sha256_check'),
        sa.CheckConstraint('setup_revision >= 1', name='confirmed_analysis_plans_setup_revision_check'),
        sa.CheckConstraint("jsonb_typeof(plan_json)='object'", name='confirmed_analysis_plans_json_check'))
    sa.Index('confirmed_analysis_plans_file_created', plans.c.file_id, plans.c.created_at.desc(), plans.c.id)
    return decisions, plans
