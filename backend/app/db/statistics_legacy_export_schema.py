"""A scoped, sealed bridge; output bytes belong to research_report_members."""
import sqlalchemy as sa

TABLE = 'statistics_legacy_report_exports'


def define_statistics_legacy_exports(metadata):
    def text(name, nullable=False):
        return sa.Column(name, sa.Text, nullable=nullable)
    def scope(table, column, name):
        return sa.ForeignKeyConstraint([column,'project_id','user_id'],
            [table+'.id',table+'.project_id',table+'.user_id'],name=name)
    sa.Table(TABLE,metadata,sa.Column('id',sa.Text,primary_key=True),text('project_id'),text('user_id'),
        text('task_id'),text('context_id'),text('report_version_id'),text('source_kind'),text('policy'),
        text('source_snapshot_sha256'),text('content_sha256'),text('build_request_id',True),
        text('report_id',True),text('collection_report_id',True),
        sa.UniqueConstraint('task_id',name='sr_legacy_task_key'),
        sa.UniqueConstraint('report_version_id',name='sr_legacy_version_key'),
        sa.UniqueConstraint('report_id',name='sr_legacy_report_key'),
        sa.UniqueConstraint('collection_report_id',name='sr_legacy_collection_report_key'),
        scope('tasks','task_id','sr_legacy_task_fk'),
        scope('statistics_report_context_versions','context_id','sr_legacy_context_fk'),
        scope('research_report_versions','report_version_id','sr_legacy_version_fk'),
        sa.ForeignKeyConstraint(['build_request_id'],['report_build_requests.id'],name='sr_legacy_build_fk'),
        sa.ForeignKeyConstraint(['report_id'],['reports.id'],name='sr_legacy_report_fk'),
        sa.ForeignKeyConstraint(['collection_report_id'],['collection_reports.id'],name='sr_legacy_collection_report_fk'),
        sa.CheckConstraint("id=task_id AND policy='statistics_reader_export_v1' AND source_snapshot_sha256 ~ '^[a-f0-9]{64}$' AND content_sha256 ~ '^[a-f0-9]{64}$'",name='sr_legacy_identity_check'),
        sa.CheckConstraint("(source_kind='analysis' AND build_request_id IS NULL AND collection_report_id IS NULL) OR (source_kind='collection' AND build_request_id IS NOT NULL AND report_id IS NULL)",name='sr_legacy_kind_check'),
        sa.Index('sr_legacy_context_lookup','context_id','project_id','user_id'))
    sa.Table('statistics_legacy_export_requests',metadata,sa.Column('id',sa.Text,primary_key=True),
        text('project_id'),text('user_id'),text('task_id'),text('request_key'),text('request_digest'),
        scope('tasks','task_id','sr_legacy_request_task_fk'),
        sa.ForeignKeyConstraint(['task_id'],[TABLE+'.task_id'],name='sr_legacy_request_export_fk'),
        sa.UniqueConstraint('project_id','user_id','request_key',name='sr_legacy_request_key'),
        sa.CheckConstraint("request_digest ~ '^[a-f0-9]{64}$' AND request_key ~ '^[!-~]{1,128}$'",name='sr_legacy_request_check'))
