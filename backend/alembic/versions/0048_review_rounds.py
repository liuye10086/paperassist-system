"""Frozen review-round storage and common task integration."""
from alembic import op
revision='0048_review_rounds'
down_revision='0047_journal_adaptations'
branch_labels=None
depends_on=None
"""Scoped frozen rounds and append-only explicit user save history."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

def define_review_round_tables(metadata):
    rounds=sa.Table('review_rounds',metadata,sa.Column('id',sa.Text,primary_key=True),sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),sa.Column('task_id',sa.Text,nullable=False,unique=True),sa.Column('round_number',sa.Integer,nullable=False),sa.Column('idempotency_key',sa.Text,nullable=False),sa.Column('request_json',JSONB,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),sa.Column('snapshot_json',JSONB,nullable=False),sa.Column('snapshot_sha256',sa.Text,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint('id','project_id','user_id',name='rr_scope_key'),sa.UniqueConstraint('project_id','user_id','idempotency_key',name='rr_request_key'),sa.UniqueConstraint('project_id','round_number',name='rr_number_key'),sa.ForeignKeyConstraint(['project_id','user_id'],['projects.id','projects.owner_id'],name='rr_owner_fk'),sa.ForeignKeyConstraint(['task_id','project_id','user_id'],['tasks.id','tasks.project_id','tasks.user_id'],name='rr_task_fk'),sa.CheckConstraint("round_number>=1 AND request_digest ~ '^[0-9a-f]{64}$' AND snapshot_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(snapshot_json)='object'",name='rr_snapshot_check'))
    events=sa.Table('review_round_events',metadata,sa.Column('id',sa.Text,primary_key=True),sa.Column('round_id',sa.Text,nullable=False),sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),sa.Column('revision',sa.Integer,nullable=False),sa.Column('kind',sa.Text,nullable=False),sa.Column('idempotency_key',sa.Text,nullable=False),sa.Column('request_json',JSONB,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),sa.Column('snapshot_json',JSONB,nullable=False),sa.Column('snapshot_sha256',sa.Text,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint('round_id','revision',name='rre_revision_key'),sa.UniqueConstraint('round_id','idempotency_key',name='rre_request_key'),sa.ForeignKeyConstraint(['round_id','project_id','user_id'],['review_rounds.id','review_rounds.project_id','review_rounds.user_id'],name='rre_round_fk'),sa.CheckConstraint("revision>=1 AND kind IN ('initial','plans','decisions') AND request_digest ~ '^[0-9a-f]{64}$' AND snapshot_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(snapshot_json)='object'",name='rre_snapshot_check'))
    return rounds,events

def tables():
    metadata=sa.MetaData()
    for name,columns in [('projects',('id','owner_id')),('tasks',('id','project_id','user_id'))]:
        sa.Table(name,metadata,*(sa.Column(c,sa.Text) for c in columns))
    return define_review_round_tables(metadata)
TASK_TYPES="'boxplot', 'explanation', 'word_report', 'parse_file', 'extract_dataset', 'prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'figure_projection', 'figure_workbench', 'figure_explanation', 'collection_word_report', 'statistics_compute', 'literature_search', 'literature_assistance', 'manuscript_draft', 'manuscript_docx', 'pdf_export', 'manuscript_writing', 'layout_docx', 'school_template_parse', 'journal_recommendation', 'journal_format_check', 'journal_adaptation', 'review_round_plan'"
WAIT_KINDS="'budget_confirmation','submission_unknown','unsupported_input','unsupported_confirmation','dataset_preparation_confirmation','ocr_review_confirmation','analysis_plan_confirmation','analysis_plan_input','figure_projection_confirmation','remote_observation','literature_configuration','literature_model_authorization'"
def upgrade():
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks','task_type IN ('+TASK_TYPES+')')
    op.create_check_constraint('tasks_review_round_snapshot_check','tasks',"task_type<>'review_round_plan' OR ((workflow_version='review_round_plan_v1' AND input_snapshot->>'kind'='review_round_plan' AND input_snapshot->>'workflow_version'='review_round_plan_v1' AND jsonb_typeof(input_snapshot->'manuscript')='object' AND jsonb_typeof(input_snapshot->'sources')='array' AND input_snapshot->'real_model_calls'='false'::jsonb AND input_snapshot->'real_network_calls'='false'::jsonb) IS TRUE)")
    op.drop_constraint('task_waits_kind_check','task_waits',type_='check')
    op.create_check_constraint('task_waits_kind_check','task_waits','kind IN ('+WAIT_KINDS+",'review_round_confirmation','review_round_input')")
    for table in tables():table.create(op.get_bind())
    op.execute("CREATE FUNCTION review_round_seal() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Immutable review round history'; END $$")
    for table in tables():op.execute('CREATE TRIGGER '+table.name+'_seal BEFORE UPDATE OR DELETE ON '+table.name+' FOR EACH ROW EXECUTE FUNCTION review_round_seal()')
def downgrade():
    if any(op.get_bind().exec_driver_sql('SELECT EXISTS(SELECT 1 FROM '+t.name+')').scalar_one() for t in tables()):raise RuntimeError('Review history exists; refusing destructive downgrade.')
    for table in reversed(tables()):table.drop(op.get_bind())
    op.execute('DROP FUNCTION review_round_seal()')
    op.drop_constraint('tasks_review_round_snapshot_check','tasks',type_='check')
    op.drop_constraint('task_waits_kind_check','task_waits',type_='check')
    op.create_check_constraint('task_waits_kind_check','task_waits','kind IN ('+WAIT_KINDS+')')
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks','task_type IN ('+TASK_TYPES.replace(", 'review_round_plan'",'')+')')
