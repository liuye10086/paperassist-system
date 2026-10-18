"""Independent append-only collection identities, versions, intents and outputs."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def define_report_collection_tables(metadata):
    def ident(): return sa.Column('id',sa.Text,primary_key=True)
    def text(name,nullable=False): return sa.Column(name,sa.Text,nullable=nullable)
    def foreign(name,target,nullable=False): return sa.Column(name,sa.Text,sa.ForeignKey(target),nullable=nullable)
    def stamp(name='created_at'): return sa.Column(name,sa.DateTime(timezone=True),nullable=False)
    def blob(name,nullable=False): return sa.Column(name,JSONB,nullable=nullable)
    collections=sa.Table('report_collections',metadata,ident(),foreign('project_id','projects.id'),foreign('created_by','users.id'),
        text('title'),text('current_version_id',True),stamp(),stamp('updated_at'),text('creation_key'),text('creation_digest'),
        sa.UniqueConstraint('project_id','created_by','creation_key',name='report_collections_creation_key'))
    versions=sa.Table('report_collection_versions',metadata,ident(),foreign('collection_id','report_collections.id'),
        sa.Column('revision',sa.Integer,nullable=False),text('language'),sa.Column('automatic',sa.Boolean,nullable=False),
        blob('source_json'),blob('content_json'),text('sha256'),text('request_key'),text('request_digest'),stamp(),
        sa.UniqueConstraint('collection_id','revision',name='report_collection_versions_revision_key'),
        sa.UniqueConstraint('collection_id','request_key',name='report_collection_versions_request_key'),
        sa.CheckConstraint("revision>=1 AND language IN ('zh-CN','en')",name='report_collection_versions_value_check'))
    items=sa.Table('report_collection_items',metadata,ident(),foreign('version_id','report_collection_versions.id'),
        sa.Column('position',sa.Integer,nullable=False),foreign('analysis_run_id','analysis_runs.id'),foreign('figure_id','figures.id',True),
        foreign('figure_config_version_id','figure_config_versions.id',True),
        foreign('explanation_id','explanations.id',True),text('dependency_engine'),sa.Column('figure_number',sa.Integer,nullable=False),
        text('caption'),blob('item_json'),text('sha256'),
        sa.UniqueConstraint('version_id','position',name='report_collection_items_position_key'),
        sa.UniqueConstraint('version_id','figure_id',name='report_collection_items_figure_key'),
        sa.UniqueConstraint('version_id','figure_config_version_id',name='report_collection_items_config_key'),
        sa.CheckConstraint('(figure_id IS NOT NULL) <> (figure_config_version_id IS NOT NULL)',name='report_collection_items_dependency_check'),
        sa.CheckConstraint('"position">=1 AND figure_number="position"',name='report_collection_items_number_check'))
    requests=sa.Table('report_build_requests',metadata,ident(),foreign('version_id','report_collection_versions.id'),
        sa.Column('export_revision',sa.Integer,nullable=False),text('renderer_version'),text('request_key'),text('request_digest'),text('status'),
        blob('dependencies_json'),blob('input_json',True),text('input_sha256',True),foreign('task_id','tasks.id',True),stamp(),stamp('updated_at'),text('error_code',True),
        sa.UniqueConstraint('version_id','renderer_version','export_revision',name='report_build_requests_revision_key'),
        sa.UniqueConstraint('version_id','request_key',name='report_build_requests_request_key'),
        sa.CheckConstraint("export_revision>=1 AND status IN ('waiting','queued','succeeded','failed','blocked')",name='report_build_requests_status_check'))
    reports=sa.Table('collection_reports',metadata,ident(),foreign('build_request_id','report_build_requests.id'),
        foreign('version_id','report_collection_versions.id'),sa.Column('export_revision',sa.Integer,nullable=False),text('renderer_version'),
        blob('report_json'),blob('input_json'),text('sha256'),stamp(),
        sa.UniqueConstraint('build_request_id',name='collection_reports_build_key'))
    sa.Index('report_build_requests_pending',requests.c.status,requests.c.created_at,requests.c.id)
    sa.Index('report_collections_project_created',collections.c.project_id,collections.c.created_at,collections.c.id)
    return collections,versions,items,requests,reports
