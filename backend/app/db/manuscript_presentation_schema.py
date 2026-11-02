"""Owner/root scoped append-only presentation snapshots."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

def define_manuscript_presentation_table(metadata):
    table=sa.Table('manuscript_presentation_versions',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('manuscript_id',sa.Text,nullable=False),
        sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('revision',sa.Integer,nullable=False),sa.Column('base_version_id',sa.Text,nullable=False),sa.Column('peer_version_id',sa.Text),
        sa.Column('idempotency_key',sa.Text,nullable=False),sa.Column('request_json',JSONB,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),
        sa.Column('snapshot_json',JSONB,nullable=False),sa.Column('snapshot_sha256',sa.Text,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['manuscript_id','project_id','user_id'],['manuscripts.id','manuscripts.project_id','manuscripts.user_id'],name='mpv_root_fk'),
        sa.ForeignKeyConstraint(['base_version_id','manuscript_id'],['manuscript_versions.id','manuscript_versions.manuscript_id'],name='mpv_base_root_fk'),
        sa.ForeignKeyConstraint(['base_version_id','project_id','user_id'],['manuscript_versions.id','manuscript_versions.project_id','manuscript_versions.user_id'],name='mpv_base_scope_fk'),
        sa.ForeignKeyConstraint(['peer_version_id','project_id','user_id'],['manuscript_versions.id','manuscript_versions.project_id','manuscript_versions.user_id'],name='mpv_peer_fk'),
        sa.UniqueConstraint('manuscript_id','revision',name='mpv_revision_key'),sa.UniqueConstraint('manuscript_id','idempotency_key',name='mpv_request_key'),
        sa.CheckConstraint("revision>=1 AND (peer_version_id IS NULL OR peer_version_id<>base_version_id) AND idempotency_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$' AND snapshot_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(request_json)='object' AND jsonb_typeof(snapshot_json)='object'",name='mpv_snapshot_check'))
    sa.Index('mpv_project_created',table.c.project_id,table.c.created_at.desc(),table.c.id)
    return table
