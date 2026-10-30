"""Small append-only operational history, separate from research payloads."""
import sqlalchemy as sa


def define_admin_operations_tables(metadata, *, include_task_operation=False):
    audit = sa.Table('admin_audit_events', metadata,
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('source', sa.Text, nullable=False),
        sa.Column('operator', sa.Text),
        sa.Column('actor_user_id', sa.Text, sa.ForeignKey('users.id')),
        sa.Column('target_user_id', sa.Text, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('before_role', sa.Text), sa.Column('after_role', sa.Text, nullable=False),
        sa.Column('before_active', sa.Boolean), sa.Column('after_active', sa.Boolean, nullable=False),
        sa.Column('reason', sa.Text, nullable=False),
        sa.Column('effective_at', sa.Double, nullable=False),
        sa.Column('request_id', sa.Text),
        sa.CheckConstraint("source IN ('web','cli') AND after_role IN ('user','admin') AND (before_role IS NULL OR before_role IN ('user','admin'))",name='admin_audit_values'),
        sa.CheckConstraint("length(reason) BETWEEN 5 AND 500 AND (operator IS NULL OR length(operator) BETWEEN 1 AND 128)",name='admin_audit_bounds'),
        sa.CheckConstraint("source<>'web' OR (actor_user_id IS NOT NULL AND request_id IS NOT NULL)",name='admin_audit_actor'),
        sa.CheckConstraint("request_id IS NULL OR request_id ~ '^[0-9a-f]{32}$'",name='admin_audit_request'),
    )
    sa.Index('admin_audit_target_time',audit.c.target_user_id,audit.c.effective_at.desc(),audit.c.id)
    events = sa.Table('operational_request_events', metadata,
        sa.Column('request_id',sa.Text,primary_key=True),
        sa.Column('route_template',sa.Text), sa.Column('method',sa.Text,nullable=False),
        sa.Column('status',sa.Integer,nullable=False), sa.Column('elapsed_ms',sa.BigInteger,nullable=False),
        sa.Column('user_id',sa.Text,sa.ForeignKey('users.id')),
        sa.Column('task_id',sa.Text,sa.ForeignKey('tasks.id')),
        sa.Column('error_code',sa.Text),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint("request_id ~ '^[0-9a-f]{32}$' AND status BETWEEN 100 AND 599 AND elapsed_ms>=0",name='operational_event_values'),
        sa.CheckConstraint("method IN ('GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS','OTHER') AND (route_template IS NULL OR length(route_template)<=512) AND (error_code IS NULL OR length(error_code)<=128)",name='operational_event_bounds'),
    )
    # 0051 imports this helper too: keep that historical table definition frozen.
    if include_task_operation:
        events.append_column(sa.Column('task_operation',sa.Text))
        events.append_constraint(sa.CheckConstraint(
            "task_operation IS NULL OR (method='POST' AND route_template IS NOT NULL AND route_template='/api/v1/tasks/{task_id}/resume' AND task_operation IN ('retry','resume'))",
            name='operational_task_operation_values'))
    sa.Index('operational_events_created',events.c.created_at.desc(),events.c.request_id)
    sa.Index('operational_events_task',events.c.task_id,events.c.created_at.desc())
    collection=sa.Table('operational_collection',metadata,
        sa.Column('id',sa.Integer,primary_key=True),
        sa.Column('started_at',sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint('id=1',name='operational_collection_singleton'))
    return audit,events,collection
