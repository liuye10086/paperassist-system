"""Append-only fixed bilingual presentation metadata, no existing data rewrite."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision='0069_manuscript_presentation'
down_revision='0068_bio_external_evidence'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('manuscript_presentation_versions',
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
    op.create_index('mpv_project_created','manuscript_presentation_versions',['project_id',sa.text('created_at DESC'),'id'])
    op.execute("CREATE FUNCTION mpv_reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Presentation versions are append-only'; END $$")
    op.execute('CREATE TRIGGER mpv_append_only BEFORE UPDATE OR DELETE ON manuscript_presentation_versions FOR EACH ROW EXECUTE FUNCTION mpv_reject_mutation()')

def downgrade():
    op.drop_table('manuscript_presentation_versions')
    op.execute('DROP FUNCTION mpv_reject_mutation()')
