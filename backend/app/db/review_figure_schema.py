"""Immutable, owner-scoped adoption of an actual saved public figure."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def define_review_figure_tables(metadata):
    table=sa.Table('review_figure_adoptions',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('project_id',sa.Text,nullable=False),
        sa.Column('user_id',sa.Text,nullable=False),sa.Column('round_id',sa.Text,nullable=False),
        sa.Column('item_id',sa.Text,nullable=False),sa.Column('plan_revision',sa.Integer,nullable=False),
        sa.Column('link_id',sa.Text,nullable=False),sa.Column('task_id',sa.Text,nullable=False),
        sa.Column('file_id',sa.Text,nullable=False),sa.Column('analysis_run_id',sa.Text,sa.ForeignKey('analysis_runs.id'),nullable=False),
        sa.Column('figure_id',sa.Text,sa.ForeignKey('figures.id'),nullable=False),
        sa.Column('manuscript_id',sa.Text,nullable=False),sa.Column('manuscript_version_id',sa.Text,nullable=False),
        sa.Column('idempotency_key',sa.Text,nullable=False),sa.Column('request_json',JSONB,nullable=False),
        sa.Column('request_digest',sa.Text,nullable=False),sa.Column('snapshot_json',JSONB,nullable=False),
        sa.Column('snapshot_sha256',sa.Text,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('id','project_id','user_id',name='rfa_scope_key'),
        sa.UniqueConstraint('project_id','user_id','idempotency_key',name='rfa_request_key'),
        sa.UniqueConstraint('round_id','item_id','figure_id',name='rfa_result_key'),
        sa.ForeignKeyConstraint(['project_id','user_id'],['projects.id','projects.owner_id'],name='rfa_owner_fk'),
        sa.ForeignKeyConstraint(['round_id','project_id','user_id'],['review_rounds.id','review_rounds.project_id','review_rounds.user_id'],name='rfa_round_fk'),
        sa.ForeignKeyConstraint(['link_id','project_id','user_id'],['review_opinion_task_links.id','review_opinion_task_links.project_id','review_opinion_task_links.user_id'],name='rfa_link_fk'),
        sa.ForeignKeyConstraint(['task_id','project_id','user_id'],['tasks.id','tasks.project_id','tasks.user_id'],name='rfa_task_fk'),
        sa.ForeignKeyConstraint(['file_id','project_id'],['files.id','files.project_id'],name='rfa_file_fk'),
        sa.ForeignKeyConstraint(['manuscript_id','project_id','user_id'],['manuscripts.id','manuscripts.project_id','manuscripts.user_id'],name='rfa_manuscript_fk'),
        sa.ForeignKeyConstraint(['manuscript_version_id','manuscript_id'],['manuscript_versions.id','manuscript_versions.manuscript_id'],name='rfa_parent_fk'),
        sa.CheckConstraint("plan_revision>=1 AND request_digest ~ '^[0-9a-f]{64}$' AND snapshot_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(request_json)='object' AND jsonb_typeof(snapshot_json)='object'",name='rfa_json_check'))
    sa.Index('rfa_round_created',table.c.round_id,table.c.created_at)
    return (table,)
