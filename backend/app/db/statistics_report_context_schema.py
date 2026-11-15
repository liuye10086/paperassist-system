"""Fixed selections and typed references for statistics reader reports."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

TABLE_NAMES = (
    'statistics_report_context_versions', 'statistics_report_context_files',
    'statistics_report_context_items', 'statistics_report_context_requests',
)

DEPENDENCY_KEYS = (
    ('analysis_runs', 'sr_context_run_file_key', ('id', 'file_id')),
    ('figures', 'sr_context_figure_run_key', ('id', 'analysis_run_id')),
    ('explanations', 'sr_context_explanation_figure_key', ('id', 'figure_id')),
    ('report_collections', 'sr_context_collection_project_key', ('id', 'project_id')),
    ('report_collection_versions', 'sr_context_collection_version_key', ('id', 'collection_id')),
)


def define_statistics_report_context_tables(metadata):
    for table, name, columns in DEPENDENCY_KEYS:
        sa.UniqueConstraint(*(metadata.tables[table].c[column] for column in columns), name=name)

    versions, files, items, requests = TABLE_NAMES

    def text(name, nullable=False):
        return sa.Column(name, sa.Text, nullable=nullable)

    def fk(table, columns, target_columns, name):
        return sa.ForeignKeyConstraint(columns, [table + '.' + c for c in target_columns], name=name)

    def context_scope(name):
        return fk(versions, ('context_id', 'project_id', 'user_id'), ('id', 'project_id', 'user_id'), name)

    sa.Table(versions, metadata, sa.Column('id', sa.Text, primary_key=True), text('project_id'), text('user_id'),
        text('content_sha256'), sa.Column('content_json', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('schema_version', sa.Integer, nullable=False, server_default='1'),
        text('collection_id', True), text('collection_version_id', True),
        sa.UniqueConstraint('id', 'project_id', 'user_id', name='sr_context_scope_key'),
        sa.UniqueConstraint('project_id', 'user_id', 'content_sha256', name='sr_context_content_key'),
        fk('projects', ('project_id', 'user_id'), ('id', 'owner_id'), 'sr_context_owner_fk'),
        fk('report_collections', ('collection_id', 'project_id'), ('id', 'project_id'), 'sr_context_collection_fk'),
        fk('report_collection_versions', ('collection_version_id', 'collection_id'), ('id', 'collection_id'),
           'sr_context_collection_version_fk'),
        sa.CheckConstraint('(collection_id IS NULL) = (collection_version_id IS NULL)', name='sr_context_collection_check'),
        sa.CheckConstraint("schema_version=1 AND content_sha256 ~ '^[0-9a-f]{64}$' AND "
                           "jsonb_typeof(content_json)='object' AND octet_length(content_json::text)<=4194304",
                           name='sr_context_content_check'),
        sa.Index('sr_context_project_created', 'project_id', 'created_at'))

    sa.Table(files, metadata, sa.Column('id', sa.Text, primary_key=True), text('context_id'), text('project_id'),
        text('user_id'), text('file_id'), text('sha256'), context_scope('sr_context_file_context_fk'),
        fk('files', ('file_id', 'project_id'), ('id', 'project_id'), 'sr_context_file_project_fk'),
        sa.UniqueConstraint('context_id', 'file_id', name='sr_context_file_key'),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name='sr_context_file_sha_check'),
        sa.Index('sr_context_file_lookup', 'file_id', 'project_id'))

    sa.Table(items, metadata, sa.Column('id', sa.Text, primary_key=True), text('context_id'), text('project_id'),
        text('user_id'), text('file_id'), text('analysis_run_id'), text('figure_id', True), text('explanation_id', True),
        sa.Column('position', sa.Integer, nullable=False), context_scope('sr_context_item_context_fk'),
        fk(files, ('context_id', 'file_id'), ('context_id', 'file_id'), 'sr_context_item_file_fk'),
        fk('analysis_runs', ('analysis_run_id', 'file_id'), ('id', 'file_id'), 'sr_context_item_run_fk'),
        fk('figures', ('figure_id', 'analysis_run_id'), ('id', 'analysis_run_id'), 'sr_context_item_figure_fk'),
        fk('explanations', ('explanation_id', 'figure_id'), ('id', 'figure_id'), 'sr_context_item_explanation_fk'),
        sa.UniqueConstraint('context_id', 'position', name='sr_context_item_position_key'),
        sa.CheckConstraint('position BETWEEN 1 AND 30 AND (figure_id IS NULL) = (explanation_id IS NULL)',
                           name='sr_context_item_check'),
        sa.Index('sr_context_item_run_lookup', 'analysis_run_id', 'project_id'))

    sa.Table(requests, metadata, sa.Column('id', sa.Text, primary_key=True), text('context_id'), text('project_id'),
        text('user_id'), text('request_key'), text('request_digest'), text('finding_version_id'),
        context_scope('sr_context_request_context_fk'),
        fk('research_finding_versions', ('finding_version_id', 'project_id', 'user_id'),
           ('id', 'project_id', 'user_id'), 'sr_context_request_finding_fk'),
        sa.UniqueConstraint('project_id', 'user_id', 'request_key', name='sr_context_request_key'),
        sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$' AND request_key ~ '^[!-~]{1,128}$'",
                           name='sr_context_request_check'),
        sa.Index('sr_context_request_context', 'context_id'),
        sa.Index('sr_context_request_finding', 'finding_version_id', 'project_id', 'user_id'))
