"""Scoped user-return producers, round lineage and append-only progress."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def define_review_continuation_tables(metadata):
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
            sa.UniqueConstraint('id', 'project_id', 'user_id', name=prefix+'_scope_key'),
            sa.UniqueConstraint('project_id', 'user_id', 'idempotency_key', name=prefix+'_request_key'),
            sa.ForeignKeyConstraint(['project_id', 'user_id'], ['projects.id', 'projects.owner_id'], name=prefix+'_owner_fk'),
            sa.CheckConstraint("idempotency_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$' AND snapshot_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(request_json)='object' AND jsonb_typeof(snapshot_json)='object'", name=prefix+'_json_check'),
        ]

    def scope(column, table, prefix):
        return sa.ForeignKeyConstraint([column, 'project_id', 'user_id'], [table+'.id', table+'.project_id', table+'.user_id'], name=prefix+'_scope_fk')

    returns = sa.Table(
        'review_round_user_returns', metadata, *common('rrur'),
        sa.Column('previous_round_id', sa.Text, nullable=False),
        sa.Column('revision_id', sa.Text),
        sa.Column('manuscript_id', sa.Text, nullable=False),
        sa.Column('base_version_id', sa.Text, nullable=False),
        sa.Column('file_id', sa.Text, nullable=False),
        sa.Column('document_version_id', sa.Text, nullable=False),
        sa.Column('base_export_id', sa.Text, sa.ForeignKey('manuscript_exports.id', name='rrur_export_fk')),
        sa.Column('output_version_id', sa.Text, unique=True),
        sa.Column('adopt_key', sa.Text),
        sa.Column('adopt_json', JSONB(none_as_null=True)),
        sa.Column('adopt_sha256', sa.Text),
        sa.Column('candidate_json', JSONB(none_as_null=True)),
        sa.Column('candidate_sha256', sa.Text),
        scope('previous_round_id', 'review_rounds', 'rrur_round'),
        scope('revision_id', 'review_revision_runs', 'rrur_revision'),
        scope('manuscript_id', 'manuscripts', 'rrur_manuscript'),
        sa.ForeignKeyConstraint(['base_version_id', 'manuscript_id'], ['manuscript_versions.id', 'manuscript_versions.manuscript_id'], name='rrur_base_fk'),
        sa.ForeignKeyConstraint(['output_version_id', 'manuscript_id'], ['manuscript_versions.id', 'manuscript_versions.manuscript_id'], name='rrur_output_fk'),
        sa.ForeignKeyConstraint(['file_id', 'project_id'], ['files.id', 'files.project_id'], name='rrur_file_fk'),
        sa.ForeignKeyConstraint(['document_version_id', 'file_id'], ['file_parse_results.id', 'file_parse_results.file_id'], name='rrur_parse_fk'),
        sa.CheckConstraint("(output_version_id IS NULL AND adopt_key IS NULL AND adopt_json IS NULL AND adopt_sha256 IS NULL AND candidate_json IS NULL AND candidate_sha256 IS NULL) OR (output_version_id IS NOT NULL AND adopt_key IS NOT NULL AND jsonb_typeof(adopt_json)='object' AND adopt_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(candidate_json)='object' AND candidate_sha256 ~ '^[0-9a-f]{64}$')", name='rrur_adopt_check'),
    )
    continuations = sa.Table(
        'review_round_continuations', metadata, *common('rrc'),
        sa.Column('round_id', sa.Text, nullable=False, unique=True),
        sa.Column('previous_round_id', sa.Text, nullable=False),
        sa.Column('user_return_id', sa.Text),
        sa.Column('manuscript_id', sa.Text, nullable=False),
        sa.Column('manuscript_version_id', sa.Text, nullable=False),
        scope('round_id', 'review_rounds', 'rrc_round'),
        scope('previous_round_id', 'review_rounds', 'rrc_previous'),
        scope('user_return_id', 'review_round_user_returns', 'rrc_return'),
        scope('manuscript_id', 'manuscripts', 'rrc_manuscript'),
        sa.ForeignKeyConstraint(['manuscript_version_id', 'manuscript_id'], ['manuscript_versions.id', 'manuscript_versions.manuscript_id'], name='rrc_input_fk'),
        sa.CheckConstraint('round_id<>previous_round_id', name='rrc_not_self'),
    )
    progress = sa.Table(
        'project_review_progress_events', metadata, *common('prpe'),
        sa.Column('corrects_event_id', sa.Text, unique=True),
        sa.Column('round_id', sa.Text),
        sa.Column('manuscript_id', sa.Text),
        sa.Column('manuscript_version_id', sa.Text),
        sa.Column('export_id', sa.Text, sa.ForeignKey('manuscript_exports.id', name='prpe_export_fk')),
        scope('corrects_event_id', 'project_review_progress_events', 'prpe_corrects'),
        scope('round_id', 'review_rounds', 'prpe_round'),
        scope('manuscript_id', 'manuscripts', 'prpe_manuscript'),
        sa.ForeignKeyConstraint(['manuscript_version_id', 'manuscript_id'], ['manuscript_versions.id', 'manuscript_versions.manuscript_id'], name='prpe_input_fk'),
        sa.CheckConstraint('corrects_event_id IS NULL OR corrects_event_id<>id', name='prpe_not_self'),
    )
    for table in (returns, continuations, progress):
        sa.Index(table.name+'_project_created', table.c.project_id, table.c.created_at.desc(), table.c.id)
    return returns, continuations, progress
