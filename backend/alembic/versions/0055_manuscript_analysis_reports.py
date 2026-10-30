"""Typed saved analysis report sources; existing predicates and rows stay intact."""
from alembic import op
import sqlalchemy as sa

revision='0055_manuscript_analysis_reports'
down_revision='0054_review_figure_adoptions'
branch_labels=None
depends_on=None

def upgrade():
    # Read the installed predecessor predicate rather than rewriting any data.
    connection=op.get_bind()
    old=connection.execute(sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='manuscript_sources'::regclass AND conname='ms_typed_source_check'")).scalar_one()
    predicate=old[len('CHECK ('):-1]
    op.add_column('manuscript_sources',sa.Column('analysis_report_id',sa.Text,nullable=True))
    op.add_column('manuscript_sources',sa.Column('collection_report_id',sa.Text,nullable=True))
    op.create_foreign_key('ms_collection_report_fk','manuscript_sources','collection_reports',['collection_report_id'],['id'])
    op.create_foreign_key('ms_analysis_report_fk','manuscript_sources','reports',['analysis_report_id'],['id'])
    op.drop_constraint('ms_typed_source_check','manuscript_sources',type_='check')
    op.create_check_constraint('ms_typed_source_check','manuscript_sources',
        '(analysis_report_id IS NULL AND collection_report_id IS NULL AND ('+predicate+")) OR (kind='analysis_report' AND collection_report_id IS NULL AND role='user_results' AND source_id=analysis_report_id AND analysis_report_id IS NOT NULL AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id,figure_language_version_id)=0) OR (kind='collection_report' AND analysis_report_id IS NULL AND role='user_results' AND source_id=collection_report_id AND collection_report_id IS NOT NULL AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id,figure_language_version_id)=0)")

def downgrade():
    connection=op.get_bind()
    if connection.execute(sa.text("SELECT count(*) FROM manuscript_sources WHERE analysis_report_id IS NOT NULL OR collection_report_id IS NOT NULL")).scalar_one():
        raise RuntimeError('Retain saved report source references before downgrade.')
    op.drop_constraint('ms_typed_source_check','manuscript_sources',type_='check')
    op.create_check_constraint('ms_typed_source_check','manuscript_sources',"(kind='original' AND source_id=file_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id,figure_language_version_id)=0) OR (kind='document_version' AND source_id=document_version_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id,figure_language_version_id)=1) OR (kind='ocr_review_version' AND source_id=ocr_review_version_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id,figure_language_version_id)=1) OR (kind='external_evidence_version' AND source_id=external_evidence_version_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id,figure_language_version_id)=1) OR (kind='analysis_run' AND source_id=analysis_run_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id,figure_language_version_id)=1) OR (kind='figure' AND source_id=figure_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id,figure_language_version_id)=1) OR (kind='figure_language_version' AND role='image_observation' AND source_id=figure_language_version_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id,figure_language_version_id)=1)")
    for kind in ('analysis_report','collection_report'):
        op.drop_constraint('ms_'+kind+'_fk','manuscript_sources',type_='foreignkey')
        op.drop_column('manuscript_sources',kind+'_id')
