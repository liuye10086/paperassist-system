"""Independent queued reference candidates and descriptive annotation evidence."""
from alembic import op
import sqlalchemy as sa

revision='0072_single_cell_annotations'
down_revision='0071_bio_cloud_runs'
branch_labels=depends_on=None


def upgrade():
    from app.db.task_schema import TASK_TYPES
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks',f'task_type IN ({TASK_TYPES})')
    # The original evidence check was unnamed; resolve only this owning table's
    # source-discriminant constraint, leaving scope/retention checks intact.
    connection=op.get_bind()
    names=connection.execute(sa.text("""SELECT conname FROM pg_constraint
        WHERE conrelid='bio_annotation_evidence'::regclass AND contype='c'
        AND pg_get_constraintdef(oid) LIKE '%kind%' AND pg_get_constraintdef(oid) LIKE '%marker%'""")).scalars().all()
    for name in names:op.drop_constraint(name,'bio_annotation_evidence',type_='check')
    op.create_check_constraint('bio_annotation_evidence_source_check','bio_annotation_evidence',
        "(kind='marker' AND analysis_artifact_id IS NOT NULL AND file_id IS NULL) OR (kind='file' AND file_id IS NOT NULL AND analysis_artifact_id IS NULL) OR (kind IN ('manual','reference') AND analysis_artifact_id IS NULL AND file_id IS NULL AND length(trim(note))>0)")
    op.create_check_constraint('tasks_annotation_snapshot_check','tasks',
        "task_type<>'bio_annotation' OR (workflow_version='bio_annotation_v1' AND input_snapshot->>'kind'=task_type AND input_snapshot->>'project_id'=project_id AND input_snapshot->>'run_id'=id AND jsonb_typeof(input_snapshot->'parent_processed_source')='object' AND input_snapshot->>'request_digest' ~ '^[0-9a-f]{64}$') IS TRUE")


def downgrade():
    raise RuntimeError('Retained machine candidates require an explicit migration plan; automatic downgrade is disabled.')
