"""Persist and revalidate exact statistics selections and their prepare receipts."""
import hashlib
import json

from app.adapters.collection_store import CollectionStore
from app.adapters.research_results_store import ResearchResultsStore, base, identity, insert, invalid
from app.adapters.storage import ProjectStore
from app.domain.artifact_contracts import artifact_language
from app.domain.bioinformatics.contracts import digest
from app.domain.dataset_preparation.service import require_key
from app.domain.research_results.contracts import FindingVersionRequest, ResearchReportRequest
from app.domain.research_results.findings import ResearchFindingService
from app.domain.research_results.sources import ResearchSourceReader
from app.domain.source_byte_verification import VerificationPhase, phase_guard, require_phase
from app.domain.storage_governance.guards import require_scope_open

from .contracts import AnalysisSelection, StatisticsReportPrepareRequest
from .materials import assemble_statistics_material
from .narrative import ADAPTER_VERSION, ORIGIN

KIND = 'statistics_report_context'
VERSIONS = 'statistics_report_context_versions'
FILES = 'statistics_report_context_files'
ITEMS = 'statistics_report_context_items'
REQUESTS = 'statistics_report_context_requests'


class StatisticsReaderReportService(ResearchResultsStore):
    def __init__(self, assets):
        super().__init__(assets)
        if isinstance(assets, ProjectStore):
            self.plots = assets
        else:
            from app.domain.report_collections.service import scoped_store
            self.plots = scoped_store(assets.owner_id, assets.db_config, assets.directory)

    def _analysis_item(self, db, project, selection, source):
        result = source.content['result']
        if result['file_id'] != selection.file_id:
            raise invalid('research_source_not_found', 404)
        if selection.figure_id is None:
            return dict(result=result, figure=None, explanation=None)
        saved = db.execute('SELECT * FROM figures WHERE id=%s AND analysis_run_id=%s',
                           (selection.figure_id, selection.analysis_run_id)).fetchone()
        if not saved:
            raise invalid('research_source_not_found', 404)
        if saved['figure_config_version_id'] is not None:
            from app.adapters.figure_workbench_store import read_bundle
            bundle = read_bundle(self.plots, project, selection.figure_id, selection.explanation_id)
            if (bundle['result'] != result or bundle['figure']['id'] != selection.figure_id
                    or (bundle['explanation'] or {}).get('id') != selection.explanation_id):
                raise invalid()
            return bundle

        row = db.execute('SELECT * FROM explanations WHERE id=%s AND analysis_run_id=%s AND figure_id=%s',
                         (selection.explanation_id, selection.analysis_run_id, selection.figure_id)).fetchone()
        if not row:
            raise invalid('research_source_not_found', 404)
        figure = json.loads(saved['figure_json'])
        explanation = json.loads(row['explanation_json'])
        if (figure.get('id') != saved['id'] or figure.get('engine', {}).get('id') != saved['renderer_version']
                or explanation.get('id') != row['id'] or explanation.get('engine', {}).get('id') != row['engine_version']):
            raise invalid()
        from app.domain.reports import validate_sources
        validate_sources(result, figure, explanation)
        return dict(result=result, figure=figure, explanation=explanation)

    def _collection_items(self, db, project, selection, language):
        repository = CollectionStore(self.plots)
        repository.require_collection(db, project, selection.collection_id)
        version = db.execute('SELECT * FROM report_collection_versions WHERE id=%s AND collection_id=%s',
                             (selection.collection_version_id, selection.collection_id)).fetchone()
        if not version:
            raise invalid('research_source_not_found', 404)
        if version['language'] != language:
            raise invalid('research_source_conflict', 422)
        snapshot = repository.resolve_snapshot(db, project, version['id'])
        if not snapshot['ready']:
            raise invalid('research_source_incomplete', 422)
        return snapshot['items'], version['sha256']

    def _build(self, db, project, request, *, phase, progress=None):
        require_phase(phase, db, self.assets, project)
        self.store.require_project(db, project)
        reader = ResearchSourceReader(self.assets)
        selection = request.selection

        def read_result(run_id):
            return reader._read_source_in_phase(
                project, dict(source_kind='analysis_run', source_id=run_id), db=db, phase=phase, progress=progress)

        if isinstance(selection, AnalysisSelection):
            sources = [read_result(selection.analysis_run_id)]
            items = [self._analysis_item(db, project, selection, sources[0])]
            collection_sha = None
        else:
            items, collection_sha = self._collection_items(db, project, selection, request.language)
            sources = [read_result(identifier) for identifier in dict.fromkeys(item['result']['id'] for item in items)]
        for item in items:
            if progress:
                progress()
            figure, explanation = item.get('figure'), item.get('explanation')
            if (artifact_language(item['result']) != request.language
                    or figure and figure.get('language', artifact_language(item['result'])) != request.language
                    or explanation and explanation['language'] != request.language):
                raise invalid('research_source_conflict', 422)
        pngs = [self.plots.figure_png(item['figure']) for item in items if item.get('figure')]
        material = assemble_statistics_material(title=request.title, language=request.language, sources=sources, items=items, pngs=pngs)
        anchors = []
        file_shas = {}
        for index, item in enumerate(items, 1):
            result = item['result']
            file_shas[result['file_id']] = result['source_sha256']
            anchors.append(dict(position=index, file_id=result['file_id'], analysis_run_id=result['id'],
                                figure_id=(item.get('figure') or {}).get('id'),
                                explanation_id=(item.get('explanation') or {}).get('id')))
        # Full TSVs and original PNG remain separate bytes. The context binds
        # their identities and the exact order without duplicating raw rows.
        file_ids = sorted(file_shas)
        available = material['local_output'] is not None
        reuse = dict(available=available, origin=ORIGIN if available else None, adapter_version=ADAPTER_VERSION,
                     gaps=material['overview']['gaps'])
        content = dict(schema_version=1, title=request.title, language=request.language,
                       selection=selection.model_dump(mode='json'), collection_sha256=collection_sha,
                       source_file_ids=file_ids, source_file_shas=file_shas, anchors=anchors,
                       runs=[dict(id=source.source_id, sha256=source.sha256,
                                  execution_verification=source.content['execution_verification']) for source in sources],
                       figures=material['figures'], tables=material['tables'], overview=material['overview'],
                       local_reuse=reuse, local_output_sha256=digest(material['local_output']) if available else None,
                       supporting_files=[dict(name=item['name'], sha256=hashlib.sha256(item['raw']).hexdigest())
                                         for item in material['files']])
        return content, material

    def _receipt(self, db, project, key):
        self.store.require_project(db, project)
        return db.execute(f'SELECT * FROM {REQUESTS} WHERE project_id=%s AND user_id=%s AND request_key=%s',
                          (project, self.store.user_id, key)).fetchone()

    def prepare(self, project, request, key):
        with self.store.connection(write=True) as db:
            return self.prepare_in_transaction(db, project, request, key)

    def prepare_in_transaction(self, db, project, request, key):
        require_key(key)
        request = StatisticsReportPrepareRequest.model_validate(request)
        request_sha = digest(request.model_dump(mode='json'))
        self.lock(db, project, 'statistics-reader-request:' + key)
        receipt = self._receipt(db, project, key)
        if receipt:
            if receipt['request_digest'] != request_sha:
                raise invalid('research_idempotency_conflict')
            return self._view(db, project, receipt['context_id'], receipt['finding_version_id']), 200
        with VerificationPhase(db, self.assets, project) as phase:
            content, _ = self._build(db, project, request, phase=phase)
        require_scope_open(db, project, file_ids=set(content['source_file_ids']))
        sha = digest(content)
        self.lock(db, project, 'statistics-reader-context:' + sha)
        context_id = identity(project, KIND, sha)
        existing = db.execute(f'SELECT id FROM {VERSIONS} WHERE project_id=%s AND user_id=%s AND content_sha256=%s',
                              (project, self.store.user_id, sha)).fetchone()
        if not existing:
            binding = {key: content['selection'].get(key) for key in ('collection_id', 'collection_version_id')}
            insert(db, VERSIONS, dict(base(context_id, project, self.store.user_id), **binding,
                                      content_json=content, content_sha256=sha))
            scope = dict(context_id=context_id, project_id=project, user_id=self.store.user_id)
            for file_id, file_sha in content['source_file_shas'].items():
                insert(db, FILES, dict(id=identity(project, 'statistics-reader-file', f'{context_id}:{file_id}'),
                                      **scope, file_id=file_id, sha256=file_sha))
            for anchor in content['anchors']:
                insert(db, ITEMS, dict(id=identity(project, 'statistics-reader-item', f"{context_id}:{anchor['position']}"),
                                      **scope, **anchor))
        elif existing['id'] != context_id:
            raise invalid()
        finding, _ = ResearchFindingService(self.assets)._create_in_transaction(
            db, project, FindingVersionRequest(title=request.title, sources=[dict(source_kind=KIND, source_id=context_id, sha256=sha)]),
            'statistics-reader:' + context_id)
        insert(db, REQUESTS, dict(id=identity(project, 'statistics-reader-request', key), project_id=project,
                                 user_id=self.store.user_id, context_id=context_id, request_key=key,
                                 request_digest=request_sha, finding_version_id=finding['id']))
        return self._view(db, project, context_id, finding['id']), 200 if existing else 201

    def request_receipt(self, project, key):
        require_key(key)
        with self.store.connection() as db:
            receipt = self._receipt(db, project, key)
            if not receipt:
                raise invalid('research_source_not_found', 404)
            return self._view(db, project, receipt['context_id'], receipt['finding_version_id'])

    def get(self, project, context_id):
        with self.store.connection() as db:
            self.require(db, VERSIONS, project, context_id)
            receipt = db.execute(f'SELECT finding_version_id FROM {REQUESTS} WHERE context_id=%s AND project_id=%s AND user_id=%s '
                                 'ORDER BY id LIMIT 1', (context_id, project, self.store.user_id)).fetchone()
            if not receipt:
                raise invalid('research_source_incomplete', 422)
            return self._view(db, project, context_id, receipt['finding_version_id'])

    def _view(self, db, project, context_id, finding_id):
        with VerificationPhase(db, self.assets, project) as phase:
            row, content, _ = self.checked(db, project, context_id, phase=phase)
        finding = self.require(db, 'research_finding_versions', project, finding_id)
        sources = self.verify_content(finding)['sources']
        if len(sources) != 1 or any(sources[0].get(key) != value for key, value in (
                ('source_kind', KIND), ('source_id', context_id), ('sha256', row['content_sha256']))):
            raise invalid()
        return dict(id=context_id, title=content['title'], language=content['language'], selection=content['selection'],
                    local_reuse=content['local_reuse'],
                    report=ResearchReportRequest(title=content['title'], language=content['language'],
                                                 finding_version_id=finding_id).model_dump(mode='json'),
                    source=dict(source_kind=KIND, source_id=context_id, sha256=row['content_sha256'],
                                supporting_sources=content['runs']))

    @phase_guard
    def checked(self, db, project, identifier, *, phase, progress=None):
        row = self.require(db, VERSIONS, project, identifier)
        content = self.verify_content(row)
        request = StatisticsReportPrepareRequest.model_validate({key: content[key] for key in ('title', 'language', 'selection')})
        if any(row[key] != content['selection'].get(key) for key in ('collection_id', 'collection_version_id')):
            raise invalid()
        parameters = (identifier, project, self.store.user_id)
        files = db.execute(f'''SELECT r.file_id,r.sha256,f.sha256 AS current_sha256 FROM {FILES} r
            JOIN files f ON f.id=r.file_id AND f.project_id=r.project_id
            WHERE r.context_id=%s AND r.project_id=%s AND r.user_id=%s ORDER BY r.file_id''', parameters).fetchall()
        if ([edge['file_id'] for edge in files] != content['source_file_ids']
                or any(edge['current_sha256'] != edge['sha256'] or edge['sha256'] != content['source_file_shas'][edge['file_id']]
                       for edge in files)):
            raise invalid()
        anchors = db.execute(f'''SELECT position,file_id,analysis_run_id,figure_id,explanation_id FROM {ITEMS}
            WHERE context_id=%s AND project_id=%s AND user_id=%s ORDER BY position''', parameters).fetchall()
        if [dict(anchor) for anchor in anchors] != content['anchors']:
            raise invalid()
        rebuilt, material = self._build(db, project, request, phase=phase, progress=progress)
        if rebuilt != content:
            raise invalid()
        return row, content, material

    def source_value(self, db, project, identifier, *, phase, progress=None):
        row, content, _ = self.checked(db, project, identifier, phase=phase, progress=progress)
        return dict(title=content['title'], sha256=row['content_sha256'], provenance='research_derived',
                    source_file_ids=content['source_file_ids'],
                    content=dict(content['overview'], language=content['language'], selection=content['selection']))

    def export_material(self, db, project, identifier, *, phase, progress=None):
        _, _, material = self.checked(db, project, identifier, phase=phase, progress=progress)
        return material

    def prepared_finding(self, db, project, identifier, finding_id):
        return db.execute(f'''SELECT 1 FROM {REQUESTS} WHERE context_id=%s AND project_id=%s AND user_id=%s
            AND finding_version_id=%s LIMIT 1''', (identifier, project, self.store.user_id, finding_id)).fetchone() is not None
