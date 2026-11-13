"""Register selected native Word and PNG bytes for the existing delivery snapshot."""

from dataclasses import dataclass
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from psycopg.types.json import Jsonb

from app.adapters.research_results_store import invalid, now
from app.core.exceptions import StorageError
from app.domain.bioinformatics.contracts import digest
from app.domain.research_intake.service import request_key
from app.domain.storage_governance import local_candidates
from app.domain.storage_governance.guards import require_scope_open
from app.domain.storage_governance.service import publish_candidate

from .contracts import MAX_DELIVERY_BYTES
from .reader_files import native_filename


@dataclass(frozen=True)
class NativeArtifact:
    filename: str
    format: str
    content: bytes
    sha256: str
    provenance: dict


def artifact_provenance(db, project_id, file):
    row = db.execute('''SELECT actor_id, provenance_json, provenance_sha256 FROM delivery_artifact_sources
        WHERE project_id=%s AND file_id=%s''', (project_id, file['id'])).fetchone()
    if row is None:
        return None
    proof = row['provenance_json']
    if (digest(proof) != row['provenance_sha256'] or proof.get('schema_version') != 1
            or proof.get('file_sha256') != file['sha256'] or proof.get('format') != file['file_type']
            or row['actor_id'] != file['upload_actor_id']):
        raise invalid()
    return proof


def _replayed(db, store, assignment, key, request_digest):
    row = db.execute('''SELECT f.*, a.request_digest FROM delivery_artifact_sources a
        JOIN files f ON f.id=a.file_id AND f.project_id=a.project_id
        WHERE a.project_id=%s AND a.actor_id=%s AND a.request_key=%s AND f.uploader_id=%s''',
        (assignment.project_id, assignment.analyst_id, key, assignment.owner_id)).fetchone()
    if row is None:
        return None
    if row['request_digest'] != request_digest:
        raise StorageError('research_request_conflict', '此请求标识已绑定其他交付来源。', 409)
    proof = artifact_provenance(db, assignment.project_id, row)
    store.objects.verify_original(dict(row))
    return dict(file_id=row['id'], filename=native_filename(proof), format=row['file_type'],
                sha256=row['sha256'], size_bytes=row['size_bytes'])


def _finish_capture(db, store, assignment, file_id, key, request_digest, candidate, capture, *, recover=False):
    proof = capture['provenance']
    file_type = proof['format']
    object_key = f'files/{file_id}.{file_type}'
    if (capture['actor_id'] != assignment.analyst_id or capture['assignment_revision'] != assignment.revision
            or file_type not in ('docx', 'png') or candidate['object_key'] != object_key
            or candidate['sha256'] != proof['file_sha256']):
        raise invalid()
    project_id = assignment.project_id
    require_scope_open(db, project_id, file_ids=proof['source_file_ids'])
    publish_candidate(db, store.directory, candidate['id'], explicit_recovery=recover)
    uploaded_at = now().isoformat()
    filename = capture['filename']
    size_bytes, file_sha256 = candidate['size_bytes'], candidate['sha256']
    db.execute('''INSERT INTO files(id, project_id, filename, file_type, size_bytes, sha256, uploaded_at,
        parse_status, uploader_id, upload_actor_id, storage_backend, object_key)
        VALUES (%s,%s,%s,%s,%s,%s,%s,'stored',%s,%s,%s,%s)''',
        (file_id, project_id, filename, file_type, size_bytes, file_sha256, uploaded_at,
         assignment.owner_id, assignment.analyst_id, store.objects.port.backend_name, object_key))
    db.execute('''INSERT INTO delivery_artifact_sources(file_id, project_id, actor_id, assignment_revision,
        request_key, request_digest, provenance_json, provenance_sha256) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',
        (file_id, project_id, assignment.analyst_id, assignment.revision,
         key, request_digest, Jsonb(proof), digest(proof)))
    db.execute('UPDATE projects SET updated_at=GREATEST(updated_at,%s) WHERE id=%s', (uploaded_at, project_id))
    return dict(file_id=file_id, filename=native_filename(proof), format=file_type, sha256=file_sha256, size_bytes=size_bytes), 201


def _resume(db, store, assignment, file_id, operation, key, request_digest):
    saved = _replayed(db, store, assignment, key, request_digest)
    if saved is not None:
        return (saved, 200), operation
    while True:
        candidate = local_candidates.lookup(db, store.directory, assignment.project_id, operation,
                                            kind='original', include_released=True)
        if candidate is None:
            return None, operation
        if candidate['candidate_json']['source_identity'] != request_digest:
            raise StorageError('research_request_conflict', '此请求标识已绑定其他交付来源。', 409)
        if candidate['state'] == 'released' or local_candidates.release_empty(db, store.directory, candidate):
            # Preserve the old journal and the request binding across attempts.
            operation = f"native-delivery-retry:{candidate['id']}"
            continue
        capture, _ = local_candidates.read(store.directory, candidate, request_digest)
        result = _finish_capture(db, store, assignment, file_id, key, request_digest, candidate, capture, recover=True)
        return result, operation


def save_native_artifact(store, project_id, request, key, load):
    assignment = store.assignment
    if assignment is None:
        raise StorageError('project_not_found', '项目不存在。', 404)
    assignment.require_project(project_id)
    if request.assignment_revision != assignment.revision:
        raise StorageError('project_assignment_stale', '项目分配已变更，请重新读取。', 409)
    request_key(key)
    request_digest = digest(request.model_dump(mode='json'))
    with store.connection() as db:
        saved = _replayed(db, store, assignment, key, request_digest)
    if saved is not None:
        return saved, 200

    operation = 'native-delivery:' + digest([project_id, assignment.owner_id, assignment.analyst_id, key])
    file_id = str(uuid5(NAMESPACE_URL, operation))
    # A completed capture can outlive a rolled-back business transaction. Look
    # for it under the writer fence before opening a disposable export cache.
    with store.connection(write=True) as db:
        resumed, operation = _resume(db, store, assignment, file_id, operation, key, request_digest)
        if resumed is not None:
            return resumed

    artifact = load()
    if len(artifact.content) > MAX_DELIVERY_BYTES:
        raise invalid('research_export_limit_exceeded', 422)
    if artifact.format not in ('docx', 'png') or not artifact.content or sha256(artifact.content).hexdigest() != artifact.sha256:
        raise invalid()
    proof = dict(artifact.provenance, schema_version=1, kind=request.kind,
                 file_sha256=artifact.sha256, format=artifact.format)
    capture = dict(actor_id=assignment.analyst_id, assignment_revision=assignment.revision,
                   filename=artifact.filename, provenance=proof)
    with store.connection(write=True) as db:
        resumed, operation = _resume(db, store, assignment, file_id, operation, key, request_digest)
        if resumed is not None:
            return resumed
        require_scope_open(db, project_id, file_ids=proof['source_file_ids'])
        target = store.files_dir / f'{file_id}.{artifact.format}'
        try:
            candidate = local_candidates.capture(db, store.directory, project_id, operation, target,
                                                 artifact.content, capture, source_identity=request_digest, kind='original')
        except OSError as exc:
            raise StorageError('storage_unavailable', '无法保存交付文件，请检查存储后重试。', 503) from exc
        return _finish_capture(db, store, assignment, file_id, key, request_digest, candidate, capture)


def single_cell_word(store, project, request):
    from app.adapters.single_cell_report import download_single_cell_report

    metadata, content = download_single_cell_report(store, project, request.version_id, request.annotation_version_id)
    filename = native_filename({**metadata['provenance'], 'kind': 'single_cell_word'})
    return NativeArtifact(filename, 'docx', content, metadata['sha256'], metadata['provenance'])


def _png_member(members, member_id, *, role=None):
    member = next((item for item in members if item['id'] == member_id), None)
    if member is None:
        raise invalid('research_source_not_found', 404)
    if member['format'] != 'png' or (role is not None and member.get('role') != role):
        raise invalid('research_source_unsupported', 422)
    if member['size_bytes'] > MAX_DELIVERY_BYTES:
        raise invalid('research_export_limit_exceeded', 422)
    return member


def _processed_png(store, project, request):
    from app.adapters.bio_analysis_store import BioAnalysisStore

    service = BioAnalysisStore(store)
    with service.store.connection() as db:
        row, manifest, members = service.processed_record(db, project, request.version_id)
        task = service.store.require_task(db, row['task_id'])
        if task['status'] != 'succeeded' or manifest.get('assay') != 'single_cell':
            raise invalid('research_source_unsupported', 422)
        member = _png_member(members, request.member_id, role='figure_png')
        raw_source = manifest.get('raw_source') or manifest['identity']['raw_source']
        provenance = dict(manifest_sha256=row['manifest_sha256'], source_file_ids=raw_source['source_file_ids'],
                          language=manifest.get('params', {}).get('output_language'))
        return member, service.objects.read(member), provenance


def _figure_png(store, project, request):
    from app.adapters.bio_figure_store import BioFigureStore

    service = BioFigureStore(store)
    figure = service.get(project, request.version_id)
    if figure['task']['status'] != 'succeeded' or not figure['manifest_sha256']:
        raise invalid('research_source_incomplete', 422)
    member = _png_member(figure['members'], request.member_id)
    _, content = service.member(project, request.version_id, request.member_id)
    provenance = dict(manifest_sha256=figure['manifest_sha256'],
                      source_file_ids=figure['processed_source']['raw_source']['source_file_ids'],
                      language=figure['config'].get('output_language'), figure_kind=figure['config']['kind'])
    return member, content, provenance


def _insight_png(store, project, request):
    from app.domain.bio_insights.results import BioInsightResultService
    from app.domain.research_results.sources import ResearchSourceReader

    source = ResearchSourceReader(store).read_source(project, {
        'source_kind': 'bio_insight_result_version', 'source_id': request.version_id, 'locator': {'kind': 'object'},
    })
    member = _png_member(source.content['members'], request.member_id, role='figure')
    _, content = BioInsightResultService(store).member(project, request.version_id, request.member_id)
    provenance = dict(manifest_sha256=source.sha256, source_file_ids=source.source_file_ids,
                      language=source.content['config'].get('output_language'),
                      figure_kind=source.content['config'].get('figure_type'))
    return member, content, provenance


def native_png(store, project, request):
    load = {'single_cell_png': _processed_png, 'bio_figure_png': _figure_png, 'bio_insight_png': _insight_png}[request.kind]
    member, content, provenance = load(store, project, request)
    if not content.startswith(b'\x89PNG\r\n\x1a\n'):
        raise invalid('research_output_invalid', 422)
    provenance.update(version_id=request.version_id, member_id=request.member_id, member_key=member['key'])
    filename = native_filename({**provenance, 'kind': request.kind})
    return NativeArtifact(filename, 'png', content, member['sha256'], provenance)
