"""Append OCR transcription review records; preserve every earlier version."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision = '0021_ocr_review'
down_revision = '0020_ocr_parsing'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks',"task_type IN ('boxplot','explanation','word_report','parse_file','extract_dataset','prepare_dataset','review_ocr')")
    op.drop_constraint('task_waits_kind_check','task_waits',type_='check')
    op.create_check_constraint('task_waits_kind_check','task_waits',"kind IN ('budget_confirmation','submission_unknown','unsupported_input','unsupported_confirmation','dataset_preparation_confirmation','ocr_review_confirmation')")
    metadata = sa.MetaData()
    for name in ('tasks','users','projects','files','file_parse_results'):
        sa.Table(name,metadata,sa.Column('id',sa.Text,primary_key=True))
    for name in ('task_waits','task_checkpoints'):
        sa.Table(name,metadata,sa.Column('id',sa.Text,primary_key=True),sa.Column('task_id',sa.Text))
    for table in define_ocr_review_tables(metadata):
        table.create(op.get_bind())


def downgrade():
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM tasks WHERE task_type='review_ocr') OR EXISTS (SELECT 1 FROM ocr_review_decisions) OR EXISTS (SELECT 1 FROM ocr_review_versions) THEN RAISE EXCEPTION 'OCR review history requires preservation before downgrade'; END IF; END $$")
    op.drop_table('ocr_review_versions')
    op.drop_table('ocr_review_decisions')
    op.drop_constraint('task_waits_kind_check','task_waits',type_='check')
    op.create_check_constraint('task_waits_kind_check','task_waits',"kind IN ('budget_confirmation','submission_unknown','unsupported_input','unsupported_confirmation','dataset_preparation_confirmation')")
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks',"task_type IN ('boxplot','explanation','word_report','parse_file','extract_dataset','prepare_dataset')")

def define_ocr_review_tables(metadata):
    decisions = sa.Table('ocr_review_decisions', metadata,
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
        sa.UniqueConstraint('user_id','task_id','idempotency_key',name='ocr_review_decisions_request_key'),
        sa.UniqueConstraint('task_id','wait_id',name='ocr_review_decisions_wait_key'),
        sa.UniqueConstraint('task_id','id',name='ocr_review_decisions_identity_key'),
        sa.ForeignKeyConstraint(['task_id','wait_id'],['task_waits.task_id','task_waits.id'],name='ocr_review_decisions_wait_fkey'),
        sa.ForeignKeyConstraint(['task_id','checkpoint_id'],['task_checkpoints.task_id','task_checkpoints.id'],name='ocr_review_decisions_checkpoint_fkey'),
        sa.CheckConstraint("operation IN ('approve','revise')",name='ocr_review_decisions_operation_check'),
        sa.CheckConstraint("idempotency_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$'",name='ocr_review_decisions_request_check'),
        sa.CheckConstraint("jsonb_typeof(request_json)='object' AND jsonb_typeof(response_json)='object'",name='ocr_review_decisions_json_check'))
    prepared = sa.Table('ocr_review_versions',metadata,
        sa.Column('id',sa.Text,primary_key=True),
        sa.Column('file_id',sa.Text,sa.ForeignKey('files.id'),nullable=False),
        sa.Column('parent_parse_id',sa.Text,sa.ForeignKey('file_parse_results.id'),nullable=False),
        sa.Column('task_id',sa.Text,sa.ForeignKey('tasks.id'),nullable=False,unique=True),
        sa.Column('decision_id',sa.Text,nullable=False,unique=True),
        sa.Column('version',sa.Integer,nullable=False),
        sa.Column('created_by',sa.Text,sa.ForeignKey('users.id'),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('object_key',sa.Text,nullable=False,unique=True),
        sa.Column('sha256',sa.Text,nullable=False),
        sa.Column('size_bytes',sa.BigInteger,nullable=False),
        sa.Column('edits_json',JSONB,nullable=False),
        sa.Column('summary_json',JSONB,nullable=False),
        sa.ForeignKeyConstraint(['task_id','decision_id'],['ocr_review_decisions.task_id','ocr_review_decisions.id'],name='ocr_review_decision_fkey'),
        sa.UniqueConstraint('parent_parse_id','version',name='ocr_review_parent_version_key'),
        sa.CheckConstraint('version >= 1',name='ocr_review_version_check'),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$' AND size_bytes>0 AND size_bytes<=16777216",name='ocr_review_object_check'),
        sa.CheckConstraint("jsonb_typeof(edits_json)='array' AND jsonb_typeof(summary_json)='object'",name='ocr_review_json_check'))
    sa.Index('ocr_review_file_created',prepared.c.file_id,prepared.c.created_at.desc(),prepared.c.id)
    return decisions,prepared
