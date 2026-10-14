"""Persistent local dataset preparation workflow; frozen table definitions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision = '0017_dataset_preparation'
down_revision = '0016_dataset_versions'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks',"task_type IN ('boxplot','explanation','word_report','parse_file','extract_dataset','prepare_dataset')")
    op.drop_constraint('task_waits_kind_check','task_waits',type_='check')
    op.create_check_constraint('task_waits_kind_check','task_waits',"kind IN ('budget_confirmation','submission_unknown','unsupported_input','unsupported_confirmation','dataset_preparation_confirmation')")
    metadata = sa.MetaData()
    for name in ('tasks','users','projects','files','dataset_versions'):
        sa.Table(name,metadata,sa.Column('id',sa.Text,primary_key=True))
    sa.Table('task_waits',metadata,sa.Column('id',sa.Text,primary_key=True),sa.Column('task_id',sa.Text))
    for table in define_dataset_preparation_tables(metadata):
        table.create(op.get_bind())


def downgrade():
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM task_checkpoints) OR EXISTS (SELECT 1 FROM tasks WHERE task_type='prepare_dataset') THEN RAISE EXCEPTION 'preparation history requires preservation before downgrade'; END IF; END $$")
    op.drop_table('prepared_dataset_versions')
    op.drop_table('dataset_preparation_decisions')
    op.drop_table('task_checkpoints')
    op.drop_constraint('task_waits_kind_check','task_waits',type_='check')
    op.create_check_constraint('task_waits_kind_check','task_waits',"kind IN ('budget_confirmation','submission_unknown','unsupported_input','unsupported_confirmation')")
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks',"task_type IN ('boxplot','explanation','word_report','parse_file','extract_dataset')")

def define_dataset_preparation_tables(metadata):
    checkpoints = sa.Table('task_checkpoints', metadata,
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('task_id', sa.Text, sa.ForeignKey('tasks.id'), nullable=False),
        sa.Column('seq', sa.Integer, nullable=False),
        sa.Column('node', sa.Text, nullable=False),
        sa.Column('next_node', sa.Text, nullable=False),
        sa.Column('state_json', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('task_id','seq',name='task_checkpoints_sequence_key'),
        sa.UniqueConstraint('task_id','id',name='task_checkpoints_identity_key'),
        sa.CheckConstraint('seq >= 1',name='task_checkpoints_sequence_check'),
        sa.CheckConstraint("node IN ('prepare_preview','await_confirmation','approve','revise','publish','done')",name='task_checkpoints_node_check'),
        sa.CheckConstraint("next_node IN ('prepare_preview','await_confirmation','publish','done')",name='task_checkpoints_next_check'),
        sa.CheckConstraint("jsonb_typeof(state_json)='object'",name='task_checkpoints_state_check'))
    decisions = sa.Table('dataset_preparation_decisions', metadata,
        sa.Column('id',sa.Text,primary_key=True),
        sa.Column('task_id',sa.Text,sa.ForeignKey('tasks.id'),nullable=False),
        sa.Column('user_id',sa.Text,sa.ForeignKey('users.id'),nullable=False),
        sa.Column('project_id',sa.Text,sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('wait_id',sa.Text,nullable=False),
        sa.Column('checkpoint_id',sa.Text,nullable=False),
        sa.Column('idempotency_key',sa.Text,nullable=False),
        sa.Column('request_digest',sa.Text,nullable=False),
        sa.Column('operation',sa.Text,nullable=False),
        sa.Column('request_json',JSONB,nullable=False),
        sa.Column('response_json',JSONB,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('user_id','task_id','idempotency_key',name='preparation_decisions_request_key'),
        sa.UniqueConstraint('task_id','wait_id',name='preparation_decisions_wait_key'),
        sa.UniqueConstraint('task_id','id',name='preparation_decisions_identity_key'),
        sa.ForeignKeyConstraint(['task_id','wait_id'],['task_waits.task_id','task_waits.id'],name='preparation_decisions_wait_fkey'),
        sa.ForeignKeyConstraint(['task_id','checkpoint_id'],['task_checkpoints.task_id','task_checkpoints.id'],name='preparation_decisions_checkpoint_fkey'),
        sa.CheckConstraint("operation IN ('approve','revise')",name='preparation_decisions_operation_check'),
        sa.CheckConstraint("idempotency_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$'",name='preparation_decisions_request_check'),
        sa.CheckConstraint("jsonb_typeof(request_json)='object' AND jsonb_typeof(response_json)='object'",name='preparation_decisions_json_check'))
    prepared = sa.Table('prepared_dataset_versions',metadata,
        sa.Column('id',sa.Text,primary_key=True),
        sa.Column('file_id',sa.Text,sa.ForeignKey('files.id'),nullable=False),
        sa.Column('parent_dataset_id',sa.Text,sa.ForeignKey('dataset_versions.id'),nullable=False),
        sa.Column('task_id',sa.Text,sa.ForeignKey('tasks.id'),nullable=False,unique=True),
        sa.Column('decision_id',sa.Text,nullable=False,unique=True),
        sa.Column('version',sa.Integer,nullable=False),
        sa.Column('created_by',sa.Text,sa.ForeignKey('users.id'),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('object_key',sa.Text,nullable=False,unique=True),
        sa.Column('sha256',sa.Text,nullable=False),
        sa.Column('size_bytes',sa.BigInteger,nullable=False),
        sa.Column('recipe_json',JSONB,nullable=False),
        sa.Column('summary_json',JSONB,nullable=False),
        sa.ForeignKeyConstraint(['task_id','decision_id'],['dataset_preparation_decisions.task_id','dataset_preparation_decisions.id'],name='prepared_dataset_decision_fkey'),
        sa.UniqueConstraint('parent_dataset_id','version',name='prepared_dataset_parent_version_key'),
        sa.CheckConstraint('version >= 1',name='prepared_dataset_version_check'),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$' AND size_bytes>0 AND size_bytes<=4194304",name='prepared_dataset_object_check'),
        sa.CheckConstraint("jsonb_typeof(recipe_json)='object' AND jsonb_typeof(summary_json)='object'",name='prepared_dataset_json_check'))
    sa.Index('prepared_dataset_file_created',prepared.c.file_id,prepared.c.created_at.desc(),prepared.c.id)
    return checkpoints,decisions,prepared
