"""Add governed reader report interpretations without changing report exports."""
from alembic import op

from app.db.reader_report_schema import TASK_SNAPSHOT_CHECK
from app.db.schema import reader_report_narrative_requests, reader_report_narratives


revision = '0082_reader_report_narratives'
down_revision = '0081_account_deletion_sessions'
branch_labels = depends_on = None

OLD_TYPES = (
    "'bio_cloud_run', 'boxplot', 'explanation', 'word_report', 'parse_file', 'extract_dataset', "
    "'prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'figure_projection', "
    "'figure_workbench', 'figure_explanation', 'collection_word_report', 'statistics_compute', 'literature_search', "
    "'literature_assistance', 'manuscript_draft', 'manuscript_docx', 'pdf_export', 'manuscript_writing', 'layout_docx', "
    "'school_template_parse', 'school_rule_suggestion', 'journal_recommendation', 'journal_format_check', 'journal_adaptation', "
    "'review_round_plan', 'review_revision', 'review_document_export', 'bio_import', 'bio_analysis', 'bio_annotation', "
    "'bio_figure', 'research_figure', 'research_report', 'research_fact_draft', 'delivery_package', 'bio_resource_import', "
    "'bio_comparison', 'bio_result_import', 'bio_enrichment', 'bio_candidate', 'bio_insight_figure', 'bio_feature_extract', 'bio_integration'"
)


def upgrade():
    op.drop_constraint('tasks_type_check', 'tasks', type_='check')
    op.create_check_constraint('tasks_type_check', 'tasks', f"task_type IN ({OLD_TYPES}, 'reader_report_narrative')")
    op.create_check_constraint('tasks_reader_report_snapshot_check', 'tasks', TASK_SNAPSHOT_CHECK)
    reader_report_narratives.create(op.get_bind())
    reader_report_narrative_requests.create(op.get_bind())
    op.execute("""CREATE FUNCTION reader_report_narrative_seal() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE result_keys text[] := ARRAY['raw_output_json','result_json','artifact_sha256','model_call_id'];
    BEGIN
        IF TG_OP='DELETE' THEN
            RAISE EXCEPTION 'Saved reader report narrative is immutable';
        END IF;
        IF OLD.result_json IS NOT NULL OR NEW.result_json IS NULL
           OR (to_jsonb(OLD)-result_keys) IS DISTINCT FROM (to_jsonb(NEW)-result_keys) THEN
            RAISE EXCEPTION 'Saved reader report narrative is immutable';
        END IF;
        RETURN NEW;
    END $$""")
    op.execute("""CREATE TRIGGER reader_report_narratives_seal BEFORE UPDATE OR DELETE ON reader_report_narratives
        FOR EACH ROW EXECUTE FUNCTION reader_report_narrative_seal()""")


def downgrade():
    if op.get_bind().exec_driver_sql("SELECT EXISTS (SELECT 1 FROM tasks WHERE task_type='reader_report_narrative')").scalar_one():
        raise RuntimeError('Saved reader report narrative tasks exist.')
    op.drop_table('reader_report_narrative_requests')
    op.drop_table('reader_report_narratives')
    op.execute('DROP FUNCTION reader_report_narrative_seal()')
    op.drop_constraint('tasks_reader_report_snapshot_check', 'tasks', type_='check')
    op.drop_constraint('tasks_type_check', 'tasks', type_='check')
    op.create_check_constraint('tasks_type_check', 'tasks', f'task_type IN ({OLD_TYPES})')
