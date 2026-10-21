"""0038 adds review history only; no existing row/column/task type changes."""
from alembic import op
import sqlalchemy as sa
revision='0038_manuscript_review'
down_revision='0037_manuscript_writing'
branch_labels=None
depends_on=None
"""Additive review candidates and immutable input/report digests."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

def define_manuscript_review_tables(metadata):
    table=sa.Table('manuscript_reviews',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('manuscript_id',sa.Text,nullable=False),sa.Column('base_version_id',sa.Text,nullable=False),
        sa.Column('idempotency_key',sa.Text,nullable=False),sa.Column('request_json',JSONB,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),
        sa.Column('input_snapshot',JSONB,nullable=False),sa.Column('input_digest',sa.Text,nullable=False),
        sa.Column('candidate_json',JSONB,nullable=False),sa.Column('candidate_sha256',sa.Text,nullable=False),
        sa.Column('report_json',JSONB,nullable=False),sa.Column('report_sha256',sa.Text,nullable=False),sa.Column('rules_version',sa.Text,nullable=False),
        sa.Column('published_revision',sa.Integer),sa.Column('publish_key',sa.Text),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['manuscript_id','project_id','user_id'],['manuscripts.id','manuscripts.project_id','manuscripts.user_id'],name='mr_root_fk'),
        sa.ForeignKeyConstraint(['base_version_id','manuscript_id'],['manuscript_versions.id','manuscript_versions.manuscript_id'],name='mr_base_fk'),
        sa.UniqueConstraint('manuscript_id','idempotency_key',name='mr_request_key'),
        sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$' AND input_digest ~ '^[0-9a-f]{64}$' AND candidate_sha256 ~ '^[0-9a-f]{64}$' AND report_sha256 ~ '^[0-9a-f]{64}$'",name='mr_hash_check'),
        sa.CheckConstraint("jsonb_typeof(request_json)='object' AND jsonb_typeof(input_snapshot)='object' AND jsonb_typeof(candidate_json)='object' AND jsonb_typeof(report_json)='object' AND updated_at>=created_at",name='mr_snapshot_check'),
        sa.CheckConstraint("(published_revision IS NULL AND publish_key IS NULL) OR (published_revision IS NOT NULL AND publish_key IS NOT NULL AND published_revision>1 AND publish_key ~ '^[!-~]{1,128}$')",name='mr_publication_check'))
    sa.Index('mr_project_created',table.c.project_id,table.c.created_at.desc(),table.c.id)
    return (table,)

def frozen_tables():
    metadata=sa.MetaData()
    for name,columns in (('manuscripts',('id','project_id','user_id')),('manuscript_versions',('id','manuscript_id'))):
        sa.Table(name,metadata,*(sa.Column(c,sa.Text) for c in columns))
    return define_manuscript_review_tables(metadata)
def upgrade():
    for table in frozen_tables(): table.create(op.get_bind())
def downgrade():
    bind=op.get_bind()
    if bind.exec_driver_sql('SELECT EXISTS(SELECT 1 FROM manuscript_reviews)').scalar_one():
        raise RuntimeError('Review history exists; refusing destructive downgrade.')
    for table in reversed(frozen_tables()): table.drop(bind)
