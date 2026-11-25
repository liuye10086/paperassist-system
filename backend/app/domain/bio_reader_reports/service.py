"""Atomic preparation of immutable native report selection and ordinary finding."""
from copy import deepcopy
import hashlib

from app.adapters.bio_analysis_store import scoped_object
from app.adapters.research_results_store import ResearchResultsStore, base, identity, insert, invalid
from app.domain.bioinformatics.contracts import digest
from app.domain.dataset_preparation.service import require_key
from app.domain.research_results.contracts import FindingVersionRequest, ResearchReportRequest
from app.domain.research_results.findings import ResearchFindingService
from app.domain.research_results.frozen_projection import matches_frozen_source
from app.domain.source_byte_verification import VerificationPhase

from .contracts import BioReportPrepareRequest
from .materials import annotation_identity, prepare_material, tsv


class BioReaderReportService(ResearchResultsStore):
    @staticmethod
    def fixed_figures(content):
        keys = ('id', 'native_source', 'manifest_sha256', 'config', 'document_image')
        return [{key: deepcopy(figure[key]) for key in keys} for figure in content['figures']]

    def prepare(self, project, request, key):
        require_key(key)
        request = BioReportPrepareRequest.model_validate(request)
        body_sha = digest(request.model_dump(mode='json'))
        with self.store.connection(write=True) as db:
            self.lock(db, project, 'bio-report-request:' + key)
            receipt = self._receipt(db, project, key)
            if receipt:
                if receipt['request_digest'] != body_sha:
                    raise invalid('research_idempotency_conflict')
                return self._view(db, project, receipt['context_id'], receipt['finding_version_id']), 200
            content = prepare_material(self.assets, db, project, request)
            sha = digest(content)
            self.lock(db, project, 'bio-report-content:' + sha)
            existing = db.execute('SELECT id FROM bio_report_context_versions WHERE project_id=%s AND user_id=%s AND content_sha256=%s', (project, self.store.user_id, sha)).fetchone()
            context_id = existing['id'] if existing else identity(project, 'bio-report-context', sha)
            if not existing:
                from app.domain.storage_governance.guards import require_scope_open
                require_scope_open(db, project, file_ids=set(content['source_file_ids']))
                insert(db, 'bio_report_context_versions', {**base(context_id, project, self.store.user_id), 'content_sha256': sha, 'content_json': content})
                for fid in content['source_file_ids']:
                    file = db.execute('SELECT id,sha256 FROM files WHERE id=%s AND project_id=%s', (fid, project)).fetchone()
                    if not file:
                        raise invalid()
                    insert(db, 'bio_report_context_files', dict(id=identity(project, 'bio-report-file', context_id + ':' + fid),
                        context_id=context_id, project_id=project, user_id=self.store.user_id, file_id=fid, sha256=file['sha256']))
            # This internal entry keeps the existing finding validation/binding
            # logic and puts context + protected files + finding + receipt in
            # one transaction. Failure leaves no durable half-success.
            finding, _ = ResearchFindingService(self.assets)._create_in_transaction(db, project,
                FindingVersionRequest(title=request.title, sources=[dict(source_kind='bio_report_context', source_id=context_id, sha256=sha)]),
                'bio-report:' + context_id)
            insert(db, 'bio_report_context_requests', dict(id=identity(project, 'bio-report-request', key),
                context_id=context_id, project_id=project, user_id=self.store.user_id, request_key=key,
                request_digest=body_sha, finding_version_id=finding['id']))
            return self._view(db, project, context_id, finding['id']), 200 if existing else 201

    def _receipt(self, db, project, key):
        self.store.require_project(db, project)
        return db.execute('SELECT * FROM bio_report_context_requests WHERE project_id=%s AND user_id=%s AND request_key=%s', (project, self.store.user_id, key)).fetchone()

    def request_receipt(self, project, key):
        require_key(key)
        with self.store.connection() as db:
            row = self._receipt(db, project, key)
            if not row:
                raise invalid('research_source_not_found', 404)
            return self._view(db, project, row['context_id'], row['finding_version_id'])

    def get(self, project, context_id):
        with self.store.connection() as db:
            self.require(db, 'bio_report_context_versions', project, context_id)
            receipt = db.execute('SELECT finding_version_id FROM bio_report_context_requests WHERE context_id=%s AND project_id=%s AND user_id=%s ORDER BY id LIMIT 1', (context_id, project, self.store.user_id)).fetchone()
            if not receipt:
                raise invalid('research_source_incomplete', 422)
            return self._view(db, project, context_id, receipt['finding_version_id'])

    def _view(self, db, project, context_id, finding_id):
        with VerificationPhase(db, self.assets, project) as phase:
            row, content = self.checked(db, project, context_id, phase=phase)
        finding = self.require(db, 'research_finding_versions', project, finding_id)
        sources = self.verify_content(finding)['sources']
        if len(sources) != 1 or sources[0]['source_kind'] != 'bio_report_context' or sources[0]['source_id'] != context_id or sources[0]['sha256'] != row['content_sha256']:
            raise invalid()
        return dict(id=context_id, selection=deepcopy(content['selection']), language=content['language'], title=content['title'],
            report=ResearchReportRequest(title=content['title'], language=content['language'], finding_version_id=finding_id, figure_version_ids=[]).model_dump(mode='json'),
            source=dict(source_kind='bio_report_context', source_id=context_id, sha256=row['content_sha256'],
                        selection=deepcopy(content['selection']), supporting_sources=deepcopy(content['supporting_sources'])),
            **({'workbook_limited': True} if content.get('workbook_limited') else {}))

    def checked(self, db, project, identifier, *, phase, progress=None):
        from app.domain.research_results.sources import ResearchSourceReader
        row = self.require(db, 'bio_report_context_versions', project, identifier)
        content = self.verify_content(row)
        files = db.execute('SELECT r.*,f.sha256 AS current_sha256 FROM bio_report_context_files r JOIN files f ON f.id=r.file_id AND f.project_id=r.project_id WHERE r.context_id=%s AND r.project_id=%s AND r.user_id=%s ORDER BY r.file_id', (identifier, project, self.store.user_id)).fetchall()
        if [value['file_id'] for value in files] != content['source_file_ids'] or any(value['sha256'] != value['current_sha256'] for value in files):
            raise invalid()
        reader = ResearchSourceReader(self.assets, allow_stale_labels=True)
        for source in content['sources']:
            selected = {key: source[key] for key in ('source_kind', 'source_id', 'sha256', 'locator')}
            current = reader._read_source_in_phase(project, selected, db=db, phase=phase, progress=progress)
            if not matches_frozen_source(current.model_dump(mode='json'), source):
                raise invalid()
        if content.get('annotation'):
            self.annotation_view(db, project, content['annotation'])
        for blob in [*content['table_blobs'], *(figure['blob'] for figure in content['figures'])]:
            self.read_blob(db, project, blob)
        return row, content

    def annotation_view(self, db, project, fixed):
        from app.adapters.bio_annotation_store import BioAnnotationStore
        service = BioAnnotationStore(self.assets)
        row = service.require(db, 'bio_annotation_versions', project, fixed['version_id'])
        current = service.get(project, row['set_id'], row['id'])
        current.pop('is_current', None)
        if annotation_identity(current, row) != fixed:
            raise invalid()
        return current

    def read_blob(self, db, project, blob):
        if 'projection' in blob:
            projection = blob['projection']
            if projection['kind'] == 'annotation':
                view = self.annotation_view(db, project, projection['annotation'])
                raw = tsv(view[projection['field']], projection['columns'])
            elif projection['kind'] == 'bulk_selection':
                from .bulk import selected_rows
                raw = tsv(selected_rows(self.read_blob(db, project, projection['source_blob']), projection['selection']), projection['columns'])
            else:
                raise invalid()
        elif 'generated' in blob:
            raw = tsv(**blob['generated'])
        else:
            from app.adapters.bio_objects import BioAnalysisObjects, BioAnnotationObjects, BioFigureObjects, BioObjects
            from app.adapters.bio_insights_store import BioInsightsObjects
            obj = scoped_object(db, project, self.store.user_id, blob['object_id'])
            if any(obj[key] != blob[key] for key in ('sha256', 'size_bytes')):
                raise invalid()
            objects = next((cls for cls in (BioAnalysisObjects, BioAnnotationObjects, BioFigureObjects, BioInsightsObjects, BioObjects) if obj['object_key'].startswith(cls.prefix + '/')), None)
            if objects is None:
                raise invalid()
            raw = objects(self.assets.directory).read(obj)
        if len(raw) != blob['size_bytes'] or hashlib.sha256(raw).hexdigest() != blob['sha256']:
            raise invalid()
        return raw

    def source_value(self, db, project, identifier, *, phase, progress=None):
        row, content = self.checked(db, project, identifier, phase=phase, progress=progress)
        scientific = deepcopy(content['scientific'])
        scientific.update(facts=content['facts'], methods=content['methods'], limitations=content['limitations'],
                          warnings=content['warnings'], gaps=content['gaps'], context_id=identifier)
        if content.get('workbook_limit_notice'):
            notice = content['workbook_limit_notice'][content['language']]
            scientific['workbook_limit_notice'] = notice
            # Use a reader-visible scope list without exceeding the fact catalog bound.
            for field in ('warnings', 'limitations', 'gaps'):
                if len(scientific[field]) < 100:
                    scientific[field] = [*scientific[field], notice]
                    break
        return dict(title=content['title'], sha256=row['content_sha256'], provenance='research_derived',
                    source_file_ids=content['source_file_ids'], content=scientific)

    def export_material(self, db, project, identifier, *, phase, progress=None):
        _, content = self.checked(db, project, identifier, phase=phase, progress=progress)
        images, files = [], []
        for ordinal, figure in enumerate(content['figures'], 1):
            raw = self.read_blob(db, project, figure['blob'])
            images.append(dict(config=deepcopy(figure['config']), raw=raw, format=figure['document_image']['format'], caption_facts=deepcopy(figure['caption_facts'])))
            files.append(dict(name=f'figures/figure_{ordinal:02d}/' + figure['document_image']['key'] + '.' + figure['document_image']['format'], raw=raw))
        return dict(language=content['language'], figures=self.fixed_figures(content), images=images, files=files, tables=deepcopy(content['tables']),
                    table_raws=[self.read_blob(db, project, blob) for blob in content['table_blobs']])
