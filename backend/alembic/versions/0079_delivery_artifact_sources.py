"""Retain immutable sources for analysis artifacts selected for delivery."""

from alembic import op

from app.db.schema import delivery_artifact_sources


revision = '0079_delivery_artifact_sources'
down_revision = '0078_project_assignments'
branch_labels = depends_on = None


def upgrade():
    delivery_artifact_sources.create(op.get_bind())


def downgrade():
    exists = op.get_bind().exec_driver_sql('SELECT EXISTS (SELECT 1 FROM delivery_artifact_sources)').scalar_one()
    if exists:
        raise RuntimeError('Saved delivery artifact provenance would be lost.')
    op.drop_table('delivery_artifact_sources')
