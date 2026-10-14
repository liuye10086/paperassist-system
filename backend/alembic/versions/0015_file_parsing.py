"""Append upload batches and immutable first parse inputs."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0015_file_parsing'
down_revision = '0014_file_assets'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('tasks_type_check', 'tasks', type_='check')
    op.create_check_constraint('tasks_type_check', 'tasks', "task_type IN ('boxplot','explanation','word_report','parse_file')")
    op.drop_constraint('files_parse_status_check', 'files', type_='check')
    op.create_check_constraint('files_parse_status_check', 'files', "parse_status IN ('queued','parsing','parsed','failed')")
    op.add_column('files', sa.Column('parse_revision', sa.Integer, nullable=False, server_default=sa.text('0')))
    op.create_check_constraint('files_parse_revision_check', 'files', 'parse_revision >= 0')
    # Freeze definitions in this migration independently of runtime metadata.
    metadata = sa.MetaData()
    for name in ('users', 'projects', 'files', 'tasks'):
        sa.Table(name, metadata, sa.Column('id', sa.Text, primary_key=True))
    tables = define_file_parsing_tables(metadata)
    for table in tables:
        table.create(op.get_bind())
    op.create_foreign_key('file_upload_items_file_id_fkey', 'file_upload_items', 'files', ['file_id'], ['id'])
    op.add_column('files', sa.Column('upload_item_id', sa.Text))
    op.create_foreign_key('files_upload_item_id_fkey', 'files', 'file_upload_items', ['upload_item_id'], ['id'])
    op.create_unique_constraint('files_upload_item_key', 'files', ['upload_item_id'])


def downgrade():
    # A downgrade must never silently discard a queued or archived parse.
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM file_parse_results) THEN RAISE EXCEPTION 'parse records require preservation before downgrade'; END IF; END $$")
    op.drop_constraint('files_upload_item_key', 'files', type_='unique')
    op.drop_constraint('files_upload_item_id_fkey', 'files', type_='foreignkey')
    op.drop_column('files', 'upload_item_id')
    for name in ('file_parse_results', 'file_upload_items', 'file_upload_batches'):
        op.drop_table(name)
    op.drop_constraint('files_parse_revision_check', 'files', type_='check')
    op.drop_column('files', 'parse_revision')
    op.drop_constraint('files_parse_status_check', 'files', type_='check')
    op.create_check_constraint('files_parse_status_check', 'files', "parse_status IN ('parsed','failed')")
    op.drop_constraint('tasks_type_check', 'tasks', type_='check')
    op.create_check_constraint('tasks_type_check', 'tasks', "task_type IN ('boxplot','explanation','word_report')")


def define_file_parsing_tables(metadata):
    batches = sa.Table('file_upload_batches', metadata,
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('project_id', sa.Text, sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('user_id', sa.Text, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('idempotency_key', sa.Text, nullable=False),
        sa.Column('request_digest', sa.Text, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id', 'project_id', 'idempotency_key', name='file_batches_request_key'),
        sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name='file_batches_digest_check'))
    items = sa.Table('file_upload_items', metadata,
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('batch_id', sa.Text, sa.ForeignKey('file_upload_batches.id'), nullable=False),
        sa.Column('ordinal', sa.Integer, nullable=False),
        sa.Column('filename', sa.Text, nullable=False),
        sa.Column('size_bytes', sa.BigInteger, nullable=False),
        sa.Column('file_id', sa.Text, sa.ForeignKey('files.id', use_alter=True, name='file_upload_items_file_id_fkey'), unique=True),
        sa.Column('error_json', JSONB(none_as_null=True)),
        sa.UniqueConstraint('batch_id', 'ordinal', name='file_items_ordinal_key'),
        sa.CheckConstraint('ordinal >= 0 AND ordinal <= 9', name='file_items_ordinal_check'),
        sa.CheckConstraint('size_bytes >= 0', name='file_items_size_check'),
        sa.CheckConstraint("error_json IS NULL OR jsonb_typeof(error_json)='object'", name='file_items_error_check'))
    results = sa.Table('file_parse_results', metadata,
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('file_id', sa.Text, sa.ForeignKey('files.id'), nullable=False),
        sa.Column('task_id', sa.Text, sa.ForeignKey('tasks.id'), nullable=False, unique=True),
        sa.Column('version', sa.Integer, nullable=False),
        sa.Column('source_sha256', sa.Text, nullable=False),
        sa.Column('parser_version', sa.Text, nullable=False),
        sa.Column('settings_json', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('result_json', JSONB(none_as_null=True)),
        sa.UniqueConstraint('file_id', 'version', name='file_parse_results_version_key'),
        sa.CheckConstraint('version = 1', name='file_parse_results_version_check'),
        sa.CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name='file_parse_results_sha_check'),
        sa.CheckConstraint("jsonb_typeof(settings_json)='object'", name='file_parse_results_settings_check'),
        sa.CheckConstraint("result_json IS NULL OR (jsonb_typeof(result_json)='object' AND completed_at IS NOT NULL)", name='file_parse_results_result_check'))
    return batches, items, results
