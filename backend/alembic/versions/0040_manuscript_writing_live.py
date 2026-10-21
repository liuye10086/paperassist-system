from alembic import op
revision="0040_manuscript_writing_live"
down_revision="0039_layout_exports"
branch_labels=None
depends_on=None
"""Scoped immutable consent material and transactional submission admissions."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

def define_manuscript_writing_live_tables(metadata):
    bundles=sa.Table('manuscript_writing_bundles',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('manuscript_id',sa.Text,nullable=False),sa.Column('base_version_id',sa.Text,nullable=False),
        sa.Column('request_key',sa.Text,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),
        sa.Column('bundle_sha256',sa.Text,nullable=False),sa.Column('bundle_json',JSONB,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('id','project_id','user_id',name='mwl_bundle_scope'),
        sa.UniqueConstraint('project_id','user_id','request_key',name='mwl_preview_key'),
        sa.ForeignKeyConstraint(['manuscript_id','project_id','user_id'],['manuscripts.id','manuscripts.project_id','manuscripts.user_id'],name='mwl_bundle_owner'),
        sa.ForeignKeyConstraint(['base_version_id','manuscript_id'],['manuscript_versions.id','manuscript_versions.manuscript_id'],name='mwl_bundle_base'),
        sa.CheckConstraint("bundle_sha256 ~ '^[0-9a-f]{64}$' AND request_digest ~ '^[0-9a-f]{64}$' AND jsonb_typeof(bundle_json)='object'",name='mwl_bundle_check'))
    authorizations=sa.Table('manuscript_writing_authorizations',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('request_key',sa.Text,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),
        sa.Column('manifest_json',JSONB,nullable=False),sa.Column('manifest_sha256',sa.Text,nullable=False),
        sa.Column('status',sa.Text,nullable=False),sa.Column('revision',sa.Integer,nullable=False),
        sa.Column('max_posts',sa.Integer,nullable=False),sa.Column('cap_micro_usd',sa.BigInteger,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('closed_at',sa.DateTime(timezone=True)),
        sa.UniqueConstraint('id','project_id','user_id',name='mwl_auth_scope'),
        sa.UniqueConstraint('project_id','user_id','request_key',name='mwl_auth_key'),
        sa.ForeignKeyConstraint(['project_id','user_id'],['projects.id','projects.owner_id'],name='mwl_auth_owner'),
        sa.CheckConstraint("status IN ('active','closed','revoked') AND revision>=1 AND max_posts>=1 AND max_posts<=6 AND cap_micro_usd>=0 AND cap_micro_usd<=12000000 AND manifest_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(manifest_json)='object'",name='mwl_auth_check'))
    tasks=sa.Table('manuscript_writing_authorized_tasks',metadata,
        sa.Column('authorization_id',sa.Text,primary_key=True),sa.Column('logical_task_id',sa.Text,primary_key=True),
        sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('bundles_json',JSONB,nullable=False),sa.Column('cap_micro_usd',sa.BigInteger,nullable=False),
        sa.UniqueConstraint('authorization_id','logical_task_id','project_id','user_id',name='mwl_task_scope'),
        sa.ForeignKeyConstraint(['authorization_id','project_id','user_id'],['manuscript_writing_authorizations.id','manuscript_writing_authorizations.project_id','manuscript_writing_authorizations.user_id'],name='mwl_task_auth'),
        sa.CheckConstraint("cap_micro_usd>=0 AND cap_micro_usd<=3000000 AND jsonb_typeof(bundles_json)='array'",name='mwl_task_check'))
    admissions=sa.Table('manuscript_writing_call_admissions',metadata,
        sa.Column('model_call_id',sa.Text,primary_key=True),
        sa.Column('bundle_id',sa.Text,nullable=False),sa.Column('authorization_id',sa.Text,nullable=False),sa.Column('logical_task_id',sa.Text,nullable=False),
        sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('reserved_micro_usd',sa.BigInteger,nullable=False),sa.Column('status',sa.Text,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('submission_started_at',sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(['model_call_id','project_id','user_id'],['model_calls.id','model_calls.project_id','model_calls.user_id'],name='mwl_admission_call'),
        sa.ForeignKeyConstraint(['bundle_id','project_id','user_id'],['manuscript_writing_bundles.id','manuscript_writing_bundles.project_id','manuscript_writing_bundles.user_id'],name='mwl_admission_bundle'),
        sa.ForeignKeyConstraint(['authorization_id','logical_task_id','project_id','user_id'],['manuscript_writing_authorized_tasks.authorization_id','manuscript_writing_authorized_tasks.logical_task_id','manuscript_writing_authorized_tasks.project_id','manuscript_writing_authorized_tasks.user_id'],name='mwl_admission_auth'),
        sa.CheckConstraint("reserved_micro_usd>=0 AND status IN ('reserved','submission_started','released') AND ((status='submission_started')=(submission_started_at IS NOT NULL))",name='mwl_admission_check'))
    return bundles,authorizations,tasks,admissions


def define_manuscript_writing_review_tables(metadata):
    table=sa.Table('manuscript_writing_reviews',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('request_id',sa.Text,nullable=False),
        sa.Column('manuscript_id',sa.Text,nullable=False),sa.Column('base_version_id',sa.Text,nullable=False),
        sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('request_key',sa.Text,nullable=False),sa.Column('request_json',JSONB,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),
        sa.Column('candidate_sha256',sa.Text,nullable=False),sa.Column('reviewed_candidate_json',JSONB,nullable=False),
        sa.Column('reviewed_candidate_sha256',sa.Text,nullable=False),sa.Column('report_json',JSONB,nullable=False),sa.Column('review_sha256',sa.Text,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('request_id','request_key',name='mwr_request_key'),
        sa.UniqueConstraint('id','project_id','user_id',name='mwr_scope'),
        sa.UniqueConstraint('id','request_id','manuscript_id','project_id','user_id','base_version_id',name='mwr_language_scope'),
        sa.ForeignKeyConstraint(['request_id','manuscript_id','project_id','user_id','base_version_id'],
            ['manuscript_writing_requests.task_id','manuscript_writing_requests.manuscript_id','manuscript_writing_requests.project_id','manuscript_writing_requests.user_id','manuscript_writing_requests.base_version_id'],name='mwr_request_scope'),
        sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$' AND candidate_sha256 ~ '^[0-9a-f]{64}$' AND reviewed_candidate_sha256 ~ '^[0-9a-f]{64}$' AND review_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(request_json)='object' AND jsonb_typeof(reviewed_candidate_json)='object' AND jsonb_typeof(report_json)='object'",name='mwr_json_hashes'))
    return (table,)

def define_manuscript_writing_language_tables(metadata):
    table=sa.Table('manuscript_writing_language_reviews',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('request_id',sa.Text,nullable=False),
        sa.Column('manuscript_id',sa.Text,nullable=False),sa.Column('base_version_id',sa.Text,nullable=False),
        sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('review_id',sa.Text,nullable=False),sa.Column('review_sha256',sa.Text,nullable=False),
        sa.Column('request_key',sa.Text,nullable=False),sa.Column('request_json',JSONB,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),
        sa.Column('candidate_json',JSONB,nullable=False),sa.Column('candidate_sha256',sa.Text,nullable=False),
        sa.Column('inventory_json',JSONB,nullable=False),sa.Column('inventory_sha256',sa.Text,nullable=False),
        sa.Column('artifact_sha256',sa.Text,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('request_id','request_key',name='mwlr_request_key'),
        sa.ForeignKeyConstraint(['review_id','request_id','manuscript_id','project_id','user_id','base_version_id'],
            ['manuscript_writing_reviews.id','manuscript_writing_reviews.request_id','manuscript_writing_reviews.manuscript_id','manuscript_writing_reviews.project_id','manuscript_writing_reviews.user_id','manuscript_writing_reviews.base_version_id'],name='mwlr_science_scope'),
        sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$' AND review_sha256 ~ '^[0-9a-f]{64}$' AND candidate_sha256 ~ '^[0-9a-f]{64}$' AND inventory_sha256 ~ '^[0-9a-f]{64}$' AND artifact_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(request_json)='object' AND jsonb_typeof(candidate_json)='object' AND jsonb_typeof(inventory_json)='array'",name='mwlr_json_hashes'))
    return (table,)

def define_manuscript_figure_language_tables(metadata):
    table=sa.Table('manuscript_figure_language_versions',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('file_id',sa.Text,sa.ForeignKey('files.id'),nullable=False),
        sa.Column('figure_id',sa.Text,sa.ForeignKey('figures.id')),
        sa.Column('document_version_id',sa.Text,sa.ForeignKey('file_parse_results.id')),
        sa.Column('replacement_file_id',sa.Text,sa.ForeignKey('files.id')),
        sa.Column('idempotency_key',sa.Text,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),
        sa.Column('request_json',JSONB,nullable=False),sa.Column('snapshot_json',JSONB,nullable=False),
        sa.Column('snapshot_sha256',sa.Text,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['project_id','user_id'],['projects.id','projects.owner_id'],name='mflv_owner_fk'),
        sa.UniqueConstraint('id','project_id','user_id',name='mflv_scope_key'),
        sa.UniqueConstraint('id','file_id',name='mflv_file_key'),
        sa.UniqueConstraint('project_id','user_id','idempotency_key',name='mflv_request_key'),
        sa.CheckConstraint("idempotency_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$' AND snapshot_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(request_json)='object' AND jsonb_typeof(snapshot_json)='object'",name='mflv_json_check'),
        sa.CheckConstraint("num_nonnulls(figure_id,document_version_id)<=1 AND snapshot_json->>'output_language' IN ('en','zh-CN') AND snapshot_json->>'mode' IN ('local_boxplot','uploaded_replacement','no_text_confirmation')",name='mflv_source_check'))
    return (table,)

def frozen_tables():
    metadata=sa.MetaData()
    for name, columns in (("files",("id",)),("figures",("id",)),("file_parse_results",("id",)),("manuscript_writing_requests",("task_id","manuscript_id","project_id","user_id","base_version_id")),("projects",("id","owner_id")),("manuscripts",("id","project_id","user_id")),("manuscript_versions",("id","manuscript_id")),("model_calls",("id","project_id","user_id"))):
        sa.Table(name,metadata,*(sa.Column(c,sa.Text) for c in columns))
    return (*define_manuscript_figure_language_tables(metadata),*define_manuscript_writing_live_tables(metadata),*define_manuscript_writing_review_tables(metadata),*define_manuscript_writing_language_tables(metadata))

OLD_SOURCE_CHECK = "(kind='original' AND source_id=file_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id)=0) OR (kind='document_version' AND source_id=document_version_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id)=1) OR (kind='ocr_review_version' AND source_id=ocr_review_version_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id)=1) OR (kind='external_evidence_version' AND source_id=external_evidence_version_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id)=1) OR (kind='analysis_run' AND source_id=analysis_run_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id)=1) OR (kind='figure' AND source_id=figure_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id)=1)"
NEW_SOURCE_CHECK = "(kind='original' AND source_id=file_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id,figure_language_version_id)=0) OR (kind='document_version' AND source_id=document_version_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id,figure_language_version_id)=1) OR (kind='ocr_review_version' AND source_id=ocr_review_version_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id,figure_language_version_id)=1) OR (kind='external_evidence_version' AND source_id=external_evidence_version_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id,figure_language_version_id)=1) OR (kind='analysis_run' AND source_id=analysis_run_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id,figure_language_version_id)=1) OR (kind='figure' AND source_id=figure_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id,figure_language_version_id)=1) OR (kind='figure_language_version' AND role='image_observation' AND source_id=figure_language_version_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id,figure_language_version_id)=1)"

def upgrade():
    op.create_unique_constraint("mw_request_review_scope","manuscript_writing_requests",["task_id","manuscript_id","project_id","user_id","base_version_id"])
    op.create_unique_constraint('model_calls_scope_key','model_calls',['id','project_id','user_id'])
    for table in frozen_tables(): table.create(op.get_bind())
    op.add_column('manuscript_sources',sa.Column('figure_language_version_id',sa.Text,nullable=True))
    op.create_foreign_key('ms_figure_language_fk','manuscript_sources','manuscript_figure_language_versions',['figure_language_version_id','file_id'],['id','file_id'])
    op.drop_constraint('ms_typed_source_check','manuscript_sources',type_='check')
    op.create_check_constraint('ms_typed_source_check','manuscript_sources',NEW_SOURCE_CHECK)
    op.execute("""CREATE FUNCTION mwl_authorization_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF (to_jsonb(NEW)-ARRAY['status','revision','closed_at']) IS DISTINCT FROM
           (to_jsonb(OLD)-ARRAY['status','revision','closed_at']) OR OLD.status<>'active' OR NEW.status NOT IN ('closed','revoked') OR NEW.revision<>OLD.revision+1 OR NEW.closed_at IS NULL
        THEN RAISE EXCEPTION 'Immutable authorization manifest'; END IF;
        RETURN NEW;
      END $$""")
    op.execute("CREATE TRIGGER mwl_auth_immutable BEFORE UPDATE ON manuscript_writing_authorizations FOR EACH ROW EXECUTE FUNCTION mwl_authorization_immutable()")

def downgrade():
    bind=op.get_bind()
    if any(bind.exec_driver_sql('SELECT EXISTS(SELECT 1 FROM '+table.name+')').scalar_one() for table in frozen_tables()):
        raise RuntimeError('Writing live history exists; refusing destructive downgrade.')
    op.drop_constraint('ms_typed_source_check','manuscript_sources',type_='check')
    op.drop_constraint('ms_figure_language_fk','manuscript_sources',type_='foreignkey')
    op.drop_column('manuscript_sources','figure_language_version_id')
    op.create_check_constraint('ms_typed_source_check','manuscript_sources',OLD_SOURCE_CHECK)
    for table in reversed(frozen_tables()): table.drop(bind)
    op.execute('DROP FUNCTION mwl_authorization_immutable()')
    op.drop_constraint("mw_request_review_scope","manuscript_writing_requests",type_="unique")
    op.drop_constraint('model_calls_scope_key','model_calls',type_='unique')
