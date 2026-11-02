"""Delivery snapshots and acceptance events; no historical data rewrite."""
from alembic import op
import sqlalchemy as sa
revision='0070_delivery_snapshots'
down_revision='0069_manuscript_presentation'
branch_labels=None
depends_on=None

def upgrade():
    from app.db.delivery_schema import define_delivery_tables
    from app.db.schema import metadata
    for name in ('delivery_snapshots','delivery_acceptance_events'):
        metadata.tables[name].create(op.get_bind())
    op.execute("CREATE FUNCTION delivery_reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Delivery facts are append-only'; END $$")
    for table in ('delivery_snapshots','delivery_acceptance_events'):
        op.execute(f'CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION delivery_reject_mutation()')
    from app.db.task_schema import TASK_TYPES
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks',f'task_type IN ({TASK_TYPES})')
    op.create_check_constraint('delivery_task_snapshot_check','tasks',"task_type<>'delivery_package' OR (workflow_version='delivery_package_v1' AND input_snapshot->>'kind'=task_type AND input_snapshot->>'project_id'=project_id AND input_snapshot->>'snapshot_id' IS NOT NULL AND input_snapshot->'real_model_calls'='false'::jsonb AND input_snapshot->'real_network_calls'='false'::jsonb) IS TRUE")

def downgrade():
    op.drop_constraint('delivery_task_snapshot_check','tasks',type_='check')
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    from app.db.task_schema import TASK_TYPES
    op.create_check_constraint('tasks_type_check','tasks',"task_type IN ("+TASK_TYPES.replace("'research_fact_draft','delivery_package'","'research_fact_draft'")+")")
    op.drop_table('delivery_acceptance_events');op.drop_table('delivery_snapshots');op.execute('DROP FUNCTION delivery_reject_mutation()')

