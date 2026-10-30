"""Scoped research intake roots and immutable requirement/design snapshots."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


TABLE_NAMES = ('research_intakes', 'research_deliveries', 'research_requirement_versions',
               'research_design_versions', 'research_material_refs')


def scoped_fk(columns, targets, name, **kwargs):
    return sa.ForeignKeyConstraint(columns, targets, name=name, **kwargs)


def define_research_intake_tables(metadata):
    roots = sa.Table('research_intakes', metadata,
        sa.Column('project_id', sa.Text, sa.ForeignKey('projects.id'), primary_key=True),
        sa.Column('owner_id', sa.Text), sa.Column('revision', sa.Integer, nullable=False, server_default='1'),
        sa.Column('current_requirement_version_id', sa.Text), sa.Column('current_design_version_id', sa.Text),
        sa.Column('creation_request_key', sa.Text), sa.Column('creation_digest', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        scoped_fk(['project_id','owner_id'], ['projects.id','projects.owner_id'], 'cr_ri_owner_fk'),
        scoped_fk(['current_requirement_version_id','project_id'], ['research_requirement_versions.id','research_requirement_versions.project_id'], 'cr_ri_requirement_fk', use_alter=True),
        scoped_fk(['current_design_version_id','project_id'], ['research_design_versions.id','research_design_versions.project_id'], 'cr_ri_design_fk', use_alter=True),
        sa.UniqueConstraint('owner_id','creation_request_key', name='cr_ri_creation_key'),
        sa.CheckConstraint('revision >= 1', name='cr_ri_revision_check'),
        sa.CheckConstraint("(creation_request_key IS NULL AND creation_digest IS NULL) OR (owner_id IS NOT NULL AND length(creation_request_key) BETWEEN 1 AND 128 AND creation_digest ~ '^[0-9a-f]{64}$')", name='cr_ri_creation_check'))
    deliveries = sa.Table('research_deliveries', metadata,
        sa.Column('id', sa.Text, primary_key=True), sa.Column('project_id', sa.Text, sa.ForeignKey('research_intakes.project_id'), nullable=False),
        *(sa.Column(k, sa.Text, nullable=False) for k in ('kind','name','origin')),
        sa.Column('active', sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column('revision', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', sa.Text, sa.ForeignKey('users.id')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('id','project_id', name='cr_rd_scope_key'), sa.UniqueConstraint('project_id','kind', name='cr_rd_kind_key'),
        sa.CheckConstraint("kind IN ('analysis','sci_draft','thesis_draft') AND origin IN ('user_selected','legacy_inferred') AND revision>=1 AND length(name) BETWEEN 1 AND 200", name='cr_rd_values_check'))
    versions = []
    for name, prefix in [('research_requirement_versions','rrv'), ('research_design_versions','rdv')]:
        table = sa.Table(name, metadata,
            sa.Column('id', sa.Text, primary_key=True), sa.Column('project_id', sa.Text, sa.ForeignKey('research_intakes.project_id'), nullable=False),
            sa.Column('version', sa.Integer, nullable=False), sa.Column('parent_id', sa.Text), sa.Column('operation', sa.Text, nullable=False),
            sa.Column('content_json', JSONB, nullable=False), sa.Column('sha256', sa.Text, nullable=False),
            sa.Column('request_key', sa.Text, nullable=False), sa.Column('request_digest', sa.Text, nullable=False),
            sa.Column('created_by', sa.Text, sa.ForeignKey('users.id'), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint('id','project_id', name=prefix+'_scope_key'), sa.UniqueConstraint('project_id','version', name=prefix+'_version_key'),
            sa.UniqueConstraint('project_id','request_key', name=prefix+'_request_key'),
            scoped_fk(['parent_id','project_id'], [name+'.id',name+'.project_id'], prefix+'_parent_fk'),
            sa.CheckConstraint("version>=1 AND operation IN ('save','confirm') AND length(request_key) BETWEEN 1 AND 128 AND sha256 ~ '^[0-9a-f]{64}$' AND request_digest ~ '^[0-9a-f]{64}$'", name=prefix+'_values_check'),
            sa.CheckConstraint("(jsonb_typeof(content_json)='object' AND content_json->'schema_version'='1'::jsonb) IS TRUE AND octet_length(content_json::text)<=4194304", name=prefix+'_content_check'))
        sa.Index(prefix+'_project_created', table.c.project_id, table.c.created_at.desc(), table.c.id)
        versions.append(table)
    refs = sa.Table('research_material_refs', metadata,
        sa.Column('id', sa.Text, primary_key=True), sa.Column('project_id', sa.Text, sa.ForeignKey('research_intakes.project_id'), nullable=False),
        *(sa.Column(k, sa.Text) for k in ('requirement_version_id','design_version_id','delivery_id','file_id','bio_dataset_version_id','locator')),
        sa.Column('availability', sa.Text, nullable=False), sa.Column('purpose', sa.Text, nullable=False), sa.Column('note', sa.Text, nullable=False, server_default=''),
        scoped_fk(['requirement_version_id','project_id'], ['research_requirement_versions.id','research_requirement_versions.project_id'], 'cr_rmr_requirement_fk'),
        scoped_fk(['design_version_id','project_id'], ['research_design_versions.id','research_design_versions.project_id'], 'cr_rmr_design_fk'),
        scoped_fk(['delivery_id','project_id'], ['research_deliveries.id','research_deliveries.project_id'], 'cr_rmr_delivery_fk'),
        scoped_fk(['file_id','project_id'], ['files.id','files.project_id'], 'cr_rmr_file_fk'),
        scoped_fk(['bio_dataset_version_id','project_id'], ['bio_dataset_versions.id','bio_dataset_versions.project_id'], 'cr_rmr_bio_fk'),
        sa.CheckConstraint("num_nonnulls(requirement_version_id,design_version_id)=1 AND availability IN ('provided','pending','none') AND ((availability='provided' AND num_nonnulls(file_id,bio_dataset_version_id)=1) OR (availability<>'provided' AND num_nonnulls(file_id,bio_dataset_version_id)=0))", name='cr_rmr_source_check'),
        sa.CheckConstraint('length(purpose) BETWEEN 1 AND 200 AND length(note)<=4000 AND (locator IS NULL OR length(locator)<=4000)', name='cr_rmr_text_check'))
    return roots, deliveries, *versions, refs
