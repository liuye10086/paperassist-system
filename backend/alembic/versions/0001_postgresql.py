"""Create the PostgreSQL schema preserving the PaperAssist v6 data contract."""

from alembic import op
import sqlalchemy as sa


revision = "0001_postgresql"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Keep the initial schema frozen here so later metadata changes do not alter
    # how existing installations replay this migration.
    op.create_table(
        "projects",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("research_topic", sa.Text(), nullable=False),
        sa.Column("project_type", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint("project_type IN ('sci', 'thesis')", name="projects_project_type_check"),
    )
    op.create_table(
        "files",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("file_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("uploaded_at", sa.Text(), nullable=False),
        sa.Column("parse_status", sa.Text(), nullable=False),
        sa.Column("error_json", sa.Text()),
        sa.Column("preview_json", sa.Text()),
        sa.CheckConstraint("parse_status IN ('parsed', 'failed')", name="files_parse_status_check"),
    )
    op.create_index("files_project", "files", ["project_id", sa.text("uploaded_at DESC")])
    op.create_table(
        "analysis_setups",
        sa.Column("file_id", sa.Text(), sa.ForeignKey("files.id"), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("setup_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("file_id", sa.Text(), sa.ForeignKey("files.id"), nullable=False),
        sa.Column("setup_revision", sa.Integer(), nullable=False),
        sa.Column("engine_version", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("file_id", "setup_revision", "engine_version", name="analysis_runs_input_key"),
    )
    op.create_table(
        "figures",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("analysis_run_id", sa.Text(), sa.ForeignKey("analysis_runs.id"), nullable=False),
        sa.Column("renderer_version", sa.Text(), nullable=False),
        sa.Column("figure_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("analysis_run_id", "renderer_version", name="figures_input_key"),
    )
    op.create_table(
        "figure_jobs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("analysis_run_id", sa.Text(), sa.ForeignKey("analysis_runs.id"), nullable=False),
        sa.Column("renderer_version", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("job_json", sa.Text(), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False, unique=True),
    )
    op.create_index("figure_jobs_run", "figure_jobs", ["analysis_run_id", sa.text("created_at DESC")])
    op.create_table(
        "explanations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("analysis_run_id", sa.Text(), sa.ForeignKey("analysis_runs.id"), nullable=False),
        sa.Column("figure_id", sa.Text(), sa.ForeignKey("figures.id"), nullable=False),
        sa.Column("engine_version", sa.Text(), nullable=False),
        sa.Column("explanation_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("figure_id", "engine_version", name="explanations_input_key"),
    )
    op.create_table(
        "explanation_jobs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("analysis_run_id", sa.Text(), sa.ForeignKey("analysis_runs.id"), nullable=False),
        sa.Column("figure_id", sa.Text(), sa.ForeignKey("figures.id"), nullable=False),
        sa.Column("engine_version", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("job_json", sa.Text(), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False, unique=True),
    )
    op.create_index("explanation_jobs_figure", "explanation_jobs", ["figure_id", sa.text("created_at DESC")])
    op.create_table(
        "reports",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("analysis_run_id", sa.Text(), sa.ForeignKey("analysis_runs.id"), nullable=False),
        sa.Column("explanation_id", sa.Text(), sa.ForeignKey("explanations.id"), nullable=False),
        sa.Column("renderer_version", sa.Text(), nullable=False),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.Column("input_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("explanation_id", "renderer_version", name="reports_input_key"),
    )


def downgrade():
    raise RuntimeError("Automatic destructive downgrade is disabled; restore a verified backup instead.")
