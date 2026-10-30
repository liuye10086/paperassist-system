"""Independent sealed school advice, without changing any confirmed template."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision='0056_school_rule_suggestions'
down_revision='0055_manuscript_analysis_reports'
branch_labels=None
depends_on=None
TASK_TYPES="'boxplot', 'explanation', 'word_report', 'parse_file', 'extract_dataset', 'prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'figure_projection', 'figure_workbench', 'figure_explanation', 'collection_word_report', 'statistics_compute', 'literature_search', 'literature_assistance', 'manuscript_draft', 'manuscript_docx', 'pdf_export', 'manuscript_writing', 'layout_docx', 'school_template_parse', 'school_rule_suggestion', 'journal_recommendation', 'journal_format_check', 'journal_adaptation', 'review_round_plan', 'review_revision', 'review_document_export'"
OLD_TYPES="'boxplot', 'explanation', 'word_report', 'parse_file', 'extract_dataset', 'prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'figure_projection', 'figure_workbench', 'figure_explanation', 'collection_word_report', 'statistics_compute', 'literature_search', 'literature_assistance', 'manuscript_draft', 'manuscript_docx', 'pdf_export', 'manuscript_writing', 'layout_docx', 'school_template_parse', 'journal_recommendation', 'journal_format_check', 'journal_adaptation', 'review_round_plan', 'review_revision', 'review_document_export'"

def upgrade():
    op.create_table('school_rule_suggestions',sa.Column('id',sa.Text,primary_key=True),
        *(sa.Column(k,sa.Text,nullable=False) for k in ('project_id','user_id','template_version_id','task_id','idempotency_key','request_digest','input_digest')),
        sa.Column('request_json',JSONB,nullable=False),sa.Column('input_snapshot',JSONB,nullable=False),
        sa.Column('raw_output_json',JSONB),sa.Column('result_json',JSONB),sa.Column('artifact_sha256',sa.Text),sa.Column('model_call_id',sa.Text),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['project_id','user_id'],['projects.id','projects.owner_id'],name='srs_owner_fk'),
        sa.ForeignKeyConstraint(['template_version_id','project_id','user_id'],['school_template_versions.id','school_template_versions.project_id','school_template_versions.user_id'],name='srs_template_scope_fk'),
        sa.ForeignKeyConstraint(['task_id','project_id','user_id'],['tasks.id','tasks.project_id','tasks.user_id'],name='srs_task_scope_fk'),
        sa.ForeignKeyConstraint(['model_call_id','project_id','user_id'],['model_calls.id','model_calls.project_id','model_calls.user_id'],name='srs_call_scope_fk'),
        sa.UniqueConstraint('task_id',name='srs_task_key'),sa.UniqueConstraint('id','project_id','user_id',name='srs_scope_key'),sa.UniqueConstraint('template_version_id','idempotency_key',name='srs_request_key'),
        sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$' AND input_digest ~ '^[0-9a-f]{64}$' AND jsonb_typeof(request_json)='object' AND jsonb_typeof(input_snapshot)='object'",name='srs_input_check'),
        sa.CheckConstraint("num_nonnulls(result_json,raw_output_json,artifact_sha256,model_call_id) IN (0,4) AND ((result_json IS NULL AND raw_output_json IS NULL AND artifact_sha256 IS NULL AND model_call_id IS NULL) OR (jsonb_typeof(result_json)='object' AND jsonb_typeof(raw_output_json)='object' AND artifact_sha256 ~ '^[0-9a-f]{64}$' AND model_call_id IS NOT NULL))",name='srs_result_check'))
    bind=op.get_bind()
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks','task_type IN ('+TASK_TYPES+')')
    op.execute("""CREATE FUNCTION school_suggestion_seal() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF TG_OP='UPDATE' AND OLD.result_json IS NULL AND NEW.result_json IS NOT NULL
        AND (to_jsonb(NEW)-ARRAY['raw_output_json','result_json','artifact_sha256','model_call_id'])=(to_jsonb(OLD)-ARRAY['raw_output_json','result_json','artifact_sha256','model_call_id']) THEN RETURN NEW; END IF;
      RAISE EXCEPTION 'Immutable school suggestion history'; END $$""")
    op.execute('CREATE TRIGGER school_rule_suggestions_seal BEFORE UPDATE OR DELETE ON school_rule_suggestions FOR EACH ROW EXECUTE FUNCTION school_suggestion_seal()')

def downgrade():
    bind=op.get_bind()
    if bind.execute(sa.text('SELECT EXISTS(SELECT 1 FROM school_rule_suggestions)')).scalar_one():raise RuntimeError('School suggestion history exists; refusing destructive downgrade.')
    op.drop_table('school_rule_suggestions');op.execute('DROP FUNCTION school_suggestion_seal()')
    # Only empty new-family tasks can exist when this downgrade is permitted.
    old=bind.execute(sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='tasks'::regclass AND conname='tasks_type_check'")).scalar_one()
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks','task_type IN ('+OLD_TYPES+')')
