"""Project-scoped Bulk workflow, sensitivity review and frozen delivery."""
import tempfile
import json
import os
from typing import Literal
from urllib.parse import quote

from app.domain.bio_insights.bulk_delivery_cache import cache_for, heavy_slot
from app.domain.bioinformatics.contracts import digest

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from app.adapters.bio_insights_store import invalid
from app.api.bio_datasets import Store
from app.domain.bio_insights.bulk_delivery_contracts import BulkDeliveryRequest, BulkDownloadRequest, BulkSensitivityQuery

router = APIRouter(prefix='/api/v1/projects/{project_id}/bulk-workflow', tags=['Bulk RNA-seq 流程与交付'])
WORD_MEDIA_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'


@router.get('')
def overview(project_id: str, store: Store):
    from app.domain.bio_insights.bulk_workflow import BulkWorkflowService

    return BulkWorkflowService(store).overview(project_id)


def sensitivity_for(service, project, request, **options):
    return service.sensitivity(project, request.baseline_version_id, request.scenario_version_id,
                               request.baseline_selection, request.scenario_selection, **options)


@router.post('/sensitivity')
def review_sensitivity(project_id: str, request: BulkSensitivityQuery, store: Store):
    from app.domain.bio_insights.bulk_workflow import BulkWorkflowService

    return sensitivity_for(BulkWorkflowService(store), project_id, request, page=request.page, page_size=request.page_size)


def resolve_delivery(project, store, request, *, change_stream=None):
    from app.domain.bio_insights.bulk_delivery import BulkDeliveryService
    from app.domain.bio_insights.bulk_workflow import BulkWorkflowService

    service = BulkDeliveryService(store)
    with service.store.connection() as db:
        identities = [service.require(db, 'bio_insight_result_versions', project, identifier)['manifest_sha256']
                      for identifier in (request.comparison_version_id, *request.result_version_ids)]
    cache = cache_for(store, project, "facts")
    key = digest([request.model_dump(mode="json", exclude={"facts_digest"}), identities])
    cached = cache.read(key)
    previous = json.loads((cached["path"] / "facts.json").read_text(encoding="utf-8")) if cached else None
    workflow = BulkWorkflowService(store)
    sensitivity = None
    if request.sensitivity:
        result = sensitivity_for(workflow, project, request.sensitivity, page_size=20, change_stream=change_stream)
        sensitivity = {key: value for key, value in result.items() if key not in ('page', 'page_size')}
    evidence = workflow.evidence(project, [entry.model_dump() for entry in request.evidence],
                                 baseline_version_id=request.comparison_version_id) if request.evidence else []
    facts = service.facts(project, request.comparison_version_id, result_version_ids=request.result_version_ids,
                          selections=request.selections, language=request.language, sensitivity=sensitivity, evidence=evidence, cached_facts=previous)
    def save(folder):
        (folder / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
        return {"facts_digest": facts["facts_digest"]}
    cache.obtain(key, save)
    return service, facts


def checked_facts(request, facts):
    if facts['facts_digest'] != request.facts_digest:
        raise invalid('bio_insight_source_conflict', 409)
    return facts


def delivery_headers(filename, facts):
    return {
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename, safe=''),
        'X-Bulk-Facts-SHA256': facts['facts_digest'],
        'Cache-Control': 'private, no-store',
        'X-Content-Type-Options': 'nosniff',
    }


@router.post('/delivery/preview')
def preview_delivery(project_id: str, request: BulkDeliveryRequest, store: Store):
    with heavy_slot(store, project_id):
        _, facts = resolve_delivery(project_id, store, request)
        return facts


def prepared_artifact(project, store, request, kind):
    """The caller holds the heavy slot through validation, publication and opening."""
    from app.domain.bio_insights.bulk_delivery_archive import BulkDeliveryArchive
    from app.adapters.bio_reader_narrative import load_bulk_cached_narrative

    service, facts = resolve_delivery(project, store, request)
    checked_facts(request, facts)
    narrative = load_bulk_cached_narrative(store.directory, project, facts['facts_digest'],
                                           'zh-CN' if facts['language'] == 'zh' else 'en')
    key = digest([facts['facts_digest'], narrative, 'reader-report'])
    def word(folder):
        (folder / 'payload').write_bytes(service.docx(project, facts, verified_contrasts=True))
        return dict(facts_digest=facts['facts_digest'], request=request.model_dump(mode='json'))
    word_entry = cache_for(store, project, 'word').obtain(key, word)
    if kind == 'word':
        return key, word_entry
    def archive(folder):
        with tempfile.TemporaryFile(mode='w+t', encoding='utf-8', newline='') as changes:
            if request.sensitivity:
                from app.domain.bio_insights.bulk_workflow import BulkWorkflowService
                sensitivity_for(BulkWorkflowService(store), project, request.sensitivity, page_size=20, change_stream=changes)
                changes.flush()
                changes.seek(0)
            package = BulkDeliveryArchive(store).export_delivery(project, facts,
                fixed_word.read(), change_table=changes.buffer if request.sensitivity else None,
                destination=folder / 'payload')
            package['file'].close()
        return dict(facts_digest=facts['facts_digest'], request=request.model_dump(mode='json'),
                    manifest_sha256=package['manifest_sha256'], analysis_inputs_self_contained=package['analysis_inputs_self_contained'])
    # A generation can expire while sensitivity or ZIP assembly is running.
    # Keep its file descriptor alive through cache eviction on both Windows and POSIX.
    with open_artifact(word_entry) as fixed_word:
        return key, cache_for(store, project, 'archive').obtain(key, archive)


def open_artifact(entry):
    try:
        return (entry['path'] / 'payload').open('rb')
    except OSError as exc:
        raise invalid('bio_insight_source_incomplete', 410) from exc


def artifact_response(entry, kind, *, handle=None):
    metadata = entry['metadata']
    headers = delivery_headers('转录组学分析报告.docx' if kind == 'word' else '转录组学分析复现资料.zip', metadata)
    if kind == 'archive':
        headers['X-Reproducibility-Manifest-SHA256'] = metadata['manifest_sha256']
        headers['X-Analysis-Inputs-Self-Contained'] = str(metadata['analysis_inputs_self_contained']).lower()
    handle = handle or open_artifact(entry)
    headers['Content-Length'] = str(os.fstat(handle.fileno()).st_size)
    def chunks():
        try:
            while block := handle.read(1024**2):
                yield block
        finally:
            handle.close()
    return StreamingResponse(chunks(), media_type=WORD_MEDIA_TYPE if kind == 'word' else 'application/zip',
                             headers=headers, background=BackgroundTask(handle.close))


@router.post('/delivery/report.docx')
def download_report(project_id: str, request: BulkDownloadRequest, store: Store):
    with heavy_slot(store, project_id):
        _, entry = prepared_artifact(project_id, store, request, 'word')
        return artifact_response(entry, 'word')


@router.post('/delivery/reproducibility-package')
def download_archive(project_id: str, request: BulkDownloadRequest, store: Store):
    with heavy_slot(store, project_id):
        _, entry = prepared_artifact(project_id, store, request, 'archive')
        return artifact_response(entry, 'archive')


@router.post('/delivery/prepare/{kind}')
def prepare_download(project_id: str, kind: Literal['word', 'archive'], request: BulkDownloadRequest, store: Store):
    with heavy_slot(store, project_id):
        key, entry = prepared_artifact(project_id, store, request, kind)
        return dict(artifact_id=key, download_url=f'/api/v1/projects/{project_id}/bulk-workflow/delivery/prepared/{kind}/{key}',
                    facts_digest=entry['metadata']['facts_digest'])


def read_prepared_artifact(project, kind, artifact_id, store):
    entry = cache_for(store, project, kind).read(artifact_id)
    if entry is None:
        raise invalid('bio_insight_source_incomplete', 410)
    handle = open_artifact(entry)
    try:
        request = BulkDownloadRequest.model_validate(entry['metadata']['request'])
        _, facts = resolve_delivery(project, store, request)
        checked_facts(request, facts)
        return entry, handle, facts
    except BaseException:
        handle.close()
        raise


@router.get('/delivery/prepared/{kind}/{artifact_id}')
def download_prepared(project_id: str, kind: Literal['word', 'archive'], artifact_id: str, store: Store):
    with heavy_slot(store, project_id):
        entry, handle, _ = read_prepared_artifact(project_id, kind, artifact_id, store)
        try:
            return artifact_response(entry, kind, handle=handle)
        except BaseException:
            handle.close()
            raise


def prepared_word_for_delivery(project, store, artifact_id, facts_digest):
    from hashlib import sha256

    from app.adapters.research_results_store import invalid as delivery_error
    from app.domain.delivery_packages.contracts import MAX_DELIVERY_BYTES
    from app.domain.delivery_packages.native_artifacts import NativeArtifact
    from app.domain.delivery_packages.reader_files import native_filename

    with heavy_slot(store, project):
        _, handle, facts = read_prepared_artifact(project, 'word', artifact_id, store)
        with handle:
            if facts['facts_digest'] != facts_digest:
                raise invalid('bio_insight_source_conflict', 409)
            if os.fstat(handle.fileno()).st_size > MAX_DELIVERY_BYTES:
                raise delivery_error('research_export_limit_exceeded', 422)
            content = handle.read(MAX_DELIVERY_BYTES + 1)

    comparison = facts['references']['comparison']
    related = {family: [dict(version_id=row['version_id'], manifest_sha256=row['manifest_sha256'])
                        for row in facts['references'][family]]
               for family in ('processed', 'results', 'resources')}
    source_files = {row['id'] for row in facts['qc']['input_files']}
    source_files.update(item['source_id'] for item in facts['evidence'] if item['kind'] == 'experimental_material')
    provenance = dict(version_id=comparison['version_id'], manifest_sha256=comparison['manifest_sha256'],
                      facts_digest=facts_digest, artifact_id=artifact_id,
                      language='zh-CN' if facts['language'] == 'zh' else 'en',
                      source_file_ids=sorted(source_files), references=related, limitations=facts['limitations'])
    filename = native_filename({'kind': 'bulk_word'})
    return NativeArtifact(filename, 'docx', content, sha256(content).hexdigest(), provenance)
