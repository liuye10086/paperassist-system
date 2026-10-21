"""Immutable final language artifact, independently bound to the scientific review."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

def define_manuscript_writing_language_tables(metadata):
    table=sa.Table('manuscript_writing_language_reviews',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('request_id',sa.Text,nullable=False),
        sa.Column('manuscript_id',sa.Text,nullable=False),sa.Column('base_version_id',sa.Text,nullable=False),
        sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('review_id',sa.Text,nullable=False),sa.Column('review_sha256',sa.Text,nullable=False),
        sa.Column('request_key',sa.Text,nullable=False),sa.Column('request_json',JSONB,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),
        sa.Column('candidate_json',JSONB,nullable=False),sa.Column('candidate_sha256',sa.Text,nullable=False),
        sa.Column('inventory_json',JSONB,nullable=False),sa.Column('inventory_sha256',sa.Text,nullable=False),
        sa.Column('artifact_sha256',sa.Text,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('request_id','request_key',name='mwlr_request_key'),
        sa.ForeignKeyConstraint(['review_id','request_id','manuscript_id','project_id','user_id','base_version_id'],
            ['manuscript_writing_reviews.id','manuscript_writing_reviews.request_id','manuscript_writing_reviews.manuscript_id','manuscript_writing_reviews.project_id','manuscript_writing_reviews.user_id','manuscript_writing_reviews.base_version_id'],name='mwlr_science_scope'),
        sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$' AND review_sha256 ~ '^[0-9a-f]{64}$' AND candidate_sha256 ~ '^[0-9a-f]{64}$' AND inventory_sha256 ~ '^[0-9a-f]{64}$' AND artifact_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(request_json)='object' AND jsonb_typeof(candidate_json)='object' AND jsonb_typeof(inventory_json)='array'",name='mwlr_json_hashes'))
    return (table,)
