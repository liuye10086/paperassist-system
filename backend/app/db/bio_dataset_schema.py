"""Frozen bio import sources, dataset versions and individually scoped members."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from app.db.research_intake_schema import scoped_fk


TABLE_NAMES = ('bio_datasets','bio_imports','bio_import_files','bio_dataset_versions','bio_dataset_members')


def define_bio_dataset_tables(metadata):
    datasets = sa.Table('bio_datasets', metadata,
        sa.Column('id', sa.Text, primary_key=True), sa.Column('project_id', sa.Text, sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('name', sa.Text, nullable=False), sa.Column('assay', sa.Text, nullable=False),
        sa.Column('revision', sa.Integer, nullable=False, server_default='1'), sa.Column('current_version_id', sa.Text),
        sa.Column('created_by', sa.Text, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('id','project_id', name='cr_bd_scope_key'),
        scoped_fk(['current_version_id','id','project_id'], ['bio_dataset_versions.id','bio_dataset_versions.dataset_id','bio_dataset_versions.project_id'], 'cr_bd_current_fk', use_alter=True),
        sa.CheckConstraint("revision>=1 AND assay='visium' AND length(name) BETWEEN 1 AND 200", name='cr_bd_values_check'))
    sa.Index('cr_bd_project_created', datasets.c.project_id, datasets.c.created_at.desc(), datasets.c.id)
    imports = sa.Table('bio_imports', metadata,
        sa.Column('id', sa.Text, primary_key=True), sa.Column('project_id', sa.Text, sa.ForeignKey('projects.id'), nullable=False),
        *(sa.Column(k, sa.Text, nullable=False) for k in ('dataset_id','task_id','request_key','request_digest','parser_version','input_sha256')),
        sa.Column('expected_dataset_revision', sa.Integer, nullable=False), sa.Column('settings_json', JSONB, nullable=False),
        sa.Column('candidate_object_id', sa.Text, sa.ForeignKey('storage_objects.id')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('id','project_id', name='cr_bi_scope_key'), sa.UniqueConstraint('id','dataset_id','project_id', name='cr_bi_dataset_scope_key'),
        sa.UniqueConstraint('project_id','request_key', name='cr_bi_request_key'), sa.UniqueConstraint('task_id', name='cr_bi_task_key'),
        scoped_fk(['dataset_id','project_id'], ['bio_datasets.id','bio_datasets.project_id'], 'cr_bi_dataset_fk'),
        scoped_fk(['task_id','project_id'], ['tasks.id','tasks.project_id'], 'cr_bi_task_fk'),
        sa.CheckConstraint("expected_dataset_revision>=1 AND length(request_key) BETWEEN 1 AND 128 AND request_digest ~ '^[0-9a-f]{64}$' AND input_sha256 ~ '^[0-9a-f]{64}$' AND length(parser_version)>0", name='cr_bi_values_check'),
        sa.CheckConstraint("jsonb_typeof(settings_json)='object' AND octet_length(settings_json::text)<=65536", name='cr_bi_settings_check'))
    files = sa.Table('bio_import_files', metadata,
        sa.Column('import_id', sa.Text, primary_key=True), sa.Column('file_id', sa.Text, primary_key=True),
        sa.Column('project_id', sa.Text, sa.ForeignKey('projects.id'), nullable=False), sa.Column('declared_role', sa.Text, nullable=False),
        sa.Column('source_sha256', sa.Text, nullable=False), sa.Column('source_size_bytes', sa.BigInteger, nullable=False),
        scoped_fk(['import_id','project_id'], ['bio_imports.id','bio_imports.project_id'], 'cr_bif_import_fk'),
        scoped_fk(['file_id','project_id'], ['files.id','files.project_id'], 'cr_bif_file_fk'),
        sa.CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$' AND source_size_bytes>=0 AND length(declared_role)>0", name='cr_bif_values_check'))
    versions = sa.Table('bio_dataset_versions', metadata,
        sa.Column('id', sa.Text, primary_key=True), sa.Column('dataset_id', sa.Text, nullable=False), sa.Column('project_id', sa.Text, sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('version', sa.Integer, nullable=False), sa.Column('parent_id', sa.Text),
        *(sa.Column(k, sa.Text, nullable=False) for k in ('import_id','task_id','manifest_object_id','manifest_sha256','parser_version')),
        sa.Column('shape_json', JSONB, nullable=False), sa.Column('checks_json', JSONB, nullable=False),
        sa.Column('created_by', sa.Text, sa.ForeignKey('users.id'), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('id','project_id', name='cr_bdv_scope_key'), sa.UniqueConstraint('id','dataset_id','project_id', name='cr_bdv_dataset_scope_key'),
        sa.UniqueConstraint('dataset_id','version', name='cr_bdv_version_key'), sa.UniqueConstraint('import_id', name='cr_bdv_import_key'),
        scoped_fk(['dataset_id','project_id'], ['bio_datasets.id','bio_datasets.project_id'], 'cr_bdv_dataset_fk'),
        scoped_fk(['parent_id','dataset_id','project_id'], ['bio_dataset_versions.id','bio_dataset_versions.dataset_id','bio_dataset_versions.project_id'], 'cr_bdv_parent_fk'),
        scoped_fk(['import_id','dataset_id','project_id'], ['bio_imports.id','bio_imports.dataset_id','bio_imports.project_id'], 'cr_bdv_import_fk'),
        scoped_fk(['task_id','project_id'], ['tasks.id','tasks.project_id'], 'cr_bdv_task_fk'),
        sa.ForeignKeyConstraint(['manifest_object_id'], ['storage_objects.id'], name='cr_bdv_manifest_fk'),
        sa.CheckConstraint("version>=1 AND manifest_sha256 ~ '^[0-9a-f]{64}$' AND length(parser_version)>0", name='cr_bdv_values_check'),
        sa.CheckConstraint("jsonb_typeof(shape_json)='object' AND jsonb_typeof(checks_json) IN ('object','array') AND octet_length(shape_json::text)<=65536 AND octet_length(checks_json::text)<=4194304", name='cr_bdv_json_check'))
    members = sa.Table('bio_dataset_members', metadata,
        sa.Column('id', sa.Text, primary_key=True), sa.Column('project_id', sa.Text, sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('dataset_version_id', sa.Text, nullable=False), sa.Column('source_file_id', sa.Text, nullable=False),
        *(sa.Column(k, sa.Text, nullable=False) for k in ('source_member_name','role','format','compression','verification_state','sha256')),
        sa.Column('object_id', sa.Text, sa.ForeignKey('storage_objects.id')), sa.Column('size_bytes', sa.BigInteger, nullable=False),
        sa.UniqueConstraint('id','project_id', name='cr_bdm_scope_key'), sa.UniqueConstraint('dataset_version_id','source_file_id','role','source_member_name', name='cr_bdm_role_key'),
        scoped_fk(['dataset_version_id','project_id'], ['bio_dataset_versions.id','bio_dataset_versions.project_id'], 'cr_bdm_version_fk'),
        scoped_fk(['source_file_id','project_id'], ['files.id','files.project_id'], 'cr_bdm_file_fk'),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$' AND size_bytes>=0 AND verification_state IN ('verified','not_checked','internal_not_checked','failed')", name='cr_bdm_values_check'))
    return datasets, imports, files, versions, members
