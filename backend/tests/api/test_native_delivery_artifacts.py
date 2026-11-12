"""Native RNA results use the same project-scoped freeze and publication path."""

from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.main import app
from tests.api.test_analyst_workspace import assign, freeze_body, upload_material
from tests.api.test_customer_workspace import create_customer_project, sign_in, write_requirements


def word_bytes(title):
    document = Document()
    document.add_paragraph(title)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def fail_receipt_once(monkeypatch):
    from app.core.exceptions import StorageError
    from app.db.database import DatabaseConnection

    original = DatabaseConnection.execute
    failures = []

    def execute(db, sql, parameters=()):
        if sql.startswith('INSERT INTO delivery_artifact_sources') and not failures:
            failures.append(True)
            raise StorageError('storage_unavailable', 'Synthetic failure after saving bytes.', 503)
        return original(db, sql, parameters)

    monkeypatch.setattr(DatabaseConnection, 'execute', execute)
    return failures


@pytest.fixture
def assigned_project():
    with TestClient(app) as customer, TestClient(app) as analyst, TestClient(app) as admin:
        sign_in(customer, 'rna-customer@workspace.test', 'customer')
        analyst_id = sign_in(analyst, 'rna-analyst@workspace.test', 'analyst')
        sign_in(admin, 'rna-admin@workspace.test', 'admin')
        project = create_customer_project(customer)
        file_id, _ = upload_material(customer, project)
        requirement = write_requirements(customer, project, 1, 'confirm')
        revision = assign(admin, project, analyst_id)
        yield SimpleNamespace(customer=customer, analyst=analyst, admin=admin, project=project,
                              file_id=file_id, requirement=requirement, revision=revision,
                              endpoint=project + '/analyst-workspace/delivery-artifacts')


def test_assigned_native_word_replays_and_publishes_the_saved_bytes(assigned_project, monkeypatch, tmp_path):
    from app.adapters import single_cell_report
    from app.core.config import get_data_dir
    from app.db.database import database_connection
    from app.domain.delivery_packages.service import run_delivery_package_task
    from app.domain.storage_governance.service import inventory, usage

    assigned = assigned_project
    raw = word_bytes('Synthetic single-cell results')
    rendered = raw
    source_sha = 'a' * 64
    renders = []

    def render(store, project, identifier, annotation_version_id=None):
        renders.append((project, identifier, annotation_version_id))
        assert identifier == 'processed'
        return dict(format='docx', filename='single-cell-analysis.docx', sha256=sha256(rendered).hexdigest(),
                    provenance=dict(version_id=identifier, manifest_sha256=source_sha, language='en',
                                    source_file_ids=[assigned.file_id])), rendered

    monkeypatch.setattr(single_cell_report, 'download_single_cell_report', render)
    body = dict(kind='single_cell_word', version_id='processed', assignment_revision=assigned.revision)
    headers = {'Idempotency-Key': 'save-single-cell-word'}
    assert assigned.customer.post(assigned.endpoint, json=body, headers=headers).status_code == 403
    failures = fail_receipt_once(monkeypatch)
    interrupted = assigned.analyst.post(assigned.endpoint, json=body, headers=headers)
    assert interrupted.status_code == 503 and failures == [True]
    assert [path.read_bytes() for path in (get_data_dir() / 'files').glob('*.docx')] == [raw]
    assert {file['id'] for file in assigned.analyst.get(assigned.project + '/files').json()} == {assigned.file_id}
    rendered = word_bytes('Changed overlays and narrative after the first write')
    conflicting = assigned.analyst.post(assigned.endpoint, headers=headers, json={
        **body, 'annotation_version_id': 'different',
    })
    assert conflicting.status_code == 409
    assert conflicting.json()['detail']['code'] == 'research_request_conflict'

    saved = assigned.analyst.post(assigned.endpoint, json=body, headers=headers)
    assert saved.status_code == 201, saved.text
    file_id = saved.json()['file_id']
    assert saved.json()['sha256'] == sha256(raw).hexdigest()
    with database_connection(write=True) as db:
        ledger = usage(db, project_id=assigned.project.rsplit('/', 1)[-1])
        assert ledger['unknown_reservation_count'] == 0 and ledger['reserved_bytes'] == 0
        assert inventory(db, get_data_dir())['status'] == 'complete'
    replayed = assigned.analyst.post(assigned.endpoint, json=body, headers=headers)
    assert replayed.status_code == 200 and replayed.json() == saved.json()
    assert assigned.analyst.post(assigned.endpoint, headers=headers, json={
        **body, 'annotation_version_id': 'different',
    }).status_code == 409
    assert assigned.analyst.post(assigned.endpoint, headers={'Idempotency-Key': 'stale'}, json={
        **body, 'assignment_revision': assigned.revision + 1,
    }).status_code == 409
    assert len(renders) == 1

    customer_workspace = assigned.project + '/customer-workspace'
    assert assigned.customer.get(assigned.project + '/files/' + file_id + '/download').status_code == 404
    assert file_id not in {item['id'] for item in assigned.customer.get(assigned.project + '/files').json()}
    assert assigned.customer.get(customer_workspace + '/deliveries').json() == {'items': []}
    intake = assigned.analyst.get(assigned.project + '/research-intake').json()
    delivery_id = next(row['id'] for row in intake['deliveries'] if row['kind'] == 'analysis')
    delivery = assigned.project + '/deliveries/' + delivery_id
    candidates = assigned.analyst.get(delivery + '/candidates').json()['items']
    assert any(row['selection'].get('file_id') == file_id and row['status'] == 'succeeded' for row in candidates)
    frozen = assigned.analyst.post(delivery + '/snapshots', headers={'Idempotency-Key': 'freeze-native-word'},
                                  json=freeze_body(assigned.requirement, file_id))
    assert frozen.status_code == 201, frozen.text
    snapshot = frozen.json()
    member = snapshot['members'][0]
    assert set(snapshot['source_file_ids']) == {file_id, assigned.file_id}
    assert member['source_metadata']['analysis_artifact']['manifest_sha256'] == source_sha
    assert assigned.customer.get(customer_workspace + '/deliveries/' + snapshot['id']).status_code == 404

    published = assigned.analyst.post(assigned.project + '/analyst-workspace/publish', json={
        'assignment_revision': assigned.revision, 'snapshot_id': snapshot['id'], 'title': 'Synthetic report',
    })
    assert published.status_code == 201, published.text
    package = assigned.analyst.post(delivery + '/snapshots/' + snapshot['id'] + '/package',
                                    headers={'Idempotency-Key': 'package-native-word'}, json={})
    assert package.status_code == 201, package.text
    queued = package.json()['task']
    completed = run_delivery_package_task(queued['id'], queued['revision'], staging_directory=tmp_path / 'staging')
    assert completed['status'] == 'succeeded', completed
    assign(assigned.admin, assigned.project, None, assigned.revision)
    assert assigned.analyst.post(assigned.endpoint, json=body, headers=headers).status_code == 404
    public = assigned.customer.get(customer_workspace + '/deliveries/' + snapshot['id']).json()
    assert set(public['members'][0]) == {'id', 'name', 'format', 'size_bytes', 'download_url'}
    assert assigned.customer.get(public['members'][0]['download_url']).content == raw
    archive = assigned.customer.get(public['package_url'])
    assert archive.status_code == 200, archive.text
    with ZipFile(BytesIO(archive.content)) as files:
        assert files.read(public['members'][0]['name']) == raw
    assert len(renders) == 1


def test_prepared_bulk_word_survives_cache_eviction_and_rejects_mismatched_facts(assigned_project, monkeypatch, tmp_path):
    from app.api import bulk_workflow
    from app.domain.bio_insights.bulk_delivery_cache import ArtifactCache

    assigned = assigned_project
    raw = word_bytes('Synthetic Bulk RNA-seq results')
    facts_digest, artifact_id = 'b' * 64, 'c' * 64
    facts = dict(facts_digest=facts_digest, comparison_version_id='comparison', language='en',
                 references=dict(comparison=dict(version_id='comparison', manifest_sha256='d' * 64),
                                 processed=[], results=[], resources=[]),
                 qc=dict(input_files=[dict(id=assigned.file_id)]), evidence=[], figures=[], limitations=[])
    cache = ArtifactCache(tmp_path / 'bulk-word')

    def write(folder):
        (folder / 'payload').write_bytes(raw)
        return dict(facts_digest=facts_digest, request=dict(comparison_version_id='comparison', facts_digest=facts_digest))

    cache.obtain(artifact_id, write)
    monkeypatch.setattr(bulk_workflow, 'cache_for', lambda store, project, kind: cache)
    monkeypatch.setattr(bulk_workflow, 'resolve_delivery', lambda project, store, request: (None, facts))
    headers = {'Idempotency-Key': 'save-bulk-word'}
    body = dict(kind='bulk_word', artifact_id=artifact_id, facts_digest=facts_digest,
                assignment_revision=assigned.revision)
    assert assigned.analyst.post(assigned.endpoint, headers={'Idempotency-Key': 'changed-facts'}, json={
        **body, 'facts_digest': 'e' * 64,
    }).status_code == 409
    failures = fail_receipt_once(monkeypatch)
    interrupted = assigned.analyst.post(assigned.endpoint, headers=headers, json=body)
    assert interrupted.status_code == 503 and failures == [True]
    monkeypatch.setattr(cache, 'read', lambda key: None)
    saved = assigned.analyst.post(assigned.endpoint, headers=headers, json=body)
    assert saved.status_code == 201, saved.text
    assert saved.json()['sha256'] == sha256(raw).hexdigest()
    replay = assigned.analyst.post(assigned.endpoint, headers=headers, json=body)
    assert replay.status_code == 200 and replay.json() == saved.json()
    assert assigned.analyst.get(assigned.project + '/files/' + saved.json()['file_id'] + '/download').content == raw


@pytest.mark.parametrize('partial_write', [False, True])
def test_native_retry_discards_only_empty_storage_capture(assigned_project, monkeypatch, partial_write):
    from app.adapters import single_cell_report
    from app.core.exceptions import StorageError
    from app.db.database import database_connection
    from app.domain.storage_governance import candidates

    assigned = assigned_project
    outputs = [word_bytes('Before the write failure'), word_bytes('Rebuilt after no bytes were saved')]
    renders = []
    source_unavailable = False

    def render(store, project, identifier, annotation_version_id=None):
        if source_unavailable:
            raise StorageError('bio_source_conflict', 'Synthetic temporary source failure.', 409)
        raw = outputs[len(renders)]
        renders.append(raw)
        return dict(sha256=sha256(raw).hexdigest(), provenance=dict(
            version_id=identifier, manifest_sha256='a' * 64, language='en', source_file_ids=[assigned.file_id],
        )), raw

    monkeypatch.setattr(single_cell_report, 'download_single_cell_report', render)
    original = candidates._write_immutable
    attempts = []

    def write(path, content):
        attempts.append(path)
        if len(attempts) == 1:
            if partial_write:
                path.write_bytes(content[:7])
            raise OSError('Synthetic write interruption')
        return original(path, content)

    monkeypatch.setattr(candidates, '_write_immutable', write)
    headers = {'Idempotency-Key': 'interrupted-native-word'}
    body = dict(kind='single_cell_word', version_id='processed', assignment_revision=assigned.revision)
    failed = assigned.analyst.post(assigned.endpoint, headers=headers, json=body)
    assert failed.status_code == 503 and attempts[0].exists() == partial_write
    wrong_source = assigned.analyst.post(assigned.endpoint, headers=headers, json={**body, 'version_id': 'other'})
    assert wrong_source.status_code == 409
    assert wrong_source.json()['detail']['code'] == (
        'storage_accounting_unknown' if partial_write else 'research_request_conflict'
    )

    if not partial_write:
        source_unavailable = True
        released = assigned.analyst.post(assigned.endpoint, headers=headers, json=body)
        assert released.json()['detail']['code'] == 'bio_source_conflict'
        source_unavailable = False
        wrong_source = assigned.analyst.post(assigned.endpoint, headers=headers, json={**body, 'version_id': 'other'})
        assert wrong_source.json()['detail']['code'] == 'research_request_conflict'

    retried = assigned.analyst.post(assigned.endpoint, headers=headers, json=body)
    if partial_write:
        assert retried.status_code == 409 and retried.json()['detail']['code'] == 'storage_accounting_unknown'
        assert renders == outputs[:1] and attempts[0].read_bytes() == outputs[0][:7]
    else:
        assert retried.status_code == 201, retried.text
        assert retried.json()['sha256'] == sha256(outputs[1]).hexdigest() and renders == outputs
        with database_connection() as db:
            states = db.execute('''SELECT state FROM storage_reservations
                WHERE project_id=%s AND capacity_bytes IS NOT NULL''', (assigned.project.rsplit('/', 1)[-1],))
            assert sorted(row['state'] for row in states) == ['released', 'settled']


def test_processed_single_cell_png_accepts_only_saved_figure_members(assigned_project, monkeypatch):
    from PIL import Image

    from app.adapters.bio_analysis_store import BioAnalysisStore
    from app.adapters.task_store import TaskStore

    assigned = assigned_project
    buffer = BytesIO()
    Image.new('RGB', (8, 8), '#0c7594').save(buffer, format='PNG')
    raw = buffer.getvalue()
    figure = dict(id='umap-png', key='umap_png', format='png', role='figure_png',
                  size_bytes=len(raw), sha256=sha256(raw).hexdigest())
    unsafe = dict(id='internal', key='object', format='json', role='manifest', size_bytes=15)

    def processed(service, db, project, version):
        service.store.require_project(db, project)
        assert version == 'processed'
        monkeypatch.setattr(service.objects, 'read', lambda member: raw if member['id'] == figure['id'] else b'internal')
        return (dict(task_id='synthetic-worker', manifest_sha256='c' * 64),
                dict(assay='single_cell', raw_source=dict(source_file_ids=[assigned.file_id])), [figure, unsafe])

    monkeypatch.setattr(BioAnalysisStore, 'processed_record', processed)
    monkeypatch.setattr(TaskStore, 'require_task', lambda self, db, task: {'status': 'succeeded'})
    body = dict(kind='single_cell_png', version_id='processed', member_id=figure['id'],
                assignment_revision=assigned.revision)
    saved = assigned.analyst.post(assigned.endpoint, headers={'Idempotency-Key': 'attach-umap'}, json=body)
    assert saved.status_code == 201, saved.text
    assert saved.json()['format'] == 'png' and saved.json()['sha256'] == figure['sha256']
    blocked = assigned.analyst.post(assigned.endpoint, headers={'Idempotency-Key': 'attach-internal'},
                                    json={**body, 'member_id': unsafe['id']})
    assert blocked.status_code == 422
    assert blocked.json()['detail']['code'] == 'research_source_unsupported'
