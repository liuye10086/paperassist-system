"""Native PostgreSQL tables for the unified task persistence contract."""

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer,
    Table, Text, UniqueConstraint, ForeignKeyConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB


TASK_TYPES = "'bio_cloud_run', 'boxplot', 'explanation', 'word_report', 'parse_file', 'extract_dataset', 'prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'figure_projection', 'figure_workbench', 'figure_explanation', 'collection_word_report', 'statistics_compute', 'literature_search', 'literature_assistance', 'manuscript_draft', 'manuscript_docx', 'pdf_export', 'manuscript_writing', 'layout_docx', 'school_template_parse', 'school_rule_suggestion', 'journal_recommendation', 'journal_format_check', 'journal_adaptation', 'review_round_plan', 'review_revision', 'review_document_export', 'bio_import', 'bio_analysis', 'bio_annotation', 'bio_figure', 'research_figure', 'research_report', 'research_fact_draft','delivery_package', 'bio_resource_import', 'bio_comparison', 'bio_result_import', 'bio_enrichment', 'bio_candidate', 'bio_insight_figure', 'bio_feature_extract', 'bio_integration'"
STATUSES = "'cancelled', 'queued', 'running', 'waiting_input', 'waiting_confirmation', 'succeeded', 'failed'"
ATTEMPT_STATUSES = "'cancelled', 'running', 'waiting_input', 'waiting_confirmation', 'succeeded', 'failed'"
PHASES = "'parse', 'plan', 'compute', 'search', 'interpret', 'write', 'export', 'verify'"
REASONS = ("'input_required', 'confirmation_required', 'submission_unknown', "
           "'budget_exceeded', 'execution_failed', 'retry_requested', "
           "'input_provided', 'confirmation_received', 'observation_expired'")


def define_task_tables(metadata):
    tasks = Table(
        'tasks', metadata,
        Column('id', Text, primary_key=True),
        Column('project_id', Text, ForeignKey('projects.id'), nullable=False),
        Column('user_id', Text, ForeignKey('users.id'), nullable=False),
        Column('task_type', Text, nullable=False),
        Column('idempotency_key', Text, nullable=False),
        Column('input_digest', Text, nullable=False),
        Column('input_snapshot', JSONB, nullable=False),
        Column('workflow_version', Text, nullable=False),
        Column('status', Text, nullable=False),
        Column('phase', Text, nullable=False),
        Column('revision', Integer, nullable=False),
        Column('current_attempt', Integer, nullable=False),
        Column('reason_code', Text),
        Column('created_at', DateTime(timezone=True), nullable=False),
        Column('updated_at', DateTime(timezone=True), nullable=False),
        Column('result_analysis_run_id', Text, ForeignKey('analysis_runs.id', name='tasks_result_analysis_run_id_fkey')),
        Column('execution_receipt', JSONB(none_as_null=True)),
        CheckConstraint("execution_receipt IS NULL OR ((jsonb_typeof(execution_receipt)='object' AND execution_receipt->'schema_version'='1'::jsonb AND jsonb_typeof(execution_receipt->'nodes')='array' AND execution_receipt->>'status' IN ('succeeded','failed')) IS TRUE)", name='tasks_execution_receipt_check'),
        Column('result_bio_resource_version_id', Text),
        Column('result_bio_insight_result_version_id', Text),
        ForeignKeyConstraint(['result_bio_resource_version_id','id','project_id'], ['bio_resource_versions.id','bio_resource_versions.task_id','bio_resource_versions.project_id'], name='b04_tasks_resource_result_fk', use_alter=True),
        ForeignKeyConstraint(['result_bio_insight_result_version_id','id','project_id'], ['bio_insight_result_versions.id','bio_insight_result_versions.task_id','bio_insight_result_versions.project_id'], name='b04_tasks_insight_result_fk', use_alter=True),
        CheckConstraint("(result_bio_resource_version_id IS NULL OR (task_type='bio_resource_import' AND status='succeeded')) AND (result_bio_insight_result_version_id IS NULL OR (task_type IN ('bio_comparison','bio_result_import','bio_enrichment','bio_candidate','bio_insight_figure','bio_feature_extract','bio_integration') AND status='succeeded')) AND num_nonnulls(result_bio_resource_version_id,result_bio_insight_result_version_id)<=1 AND (num_nonnulls(result_bio_resource_version_id,result_bio_insight_result_version_id)=0 OR num_nonnulls(result_research_figure_version_id,result_research_report_version_id,result_research_candidate_id,result_bio_dataset_version_id,result_bio_processed_dataset_version_id,result_bio_figure_version_id,result_analysis_run_id,result_report_id,result_explanation_id,result_figure_id)=0)", name='b04_tasks_results_check'),
        CheckConstraint("(task_type<>'bio_resource_import' AND task_type<>'bio_comparison' AND task_type<>'bio_result_import' AND task_type<>'bio_enrichment' AND task_type<>'bio_candidate' AND task_type<>'bio_insight_figure' AND task_type<>'bio_feature_extract' AND task_type<>'bio_integration') OR (((workflow_version=task_type||'_v1' OR (task_type='bio_comparison' AND workflow_version IN ('bio_comparison_v2','bio_comparison_qpcr_v1','bio_comparison_microbiome_v1'))) AND input_snapshot->'schema_version'='1'::jsonb AND input_snapshot->>'kind'=task_type AND input_snapshot->>'workflow_version'=workflow_version AND input_snapshot->>'project_id'=project_id AND input_snapshot->>'output_language' IN ('zh-CN','en') AND input_snapshot->'real_model_calls'='false'::jsonb AND input_snapshot->'real_network_calls'='false'::jsonb AND ((task_type='bio_resource_import' AND length(input_snapshot->>'resource_version_id')>0) OR (task_type<>'bio_resource_import' AND length(input_snapshot->>'plan_version_id')>0 AND length(input_snapshot->>'run_id')>0 AND input_snapshot->>'source_digest' ~ '^[0-9a-f]{64}$'))) IS TRUE)", name='b04_tasks_snapshot_check'),
        Column('result_research_figure_version_id', Text),
        ForeignKeyConstraint(['result_research_figure_version_id','id','project_id'], ['research_figure_versions.id','research_figure_versions.task_id','research_figure_versions.project_id'], name='b03_tasks_result_research_figure_version_id_fk', use_alter=True),
        Column('result_research_report_version_id', Text),
        ForeignKeyConstraint(['result_research_report_version_id','id','project_id'], ['research_report_versions.id','research_report_versions.task_id','research_report_versions.project_id'], name='b03_tasks_result_research_report_version_id_fk', use_alter=True),
        Column('result_research_candidate_id', Text),
        ForeignKeyConstraint(['result_research_candidate_id','id','project_id'], ['research_manuscript_candidates.id','research_manuscript_candidates.task_id','research_manuscript_candidates.project_id'], name='b03_tasks_result_research_candidate_id_fk', use_alter=True),
        CheckConstraint("(result_research_figure_version_id IS NULL OR (task_type='research_figure' AND status='succeeded')) AND (result_research_report_version_id IS NULL OR (task_type='research_report' AND status='succeeded')) AND (result_research_candidate_id IS NULL OR (task_type='research_fact_draft' AND status='succeeded')) AND num_nonnulls(result_research_figure_version_id,result_research_report_version_id,result_research_candidate_id)<=1 AND (num_nonnulls(result_research_figure_version_id,result_research_report_version_id,result_research_candidate_id)=0 OR num_nonnulls(result_bio_dataset_version_id,result_bio_processed_dataset_version_id,result_bio_figure_version_id,result_analysis_run_id,result_report_id,result_explanation_id,result_figure_id)=0)", name='b03_tasks_results_check'),
        CheckConstraint("(task_type<>'research_figure' AND task_type<>'research_report' AND task_type<>'research_fact_draft') OR ((((task_type='research_fact_draft' AND workflow_version='research_results_methods_v1') OR ((task_type='research_figure' OR task_type='research_report') AND workflow_version=task_type||'_v1')) AND input_snapshot->'schema_version'='1'::jsonb AND input_snapshot->>'kind'=task_type AND input_snapshot->>'project_id'=project_id AND input_snapshot->'real_model_calls'='false'::jsonb AND input_snapshot->'real_network_calls'='false'::jsonb) IS TRUE)", name='b03_tasks_snapshot_check'),
        Column('result_bio_dataset_version_id', Text),
        Column('result_bio_processed_dataset_version_id', Text),
        Column('result_bio_figure_version_id', Text),
        ForeignKeyConstraint(['result_bio_processed_dataset_version_id','project_id'], ['bio_processed_dataset_versions.id','bio_processed_dataset_versions.project_id'], name='tasks_bio_processed_result_fk', use_alter=True),
        ForeignKeyConstraint(['result_bio_figure_version_id','project_id'], ['bio_figure_versions.id','bio_figure_versions.project_id'], name='tasks_bio_figure_result_fk', use_alter=True),
        CheckConstraint("(result_bio_processed_dataset_version_id IS NULL OR (task_type='bio_analysis' AND status='succeeded')) AND (result_bio_figure_version_id IS NULL OR (task_type='bio_figure' AND status='succeeded')) AND num_nonnulls(result_bio_processed_dataset_version_id,result_bio_figure_version_id)<=1 AND (num_nonnulls(result_bio_processed_dataset_version_id,result_bio_figure_version_id)=0 OR num_nonnulls(result_bio_dataset_version_id,result_analysis_run_id,result_report_id,result_explanation_id,result_figure_id)=0)", name='tasks_bio_results_check'),
        CheckConstraint("(((task_type<>'bio_analysis' AND task_type<>'bio_figure') OR ((workflow_version=task_type||'_v1' AND input_snapshot->'schema_version'='1'::jsonb AND input_snapshot->>'kind'=task_type AND input_snapshot->>'workflow_version'=workflow_version AND input_snapshot->>'project_id'=project_id AND input_snapshot->>'engine_version'='visium_explore_v1.0.0' AND (input_snapshot->>'environment_digest') ~ '^[0-9a-f]{64}$' AND (input_snapshot->>'code_digest') ~ '^[0-9a-f]{64}$' AND jsonb_typeof(input_snapshot->'limits')='object') IS TRUE)) OR ((task_type='bio_analysis' AND workflow_version='bio_analysis_v2' AND input_snapshot->'schema_version'='1'::jsonb AND input_snapshot->>'kind'='bio_analysis' AND input_snapshot->>'workflow_version'=workflow_version AND input_snapshot->>'project_id'=project_id AND input_snapshot->>'engine_version'='tabular_quantitative_v1.0.0' AND input_snapshot->>'environment_digest' ~ '^[0-9a-f]{64}$' AND input_snapshot->>'code_digest' ~ '^[0-9a-f]{64}$' AND jsonb_typeof(input_snapshot->'limits')='object') IS TRUE)) OR ((task_type='bio_analysis' AND workflow_version='bio_analysis_v3' AND input_snapshot->'schema_version'='1'::jsonb AND input_snapshot->>'kind'='bio_analysis' AND input_snapshot->>'workflow_version'=workflow_version AND input_snapshot->>'project_id'=project_id AND input_snapshot->>'engine_version'='visium_explore_v1.0.0' AND input_snapshot->>'environment_digest' ~ '^[0-9a-f]{64}$' AND input_snapshot->>'code_digest' ~ '^[0-9a-f]{64}$' AND jsonb_typeof(input_snapshot->'limits')='object' AND input_snapshot->'params'->'in_tissue_only'='false'::jsonb) IS TRUE)",name='tasks_bio_analysis_snapshot_check'),
        ForeignKeyConstraint(['result_bio_dataset_version_id','project_id'], ['bio_dataset_versions.id','bio_dataset_versions.project_id'], name='tasks_bio_result_fk', use_alter=True),
        UniqueConstraint('id','project_id', name='tasks_project_scope_key'),
        Column('result_report_id', Text, ForeignKey('reports.id', name='tasks_result_report_id_fkey')),
        Column('error_code', Text),
        Column('result_explanation_id', Text, ForeignKey('explanations.id', name='tasks_result_explanation_id_fkey')),
        Column('result_figure_id', Text, ForeignKey('figures.id', name='tasks_result_figure_id_fkey')),
        Column('figure_candidate', JSONB(none_as_null=True)),
        CheckConstraint("verification_failure IS NULL OR jsonb_typeof(verification_failure)='object'", name='tasks_verification_failure_check'),
        UniqueConstraint('id','project_id','user_id', name='tasks_scope_key'),
        UniqueConstraint('user_id', 'project_id', 'task_type', 'idempotency_key', name='tasks_idempotency_key'),
        CheckConstraint(f'task_type IN ({TASK_TYPES})', name='tasks_type_check'),
        CheckConstraint("task_type<>'delivery_package' OR (workflow_version='delivery_package_v1' AND input_snapshot->>'kind'=task_type AND input_snapshot->>'project_id'=project_id AND input_snapshot->>'snapshot_id' IS NOT NULL AND input_snapshot->'real_model_calls'='false'::jsonb AND input_snapshot->'real_network_calls'='false'::jsonb) IS TRUE",name='delivery_task_snapshot_check'),
        CheckConstraint("((task_type<>'bio_import' OR ((workflow_version IN ('bio_import_v1','bio_import_v2') AND input_snapshot->'schema_version'='1'::jsonb AND input_snapshot->>'kind'='bio_import' AND input_snapshot->>'workflow_version'=workflow_version AND (workflow_version='bio_import_v1' OR (input_snapshot->>'parser_version'='geo_visium_import_v2' AND input_snapshot->>'matrix_representation' IN ('mtx','10x_h5') AND input_snapshot->'compare_alternate' IN ('true'::jsonb,'false'::jsonb) AND jsonb_typeof(input_snapshot->'analysis_limits')='object' AND input_snapshot->>'engine_version'='visium_explore_v1.0.0' AND (input_snapshot->>'environment_digest') ~ '^[0-9a-f]{64}$' AND (input_snapshot->>'code_digest') ~ '^[0-9a-f]{64}$')) AND input_snapshot->>'project_id'=project_id AND jsonb_typeof(input_snapshot->'files')='array' AND jsonb_array_length(input_snapshot->'files')>=1 AND jsonb_array_length(input_snapshot->'files')<=10 AND jsonb_typeof(input_snapshot->'settings')='object') IS TRUE)) OR ((task_type='bio_import' AND workflow_version='bio_import_v3' AND input_snapshot->'schema_version'='1'::jsonb AND input_snapshot->>'kind'='bio_import' AND input_snapshot->>'workflow_version'=workflow_version AND input_snapshot->>'project_id'=project_id AND input_snapshot->>'parser_version'='tabular_assay_import_v1' AND input_snapshot->>'engine_version'='tabular_quantitative_v1.0.0' AND input_snapshot->>'assay' IN ('bulk_rna_counts','normalized_expression','proteomics','metabolomics','microbiome') AND jsonb_typeof(input_snapshot->'tabular_config')='object' AND jsonb_typeof(input_snapshot->'files')='array' AND jsonb_array_length(input_snapshot->'files') BETWEEN 2 AND 5 AND jsonb_typeof(input_snapshot->'settings')='object' AND input_snapshot->>'environment_digest' ~ '^[0-9a-f]{64}$' AND input_snapshot->>'code_digest' ~ '^[0-9a-f]{64}$') IS TRUE)) OR ((task_type='bio_import' AND workflow_version='bio_import_v4' AND input_snapshot->'schema_version'='1'::jsonb AND input_snapshot->>'kind'='bio_import' AND input_snapshot->>'workflow_version'=workflow_version AND input_snapshot->>'project_id'=project_id AND input_snapshot->>'assay'='single_cell' AND input_snapshot->>'parser_version'='single_cell_import_v1' AND input_snapshot->>'engine_version'='visium_explore_v1.0.0' AND jsonb_typeof(input_snapshot->'single_cell_config')='object' AND jsonb_typeof(input_snapshot->'analysis_limits')='object' AND jsonb_typeof(input_snapshot->'files')='array' AND jsonb_array_length(input_snapshot->'files') BETWEEN 1 AND 10 AND jsonb_typeof(input_snapshot->'settings')='object' AND input_snapshot->>'environment_digest' ~ '^[0-9a-f]{64}$' AND input_snapshot->>'code_digest' ~ '^[0-9a-f]{64}$') IS TRUE)", name='tasks_bio_snapshot_check'),
        CheckConstraint("task_type<>'journal_recommendation' OR ((input_snapshot->>'kind'='journal_recommendation' AND input_snapshot->>'workflow_version'='journal_recommendation_v1' AND jsonb_typeof(input_snapshot->'profiles')='array' AND jsonb_typeof(input_snapshot->'research')='object' AND input_snapshot->'real_model_calls'='false'::jsonb AND input_snapshot->'real_network_calls'='false'::jsonb) IS TRUE)",name='tasks_journal_snapshot_check'),
        CheckConstraint("task_type<>'journal_format_check' OR ((input_snapshot->>'kind'='journal_format_check' AND input_snapshot->>'workflow_version'='journal_format_check_v1' AND jsonb_typeof(input_snapshot->'target')='object' AND jsonb_typeof(input_snapshot->'manuscript')='object' AND input_snapshot->>'check_version'='1' AND input_snapshot->'real_model_calls'='false'::jsonb AND input_snapshot->'real_network_calls'='false'::jsonb) IS TRUE)",name='tasks_journal_format_snapshot_check'),
        CheckConstraint("task_type<>'journal_adaptation' OR ((input_snapshot->>'kind'='journal_adaptation' AND input_snapshot->>'workflow_version'='journal_adaptation_v1' AND jsonb_typeof(input_snapshot->'manuscript')='object' AND jsonb_typeof(input_snapshot->'selected_action_ids')='array' AND input_snapshot->'real_model_calls'='false'::jsonb AND input_snapshot->'real_network_calls'='false'::jsonb) IS TRUE)",name='tasks_journal_adaptation_snapshot_check'),
        CheckConstraint("task_type<>'review_round_plan' OR ((workflow_version='review_round_plan_v1' AND input_snapshot->>'kind'='review_round_plan' AND input_snapshot->>'workflow_version'='review_round_plan_v1' AND jsonb_typeof(input_snapshot->'manuscript')='object' AND jsonb_typeof(input_snapshot->'sources')='array' AND input_snapshot->'real_model_calls'='false'::jsonb AND input_snapshot->'real_network_calls'='false'::jsonb) IS TRUE)",name='tasks_review_round_snapshot_check'),
        CheckConstraint("task_type<>'review_revision' OR ((workflow_version='review_revision_v1' AND input_snapshot->>'kind'='review_revision' AND input_snapshot->'real_model_calls'='false'::jsonb AND input_snapshot->'real_network_calls'='false'::jsonb) IS TRUE)",name='tasks_review_revision_snapshot_check'),
        CheckConstraint("task_type<>'review_document_export' OR ((workflow_version='review_document_export_v1' AND input_snapshot->>'kind'='review_document_export' AND input_snapshot->'real_model_calls'='false'::jsonb AND input_snapshot->'real_network_calls'='false'::jsonb) IS TRUE)",name='tasks_review_document_export_snapshot_check'),
        CheckConstraint(f'status IN ({STATUSES})', name='tasks_status_check'),
        CheckConstraint(f'phase IN ({PHASES})', name='tasks_phase_check'),
        CheckConstraint(f'reason_code IN ({REASONS})', name='tasks_reason_check'),
        CheckConstraint('revision >= 1', name='tasks_revision_check'),
        CheckConstraint('current_attempt >= 0', name='tasks_current_attempt_check'),
        CheckConstraint('length(idempotency_key) >= 1 AND length(idempotency_key) <= 128', name='tasks_key_length_check'),
        CheckConstraint("input_digest ~ '^[0-9a-f]{64}$'", name='tasks_digest_check'),
        CheckConstraint('length(workflow_version) >= 1', name='tasks_workflow_version_check'),
        CheckConstraint("jsonb_typeof(input_snapshot) = 'object'", name='tasks_snapshot_object_check'),
        CheckConstraint("figure_candidate IS NULL OR jsonb_typeof(figure_candidate) = 'object'",
                        name='tasks_figure_candidate_check'),
        CheckConstraint('updated_at >= created_at', name='tasks_time_order_check'),
    )
    Index('tasks_result_analysis_run', tasks.c.result_analysis_run_id)
    Index('tasks_project_created', tasks.c.project_id, tasks.c.created_at.desc(), tasks.c.id)
    Index('tasks_user_status', tasks.c.user_id, tasks.c.status)

    attempts = Table(
        'task_attempts', metadata,
        Column('id', Text, primary_key=True),
        Column('task_id', Text, ForeignKey('tasks.id'), nullable=False),
        Column('attempt_no', Integer, nullable=False),
        Column('status', Text, nullable=False),
        Column('started_at', DateTime(timezone=True), nullable=False),
        Column('finished_at', DateTime(timezone=True)),
        Column('reason_code', Text),
        Column('lease_owner', Text),
        Column('lease_expires_at', DateTime(timezone=True)),
        Column('heartbeat_at', DateTime(timezone=True)),
        UniqueConstraint('task_id', 'attempt_no', name='task_attempts_number_key'),
        CheckConstraint('attempt_no >= 1', name='task_attempts_number_check'),
        CheckConstraint(f'status IN ({ATTEMPT_STATUSES})', name='task_attempts_status_check'),
        CheckConstraint(f'reason_code IN ({REASONS})', name='task_attempts_reason_check'),
        CheckConstraint('finished_at >= started_at', name='task_attempts_time_order_check'),
        CheckConstraint("(status = 'running' AND finished_at IS NULL) OR (status <> 'running' AND finished_at IS NOT NULL)", name='task_attempts_finish_check'),
    )

    Index('task_attempts_expiring', attempts.c.status, attempts.c.lease_expires_at)

    events = Table(
        'task_events', metadata,
        Column('task_id', Text, ForeignKey('tasks.id'), primary_key=True),
        Column('seq', BigInteger, primary_key=True, autoincrement=False),
        Column('task_revision', Integer, nullable=False),
        Column('event_type', Text, nullable=False),
        Column('status', Text, nullable=False),
        Column('phase', Text, nullable=False),
        Column('reason_code', Text),
        Column('created_at', DateTime(timezone=True), nullable=False),
        CheckConstraint('seq = task_revision AND task_revision >= 1', name='task_events_revision_check'),
        CheckConstraint("event_type IN ('created', 'started', 'phase_changed', 'waiting', 'succeeded', 'failed', 'cancelled', 'requeued', 'deferred')", name='task_events_type_check'),
        CheckConstraint(f'status IN ({STATUSES})', name='task_events_status_check'),
        CheckConstraint(f'phase IN ({PHASES})', name='task_events_phase_check'),
        CheckConstraint(f'reason_code IN ({REASONS})', name='task_events_reason_check'),
    )

    outbox = Table(
        'task_outbox', metadata,
        Column('id', Text, primary_key=True),
        Column('task_id', Text, ForeignKey('tasks.id'), nullable=False),
        Column('task_revision', Integer, nullable=False),
        Column('event_type', Text, nullable=False),
        Column('available_at', DateTime(timezone=True), nullable=False),
        Column('created_at', DateTime(timezone=True), nullable=False),
        Column('published_at', DateTime(timezone=True)),
        Column('publish_attempts', Integer, nullable=False),
        UniqueConstraint('task_id', 'task_revision', 'event_type', name='task_outbox_event_key'),
        CheckConstraint('task_revision >= 1', name='task_outbox_revision_check'),
        CheckConstraint("event_type = 'task_ready'", name='task_outbox_type_check'),
        CheckConstraint('publish_attempts >= 0', name='task_outbox_attempts_check'),
    )
    Index('task_outbox_pending', outbox.c.published_at, outbox.c.available_at, outbox.c.id)
    return tasks, attempts, events, outbox
