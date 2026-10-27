"""Small fixture registry and durable deletion receipt/barrier tables."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def define_storage_deletion_tables(metadata):
    fixtures=sa.Table('storage_disposable_fixtures',metadata,
        sa.Column('id',sa.Text,primary_key=True),
        sa.Column('project_id',sa.Text,sa.ForeignKey('projects.id'),nullable=False,unique=True),
        sa.Column('owner_id',sa.Text,sa.ForeignKey('users.id'),nullable=False),
        sa.Column('manifest',JSONB,nullable=False),sa.Column('manifest_sha256',sa.Text,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('clock_timestamp()')))
    operations=sa.Table('storage_deletion_operations',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('project_id',sa.Text,sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('owner_id',sa.Text,sa.ForeignKey('users.id'),nullable=False),
        sa.Column('file_id',sa.Text,sa.ForeignKey('files.id')),sa.Column('scope_kind',sa.Text,nullable=False),
        sa.Column('reason',sa.Text,nullable=False),sa.Column('manifest',JSONB,nullable=False),
        sa.Column('manifest_sha256',sa.Text,nullable=False),sa.Column('state',sa.Text,nullable=False),
        sa.Column('idempotency_key',sa.Text),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('clock_timestamp()')),
        sa.UniqueConstraint('project_id','owner_id','idempotency_key',name='storage_deletion_idempotency'),
        sa.CheckConstraint("scope_kind IN ('project','file','temporary') AND ((scope_kind='file')=(file_id IS NOT NULL))",name='storage_deletion_scope'),
        sa.CheckConstraint("state IN ('preview','running','partial_failed','partial_retained')",name='storage_deletion_state'))
    items=sa.Table('storage_deletion_items',metadata,
        sa.Column('operation_id',sa.Text,sa.ForeignKey('storage_deletion_operations.id'),primary_key=True),
        sa.Column('object_id',sa.Text,sa.ForeignKey('storage_objects.id'),primary_key=True),
        sa.Column('state',sa.Text,nullable=False),sa.Column('attempt_no',sa.Integer,nullable=False,server_default='0'),
        sa.Column('error_code',sa.Text),sa.Column('disposed_at',sa.DateTime(timezone=True)),
        sa.CheckConstraint("state IN ('pending','processing','deleted','retained','failed') AND attempt_no>=0",name='storage_deletion_item_state'))
    events=sa.Table('storage_deletion_events',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('operation_id',sa.Text,sa.ForeignKey('storage_deletion_operations.id'),nullable=False),
        sa.Column('object_id',sa.Text),sa.Column('state',sa.Text,nullable=False),sa.Column('reason_code',sa.Text,nullable=False),
        sa.Column('attempt_no',sa.Integer,nullable=False,server_default='0'),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('clock_timestamp()')))
    return fixtures,operations,items,events


# Explicit producer table mapping. Values are trusted SQL expressions using NEW.
# No reads, billing receipts, immutable old histories or generic SQL interception.
DIRECT_PROJECT_TABLES='''files file_upload_batches dataset_preparation_decisions analysis_plan_decisions
ocr_review_decisions figure_configurations report_collections external_evidence_versions literature_searches
project_references literature_fetch_receipts literature_search_hits literature_materials literature_claims
literature_claim_versions literature_claim_evidence literature_claim_reviews literature_claim_supplements
literature_assistance_requests literature_pmc_receipts literature_citation_metadata_versions
literature_material_confirmations literature_citation_drafts literature_citation_versions literature_check_receipts
manuscripts manuscript_versions pdf_exports manuscript_writing_requests manuscript_reviews layout_exports
manuscript_writing_bundles manuscript_writing_authorizations manuscript_writing_authorized_tasks
manuscript_writing_call_admissions manuscript_writing_reviews manuscript_writing_language_reviews
manuscript_figure_language_versions school_template_versions school_template_sources school_template_confirmations
thesis_profiles manuscript_school_changes journal_profiles journal_recommendations journal_material_refs
journal_guides journal_targets journal_format_checks journal_adaptations journal_submission_events review_rounds
review_round_events review_revision_runs review_documents review_document_exports review_round_user_returns
review_round_continuations project_review_progress_events review_opinion_task_links review_analysis_adoptions'''.split()
FILE_TABLES='''file_purposes analysis_setups analysis_runs file_parse_results file_structure_versions
dataset_versions prepared_dataset_versions confirmed_analysis_plans ocr_review_versions'''.split()
RUN_TABLES='figures figure_jobs explanations explanation_jobs reports'.split()
INDIRECT={
    'file_upload_items':"SELECT project_id INTO pid FROM file_upload_batches WHERE id=NEW.batch_id; fid=NEW.file_id;",
    'prepared_dataset_derivations':"SELECT f.project_id,p.file_id INTO pid,fid FROM prepared_dataset_versions p JOIN files f ON f.id=p.file_id WHERE p.id=NEW.prepared_dataset_id;",
    'prepared_dataset_derivations_v3':"SELECT f.project_id,p.file_id INTO pid,fid FROM prepared_dataset_versions p JOIN files f ON f.id=p.file_id WHERE p.id=NEW.prepared_dataset_id;",
    'figure_config_versions':"SELECT c.project_id,r.file_id INTO pid,fid FROM figure_configurations c JOIN analysis_runs r ON r.id=c.analysis_run_id WHERE c.id=NEW.configuration_id;",
    'figure_projection_decisions':"SELECT project_id INTO pid FROM tasks WHERE id=NEW.task_id;",
    'figure_projection_results':"SELECT c.project_id,r.file_id INTO pid,fid FROM figure_config_versions v JOIN figure_configurations c ON c.id=v.configuration_id JOIN analysis_runs r ON r.id=c.analysis_run_id WHERE v.id=NEW.config_version_id;",
    'report_collection_versions':"SELECT project_id INTO pid FROM report_collections WHERE id=NEW.collection_id;",
    'report_collection_items':"SELECT c.project_id INTO pid FROM report_collection_versions v JOIN report_collections c ON c.id=v.collection_id WHERE v.id=NEW.version_id; SELECT file_id INTO fid FROM analysis_runs WHERE id=NEW.analysis_run_id;",
    'report_build_requests':"SELECT c.project_id INTO pid FROM report_collection_versions v JOIN report_collections c ON c.id=v.collection_id WHERE v.id=NEW.version_id;",
    'collection_reports':"SELECT c.project_id INTO pid FROM report_collection_versions v JOIN report_collections c ON c.id=v.collection_id WHERE v.id=NEW.version_id;",
    'manuscript_sources':"SELECT project_id INTO pid FROM manuscript_versions WHERE id=NEW.version_id; fid=NEW.file_id; IF fid IS NULL THEN SELECT file_id INTO fid FROM analysis_runs WHERE id=NEW.analysis_run_id; END IF;",
    'manuscript_citations':"SELECT project_id INTO pid FROM manuscript_versions WHERE id=NEW.version_id;",
    'manuscript_exports':"SELECT project_id INTO pid FROM manuscript_versions WHERE id=NEW.version_id;",
}


def install_barriers(execute):
    for table in DIRECT_PROJECT_TABLES+FILE_TABLES+RUN_TABLES+list(INDIRECT):
        if table in DIRECT_PROJECT_TABLES:
            resolve="pid=NEW.project_id; fid=to_jsonb(NEW)->>'file_id';"
            if table=='files':resolve+=" fid=NEW.id;"
        elif table in FILE_TABLES:
            resolve="fid=NEW.file_id; SELECT project_id INTO pid FROM files WHERE id=fid;"
        elif table in RUN_TABLES:
            resolve="SELECT f.project_id,r.file_id INTO pid,fid FROM analysis_runs r JOIN files f ON f.id=r.file_id WHERE r.id=NEW.analysis_run_id;"
        else:resolve=INDIRECT[table]
        execute(f'''CREATE FUNCTION storage_guard_{table}() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE pid text; fid text;
        BEGIN {resolve}
          IF EXISTS(SELECT 1 FROM storage_deletion_operations o WHERE o.state<>'preview' AND (
             (o.project_id=pid AND (o.scope_kind='project' OR o.state IN ('running','partial_failed')))
             OR (o.scope_kind='file' AND o.file_id=fid AND EXISTS(
                      SELECT 1 FROM storage_deletion_items i WHERE i.operation_id=o.id AND i.state<>'retained'))
             OR (o.scope_kind='project' AND o.project_id=(SELECT project_id FROM files WHERE id=fid))))
          THEN RAISE EXCEPTION USING ERRCODE='P7501', MESSAGE='storage_deletion_pending'; END IF;
          RETURN NEW;
        END $$''')
        execute(f'CREATE TRIGGER storage_deletion_guard BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION storage_guard_{table}()')
    execute('''CREATE FUNCTION storage_guard_object_reference() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF TG_OP='INSERT' AND EXISTS(SELECT 1 FROM storage_references WHERE object_id=NEW.object_id AND project_id=NEW.project_id) THEN RETURN NEW; END IF;
      IF EXISTS(SELECT 1 FROM storage_deletion_items WHERE object_id=NEW.object_id AND state<>'retained')
         OR EXISTS(SELECT 1 FROM storage_deletion_operations WHERE project_id=NEW.project_id AND state<>'preview'
                   AND (scope_kind='project' OR state IN ('running','partial_failed')))
      THEN RAISE EXCEPTION USING ERRCODE='P7501',MESSAGE='storage_deletion_pending'; END IF;
      RETURN NEW; END $$''')
    execute('CREATE TRIGGER storage_deletion_guard BEFORE INSERT OR UPDATE ON storage_references FOR EACH ROW EXECUTE FUNCTION storage_guard_object_reference()')
    # New call admission is prohibited; updates/usage/budget settlement of an
    # existing call remain allowed so a late fee receipt cannot be discarded.
    execute('''CREATE FUNCTION storage_guard_task_admission() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE pid text;
      BEGIN
        IF TG_TABLE_NAME IN ('tasks','model_calls') THEN pid=NEW.project_id;
        ELSE SELECT project_id INTO pid FROM tasks WHERE id=NEW.task_id; END IF;
        IF EXISTS(SELECT 1 FROM storage_deletion_operations WHERE project_id=pid AND state<>'preview'
                  AND (scope_kind='project' OR state IN ('running','partial_failed')))
        THEN RAISE EXCEPTION USING ERRCODE='P7501',MESSAGE='storage_deletion_pending'; END IF;
        RETURN NEW; END $$''')
    for table in ('tasks','task_outbox','task_attempts','model_calls','task_checkpoints','task_resume_requests'):
        execute(f'CREATE TRIGGER storage_deletion_guard BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION storage_guard_task_admission()')
    execute('''CREATE FUNCTION storage_deletion_identity_seal() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Deletion evidence is immutable'; END IF;
      IF TG_TABLE_NAME='storage_deletion_operations' THEN
        IF ((to_jsonb(OLD)-'state'-'idempotency_key')<>(to_jsonb(NEW)-'state'-'idempotency_key')
          OR (OLD.idempotency_key IS NOT NULL AND OLD.idempotency_key IS DISTINCT FROM NEW.idempotency_key)
          OR (OLD.state<>'preview' AND NEW.state='preview')) THEN RAISE EXCEPTION 'Deletion identity is immutable'; END IF;
      ELSE
        IF (OLD.operation_id<>NEW.operation_id OR OLD.object_id<>NEW.object_id OR NEW.attempt_no<OLD.attempt_no
          OR (OLD.state IN ('deleted','retained') AND to_jsonb(OLD)<>to_jsonb(NEW))) THEN RAISE EXCEPTION 'Disposition is immutable'; END IF;
      END IF;
      RETURN NEW; END $$''')
    for table in ('storage_deletion_operations','storage_deletion_items'):
        execute(f'CREATE TRIGGER storage_identity_seal BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION storage_deletion_identity_seal()')
    for table in ('storage_disposable_fixtures','storage_deletion_events'):
        execute(f'CREATE TRIGGER storage_evidence_seal BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION admin_configuration_seal()')


def remove_barriers(execute):
    for table in DIRECT_PROJECT_TABLES+FILE_TABLES+RUN_TABLES+list(INDIRECT):
        execute(f'DROP TRIGGER storage_deletion_guard ON {table}')
        execute(f'DROP FUNCTION storage_guard_{table}()')
    for table in ('storage_references','tasks','task_outbox','task_attempts','model_calls','task_checkpoints','task_resume_requests'):
        execute(f'DROP TRIGGER storage_deletion_guard ON {table}')
    execute('DROP FUNCTION storage_guard_object_reference()')
    execute('DROP FUNCTION storage_guard_task_admission()')
    for table in ('storage_deletion_operations','storage_deletion_items'):
        execute(f'DROP TRIGGER storage_identity_seal ON {table}')
    execute('DROP FUNCTION storage_deletion_identity_seal()')
