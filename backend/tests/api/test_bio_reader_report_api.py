"""Native report HTTP entry points with formal storage and synthetic scientific fixtures."""
from hashlib import sha256
from io import BytesIO
import json
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app.db.database import database_connection
from app.main import app
from tests.api.test_analyst_workspace import assign, freeze_body
from tests.api.test_bio_reader_report_annotation import labels, native_figure
from tests.api.test_bio_reader_reports import service_for
from tests.api.test_customer_workspace import create_customer_project, sign_in, write_requirements
from tests.api.test_projects import client, create_project
from tests.api.test_reader_report_narratives import authorize_user_and_project, reader_policy, worker
from tests.api.test_school_rule_suggestions import Fixture
from tests.api.test_single_cell_batch4_flow import parent_result
from tests.helpers.research_report import sample_reader_record


def post(client, path, key, body):
    return client.post(path, json=body, headers={'Idempotency-Key': key})


def prepare(client, base, body, key='native-context'):
    response = post(client, base + '/bio-reader-reports/prepare', key, body)
    assert response.status_code == 201, response.text
    return response.json()


def report_path(base, context, report):
    return f"{base}/bio-reader-reports/{context['id']}/reports/{report['id']}"


def member_path(base, context, report, role):
    return report_path(base, context, report) + f'/members/{role}/download'


def ledger(project):
    with database_connection() as db:
        return [dict(row) for row in db.execute(
            "SELECT m.id,m.status FROM model_calls m JOIN tasks t ON t.id=m.task_id WHERE t.project_id=%s ORDER BY m.id",
            (project,))]


def create_report(client, base, context, tmp_path):
    from app.adapters.research_report_render import render_report
    from app.domain.research_results.contracts import ResearchReportRequest
    from app.domain.research_results.execution import run_research_report_task
    from app.domain.research_results.reports import ResearchReportService

    project = base.rsplit('/', 1)[-1]
    analysis = service_for(project)
    with analysis.store.connection() as db:
        snapshot, _, payload = ResearchReportService(analysis.assets).freeze(
            db, project, ResearchReportRequest.model_validate(context['report']))
    if context['selection']['kind'] == 'bulk':
        from app.domain.reader_reports.content import input_text_bytes, instructions, make_material

        figures = [dict(figure, content=figure['raw']) for figure in payload['figures']]
        material = make_material(snapshot, figures)
        overview_bytes = input_text_bytes(dict(material, figures=[]))
        text_bytes = input_text_bytes(material)
        prompt_bytes = len(instructions(material['language']).encode('utf-8'))
        estimated_minimum = text_bytes + prompt_bytes + 8192 * len(figures) + 4096
        print(f'Bulk R1 input: overview_bytes={overview_bytes}, figure_text_bytes={text_bytes - overview_bytes}, '
              f'prompt_bytes={prompt_bytes}, figures={len(figures)}, png_bytes={sum(len(f["raw"]) for f in figures)}, '
              f'policy_minimum={estimated_minimum}')
    endpoint = base + '/research-report-narratives'
    preview = client.post(endpoint + '/preview', json=context['report'])
    assert preview.status_code == 200, preview.text
    narrative = post(client, endpoint, 'native-narrative', dict(report=context['report'],
        bundle_sha256=preview.json()['bundle_sha256'], confirmed_external_processing=True))
    assert narrative.status_code == 202, narrative.text
    queued = narrative.json()
    authorize_user_and_project(queued)
    sample = sample_reader_record(snapshot)
    provider = Fixture(dict(narrative=sample['narrative'], figures=[
        {k: v for k, v in figure.items() if k != 'caption'} for figure in sample['figures']]))
    done = worker(queued, provider)
    assert done['status'] == 'succeeded' and len(provider.posts) == 1, done
    report = post(client, base + '/research-reports', 'native-report',
                  context['report'] | {'reader_narrative_id': queued['id']})
    assert report.status_code == 201, report.text
    created = report.json()
    catalog = client.get(report_path(base, context, created).rsplit('/', 1)[0])
    assert catalog.status_code == 200, catalog.text
    assert [(r['id'], r['task']['status'], r['members']) for r in catalog.json()['items']] == [(created['id'], 'queued', [])]
    waiting = client.get(member_path(base, context, created, 'docx'))
    assert waiting.status_code == 422, waiting.text
    done = run_research_report_task(created['task_id'], created['task']['revision'], engine=render_report,
                                    staging_directory=tmp_path / 'reader-report')
    assert done['status'] == 'succeeded', done
    saved = client.get(base + '/research-reports/' + created['id'])
    assert saved.status_code == 200, saved.text
    return saved.json()


def fixed_members(client, base, context, report):
    catalog_url = report_path(base, context, report).rsplit('/', 1)[0]
    response = client.get(catalog_url)
    assert response.status_code == 200, response.text
    catalog = response.json()
    assert (catalog['total'], catalog['page'], catalog['page_size']) == (1, 1, 20)
    assert client.get(catalog_url, params={'page': 2}).json()['items'] == []
    row, = catalog['items']
    assert row['id'] == report['id'] and row['task_id'] == report['task_id']
    assert row['task']['status'] == 'succeeded'
    original = {member['id']: member for member in report['members']}
    actual = {}
    for member in row['members']:
        role = member['role']
        expected = original[member['id']]
        assert member['download_url'] == member_path(base, context, report, role)
        download = client.get(member['download_url'])
        assert download.status_code == 200, download.text
        assert download.headers['ETag'] == f'"{member["sha256"]}"'
        assert download.content == client.get(expected['download_url']).content
        assert sha256(download.content).hexdigest() == expected['sha256'] == member['sha256']
        actual[role] = download.content
    assert set(actual) == {'docx', 'xlsx', 'zip'}
    return actual


def processed_body(f, annotation=None, figures=()):
    return dict(title='Reviewed cell selection', language='en', selection=dict(kind='processed',
        processed_version_id=f['source']['processed_dataset_version_id'], annotation_version_id=annotation,
        figure_version_ids=list(figures)))


def test_prepare_and_recover_only_in_assigned_scope(client, monkeypatch, tmp_path):
    with TestClient(app) as customer, TestClient(app) as admin, TestClient(app) as analyst, TestClient(app) as outsider:
        sign_in(customer, 'native-owner@report.test', 'customer')
        sign_in(admin, 'native-admin@report.test', 'admin')
        analyst_id = sign_in(analyst, 'native-analyst@report.test', 'analyst')
        sign_in(outsider, 'native-outsider@report.test', 'analyst')
        base = create_customer_project(customer)
        other = create_customer_project(customer, 'other-project')
        endpoint = base + '/bio-reader-reports'
        placeholder = processed_body({'source': {'processed_dataset_version_id': 'missing'}})
        response = post(customer, endpoint + '/prepare', 'native-context', placeholder)
        assert response.status_code == 403, response.text
        assert post(analyst, endpoint + '/prepare', 'native-context', placeholder).status_code == 404
        assign(admin, base, analyst_id)
        assign(admin, other, analyst_id)
        f = parent_result.__wrapped__(analyst, monkeypatch, tmp_path, base)
        body = processed_body(f)
        assert post(outsider, endpoint + '/prepare', 'native-context', body).status_code == 404
        assert post(analyst, other + '/bio-reader-reports/prepare', 'cross-project', body).status_code == 404
        context = prepare(analyst, base, body)
        receipt = endpoint + '/requests/native-context'
        fixed = endpoint + '/' + context['id']
        assert analyst.get(receipt).json() == analyst.get(fixed).json() == context
        for key in ('native-context', 'same-selection'):
            replay = post(analyst, endpoint + '/prepare', key, body)
            assert replay.status_code == 200 and replay.json() == context
        assert post(analyst, endpoint + '/prepare', 'native-context', body | {'title': 'Different'}).status_code == 409
        assert analyst.get(other + '/bio-reader-reports/' + context['id']).status_code == 404
        assert outsider.get(fixed).status_code == 404
        assert customer.get(fixed).status_code == customer.get(receipt).status_code == 403
        assert customer.post(base + '/research-report-narratives/preview', json=context['report']).status_code == 403
        denied_narrative = post(customer, base + '/research-report-narratives', 'forbidden-narrative',
            dict(report=context['report'], bundle_sha256='a'*64, confirmed_external_processing=True))
        assert denied_narrative.status_code == 403, denied_narrative.text
        assert ledger(f['source']['project_id']) == []
        with database_connection() as db:
            assert not db.execute("SELECT 1 FROM tasks WHERE task_type IN ('reader_report_narrative','research_report')").fetchone()
        assign(admin, base, None, 1)
        assert analyst.get(fixed).status_code == analyst.get(receipt).status_code == 404
        assert post(analyst, endpoint + '/prepare', 'revoked', body).status_code == 404


def test_assigned_processed_members_remain_exact_after_annotation_changes_and_publication(client, monkeypatch, tmp_path):
    with TestClient(app) as customer, TestClient(app) as admin, TestClient(app) as analyst:
        sign_in(customer, 'report-owner@report.test', 'customer')
        sign_in(admin, 'report-admin@report.test', 'admin')
        analyst_id = sign_in(analyst, 'report-analyst@report.test', 'analyst')
        base = create_customer_project(customer)
        requirement = write_requirements(customer, base, 1, 'confirm')
        revision = assign(admin, base, analyst_id)
        f = parent_result.__wrapped__(analyst, monkeypatch, tmp_path, base)
        annotation_body, annotation = labels(analyst, f)
        first, _ = native_figure(analyst, f, monkeypatch, 'first', 'red', annotation['id'])
        second, _ = native_figure(analyst, f, monkeypatch, 'second', 'blue', annotation['id'])
        context = prepare(analyst, base, processed_body(f, annotation['id'], [first, second]))
        report = create_report(analyst, base, context, tmp_path)
        before = ledger(f['source']['project_id'])
        assert len(before) == 1
        files = fixed_members(analyst, base, context, report)
        old_word = base + '/bio-processed-datasets/' + f['source']['processed_dataset_version_id'] + '/report.docx'
        params = dict(report_version_id=report['id'], language='en', figure_version_ids=[first, second],
                      annotation_version_id=annotation['id'])
        assert analyst.get(old_word, params=params).content == files['docx']
        assert analyst.get(old_word, params=params | {'language': 'zh-CN'}).status_code == 409
        assert analyst.get(old_word, params=params | {'figure_version_ids': [second, first]}).status_code == 409
        assert analyst.get(old_word, params={k:v for k,v in params.items() if k != 'annotation_version_id'}).status_code == 409
        assert customer.get(member_path(base, context, report, 'docx')).status_code == 403

        changed = post(analyst, base + f"/bio-annotation-sets/{annotation['set_id']}/versions", 'new-labels',
                       annotation_body | {'expected_revision': 1, 'labels': [
                           dict(id='T', name='New label', status='confirmed', cell_ids=['c1'])]})
        assert changed.status_code == 201, changed.text
        assert analyst.get(old_word, params=params).content == files['docx']
        assert analyst.get(old_word, params=params | {'annotation_version_id': changed.json()['id']}).status_code == 409

        intake = analyst.get(base + '/research-intake').json()
        delivery_id = next(row['id'] for row in intake['deliveries'] if row['kind'] == 'analysis')
        delivery = f'{base}/deliveries/{delivery_id}'
        selections = {m['role']: dict(kind='research_report_member', version_id=report['id'], member_id=m['id'])
                      for m in report['members']}
        response = analyst.get(delivery + '/candidates')
        assert response.status_code == 200, response.text
        available = [r['selection'] for r in response.json()['items']]
        assert selections['docx'] in available and selections['xlsx'] in available and selections['zip'] not in available
        body = freeze_body(requirement, 'unused')
        denied = post(analyst, delivery + '/snapshots', 'no-system-zip', body | {'members': [selections['zip']]})
        assert denied.status_code == 422, denied.text
        frozen = post(analyst, delivery + '/snapshots', 'freeze-native', body | {'members': [selections['docx'], selections['xlsx']]})
        assert frozen.status_code == 201, frozen.text
        snapshot = frozen.json()
        published = analyst.post(base + '/analyst-workspace/publish', json=dict(
            assignment_revision=revision, snapshot_id=snapshot['id'], title='Fixed report'))
        assert published.status_code == 201, published.text
        assign(admin, base, None, revision)
        assert analyst.get(member_path(base, context, report, 'docx')).status_code == 404
        public = customer.get(base + '/customer-workspace/deliveries/' + snapshot['id'])
        assert public.status_code == 200, public.text
        for item in public.json()['members']:
            assert customer.get(item['download_url']).content == files[item['format']]
        assert ledger(f['source']['project_id']) == before


def test_fixed_insight_legacy_download_rejects_unmatched_result_and_language(client, monkeypatch, tmp_path):
    from tests.api.test_bio_insight_research_bridge import published

    project, result, _ = published(client, monkeypatch, tmp_path)
    base = f'/api/v1/projects/{project}'
    context = prepare(client, base, dict(title='External results', language='en',
        selection=dict(kind='insight', result_version_id=result['id'], figure_version_ids=[])))
    report = create_report(client, base, context, tmp_path)
    before = ledger(project)
    files = fixed_members(client, base, context, report)
    legacy = base + '/bio-insight-results/' + result['id'] + '/report.docx'
    params = dict(report_version_id=report['id'], language='en')
    assert client.get(legacy, params=params).content == files['docx']
    assert client.get(legacy, params=params | {'language': 'zh-CN'}).status_code == 409
    assert client.get(legacy, params=params | {'figure_version_ids': ['unrelated-figure']}).status_code == 409
    assert client.get(legacy, params={'report_version_id': report['id']}).status_code == 422
    assert client.get(legacy.replace(result['id'], 'another-result'), params=params).status_code == 409
    alternate = prepare(client, base, dict(title='Other report', language='en', selection=context['selection']), 'other-context')
    assert not client.get(report_path(base, alternate, report).rsplit('/', 1)[0]).json()['items']
    assert client.get(member_path(base, alternate, report, 'docx')).status_code == 409
    other = f"/api/v1/projects/{create_project(client)['id']}"
    assert client.get(member_path(other, context, report, 'docx')).status_code == 404
    assert ledger(project) == before


def test_bulk_package_combines_fixed_report_with_only_selected_scientific_closure(client, monkeypatch, tmp_path):
    from pathlib import Path
    import os
    from app.domain.bio_insights import reproducibility
    from tests.helpers.bio_report_contexts import published_bulk
    from tests.helpers.bio_report_bulk_enrichment import publish_enrichment_replot

    # Exercise the same policy and ledger with an explicit synthetic allowance
    # for the saved Bulk inputs and selected plot.
    policy_path = Path(os.environ['PAPERASSIST_READER_REPORT_POLICY_FILE'])
    policy = json.loads(policy_path.read_text(encoding='utf-8'))
    policy.update(input_token_allowance=300000, task_limit_micro_usd=400000)
    policy_path.write_text(json.dumps(policy), encoding='utf-8')
    environment_proof = reproducibility.environment_proof
    base, processed, comparison = published_bulk(client, monkeypatch, tmp_path)
    enrichment, replot = publish_enrichment_replot(client, monkeypatch, tmp_path, base, comparison)
    # The Windows fixture did not run the exact locked Linux worker. Let the
    # real exporter select its fixed-data-only mode for this archive.
    monkeypatch.setattr(reproducibility, 'environment_proof', environment_proof)
    selection = dict(contrast_id='B_A', direction='up', minimum_absolute_effect=1.0, q_threshold=0.05)
    sensitivity = dict(baseline_version_id=comparison['id'], scenario_version_id=comparison['id'],
                       baseline_selection=selection, scenario_selection=selection | {'q_threshold': 1e-8})
    evidence_bytes = b'fixture_term\tSynthetic evidence\tf1\tf2\n'
    upload = client.post(base + '/bio-resource-files', files={'file': ('experimental.gmt', evidence_bytes)},
                         headers={'Idempotency-Key': 'experimental-file'})
    assert upload.status_code == 201, upload.text
    material = upload.json()
    delivery = dict(comparison_version_id=comparison['id'], language='en', result_version_ids=[replot['id']],
                    selections=[selection], sensitivity=sensitivity,
                    evidence=[dict(kind='experimental_material', source_id=material['file_id'])])
    legacy = base + '/bulk-workflow/delivery'
    preview = client.post(legacy + '/preview', json=delivery)
    assert preview.status_code == 200, preview.text
    facts = preview.json()
    body = dict(title='Frozen bulk analysis', language='en',
                selection=dict(kind='bulk', delivery=delivery | {'facts_digest': facts['facts_digest']}))
    context = prepare(client, base, body)
    other = prepare(client, base, body | {'title': 'Different frozen selection'}, 'different')
    report = create_report(client, base, context, tmp_path)
    before = ledger(base.rsplit('/', 1)[-1])
    files = fixed_members(client, base, context, report)
    fixed = report_path(base, context, report) + '/bulk-reproduction'
    prepared = client.post(fixed + '/prepare')
    assert prepared.status_code == 200, prepared.text
    artifact = prepared.json()
    assert client.post(fixed + '/prepare').json() == artifact
    bundle = client.get(artifact['download_url'])
    assert bundle.status_code == 200, bundle.text
    assert 'X-Reproducibility-Manifest-SHA256' in bundle.headers
    assert bundle.headers['X-Bulk-Facts-SHA256'] == facts['facts_digest']
    assert bundle.headers['Content-Disposition'] != client.get(member_path(base, context, report, 'zip')).headers['Content-Disposition']
    with ZipFile(BytesIO(bundle.content)) as outer:
        assert outer.read('report/report.docx') == files['docx']
        assert outer.read('report/results.xlsx') == files['xlsx']
        saved = json.loads(outer.read('report/facts.json'))
        assert saved['selected_result_version_ids'] == [replot['id']]
        assert saved['result_version_ids'] == [enrichment['id'], replot['id']]
        assert saved['selections'] == facts['selections']
        evidence_path = f"evidence/materials/{material['file_id']}.bin"
        assert outer.read(evidence_path) == evidence_bytes
        assert {name for name in outer.namelist() if name.startswith('results/')} == {
            f"results/{row['id']}.zip" for row in (comparison, enrichment, replot)}
        assert any(name.startswith('resources/') for name in outer.namelist())
        assert any(name.startswith('tasks/') for name in outer.namelist())
        assert len(outer.read('tables/contrast-01-filtered.tsv').splitlines()) == facts['contrasts'][0]['counts']['up'] + 1
        assert b'\tlost\t' in outer.read('sensitivity/feature-changes.tsv')
        package = json.loads(outer.read('package.json'))
        assert processed in package['processed_version_ids']
        assert package['report']['context_sha256'] == context['source']['sha256']
        assert package['report']['report_version_id'] == report['id'] and package['report']['language'] == 'en'
        for role, data in [('docx', files['docx']), ('xlsx', files['xlsx'])]:
            assert package['report']['members'][role]['sha256'] == sha256(data).hexdigest()
        with ZipFile(BytesIO(outer.read(f"results/{comparison['id']}.zip"))) as inner:
            assert {'result/comparison_results.tsv', 'input/payload.json', 'provenance/task-input.json', 'README.md'} <= set(inner.namelist())
            assert any(name.startswith('input/objects/') for name in inner.namelist())
    bad_path = report_path(base, other, report) + '/bulk-reproduction'
    assert client.post(bad_path + '/prepare').status_code == 409
    assert client.get(bad_path + '/' + artifact['artifact_id']).status_code == 409
    legacy_prepared = client.post(legacy + '/prepare/archive', json=context['selection']['delivery'])
    assert legacy_prepared.status_code == 200, legacy_prepared.text
    assert legacy_prepared.json()['artifact_id'] != artifact['artifact_id']
    legacy_zip = client.get(legacy_prepared.json()['download_url'])
    assert legacy_zip.status_code == 200, legacy_zip.text
    with ZipFile(BytesIO(legacy_zip.content)) as outer:
        assert 'report/report.docx' in outer.namelist() and 'report/results.xlsx' not in outer.namelist()
        with ZipFile(BytesIO(bundle.content)) as formal:
            assert outer.read('sensitivity/feature-changes.tsv') == formal.read('sensitivity/feature-changes.tsv')
    shortcut = base + '/bio-insight-results/' + comparison['id'] + '/report.docx'
    assert client.get(shortcut, params=dict(language='en', report_version_id=report['id'])).status_code == 409
    from app.core.config import get_data_dir

    with database_connection() as db:
        saved_object = db.execute("""SELECT o.object_key FROM storage_objects o
            JOIN research_report_members m ON m.storage_object_id=o.id
            WHERE m.report_version_id=%s AND m.role='xlsx'""", (report['id'],)).fetchone()
    workbook = get_data_dir() / saved_object['object_key']
    try:
        workbook.write_bytes(files['xlsx'][:-1] + bytes([files['xlsx'][-1] ^ 1]))
        assert client.get(artifact['download_url']).status_code == 409
    finally:
        workbook.write_bytes(files['xlsx'])

    restriction = post(client, base + '/bio-resources', 'restricted-original', dict(
        kind='gene_sets', title='Restricted experimental sets', species_taxon_id=9606, namespace='ensembl',
        release='fixed', offline_enrichment=True, source=dict(institution='test', name='synthetic',
        description='Engineering fixture'), usage=dict(basis='Project-only research fixture', scope='project',
        redistribution_allowed=False), files=[dict(file_id=material['file_id'], sha256=material['sha256'],
        role='gmt', format='gmt')]))
    assert restriction.status_code == 202, restriction.text
    current_preview = client.post(legacy + '/preview', json=delivery)
    assert current_preview.status_code == 200, current_preview.text
    assert current_preview.json()['facts_digest'] == facts['facts_digest']
    expired = client.get(artifact['download_url'])
    assert expired.status_code == 410, expired.text[:200] if expired.status_code != 200 else 'Revoked original still downloaded'
    new_prepare = client.post(fixed + '/prepare')
    assert new_prepare.status_code == 200, new_prepare.text
    replacement = new_prepare.json()
    assert replacement['artifact_id'] != artifact['artifact_id'] and replacement['facts_digest'] == artifact['facts_digest']
    safe_bundle = client.get(replacement['download_url'])
    assert safe_bundle.status_code == 200, safe_bundle.text[:200]
    with ZipFile(BytesIO(safe_bundle.content)) as outer:
        assert evidence_path not in outer.namelist()
        evidence, = json.loads(outer.read('evidence/references.json'))
        assert evidence['sha256'] == material['sha256'] and evidence['distribution'] == 'reference_only_resource_license'
        assert outer.read('report/report.docx') == files['docx']
        assert outer.read('report/results.xlsx') == files['xlsx']
    assert ledger(base.rsplit('/', 1)[-1]) == before
