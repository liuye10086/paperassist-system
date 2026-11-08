"""Immutable aliases for repeated analysis/report submissions."""
from alembic import op

revision='0073_analysis_request_receipts'
down_revision='0072_single_cell_annotations'
branch_labels=depends_on=None


def upgrade():
    op.execute("""CREATE TABLE analysis_request_receipts (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        request_key TEXT NOT NULL,
        request_digest TEXT NOT NULL,
        target_id TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        FOREIGN KEY(project_id,user_id) REFERENCES projects(id,owner_id),
        CONSTRAINT analysis_receipt_request_key UNIQUE(user_id,project_id,kind,request_key),
        CONSTRAINT analysis_receipt_kind CHECK(kind IN ('bio_analysis_run','bio_insight_run','research_report')),
        CONSTRAINT analysis_receipt_key CHECK(length(request_key) BETWEEN 1 AND 128),
        CONSTRAINT analysis_receipt_digest CHECK(request_digest ~ '^[0-9a-f]{64}$'),
        CONSTRAINT analysis_receipt_target CHECK(length(target_id) BETWEEN 1 AND 64)
    )""")
    op.execute('CREATE INDEX analysis_receipt_target_scope ON analysis_request_receipts(project_id,kind,target_id)')


def downgrade():
    raise RuntimeError('Request identities are retained; automatic downgrade is disabled.')
