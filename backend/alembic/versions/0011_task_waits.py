"""Persist waiting generations and idempotent recovery receipts."""
from uuid import UUID, uuid5

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0011_task_waits'
down_revision = '0010_boxplot_tasks'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('task_waits',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('task_id', sa.Text, sa.ForeignKey('tasks.id'), nullable=False),
        sa.Column('user_id', sa.Text, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('project_id', sa.Text, sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('kind', sa.Text, nullable=False), sa.Column('status', sa.Text, nullable=False),
        sa.Column('task_revision', sa.Integer, nullable=False), sa.Column('input_version', JSONB, nullable=False),
        sa.Column('reason_code', sa.Text), sa.Column('error_code', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True)), sa.Column('resolved_task_revision', sa.Integer),
        sa.UniqueConstraint('task_id', 'task_revision', name='task_waits_generation_key'),
        sa.UniqueConstraint('task_id', 'id', name='task_waits_task_id_key'),
        sa.CheckConstraint("kind IN ('budget_confirmation','submission_unknown','unsupported_input','unsupported_confirmation')", name='task_waits_kind_check'),
        sa.CheckConstraint("status IN ('open','resolved','superseded')", name='task_waits_status_check'),
        sa.CheckConstraint('task_revision >= 1', name='task_waits_revision_check'),
        sa.CheckConstraint("jsonb_typeof(input_version) = 'object'", name='task_waits_input_object_check'),
        sa.CheckConstraint("(status='open' AND resolved_at IS NULL AND resolved_task_revision IS NULL) OR (status<>'open' AND resolved_at IS NOT NULL AND resolved_task_revision IS NOT NULL AND resolved_at>=created_at AND resolved_task_revision>task_revision)", name='task_waits_resolution_check'))
    op.create_index('task_waits_one_open', 'task_waits', ['task_id'], unique=True, postgresql_where=sa.text("status='open'"))
    op.create_index('task_waits_owner_status', 'task_waits', ['user_id', 'status', 'created_at'])
    op.create_table('task_resume_requests',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('task_id', sa.Text, sa.ForeignKey('tasks.id'), nullable=False),
        sa.Column('user_id', sa.Text, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('idempotency_key', sa.Text, nullable=False), sa.Column('operation', sa.Text, nullable=False),
        sa.Column('wait_id', sa.Text), sa.Column('request_digest', sa.Text, nullable=False),
        sa.Column('expected_task_revision', sa.Integer, nullable=False), sa.Column('input_version', JSONB, nullable=False),
        sa.Column('result_task_revision', sa.Integer, nullable=False), sa.Column('response_json', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['task_id', 'wait_id'], ['task_waits.task_id', 'task_waits.id'], name='task_resume_requests_wait_fkey'),
        sa.UniqueConstraint('user_id', 'task_id', 'idempotency_key', name='task_resume_requests_idempotency_key'),
        sa.CheckConstraint("operation IN ('resume','retry')", name='task_resume_requests_operation_check'),
        sa.CheckConstraint("(operation='resume' AND wait_id IS NOT NULL) OR (operation='retry' AND wait_id IS NULL)", name='task_resume_requests_wait_check'),
        sa.CheckConstraint("idempotency_key ~ '^[!-~]{1,128}$'", name='task_resume_requests_key_check'),
        sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name='task_resume_requests_digest_check'),
        sa.CheckConstraint('expected_task_revision >= 1 AND result_task_revision=expected_task_revision+1', name='task_resume_requests_revision_check'),
        sa.CheckConstraint("jsonb_typeof(input_version)='object' AND jsonb_typeof(response_json)='object'", name='task_resume_requests_json_check'))
    # Only existing waiting lifecycle facts are projected. No events, calls,
    # budgets, fees, decisions, or runnable tasks are fabricated by migration.
    db = op.get_bind()
    rows = db.execute(sa.text("SELECT * FROM tasks WHERE status IN ('waiting_input','waiting_confirmation')")).mappings()
    types = {'input_version': JSONB, 'task_revision': sa.Integer, 'created_at': sa.DateTime(timezone=True)}
    table = sa.table('task_waits', *[sa.column(name, types.get(name, sa.Text))
        for name in ('id','task_id','user_id','project_id','kind','status','task_revision','input_version','reason_code','error_code','created_at')])
    for task in rows:
        kind = ('unsupported_input' if task['status'] == 'waiting_input' else
            {'budget_exceeded': 'budget_confirmation', 'submission_unknown': 'submission_unknown'}.get(task['reason_code'], 'unsupported_confirmation'))
        snapshot = task['input_snapshot']
        db.execute(table.insert().values(id=str(uuid5(UUID('5e461181-21a8-471e-a14e-4d8425e1b23f'), f"{task['id']}:{task['revision']}")),
            task_id=task['id'], user_id=task['user_id'], project_id=task['project_id'], kind=kind, status='open',
            task_revision=task['revision'], input_version={'setup_revision': snapshot['result']['setup_revision'],
                'output_language': snapshot['output_language']}, reason_code=task['reason_code'],
            error_code=task['error_code'], created_at=task['updated_at']))


def downgrade():
    op.drop_table('task_resume_requests')
    op.drop_table('task_waits')
