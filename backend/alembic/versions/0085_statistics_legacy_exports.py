"""Bind existing export tasks to governed detailed report members."""
from alembic import op
from app.db.schema import metadata

revision = '0085_statistics_legacy_exports'
down_revision = '0084_statistics_report_context'
branch_labels = depends_on = None


def upgrade():
    metadata.tables['statistics_legacy_report_exports'].create(op.get_bind())
    metadata.tables['statistics_legacy_export_requests'].create(op.get_bind())
    op.execute('CREATE TRIGGER statistics_legacy_request_seal BEFORE UPDATE OR DELETE ON statistics_legacy_export_requests FOR EACH ROW EXECUTE FUNCTION statistics_report_context_seal()')
    op.execute("""CREATE FUNCTION statistics_legacy_export_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE t tasks%ROWTYPE; c statistics_report_context_versions%ROWTYPE; v research_report_versions%ROWTYPE;
            q report_build_requests%ROWTYPE; r reports%ROWTYPE; cr collection_reports%ROWTYPE; m jsonb;
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Saved statistics export bindings are immutable'; END IF;
      IF TG_OP='UPDATE' AND (
        (to_jsonb(OLD)-'report_id'-'collection_report_id') IS DISTINCT FROM (to_jsonb(NEW)-'report_id'-'collection_report_id')
        OR OLD.report_id IS NOT NULL OR OLD.collection_report_id IS NOT NULL
        OR num_nonnulls(NEW.report_id,NEW.collection_report_id)<>1)
      THEN RAISE EXCEPTION 'Saved statistics export bindings are immutable'; END IF;
      SELECT * INTO STRICT t FROM tasks WHERE id=NEW.task_id AND project_id=NEW.project_id AND user_id=NEW.user_id;
      SELECT * INTO STRICT c FROM statistics_report_context_versions WHERE id=NEW.context_id AND project_id=NEW.project_id AND user_id=NEW.user_id;
      SELECT * INTO STRICT v FROM research_report_versions WHERE id=NEW.report_version_id AND project_id=NEW.project_id AND user_id=NEW.user_id;
      m=t.input_snapshot->'reader_export';
      IF m IS NULL OR m->>'policy' IS DISTINCT FROM NEW.policy OR m->>'context_id' IS DISTINCT FROM NEW.context_id
        OR m->>'report_version_id' IS DISTINCT FROM NEW.report_version_id OR m->>'content_sha256' IS DISTINCT FROM NEW.content_sha256
        OR m->>'source_snapshot_sha256' IS DISTINCT FROM NEW.source_snapshot_sha256 OR v.task_id<>t.id
        OR v.content_sha256<>NEW.content_sha256 OR v.finding_version_id IS DISTINCT FROM m->'request'->>'finding_version_id'
        OR c.content_json->'selection'->>'kind' IS DISTINCT FROM NEW.source_kind
      THEN RAISE EXCEPTION 'Statistics export scope mismatch'; END IF;
      IF NEW.source_kind='analysis' THEN
        IF t.task_type<>'word_report' OR c.content_json->'selection'->>'file_id' IS DISTINCT FROM t.input_snapshot->'file'->>'id'
          OR c.content_json->'selection'->>'analysis_run_id' IS DISTINCT FROM t.input_snapshot->'result'->>'id'
          OR c.content_json->'selection'->>'figure_id' IS DISTINCT FROM t.input_snapshot->'figure'->>'id'
          OR c.content_json->'selection'->>'explanation_id' IS DISTINCT FROM t.input_snapshot->'explanation'->>'id'
          OR t.input_snapshot->'versions'->>'report' IS DISTINCT FROM 'statistics_reader_report_v1'
        THEN RAISE EXCEPTION 'Statistics analysis selection mismatch'; END IF;
        IF NEW.report_id IS NOT NULL THEN
          SELECT * INTO STRICT r FROM reports WHERE id=NEW.report_id;
          IF r.analysis_run_id IS DISTINCT FROM t.input_snapshot->'result'->>'id'
            OR r.explanation_id IS DISTINCT FROM t.input_snapshot->'explanation'->>'id'
            OR r.renderer_version<>'statistics_reader_report_v1' OR r.input_json::jsonb<>t.input_snapshot
          THEN RAISE EXCEPTION 'Statistics report identity mismatch'; END IF;
        END IF;
      ELSE
        SELECT * INTO STRICT q FROM report_build_requests WHERE id=NEW.build_request_id;
        IF t.task_type<>'collection_word_report' OR q.task_id IS DISTINCT FROM t.id
          OR q.input_json IS DISTINCT FROM t.input_snapshot OR q.renderer_version<>'statistics_reader_report_v1'
          OR c.collection_version_id IS DISTINCT FROM t.input_snapshot->>'collection_version_id'
          OR c.collection_id IS DISTINCT FROM t.input_snapshot->>'collection_id'
        THEN RAISE EXCEPTION 'Statistics collection selection mismatch'; END IF;
        IF NEW.collection_report_id IS NOT NULL THEN
          SELECT * INTO STRICT cr FROM collection_reports WHERE id=NEW.collection_report_id;
          IF cr.build_request_id<>q.id OR cr.version_id<>q.version_id OR cr.input_json<>t.input_snapshot
            OR cr.renderer_version<>'statistics_reader_report_v1'
          THEN RAISE EXCEPTION 'Statistics collection report identity mismatch'; END IF;
        END IF;
      END IF;
      IF num_nonnulls(NEW.report_id,NEW.collection_report_id)>0 AND v.manifest_object_id IS NULL
        THEN RAISE EXCEPTION 'Statistics publication is incomplete'; END IF;
      RETURN NEW;
    END $$""")
    op.execute('CREATE TRIGGER statistics_legacy_export_guard BEFORE INSERT OR UPDATE OR DELETE ON statistics_legacy_report_exports FOR EACH ROW EXECUTE FUNCTION statistics_legacy_export_guard()')


def downgrade():
    if op.get_bind().exec_driver_sql('SELECT EXISTS (SELECT 1 FROM statistics_legacy_report_exports)').scalar_one():
        raise RuntimeError('Saved statistics exports exist; downgrade would erase fixed associations.')
    op.drop_table('statistics_legacy_export_requests')
    op.drop_table('statistics_legacy_report_exports')
    op.execute('DROP FUNCTION statistics_legacy_export_guard()')
