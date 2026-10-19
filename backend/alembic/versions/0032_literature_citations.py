"""Frozen additive citation history schema."""
from alembic import op
revision = '0032_literature_citations'
down_revision = '0031_literature_evidence'
branch_labels = None
depends_on = None
"""Additive citation snapshots; the migration contains its own frozen definition."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def define_literature_citation_tables(metadata):
    def common(name):
        return [sa.Column('id',sa.Text,primary_key=True),
            sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
            sa.ForeignKeyConstraint(['project_id','user_id'],['projects.id','projects.owner_id'],name=name+'_owner_fkey'),
            sa.Column('idempotency_key',sa.Text,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),
            sa.Column('request_json',JSONB,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
            sa.CheckConstraint("idempotency_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$' AND jsonb_typeof(request_json)='object'",name=name+'_request_check')]

    def snapshot(name):
        return [sa.Column('snapshot_json',JSONB,nullable=False),sa.Column('snapshot_sha256',sa.Text,nullable=False),
            sa.CheckConstraint("jsonb_typeof(snapshot_json)='object' AND snapshot_sha256 ~ '^[0-9a-f]{64}$'",name=name+'_snapshot_check')]

    meta = sa.Table('literature_citation_metadata_versions',metadata,*common('lc_metadata'),*snapshot('lc_metadata'),
        sa.Column('project_reference_id',sa.Text,nullable=False),sa.Column('reference_id',sa.Text,nullable=False),
        sa.Column('revision',sa.Integer,nullable=False),
        sa.ForeignKeyConstraint(['project_reference_id','project_id','user_id','reference_id'],
            ['project_references.id','project_references.project_id','project_references.user_id','project_references.reference_id'],name='lc_metadata_reference_fkey'),
        sa.UniqueConstraint('project_reference_id','revision',name='lc_metadata_revision_key'),
        sa.UniqueConstraint('user_id','project_id','idempotency_key',name='lc_metadata_request_key'),
        sa.CheckConstraint('revision>=1',name='lc_metadata_revision_check'))
    confirmations=sa.Table('literature_material_confirmations',metadata,*common('lc_material'),*snapshot('lc_material'),
        sa.Column('material_id',sa.Text,nullable=False),sa.Column('project_reference_id',sa.Text,nullable=False),
        sa.Column('revision',sa.Integer,nullable=False),
        sa.ForeignKeyConstraint(['material_id','project_id','user_id','project_reference_id'],
            ['literature_materials.id','literature_materials.project_id','literature_materials.user_id','literature_materials.project_reference_id'],name='lc_material_source_fkey'),
        sa.UniqueConstraint('material_id','revision',name='lc_material_revision_key'),
        sa.UniqueConstraint('user_id','project_id','idempotency_key',name='lc_material_request_key'),
        sa.CheckConstraint('revision>=1',name='lc_material_revision_check'))
    drafts=sa.Table('literature_citation_drafts',metadata,*common('lc_drafts'),
        sa.Column('revision',sa.Integer,nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('id','project_id','user_id',name='lc_drafts_scope_key'),
        sa.UniqueConstraint('user_id','project_id','idempotency_key',name='lc_drafts_request_key'),
        sa.CheckConstraint('revision>=1 AND updated_at>=created_at',name='lc_drafts_revision_check'))
    versions=sa.Table('literature_citation_versions',metadata,*common('lc_versions'),*snapshot('lc_versions'),
        sa.Column('draft_id',sa.Text,nullable=False),sa.Column('revision',sa.Integer,nullable=False),
        sa.ForeignKeyConstraint(['draft_id','project_id','user_id'],
            ['literature_citation_drafts.id','literature_citation_drafts.project_id','literature_citation_drafts.user_id'],name='lc_versions_draft_fkey'),
        sa.UniqueConstraint('draft_id','revision',name='lc_versions_revision_key'),
        sa.UniqueConstraint('user_id','project_id','draft_id','idempotency_key',name='lc_versions_request_key'),
        sa.CheckConstraint('revision>=1',name='lc_versions_revision_check'))
    for table in (meta,confirmations,drafts,versions):
        sa.Index(table.name+'_project_created',table.c.project_id,table.c.created_at.desc(),table.c.id)
    return meta,confirmations,drafts,versions


def frozen_tables():
    metadata = sa.MetaData()
    for name, columns in (
        ('projects',('id','owner_id')),
        ('project_references',('id','project_id','user_id','reference_id')),
        ('literature_materials',('id','project_id','user_id','project_reference_id')),
    ):
        sa.Table(name,metadata,*(sa.Column(column,sa.Text) for column in columns))
    return define_literature_citation_tables(metadata)


def upgrade():
    for table in frozen_tables():
        table.create(op.get_bind())


def downgrade():
    tables=frozen_tables()
    bind=op.get_bind()
    if any(bind.exec_driver_sql('SELECT EXISTS(SELECT 1 FROM "'+table.name+'")').scalar_one() for table in tables):
        raise RuntimeError('Cannot remove citation or material confirmation history')
    for table in reversed(tables):
        table.drop(bind)
