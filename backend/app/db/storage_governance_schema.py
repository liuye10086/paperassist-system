"""Asset quota ledger, logical references and durable publication reservations."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def define_storage_governance_tables(metadata):
    policies=sa.Table('storage_policies',metadata,
        sa.Column('scope_type',sa.Text,primary_key=True),sa.Column('scope_id',sa.Text,primary_key=True),
        sa.Column('mode',sa.Text,nullable=False),sa.Column('limit_bytes',sa.BigInteger,nullable=False),
        sa.Column('revision',sa.Integer,nullable=False,server_default='0'),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('clock_timestamp()')),
        sa.CheckConstraint("scope_type IN ('user','project') AND mode IN ('observe_only','enforced') AND limit_bytes>=0",name='storage_policy_values'))
    objects=sa.Table('storage_objects',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('namespace',sa.Text,nullable=False),
        sa.Column('object_key',sa.Text,nullable=False),sa.Column('size_bytes',sa.BigInteger,nullable=False),
        sa.Column('sha256',sa.Text,nullable=False),sa.Column('state',sa.Text,nullable=False),
        sa.Column('scanned_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('clock_timestamp()')),
        sa.UniqueConstraint('namespace','object_key',name='storage_physical_identity'),
        sa.CheckConstraint("size_bytes>=0 AND state IN ('present','missing','changed','unknown','deleted')",name='storage_object_values'))
    refs=sa.Table('storage_references',metadata,
        sa.Column('object_id',sa.Text,sa.ForeignKey('storage_objects.id'),primary_key=True),
        sa.Column('project_id',sa.Text,sa.ForeignKey('projects.id'),primary_key=True),
        sa.Column('owner_id',sa.Text,sa.ForeignKey('users.id')),sa.Column('kind',sa.Text,nullable=False))
    reservations=sa.Table('storage_reservations',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('namespace',sa.Text,nullable=False),
        sa.Column('project_id',sa.Text,sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('owner_id',sa.Text,sa.ForeignKey('users.id')),sa.Column('operation_key',sa.Text,nullable=False),
        sa.Column('object_key',sa.Text,nullable=False),sa.Column('size_bytes',sa.BigInteger,nullable=False),
        sa.Column('state',sa.Text,nullable=False),sa.Column('kind',sa.Text,nullable=False),
        sa.Column('task_id',sa.Text),sa.Column('sha256',sa.Text),
        sa.Column('capacity_bytes',sa.BigInteger),sa.Column('candidate_json',JSONB),
        sa.CheckConstraint('capacity_bytes IS NULL OR (capacity_bytes>=size_bytes AND capacity_bytes>=0)',name='storage_capacity_values'),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('clock_timestamp()')),
        sa.UniqueConstraint('namespace','project_id','operation_key',name='storage_reservation_operation'),
        sa.CheckConstraint("size_bytes>=0 AND state IN ('reserved','settled','released','unknown')",name='storage_reservation_values'))
    scans=sa.Table('storage_inventory_scans',metadata,
        sa.Column('id',sa.Integer,primary_key=True),sa.Column('summary',JSONB,nullable=False),
        sa.CheckConstraint('id=1',name='storage_scan_singleton'))
    events=sa.Table('storage_policy_events',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('scope_type',sa.Text,nullable=False),sa.Column('scope_id',sa.Text,nullable=False),
        sa.Column('revision',sa.Integer,nullable=False),sa.Column('actor_user_id',sa.Text,sa.ForeignKey('users.id')),
        sa.Column('reason',sa.Text,nullable=False),sa.Column('before_limit_bytes',sa.BigInteger,nullable=False),
        sa.Column('after_limit_bytes',sa.BigInteger,nullable=False),sa.Column('before_mode',sa.Text,nullable=False),sa.Column('after_mode',sa.Text,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('clock_timestamp()')),
        sa.UniqueConstraint('scope_type','scope_id','revision',name='storage_policy_event_revision'))
    return policies,objects,refs,reservations,scans,events
