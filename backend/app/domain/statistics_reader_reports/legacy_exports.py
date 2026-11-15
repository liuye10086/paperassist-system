"""Explicit bridge from genuine old tasks to the governed report publication protocol."""
import json
from uuid import UUID, uuid5

from psycopg.types.json import Jsonb

from app.adapters.research_results_store import base, identity, insert, invalid
from app.domain.bioinformatics.contracts import digest
from app.domain.bioinformatics.service import append_checkpoint
from app.domain.research_results.reports import ResearchReportService, OUTPUT_POLICY, narrative_required
from app.domain.research_results.contracts import ResearchReportRequest
from app.domain.source_byte_verification import VerificationPhase
from .narrative import ADAPTER_VERSION, ORIGIN

POLICY = 'statistics_reader_export_v1'
RENDERER = 'statistics_reader_report_v1'
LEGACY_TASKS = ('word_report', 'collection_word_report')
TABLE = 'statistics_legacy_report_exports'


def lock_submission(db, project, request):
    # The same explanation has one current policy output. Serialize acceptance,
    # including different explicit request keys, before looking for a producer.
    db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
               ('statistics-word:' + project + ':' + request.explanation_id,))


def bind_request(db, task, key, request_sha):
    insert(db, 'statistics_legacy_export_requests', dict(id=identity(task['project_id'],'legacy-request',key),
        project_id=task['project_id'],user_id=task['user_id'],task_id=task['id'],request_key=key,request_digest=request_sha))


def reusable_task(db, store, project, request, key, request_sha):
    row=db.execute("""SELECT * FROM tasks WHERE project_id=%s AND user_id=%s AND task_type='word_report'
        AND input_digest=%s AND input_snapshot->'reader_export'->>'policy'=%s
        AND status IN ('queued','running','failed','succeeded') ORDER BY created_at DESC LIMIT 1""",
        (project,store.user_id,request_sha,POLICY)).fetchone()
    if row:
        bind_request(db,row,key,request_sha)
        return dict(row)


def is_reader_export(task):
    return (task['task_type'] in LEGACY_TASKS
            and task['input_snapshot'].get('reader_export', {}).get('policy') == POLICY)


def legacy_snapshot(snapshot):
    value = {key: value for key, value in snapshot.items() if key != 'reader_export'}
    return value


def input_identity(task):
    if not is_reader_export(task):
        raise invalid()
    snapshot, marker = task['input_snapshot'], task['input_snapshot']['reader_export']
    if (marker['source_snapshot_sha256'] != digest(legacy_snapshot(snapshot))
            or marker['adapter_version'] != ADAPTER_VERSION
            or marker['output_policy'] != OUTPUT_POLICY):
        raise invalid()
    if task['task_type'] == 'collection_word_report':
        if digest(snapshot) != task['input_digest'] or snapshot['project_id'] != task['project_id']:
            raise invalid()
    else:
        from app.domain.tasks.contracts import TaskCreateRequest
        from app.domain.external_processing import request_digest
        request = TaskCreateRequest(task_type='word_report', file_id=snapshot['file']['id'],
            analysis_run_id=snapshot['result']['id'], expected_revision=snapshot['result']['setup_revision'],
            figure_id=snapshot['figure']['id'], explanation_id=snapshot['explanation']['id'])
        if request_digest(request) != task['input_digest'] or snapshot['project']['id'] != task['project_id']:
            raise invalid()
    return dict(kind=task['task_type'], workflow_version=task['workflow_version'], policy=POLICY,
                source_sha256=task['input_digest'], snapshot_sha256=digest(snapshot),
                content_sha256=marker['content_sha256'], output_language=snapshot['output_language'])


class StatisticsLegacyReportService(ResearchReportService):
    def freeze_task(self, db, task):
        """Freeze before insert_task; all rows are bound in that same transaction."""
        from .service import StatisticsReaderReportService
        from .render import renderer_identity
        snapshot = task['input_snapshot']
        if task['task_type'] == 'word_report':
            snapshot['versions']['report'] = RENDERER
            selection = dict(kind='analysis', file_id=snapshot['file']['id'], analysis_run_id=snapshot['result']['id'],
                             figure_id=snapshot['figure']['id'], explanation_id=snapshot['explanation']['id'])
            title = 'Statistical analysis report' if snapshot['output_language'] == 'en' else '统计分析报告'
        else:
            selection = dict(kind='collection', collection_id=snapshot['collection_id'],
                             collection_version_id=snapshot['collection_version_id'])
            title = snapshot['title']
        prepared, _ = StatisticsReaderReportService(self.assets).prepare_in_transaction(db, task['project_id'],
            dict(title=title, language=snapshot['output_language'], selection=selection), 'legacy:' + task['id'])
        request = ResearchReportRequest.model_validate(prepared['report'])
        content, bindings, _ = self.freeze(db, task['project_id'], request)
        if content.get('reader_report', {}).get('origin') != ORIGIN:
            raise narrative_required(request.language)
        identifier = identity(task['project_id'], 'legacy-report', task['id'])
        snapshot['reader_export'] = dict(policy=POLICY, output_policy=OUTPUT_POLICY, adapter_version=ADAPTER_VERSION,
            renderer_identity=renderer_identity(), context_id=prepared['id'], request=prepared['report'],
            report_version_id=identifier, content_sha256=digest(content),
            source_snapshot_sha256=digest(snapshot), source_file_ids=sorted({f for b in bindings for f in b.source_file_ids}))
        if task['task_type'] == 'collection_word_report':
            task['input_digest'] = digest(snapshot)
        return content, bindings

    def bind_task(self, db, task, frozen):
        content, bindings = frozen
        marker = task['input_snapshot']['reader_export']; identifier = marker['report_version_id']
        insert(db, 'research_report_versions', {**base(identifier, task['project_id'], task['user_id']),
            'root_id': identifier, 'revision': 1, 'parent_id': None,
            'finding_version_id': marker['request']['finding_version_id'], 'task_id': task['id'],
            'language': task['input_snapshot']['output_language'], 'content_json': content,
            'content_sha256': marker['content_sha256'], 'manifest_object_id': None, 'manifest_sha256': None,
            'request_key': 'legacy:' + task['id'], 'request_digest': task['input_digest']})
        for source in bindings:
            self.bind(db, task['project_id'], 'report', identifier, source)
        insert(db, TABLE, dict(id=task['id'], project_id=task['project_id'], user_id=task['user_id'], task_id=task['id'],
            context_id=marker['context_id'], report_version_id=identifier, source_kind='analysis' if task['task_type']=='word_report' else 'collection',
            build_request_id=task['input_snapshot'].get('build_request_id'), policy=POLICY,
            source_snapshot_sha256=marker['source_snapshot_sha256'], content_sha256=marker['content_sha256'],
            report_id=None, collection_report_id=None))
        append_checkpoint(db, task, 'check', 'check', dict(input_version=input_identity(task), stage='report'))

    def association(self, db, task):
        input_identity(task)
        marker = task['input_snapshot']['reader_export']
        row = self.require(db, TABLE, task['project_id'], task['id'])
        if any(row[key] != marker[key] for key in ('context_id', 'report_version_id', 'policy', 'source_snapshot_sha256', 'content_sha256')):
            raise invalid()
        if task['status']=='succeeded':
            if task['task_type']=='word_report':
                if not row['report_id'] or row['report_id']!=task.get('result_report_id'):raise invalid()
            elif not row['collection_report_id']:
                raise invalid()
            if task.get('result_research_report_version_id'):raise invalid()
        return row

    def require_sources(self, db, task, *, progress=None):
        from .validation import validate_sources
        return validate_sources(lambda:self._require_sources(db,task,progress=progress))

    def _require_sources(self, db, task, *, progress=None):
        self.association(db, task)
        snapshot = task['input_snapshot']; marker = snapshot['reader_export']
        from .render import frozen_renderer_identity
        if marker['renderer_identity'] != frozen_renderer_identity(marker['renderer_identity']):
            raise invalid()
        if task['task_type'] == 'collection_word_report':
            from app.adapters.collection_store import CollectionStore
            from app.domain.report_collections.service import scoped_store
            CollectionStore(scoped_store(task['user_id'], self.store.config, self.assets.directory)).verify_task_snapshot(db, task)
        with VerificationPhase(db, self.assets, task['project_id']) as phase:
            content, _, payload = self._freeze_in_phase(db, task['project_id'],
                ResearchReportRequest.model_validate(marker['request']), phase=phase, progress=progress)
        row = self.require(db, 'research_report_versions', task['project_id'], marker['report_version_id'])
        if row['task_id'] != task['id'] or row['content_json'] != content or digest(content) != marker['content_sha256']:
            raise invalid()
        # The context verifies all original result/figure/explanation bytes. Also
        # bind their exact identities to the preserved old top-level fields.
        context = self.require(db, 'statistics_report_context_versions', task['project_id'], marker['context_id'])['content_json']
        selected = context['selection']
        if task['task_type'] == 'word_report':
            expected = dict(kind='analysis', file_id=snapshot['file']['id'], analysis_run_id=snapshot['result']['id'],
                            figure_id=snapshot['figure']['id'], explanation_id=snapshot['explanation']['id'])
            if selected != expected:
                raise invalid()
            for table, column, value in [('analysis_runs','result_json',snapshot['result']),
                                         ('figures','figure_json',snapshot['figure']), ('explanations','explanation_json',snapshot['explanation'])]:
                saved = db.execute(f'SELECT {column} FROM {table} WHERE id=%s', (value['id'],)).fetchone()
                if not saved or json.loads(saved[column]) != value:
                    raise invalid()
            file = db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s', (snapshot['file']['id'], task['project_id'])).fetchone()
            if not file or any(file[k] != snapshot['file'][k] for k in ('id','filename','sha256','size_bytes','file_type')):
                raise invalid()
        elif selected != dict(kind='collection', collection_id=snapshot['collection_id'], collection_version_id=snapshot['collection_version_id']):
            raise invalid()
        return payload

    def publish(self, db, task, checkpoint, moment, prepared, *, progress):
        from app.adapters.task_execution_store import TaskExecutionStore
        from app.adapters.task_store import TaskStore
        self.association(db, task)
        snapshot = task['input_snapshot']; marker = snapshot['reader_export']
        identifier = marker['report_version_id']
        self.publish_members(db, task, identifier, prepared, progress=progress)
        member = next(m for m in prepared['members'] if m['role']=='docx')
        report_id = str(uuid5(UUID(identifier), 'legacy-word'))
        if task['task_type']=='word_report':
            from app.adapters.report_store import ReportStore
            metadata = ReportStore.metadata(snapshot)
            metadata.update(id=report_id, created_at=task['created_at'].isoformat(), language=snapshot['output_language'])
            metadata['engine']['id'] = RENDERER
        else:
            metadata = dict(id=report_id, schema_version=1, created_at=task['created_at'].isoformat(),
                **{k:snapshot[k] for k in ('collection_id','collection_version_id','build_request_id','export_revision','language')},
                engine=dict(id=RENDERER), input_sha256=digest(snapshot), filename='Analysis report.docx' if snapshot['language']=='en' else '分析报告.docx')
        metadata.update(sha256=member['sha256'], size_bytes=member['size_bytes'],
            reader_export=dict(policy=POLICY, context_id=marker['context_id'], report_version_id=identifier,
                task_id=task['id'], task_type=task['task_type'], origin=ORIGIN, adapter_version=ADAPTER_VERSION),
            reader_report=self.require(db,'research_report_versions',task['project_id'],identifier)['content_json']['reader_report'],
            members=[{**{k:m[k] for k in ('id','key','role','format','sha256','size_bytes')},
                'download_url':f'/api/v1/projects/{task["project_id"]}/research-reports/{identifier}/members/{m["id"]}/download'} for m in prepared['members'] if m['role'] in ('docx','xlsx','zip')])
        if task['task_type']=='word_report':
            db.execute('INSERT INTO reports (id,analysis_run_id,explanation_id,renderer_version,report_json,input_json) VALUES (%s,%s,%s,%s,%s,%s)',
                (report_id,snapshot['result']['id'],snapshot['explanation']['id'],RENDERER,json.dumps(metadata,ensure_ascii=False),json.dumps(snapshot,ensure_ascii=False)))
            db.execute(f'UPDATE {TABLE} SET report_id=%s WHERE task_id=%s', (report_id,task['id']))
            task['result_report_id'] = report_id
        else:
            db.execute('INSERT INTO collection_reports (id,build_request_id,version_id,export_revision,renderer_version,report_json,input_json,sha256,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (report_id,snapshot['build_request_id'],snapshot['collection_version_id'],snapshot['export_revision'],RENDERER,Jsonb(metadata),Jsonb(snapshot),metadata['sha256'],moment))
            db.execute(f'UPDATE {TABLE} SET collection_report_id=%s WHERE task_id=%s', (report_id,task['id']))
            db.execute("UPDATE report_build_requests SET status='succeeded',error_code=NULL,updated_at=%s WHERE id=%s", (moment,snapshot['build_request_id']))
        progress()
        append_checkpoint(db,task,'done','done',{**checkpoint['state_json'],'stage':'published'},checkpoint)
        TaskExecutionStore(config=self.store.config,directory=self.assets.directory)._finish(db,task,'succeeded',None)
        return TaskStore.public_task(task)


def governed_content(assets, metadata, *, collection=False):
    """Resolve the old report ID through a trusted association, never JSON keys."""
    service = StatisticsLegacyReportService(assets)
    with service.store.connection() as db:
        column = 'collection_report_id' if collection else 'report_id'
        binding = db.execute(f'SELECT * FROM {TABLE} WHERE {column}=%s AND user_id=%s', (metadata['id'],service.store.user_id)).fetchone()
        if not binding:
            raise invalid()
        task = service.store.require_task(db,binding['task_id'])
        service.association(db,task)
        if task['status']!='succeeded':
            raise invalid('research_source_incomplete',422)
        row=service.require(db,'research_report_versions',binding['project_id'],binding['report_version_id'])
        _,members=service.checked_members(db,binding['project_id'],row)
        member=next(m for m in members if m['role']=='docx')
        if any(metadata[k]!=member[k] for k in ('sha256','size_bytes')):
            raise invalid()
    return service.member(binding['project_id'],binding['report_version_id'],member['id'])[1]


def audit_task(db,task):
    from app.adapters.task_store import DatasetTaskAssets
    from app.core.config import get_data_dir
    service=StatisticsLegacyReportService(DatasetTaskAssets(task['user_id'],db.config,get_data_dir()))
    binding=service.association(db,task)
    service.require_sources(db,task)
    cp=db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()
    if not cp or cp['state_json']['input_version']!=input_identity(task):raise invalid()
    row=service.require(db,'research_report_versions',task['project_id'],binding['report_version_id'])
    if task['status']=='succeeded':
        if cp['next_node']!='done' or (not binding['report_id'] and not binding['collection_report_id']):raise invalid()
        if task['task_type']=='word_report' and task['result_report_id']!=binding['report_id']:raise invalid()
        if task.get('result_research_report_version_id'):raise invalid()
        service.checked_members(db,task['project_id'],row)
    return row


def dispatch(task_id, task_revision, repository, **kwargs):
    with repository.connection() as db:
        task=db.execute('SELECT * FROM tasks WHERE id=%s',(task_id,)).fetchone()
        if not task or not is_reader_export(task):
            return False, None
    from app.domain.research_results.execution import run_research_task
    from .validation import worker_verification
    with worker_verification():
        return True, run_research_task(task_id,task_revision,task_type=task['task_type'],
            config=repository.config,directory=repository.assets.directory,**kwargs)
