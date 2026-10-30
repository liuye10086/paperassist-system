"""Append-only upload and first-version parse records."""
from sqlalchemy import Table, Column, Text, Integer, BigInteger, ForeignKey, UniqueConstraint, CheckConstraint, DateTime
from sqlalchemy.dialects.postgresql import JSONB


def define_file_parsing_tables(metadata):
    batches = Table('file_upload_batches', metadata,
        Column('id', Text, primary_key=True),
        Column('project_id', Text, ForeignKey('projects.id'), nullable=False),
        Column('user_id', Text, ForeignKey('users.id'), nullable=False),
        Column('idempotency_key', Text, nullable=False),
        Column('request_digest', Text, nullable=False),
        Column('profile', Text, nullable=False, server_default='documents'),
        CheckConstraint("profile IN ('documents','bioinformatics_v1')", name='file_batches_profile_check'),
        Column('created_at', DateTime(timezone=True), nullable=False),
        UniqueConstraint('user_id', 'project_id', 'idempotency_key', name='file_batches_request_key'),
        CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name='file_batches_digest_check'))
    items = Table('file_upload_items', metadata,
        Column('id', Text, primary_key=True),
        Column('batch_id', Text, ForeignKey('file_upload_batches.id'), nullable=False),
        Column('ordinal', Integer, nullable=False),
        Column('filename', Text, nullable=False),
        Column('size_bytes', BigInteger, nullable=False),
        Column('file_id', Text, ForeignKey('files.id', use_alter=True, name='file_upload_items_file_id_fkey'), unique=True),
        Column('error_json', JSONB(none_as_null=True)),
        UniqueConstraint('batch_id', 'ordinal', name='file_items_ordinal_key'),
        CheckConstraint('ordinal >= 0 AND ordinal <= 9', name='file_items_ordinal_check'),
        CheckConstraint('size_bytes >= 0', name='file_items_size_check'),
        CheckConstraint("error_json IS NULL OR jsonb_typeof(error_json)='object'", name='file_items_error_check'))
    results = Table('file_parse_results', metadata,
        Column('id', Text, primary_key=True),
        Column('file_id', Text, ForeignKey('files.id'), nullable=False),
        Column('task_id', Text, ForeignKey('tasks.id'), nullable=False, unique=True),
        Column('version', Integer, nullable=False),
        Column('source_sha256', Text, nullable=False),
        Column('parser_version', Text, nullable=False),
        Column('settings_json', JSONB, nullable=False),
        Column('created_at', DateTime(timezone=True), nullable=False),
        Column('completed_at', DateTime(timezone=True)),
        Column('result_json', JSONB(none_as_null=True)),
        UniqueConstraint('file_id', 'version', name='file_parse_results_version_key'),
        CheckConstraint('version > 0', name='file_parse_results_version_check'),
        CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name='file_parse_results_sha_check'),
        CheckConstraint("jsonb_typeof(settings_json)='object'", name='file_parse_results_settings_check'),
        CheckConstraint("result_json IS NULL OR (jsonb_typeof(result_json)='object' AND completed_at IS NOT NULL)", name='file_parse_results_result_check'))
    return batches, items, results
