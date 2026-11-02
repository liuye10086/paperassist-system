"""Only the two append-only delivery facts. Package state lives in existing tasks."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

def define_delivery_tables(metadata):
    snapshots=sa.Table('delivery_snapshots',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('project_id',sa.Text,nullable=False),sa.Column('delivery_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,sa.ForeignKey('users.id'),nullable=False),
        sa.Column('revision',sa.Integer,nullable=False),sa.Column('parent_snapshot_id',sa.Text),sa.Column('requirement_version_id',sa.Text,nullable=False),
        sa.Column('stage',sa.Text,nullable=False),sa.Column('request_key',sa.Text,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),sa.Column('snapshot_json',JSONB,nullable=False),sa.Column('sha256',sa.Text,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('id','delivery_id','project_id',name='ds_scope'),sa.UniqueConstraint('delivery_id','revision',name='ds_revision'),sa.UniqueConstraint('delivery_id','request_key',name='ds_request'),
        sa.ForeignKeyConstraint(['delivery_id','project_id'],['research_deliveries.id','research_deliveries.project_id']),
        sa.ForeignKeyConstraint(['requirement_version_id','project_id'],['research_requirement_versions.id','research_requirement_versions.project_id']),
        sa.ForeignKeyConstraint(['parent_snapshot_id','delivery_id','project_id'],['delivery_snapshots.id','delivery_snapshots.delivery_id','delivery_snapshots.project_id']),
        sa.CheckConstraint("revision>=1 AND stage IN ('first','revision','final') AND sha256 ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$' AND length(request_key) BETWEEN 1 AND 128 AND jsonb_typeof(snapshot_json)='object' AND octet_length(snapshot_json::text)<=4194304",name='ds_values'))
    acceptances=sa.Table('delivery_acceptance_events',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('snapshot_id',sa.Text,nullable=False),sa.Column('delivery_id',sa.Text,nullable=False),sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,sa.ForeignKey('users.id'),nullable=False),
        sa.Column('snapshot_sha256',sa.Text,nullable=False),sa.Column('request_key',sa.Text,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),sa.Column('event_json',JSONB,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['snapshot_id','delivery_id','project_id'],['delivery_snapshots.id','delivery_snapshots.delivery_id','delivery_snapshots.project_id']),
        sa.UniqueConstraint('snapshot_id','request_key',name='dae_request'),sa.CheckConstraint("snapshot_sha256 ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$' AND jsonb_typeof(event_json)='object'",name='dae_values'))
    return snapshots,acceptances
