"""Add research materials and v3 derivations; preserve all earlier rows."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def define_research_materials(metadata):
    derivations=sa.Table('prepared_dataset_derivations_v3',metadata,
        sa.Column('prepared_dataset_id',sa.Text,sa.ForeignKey('prepared_dataset_versions.id'),primary_key=True),
        sa.Column('base_prepared_dataset_id',sa.Text,sa.ForeignKey('prepared_dataset_versions.id'),nullable=False),
        sa.Column('operation',sa.Text,nullable=False),
        sa.Column('object_schema_version',sa.Integer,nullable=False),
        sa.Column('transform_version',sa.Text,nullable=False),
        sa.Column('workflow_version',sa.Text,nullable=False),
        sa.Column('rules_version',sa.Text,nullable=False),
        sa.Column('manifest_object_key',sa.Text,nullable=False,unique=True),
        sa.Column('manifest_sha256',sa.Text,nullable=False),
        sa.Column('manifest_size_bytes',sa.BigInteger,nullable=False),
        sa.Column('manifest_entry_count',sa.Integer,nullable=False),
        sa.CheckConstraint('prepared_dataset_id <> base_prepared_dataset_id',name='derivation_v3_not_self'),
        sa.CheckConstraint("object_schema_version=3 AND transform_version='excel_prepare_v3' AND workflow_version='dataset_preparation_v3'",name='derivation_v3_versions'),
        sa.CheckConstraint("(operation='population_filter' AND rules_version='population_filter_rules_v1') OR (operation='quality' AND rules_version='quality_rules_v1')",name='derivation_v3_operation'),
        sa.CheckConstraint("manifest_sha256 ~ '^[0-9a-f]{64}$' AND manifest_size_bytes>0 AND manifest_size_bytes<=16777216 AND manifest_entry_count>=0",name='derivation_v3_manifest'))
    sa.Index('derivation_v3_base',derivations.c.base_prepared_dataset_id)
    evidence=sa.Table('external_evidence_versions',metadata,
        sa.Column('id',sa.Text,primary_key=True),
        sa.Column('evidence_id',sa.Text,nullable=False),
        sa.Column('version',sa.Integer,nullable=False),
        sa.Column('previous_version_id',sa.Text,sa.ForeignKey('external_evidence_versions.id')),
        sa.Column('project_id',sa.Text,sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('user_id',sa.Text,sa.ForeignKey('users.id'),nullable=False),
        sa.Column('file_id',sa.Text,sa.ForeignKey('files.id'),nullable=False),
        sa.Column('source_kind',sa.Text,nullable=False),
        sa.Column('document_version_id',sa.Text,sa.ForeignKey('file_parse_results.id')),
        sa.Column('ocr_review_version_id',sa.Text,sa.ForeignKey('ocr_review_versions.id')),
        sa.Column('idempotency_key',sa.Text,nullable=False),
        sa.Column('request_digest',sa.Text,nullable=False),
        sa.Column('request_json',JSONB,nullable=False),
        sa.Column('snapshot_json',JSONB,nullable=False),
        sa.Column('sha256',sa.Text,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('user_id','project_id','idempotency_key',name='evidence_request_key'),
        sa.UniqueConstraint('evidence_id','version',name='evidence_version_key'),
        sa.UniqueConstraint('previous_version_id',name='evidence_single_successor'),
        sa.CheckConstraint("version>=1 AND ((version=1 AND previous_version_id IS NULL AND id=evidence_id) OR (version>1 AND previous_version_id IS NOT NULL AND previous_version_id<>id))",name='evidence_version_shape'),
        sa.CheckConstraint("(source_kind='original' AND document_version_id IS NULL AND ocr_review_version_id IS NULL) OR (source_kind='document_version' AND document_version_id IS NOT NULL AND ocr_review_version_id IS NULL) OR (source_kind='ocr_review_version' AND document_version_id IS NULL AND ocr_review_version_id IS NOT NULL)",name='evidence_source_kind'),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$' AND request_digest ~ '^[0-9a-f]{64}$' AND idempotency_key ~ '^[!-~]{1,128}$'",name='evidence_digests'),
        sa.CheckConstraint("jsonb_typeof(request_json)='object' AND jsonb_typeof(snapshot_json)='object'",name='evidence_objects'))
    sa.Index('external_evidence_project_created',evidence.c.project_id,evidence.c.created_at.desc(),evidence.c.id)
    sa.Index('external_evidence_file',evidence.c.file_id)
    return derivations,evidence


revision='0028_research_materials'
down_revision='0027_quality_derivations'
branch_labels=None
depends_on=None

def upgrade():
    metadata=sa.MetaData()
    for name in ('prepared_dataset_versions','projects','users','files','file_parse_results','ocr_review_versions'):
        sa.Table(name,metadata,sa.Column('id',sa.Text,primary_key=True))
    derivations,evidence=define_research_materials(metadata)
    derivations.create(op.get_bind())
    evidence.create(op.get_bind())

def downgrade():
    db=op.get_bind()
    if db.exec_driver_sql("SELECT EXISTS(SELECT 1 FROM prepared_dataset_derivations_v3) OR EXISTS(SELECT 1 FROM external_evidence_versions) OR EXISTS(SELECT 1 FROM tasks WHERE workflow_version IN ('dataset_preparation_v3','analysis_plan_v4','analysis_recommendation_v4'))").scalar_one():
        raise RuntimeError('Cannot remove research materials, derivation history or v4 workflow state')
    op.drop_table('external_evidence_versions')
    op.drop_table('prepared_dataset_derivations_v3')
