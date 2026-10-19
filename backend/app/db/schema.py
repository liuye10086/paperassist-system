"""SQLAlchemy Core metadata matching the persisted PaperAssist v6 contract."""

from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION, JSONB

from sqlalchemy import (
    Boolean, BigInteger, CheckConstraint, Column, ForeignKey, Identity, Index, Integer,
    MetaData, Table, Text, UniqueConstraint, text,
)


metadata = MetaData()

projects = Table(
    "projects", metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("research_topic", Text, nullable=False),
    Column("project_type", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Column("owner_id", Text, ForeignKey("users.id")),
    Column("default_output_language", Text, nullable=False, server_default="zh-CN"),
    UniqueConstraint('id', 'owner_id', name='projects_owner_scope_key'),
    CheckConstraint("default_output_language IN ('zh-CN', 'en')", name="projects_output_language_check"),
    CheckConstraint("project_type IN ('sci', 'thesis')", name="projects_project_type_check"),
)

files = Table(
    "files", metadata,
    Column("id", Text, primary_key=True),
    Column("project_id", Text, ForeignKey("projects.id"), nullable=False),
    Column("filename", Text, nullable=False),
    Column("file_type", Text, nullable=False),
    CheckConstraint("file_type IN ('xlsx','docx','pdf','png','jpeg')", name="files_type_check"),
    Column("size_bytes", BigInteger, nullable=False),
    Column("sha256", Text, nullable=False),
    Column("uploaded_at", Text, nullable=False),
    Column("parse_status", Text, nullable=False),
    Column("error_json", Text),
    Column("preview_json", Text),
    Column("uploader_id", Text, ForeignKey("users.id")),
    Column("storage_backend", Text, nullable=False, server_default="local"),
    Column("object_key", Text),
    Column("metadata_revision", Integer, nullable=False, server_default=text("1")),
    Column("parse_revision", Integer, nullable=False, server_default=text("0")),
    Column("upload_item_id", Text, ForeignKey("file_upload_items.id", name="files_upload_item_id_fkey")),
    UniqueConstraint("upload_item_id", name="files_upload_item_key"),
    CheckConstraint("parse_revision >= 0", name="files_parse_revision_check"),
    CheckConstraint("storage_backend = 'local'", name="files_storage_backend_check"),
    CheckConstraint("metadata_revision >= 1", name="files_metadata_revision_check"),
    CheckConstraint("parse_status IN ('queued', 'parsing', 'parsed', 'failed')", name="files_parse_status_check"),
)
Index("files_project", files.c.project_id, files.c.uploaded_at.desc())
Index("files_project_uploaded_id", files.c.project_id, files.c.uploaded_at.desc(), files.c.id.asc())

file_purposes = Table(
    "file_purposes", metadata,
    Column("file_id", Text, ForeignKey("files.id"), primary_key=True),
    Column("purpose", Text, primary_key=True),
    Column("assigned_by", Text, ForeignKey("users.id")),
    Column("assigned_at", Text, nullable=False),
    CheckConstraint("purpose IN ('raw_data','figure','methods','school_template','paper','revision_material')", name="file_purposes_purpose_check"),
)

analysis_setups = Table(
    "analysis_setups", metadata,
    Column("file_id", Text, ForeignKey("files.id"), primary_key=True),
    Column("revision", Integer, nullable=False),
    Column("setup_json", Text, nullable=False),
)

analysis_runs = Table(
    "analysis_runs", metadata,
    Column("id", Text, primary_key=True),
    Column("file_id", Text, ForeignKey("files.id"), nullable=False),
    Column("setup_revision", Integer, nullable=False),
    Column("engine_version", Text, nullable=False),
    Column("completed_at", Text, nullable=False),
    Column("result_json", Text, nullable=False),
    UniqueConstraint("file_id", "setup_revision", "engine_version", name="analysis_runs_input_key"),
)

figures = Table(
    "figures", metadata,
    Column("id", Text, primary_key=True),
    Column("analysis_run_id", Text, ForeignKey("analysis_runs.id"), nullable=False),
    Column("renderer_version", Text, nullable=False),
    Column("figure_json", Text, nullable=False),
    Column("figure_config_version_id", Text, ForeignKey("figure_config_versions.id"), nullable=True),
)

figure_jobs = Table(
    "figure_jobs", metadata,
    Column("id", Text, primary_key=True),
    Column("analysis_run_id", Text, ForeignKey("analysis_runs.id"), nullable=False),
    Column("renderer_version", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("job_json", Text, nullable=False),
    Column("seq", BigInteger, Identity(always=True), nullable=False, unique=True),
)
Index("figure_jobs_run", figure_jobs.c.analysis_run_id, figure_jobs.c.created_at.desc())

explanations = Table(
    "explanations", metadata,
    Column("id", Text, primary_key=True),
    Column("analysis_run_id", Text, ForeignKey("analysis_runs.id"), nullable=False),
    Column("figure_id", Text, ForeignKey("figures.id"), nullable=False),
    Column("engine_version", Text, nullable=False),
    Column("explanation_json", Text, nullable=False),
    UniqueConstraint("figure_id", "engine_version", name="explanations_input_key"),
)

explanation_jobs = Table(
    "explanation_jobs", metadata,
    Column("id", Text, primary_key=True),
    Column("analysis_run_id", Text, ForeignKey("analysis_runs.id"), nullable=False),
    Column("figure_id", Text, ForeignKey("figures.id"), nullable=False),
    Column("engine_version", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("job_json", Text, nullable=False),
    Column("seq", BigInteger, Identity(always=True), nullable=False, unique=True),
)
Index("explanation_jobs_figure", explanation_jobs.c.figure_id, explanation_jobs.c.created_at.desc())

reports = Table(
    "reports", metadata,
    Column("id", Text, primary_key=True),
    Column("analysis_run_id", Text, ForeignKey("analysis_runs.id"), nullable=False),
    Column("explanation_id", Text, ForeignKey("explanations.id"), nullable=False),
    Column("renderer_version", Text, nullable=False),
    Column("report_json", Text, nullable=False),
    Column("input_json", Text, nullable=False),
    UniqueConstraint("explanation_id", "renderer_version", name="reports_input_key"),
)

Index("projects_owner", projects.c.owner_id)
users = Table("users", metadata,
    Column("id", Text, primary_key=True),
    Column("email", Text, nullable=False, unique=True),
    Column("password_hash", Text, nullable=False),
    Column("role", Text, nullable=False),
    Column("active", Boolean, nullable=False),
    Column("created_at", DOUBLE_PRECISION, nullable=False),
    Column("updated_at", DOUBLE_PRECISION, nullable=False),
    Column("ui_language", Text, nullable=False, server_default="zh-CN"),
    CheckConstraint("ui_language IN ('zh-CN', 'en')", name="users_ui_language_check"),
    CheckConstraint("role IN ('user','admin')", name="users_role_check"))
sessions = Table("sessions", metadata,
    Column("token_hash", Text, primary_key=True),
    Column("user_id", Text, ForeignKey("users.id"), nullable=False),
    Column("csrf_token", Text, nullable=False),
    Column("created_at", DOUBLE_PRECISION, nullable=False),
    Column("last_seen_at", DOUBLE_PRECISION, nullable=False),
    Column("expires_at", DOUBLE_PRECISION, nullable=False))
Index("sessions_user", sessions.c.user_id)
auth_login_attempts = Table("auth_login_attempts", metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("email", Text, nullable=False),
    Column("client_ip", Text, nullable=False),
    Column("attempted_at", DOUBLE_PRECISION, nullable=False))
Index("auth_attempts_email_time", auth_login_attempts.c.email, auth_login_attempts.c.attempted_at)
Index("auth_attempts_ip_time", auth_login_attempts.c.client_ip, auth_login_attempts.c.attempted_at)

session_revocations = Table("session_revocations", metadata,
    Column("token_hash", Text, primary_key=True),
    Column("user_id", Text, ForeignKey("users.id"), nullable=False),
    Column("reason", Text, nullable=False),
    Column("revoked_at", DOUBLE_PRECISION, nullable=False),
    Column("source", Text, nullable=False))
Index("session_revocations_user_time", session_revocations.c.user_id, session_revocations.c.revoked_at)

password_recovery_codes = Table("password_recovery_codes", metadata,
    Column("code_hash", Text, primary_key=True),
    Column("user_id", Text, ForeignKey("users.id"), nullable=False),
    Column("created_at", DOUBLE_PRECISION, nullable=False),
    Column("expires_at", DOUBLE_PRECISION, nullable=False),
    Column("used_at", DOUBLE_PRECISION),
    Column("revoked_at", DOUBLE_PRECISION),
    CheckConstraint("used_at IS NULL OR revoked_at IS NULL", name="recovery_single_terminal_state"))
Index("password_recovery_user", password_recovery_codes.c.user_id)

auth_password_attempts = Table("auth_password_attempts", metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("user_id", Text, ForeignKey("users.id")),
    Column("code_hash", Text),
    Column("client_ip", Text, nullable=False),
    Column("attempted_at", DOUBLE_PRECISION, nullable=False))
Index("password_attempts_user_time", auth_password_attempts.c.user_id, auth_password_attempts.c.attempted_at)
Index("password_attempts_code_time", auth_password_attempts.c.code_hash, auth_password_attempts.c.attempted_at)
Index("password_attempts_ip_time", auth_password_attempts.c.client_ip, auth_password_attempts.c.attempted_at)
Index("projects_owner_updated", projects.c.owner_id, projects.c.updated_at.desc(), projects.c.id.asc())
Index("explanations_run", explanations.c.analysis_run_id)
Index("explanation_jobs_run", explanation_jobs.c.analysis_run_id)
Index("reports_run", reports.c.analysis_run_id)

from app.db.task_schema import define_task_tables

tasks, task_attempts, task_events, task_outbox = define_task_tables(metadata)

from app.db.model_usage_schema import define_model_usage_tables

model_budgets, model_calls, usage_events, budget_reservations = define_model_usage_tables(metadata)

from app.db.task_wait_schema import define_task_wait_tables

task_waits, task_resume_requests = define_task_wait_tables(metadata)

from app.db.task_error_schema import add_task_error_columns

add_task_error_columns(tasks, task_attempts, task_events)
tasks.append_column(Column('verification_failure', JSONB(none_as_null=True)))

from app.db.file_parsing_schema import define_file_parsing_tables
file_upload_batches, file_upload_items, file_parse_results = define_file_parsing_tables(metadata)

from app.db.dataset_schema import define_dataset_tables
file_structure_versions, dataset_versions = define_dataset_tables(metadata)

from app.db.dataset_preparation_schema import define_dataset_preparation_tables
task_checkpoints, dataset_preparation_decisions, prepared_dataset_versions = define_dataset_preparation_tables(metadata)
from app.db.quality_derivations_schema import define_quality_derivations
prepared_dataset_derivations = define_quality_derivations(metadata)

from app.db.analysis_plan_schema import define_analysis_plan_tables
analysis_plan_decisions, confirmed_analysis_plans = define_analysis_plan_tables(metadata)

from app.db.ocr_review_schema import define_ocr_review_tables
ocr_review_decisions, ocr_review_versions = define_ocr_review_tables(metadata)

from app.db.file_lifecycle_schema import define_file_lifecycle_tables
file_deletion_requests, file_reparse_assessments = define_file_lifecycle_tables(metadata)
Index('file_upload_batches_owner_created', file_upload_batches.c.project_id, file_upload_batches.c.user_id,
      file_upload_batches.c.created_at.desc(), file_upload_batches.c.id)

from app.db.figure_workbench_schema import define_figure_workbench_tables
figure_configurations, figure_config_versions, figure_projection_decisions, figure_projection_results = define_figure_workbench_tables(metadata)
Index('figures_legacy_input_key', figures.c.analysis_run_id, figures.c.renderer_version,
      unique=True, postgresql_where=text('figure_config_version_id IS NULL'))
Index('figures_config_input_key', figures.c.figure_config_version_id, figures.c.renderer_version,
      unique=True, postgresql_where=text('figure_config_version_id IS NOT NULL'))

from app.db.report_collection_schema import define_report_collection_tables
report_collections, report_collection_versions, report_collection_items, report_build_requests, collection_reports = define_report_collection_tables(metadata)

from app.db.research_materials_schema import define_research_materials
prepared_dataset_derivations_v3, external_evidence_versions = define_research_materials(metadata)

from app.db.literature_schema import define_literature_tables
literature_records, literature_searches, project_references, literature_fetch_receipts, literature_search_hits, ncbi_rate_limits = define_literature_tables(metadata)

from app.db.literature_evidence_schema import define_literature_evidence_tables
literature_materials, literature_claims, literature_claim_versions, literature_claim_evidence, literature_claim_reviews, literature_claim_supplements = define_literature_evidence_tables(metadata)

from app.db.literature_assistance_schema import define_literature_assistance_tables
literature_assistance_requests, = define_literature_assistance_tables(metadata)

from app.db.literature_pmc_schema import define_literature_pmc_tables
literature_pmc_receipts, = define_literature_pmc_tables(metadata)

from app.db.literature_citation_schema import define_literature_citation_tables
literature_citation_metadata_versions, literature_material_confirmations, literature_citation_drafts, literature_citation_versions = define_literature_citation_tables(metadata)

from app.db.literature_check_schema import define_literature_check_tables
literature_check_receipts, = define_literature_check_tables(metadata)
