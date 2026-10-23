"""Add explicit school change inputs; leave all old JSON and hashes untouched."""
from alembic import op
revision='0044_school_changes'
down_revision='0043_school_exports'
branch_labels=None
depends_on=None
"""One sealed input and adoption record, reusing public manuscript versions."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def define_school_change_table(metadata):
    return sa.Table('manuscript_school_changes',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('manuscript_id',sa.Text,nullable=False),sa.Column('base_version_id',sa.Text,nullable=False),
        sa.Column('kind',sa.Text,nullable=False),sa.Column('target_confirmation_id',sa.Text),sa.Column('file_id',sa.Text),sa.Column('document_version_id',sa.Text),sa.Column('base_export_id',sa.Text),
        sa.Column('idempotency_key',sa.Text,nullable=False),sa.Column('request_json',JSONB,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),
        sa.Column('input_json',JSONB,nullable=False),sa.Column('input_sha256',sa.Text,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('adopted_revision',sa.Integer),sa.Column('adopt_key',sa.Text),sa.Column('adopt_json',JSONB(none_as_null=True)),sa.Column('adopt_sha256',sa.Text),
        sa.Column('candidate_json',JSONB(none_as_null=True)),sa.Column('candidate_sha256',sa.Text),
        sa.ForeignKeyConstraint(['manuscript_id','project_id','user_id'],['manuscripts.id','manuscripts.project_id','manuscripts.user_id'],name='msc_root_scope_fk'),
        sa.ForeignKeyConstraint(['base_version_id','manuscript_id'],['manuscript_versions.id','manuscript_versions.manuscript_id'],name='msc_base_scope_fk'),
        sa.ForeignKeyConstraint(['target_confirmation_id','project_id','user_id'],['school_template_confirmations.id','school_template_confirmations.project_id','school_template_confirmations.user_id'],name='msc_confirmation_scope_fk'),
        sa.ForeignKeyConstraint(['file_id','project_id'],['files.id','files.project_id'],name='msc_file_scope_fk'),
        sa.ForeignKeyConstraint(['document_version_id','file_id'],['file_parse_results.id','file_parse_results.file_id'],name='msc_document_scope_fk'),
        sa.ForeignKeyConstraint(['base_export_id'],['manuscript_exports.id'],name='msc_export_fk'),
        sa.ForeignKeyConstraint(['manuscript_id','adopted_revision'],['manuscript_versions.manuscript_id','manuscript_versions.revision'],name='msc_adopted_fk'),
        sa.UniqueConstraint('manuscript_id','idempotency_key',name='msc_request_key'),
        sa.CheckConstraint("idempotency_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$' AND input_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(input_json)='object' AND jsonb_typeof(request_json)='object'",name='msc_input_check'),
        sa.CheckConstraint("(kind='template_migration' AND target_confirmation_id IS NOT NULL AND file_id IS NULL AND document_version_id IS NULL AND base_export_id IS NULL) OR (kind='docx_return' AND target_confirmation_id IS NULL AND file_id IS NOT NULL AND document_version_id IS NOT NULL)",name='msc_kind_check'),
        sa.CheckConstraint("(adopted_revision IS NULL AND adopt_key IS NULL AND adopt_json IS NULL AND adopt_sha256 IS NULL AND candidate_json IS NULL AND candidate_sha256 IS NULL) OR (adopted_revision>1 AND adopt_key IS NOT NULL AND adopt_json IS NOT NULL AND adopt_sha256 ~ '^[0-9a-f]{64}$' AND candidate_json IS NOT NULL AND candidate_sha256 ~ '^[0-9a-f]{64}$')",name='msc_adoption_check'))

def frozen_table():
    metadata=sa.MetaData()
    for name,columns in [('manuscripts',('id','project_id','user_id')),('manuscript_versions',('id','manuscript_id','revision')),('school_template_confirmations',('id','project_id','user_id')),('files',('id','project_id')),('file_parse_results',('id','file_id')),('manuscript_exports',('id',))]:
        sa.Table(name,metadata,*(sa.Column(c,sa.Text) for c in columns))
    return define_school_change_table(metadata)

def upgrade():
    op.add_column('school_template_versions',sa.Column('previous_version_id',sa.Text))
    op.create_foreign_key('stv_previous_scope_fk','school_template_versions','school_template_versions',['previous_version_id','project_id','user_id'],['id','project_id','user_id'])
    op.create_check_constraint('stv_previous_check','school_template_versions','previous_version_id IS NULL OR previous_version_id<>id')
    frozen_table().create(op.get_bind())
    op.execute("""CREATE FUNCTION school_change_seal() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP='UPDATE' AND OLD.adopted_revision IS NULL AND NEW.adopted_revision IS NOT NULL
          AND (to_jsonb(NEW)-ARRAY['adopted_revision','adopt_key','adopt_json','adopt_sha256','candidate_json','candidate_sha256'])=(to_jsonb(OLD)-ARRAY['adopted_revision','adopt_key','adopt_json','adopt_sha256','candidate_json','candidate_sha256'])
        THEN RETURN NEW; END IF;
        RAISE EXCEPTION 'Immutable school change input and adoption';
      END $$""")
    op.execute('CREATE TRIGGER manuscript_school_changes_seal BEFORE UPDATE OR DELETE ON manuscript_school_changes FOR EACH ROW EXECUTE FUNCTION school_change_seal()')

def downgrade():
    if op.get_bind().exec_driver_sql('SELECT EXISTS(SELECT 1 FROM manuscript_school_changes) OR EXISTS(SELECT 1 FROM school_template_versions WHERE previous_version_id IS NOT NULL)').scalar_one():
        raise RuntimeError('School change history exists; refusing destructive downgrade.')
    frozen_table().drop(op.get_bind())
    op.execute('DROP FUNCTION school_change_seal()')
    op.drop_constraint('stv_previous_check','school_template_versions',type_='check')
    op.drop_constraint('stv_previous_scope_fk','school_template_versions',type_='foreignkey')
    op.drop_column('school_template_versions','previous_version_id')
