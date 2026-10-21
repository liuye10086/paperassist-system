"""Immutable candidate-bound manual review artifacts."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

def define_manuscript_writing_review_tables(metadata):
    table=sa.Table('manuscript_writing_reviews',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('request_id',sa.Text,nullable=False),
        sa.Column('manuscript_id',sa.Text,nullable=False),sa.Column('base_version_id',sa.Text,nullable=False),
        sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('request_key',sa.Text,nullable=False),sa.Column('request_json',JSONB,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),
        sa.Column('candidate_sha256',sa.Text,nullable=False),sa.Column('reviewed_candidate_json',JSONB,nullable=False),
        sa.Column('reviewed_candidate_sha256',sa.Text,nullable=False),sa.Column('report_json',JSONB,nullable=False),sa.Column('review_sha256',sa.Text,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('request_id','request_key',name='mwr_request_key'),
        sa.UniqueConstraint('id','project_id','user_id',name='mwr_scope'),
        sa.UniqueConstraint('id','request_id','manuscript_id','project_id','user_id','base_version_id',name='mwr_language_scope'),
        sa.ForeignKeyConstraint(['request_id','manuscript_id','project_id','user_id','base_version_id'],
            ['manuscript_writing_requests.task_id','manuscript_writing_requests.manuscript_id','manuscript_writing_requests.project_id','manuscript_writing_requests.user_id','manuscript_writing_requests.base_version_id'],name='mwr_request_scope'),
        sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$' AND candidate_sha256 ~ '^[0-9a-f]{64}$' AND reviewed_candidate_sha256 ~ '^[0-9a-f]{64}$' AND review_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(request_json)='object' AND jsonb_typeof(reviewed_candidate_json)='object' AND jsonb_typeof(report_json)='object'",name='mwr_json_hashes'))
    return (table,)
