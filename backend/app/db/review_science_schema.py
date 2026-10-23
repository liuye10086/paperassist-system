"""Scoped immutable task links and receipt-backed local analysis adoptions."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def define_review_science_tables(metadata):
    def common(prefix):
        return [
            sa.Column('id', sa.Text, primary_key=True),
            sa.Column('project_id', sa.Text, nullable=False),
            sa.Column('user_id', sa.Text, nullable=False),
            sa.Column('idempotency_key', sa.Text, nullable=False),
            sa.Column('request_json', JSONB, nullable=False),
            sa.Column('request_digest', sa.Text, nullable=False),
            sa.Column('snapshot_json', JSONB, nullable=False),
            sa.Column('snapshot_sha256', sa.Text, nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('round_id', sa.Text, nullable=False),
            sa.Column('item_id', sa.Text, nullable=False),
            sa.Column('plan_revision', sa.Integer, nullable=False),
            sa.UniqueConstraint('id', 'project_id', 'user_id', name=prefix + '_scope_key'),
            sa.UniqueConstraint('project_id', 'user_id', 'idempotency_key', name=prefix + '_request_key'),
            sa.ForeignKeyConstraint(['project_id', 'user_id'], ['projects.id', 'projects.owner_id'], name=prefix + '_owner_fk'),
            sa.ForeignKeyConstraint(['round_id', 'project_id', 'user_id'], ['review_rounds.id', 'review_rounds.project_id', 'review_rounds.user_id'], name=prefix + '_round_fk'),
            sa.CheckConstraint("plan_revision>=1 AND request_digest ~ '^[0-9a-f]{64}$' AND snapshot_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(snapshot_json)='object'", name=prefix + '_json_check'),
        ]

    links = sa.Table(
        'review_opinion_task_links', metadata, *common('rotl'),
        sa.Column('task_id', sa.Text, nullable=False),
        sa.ForeignKeyConstraint(['task_id', 'project_id', 'user_id'], ['tasks.id', 'tasks.project_id', 'tasks.user_id'], name='rotl_task_fk'),
    )
    adoptions = sa.Table(
        'review_analysis_adoptions', metadata, *common('raa'),
        sa.Column('link_id', sa.Text, nullable=False),
        sa.Column('analysis_run_id', sa.Text, sa.ForeignKey('analysis_runs.id', name='raa_analysis_fk'), nullable=False),
        sa.Column('manuscript_version_id', sa.Text, sa.ForeignKey('manuscript_versions.id', name='raa_manuscript_fk'), nullable=False),
        sa.ForeignKeyConstraint(['link_id', 'project_id', 'user_id'], ['review_opinion_task_links.id', 'review_opinion_task_links.project_id', 'review_opinion_task_links.user_id'], name='raa_link_fk'),
        sa.UniqueConstraint('round_id', 'item_id', 'analysis_run_id', name='raa_result_key'),
    )
    sa.Index('rotl_round_created', links.c.round_id, links.c.created_at)
    sa.Index('raa_round_created', adoptions.c.round_id, adoptions.c.created_at)
    return links, adoptions
