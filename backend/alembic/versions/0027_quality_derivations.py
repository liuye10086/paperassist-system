"""Add quality derivation references without rewriting historical rows."""
from alembic import op
import sqlalchemy as sa

revision='0027_quality_derivations'
down_revision='0026_figure_report_versions'
branch_labels=None
depends_on=None

def upgrade():
    metadata=sa.MetaData()
    sa.Table('prepared_dataset_versions',metadata,sa.Column('id',sa.Text,primary_key=True))
    table=sa.Table('prepared_dataset_derivations',metadata,
        sa.Column('prepared_dataset_id',sa.Text,sa.ForeignKey('prepared_dataset_versions.id'),primary_key=True),
        sa.Column('base_prepared_dataset_id',sa.Text,sa.ForeignKey('prepared_dataset_versions.id'),nullable=False),
        sa.Column('object_schema_version',sa.Integer,nullable=False),
        sa.Column('transform_version',sa.Text,nullable=False),
        sa.Column('workflow_version',sa.Text,nullable=False),
        sa.Column('rules_version',sa.Text,nullable=False),
        sa.Column('manifest_object_key',sa.Text,nullable=False,unique=True),
        sa.Column('manifest_sha256',sa.Text,nullable=False),
        sa.Column('manifest_size_bytes',sa.BigInteger,nullable=False),
        sa.Column('manifest_entry_count',sa.Integer,nullable=False),
        sa.CheckConstraint('prepared_dataset_id <> base_prepared_dataset_id',name='quality_derivation_not_self'),
        sa.CheckConstraint("object_schema_version=2 AND transform_version='excel_prepare_v2' AND workflow_version='dataset_preparation_v2' AND rules_version='quality_rules_v1'",name='quality_derivation_versions'),
        sa.CheckConstraint("manifest_sha256 ~ '^[0-9a-f]{64}$' AND manifest_size_bytes>0 AND manifest_size_bytes<=16777216 AND manifest_entry_count>=0",name='quality_derivation_manifest'))
    sa.Index('quality_derivation_base',table.c.base_prepared_dataset_id)
    table.create(op.get_bind())

def downgrade():
    db=op.get_bind()
    if db.exec_driver_sql("SELECT EXISTS(SELECT 1 FROM prepared_dataset_derivations) OR EXISTS(SELECT 1 FROM tasks WHERE workflow_version='dataset_preparation_v2')").scalar_one():
        raise RuntimeError('Cannot remove quality history or v2 workflow state')
    op.drop_table('prepared_dataset_derivations')
