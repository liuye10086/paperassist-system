"""Typed external evidence source references; existing declarations remain unchanged."""
from alembic import op
import sqlalchemy as sa
revision='0068_bio_external_evidence'
down_revision='0067_bio_integration'
branch_labels=None
depends_on=None
OLD="num_nonnulls(processed_version_id,observation_map_version_id,annotation_version_id,design_version_id,resource_version_id,source_result_version_id,file_id)=1 AND ((source_kind='bio_processed_dataset_version' AND processed_version_id IS NOT NULL AND source_id=processed_version_id) OR (source_kind='bio_observation_map_version' AND observation_map_version_id IS NOT NULL AND source_id=observation_map_version_id) OR (source_kind='bio_annotation_version' AND annotation_version_id IS NOT NULL AND source_id=annotation_version_id) OR (source_kind='research_design_version' AND design_version_id IS NOT NULL AND source_id=design_version_id) OR (source_kind='bio_resource_version' AND resource_version_id IS NOT NULL AND source_id=resource_version_id) OR (source_kind='bio_insight_result_version' AND source_result_version_id IS NOT NULL AND source_id=source_result_version_id) OR (source_kind='original_file' AND file_id IS NOT NULL AND source_id=file_id))"
NEW="num_nonnulls(processed_version_id,observation_map_version_id,annotation_version_id,design_version_id,resource_version_id,source_result_version_id,file_id,external_evidence_version_id)=1 AND ((source_kind='bio_processed_dataset_version' AND processed_version_id IS NOT NULL AND source_id=processed_version_id) OR (source_kind='bio_observation_map_version' AND observation_map_version_id IS NOT NULL AND source_id=observation_map_version_id) OR (source_kind='bio_annotation_version' AND annotation_version_id IS NOT NULL AND source_id=annotation_version_id) OR (source_kind='research_design_version' AND design_version_id IS NOT NULL AND source_id=design_version_id) OR (source_kind='bio_resource_version' AND resource_version_id IS NOT NULL AND source_id=resource_version_id) OR (source_kind='bio_insight_result_version' AND source_result_version_id IS NOT NULL AND source_id=source_result_version_id) OR (source_kind='original_file' AND file_id IS NOT NULL AND source_id=file_id) OR (source_kind='external_evidence_version' AND external_evidence_version_id IS NOT NULL AND source_id=external_evidence_version_id))"
def upgrade():
    op.add_column('bio_insight_plan_sources',sa.Column('external_evidence_version_id',sa.Text,nullable=True))
    op.create_foreign_key('b05_evidence_project_fk','bio_insight_plan_sources','external_evidence_versions',['external_evidence_version_id','project_id'],['id','project_id'])
    op.create_index('bio_insight_plan_sources_external_evidence_version_id','bio_insight_plan_sources',['external_evidence_version_id'])
    op.drop_constraint('b04_ck_d58e7e56786d52a1','bio_insight_plan_sources',type_='check')
    op.create_check_constraint('b04_ck_c73b17877123dc3a','bio_insight_plan_sources',NEW)
def downgrade():
    op.drop_constraint('b04_ck_c73b17877123dc3a','bio_insight_plan_sources',type_='check')
    op.create_check_constraint('b04_ck_d58e7e56786d52a1','bio_insight_plan_sources',OLD)
    op.drop_index('bio_insight_plan_sources_external_evidence_version_id',table_name='bio_insight_plan_sources')
    op.drop_constraint('b05_evidence_project_fk','bio_insight_plan_sources',type_='foreignkey')
    op.drop_column('bio_insight_plan_sources','external_evidence_version_id')
