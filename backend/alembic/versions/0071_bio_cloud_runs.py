"""External single-cell runs and cancellable unified tasks."""
from alembic import op

revision = '0071_bio_cloud_runs'
down_revision = '0070_delivery_snapshots'
branch_labels = depends_on = None


def upgrade():
    from app.db.schema import metadata
    from app.db.bio_cloud_schema import TABLE_NAMES
    from app.db.task_schema import TASK_TYPES, STATUSES, ATTEMPT_STATUSES
    for name in TABLE_NAMES:
        metadata.tables[name].create(bind=op.get_bind(), checkfirst=False)
    changes = [('tasks', 'tasks_type_check', f'task_type IN ({TASK_TYPES})'),
        ('tasks','tasks_status_check',f'status IN ({STATUSES})'),
        ('task_attempts','task_attempts_status_check',f'status IN ({ATTEMPT_STATUSES})'),
        ('task_events','task_events_status_check',f'status IN ({STATUSES})'),
        ('task_events','task_events_type_check',"event_type IN ('created','started','phase_changed','waiting','succeeded','failed','cancelled','requeued','deferred')")]
    for table, name, condition in changes:
        op.drop_constraint(name, table, type_='check')
        op.create_check_constraint(name, table, condition)
    op.create_check_constraint('tasks_bio_cloud_snapshot_check', 'tasks', "task_type<>'bio_cloud_run' OR (workflow_version='bio_cloud_run_v1' AND input_snapshot->>'kind'='bio_cloud_run' AND input_snapshot->>'project_id'=project_id AND input_snapshot->>'run_id' IS NOT NULL) IS TRUE")


def downgrade():
    # No silent deletion of retained cloud receipts or changes to completed tasks.
    raise RuntimeError('Cloud run history requires an explicit retention/migration plan; automatic downgrade is disabled.')
