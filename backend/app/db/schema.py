"""SQLAlchemy Core metadata matching the persisted PaperAssist v6 contract."""

from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION

from sqlalchemy import (
    Boolean, BigInteger, CheckConstraint, Column, ForeignKey, Identity, Index, Integer,
    MetaData, Table, Text, UniqueConstraint,
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
    CheckConstraint("default_output_language IN ('zh-CN', 'en')", name="projects_output_language_check"),
    CheckConstraint("project_type IN ('sci', 'thesis')", name="projects_project_type_check"),
)

files = Table(
    "files", metadata,
    Column("id", Text, primary_key=True),
    Column("project_id", Text, ForeignKey("projects.id"), nullable=False),
    Column("filename", Text, nullable=False),
    Column("file_type", Text, nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    Column("sha256", Text, nullable=False),
    Column("uploaded_at", Text, nullable=False),
    Column("parse_status", Text, nullable=False),
    Column("error_json", Text),
    Column("preview_json", Text),
    CheckConstraint("parse_status IN ('parsed', 'failed')", name="files_parse_status_check"),
)
Index("files_project", files.c.project_id, files.c.uploaded_at.desc())

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
    UniqueConstraint("analysis_run_id", "renderer_version", name="figures_input_key"),
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
