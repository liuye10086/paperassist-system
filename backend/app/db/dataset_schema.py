"""Independent raw structure and per-sheet immutable version metadata."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def define_dataset_tables(metadata):
    structures = sa.Table('file_structure_versions', metadata,
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('file_id', sa.Text, sa.ForeignKey('files.id'), nullable=False),
        sa.Column('task_id', sa.Text, sa.ForeignKey('tasks.id'), nullable=False, unique=True),
        sa.Column('version', sa.Integer, nullable=False),
        sa.Column('parent_id', sa.Text, sa.ForeignKey('file_structure_versions.id')),
        sa.Column('created_by', sa.Text, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('idempotency_key', sa.Text, nullable=False),
        sa.Column('request_digest', sa.Text, nullable=False),
        sa.Column('source_sha256', sa.Text, nullable=False),
        sa.Column('parser_version', sa.Text, nullable=False),
        sa.Column('settings_json', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('manifest_json', JSONB(none_as_null=True)),
        sa.UniqueConstraint('file_id', 'version', name='structure_file_version_key'),
        sa.UniqueConstraint('id', 'file_id', 'version', name='structure_identity_key'),
        sa.UniqueConstraint('id', 'file_id', name='structure_parent_identity_key'),
        sa.ForeignKeyConstraint(['parent_id','file_id'], ['file_structure_versions.id','file_structure_versions.file_id'],name='structure_parent_file_fkey'),
        sa.UniqueConstraint('file_id', 'created_by', 'idempotency_key', name='structure_request_key'),
        sa.CheckConstraint('version > 0', name='structure_version_check'),
        sa.CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$' AND request_digest ~ '^[0-9a-f]{64}$'", name='structure_digest_check'),
        sa.CheckConstraint("jsonb_typeof(settings_json)='object'", name='structure_settings_check'),
        sa.CheckConstraint("manifest_json IS NULL OR (jsonb_typeof(manifest_json)='object' AND completed_at IS NOT NULL)", name='structure_manifest_check'))
    datasets = sa.Table('dataset_versions', metadata,
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('file_id', sa.Text, sa.ForeignKey('files.id'), nullable=False),
        sa.Column('structure_id', sa.Text, sa.ForeignKey('file_structure_versions.id'), nullable=False),
        sa.Column('sheet_index', sa.Integer, nullable=False),
        sa.Column('version', sa.Integer, nullable=False),
        sa.Column('parent_id', sa.Text, sa.ForeignKey('dataset_versions.id')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sheet_name', sa.Text, nullable=False),
        sa.Column('object_key', sa.Text, nullable=False, unique=True),
        sa.Column('sha256', sa.Text, nullable=False),
        sa.Column('size_bytes', sa.BigInteger, nullable=False),
        sa.Column('schema_version', sa.Integer, nullable=False),
        sa.Column('summary_json', JSONB, nullable=False),
        sa.UniqueConstraint('structure_id', 'sheet_index', name='dataset_structure_sheet_key'),
        sa.UniqueConstraint('id','file_id','sheet_index',name='dataset_parent_identity_key'),
        sa.ForeignKeyConstraint(['structure_id','file_id','version'], ['file_structure_versions.id','file_structure_versions.file_id','file_structure_versions.version'],name='dataset_structure_identity_fkey'),
        sa.ForeignKeyConstraint(['parent_id','file_id','sheet_index'], ['dataset_versions.id','dataset_versions.file_id','dataset_versions.sheet_index'],name='dataset_parent_identity_fkey'),
        sa.CheckConstraint('version > 0 AND sheet_index >= 0 AND sheet_index < 50', name='dataset_version_check'),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name='dataset_sha_check'),
        sa.CheckConstraint('size_bytes > 0 AND size_bytes <= 4194304 AND schema_version = 1', name='dataset_size_schema_check'),
        sa.CheckConstraint("jsonb_typeof(summary_json)='object' AND NOT (summary_json ? 'cells')", name='dataset_summary_check'))
    sa.Index('structure_file_created', structures.c.file_id, structures.c.version.desc())
    sa.Index('dataset_file_sheet', datasets.c.file_id, datasets.c.sheet_index, datasets.c.version.desc())
    return structures, datasets
