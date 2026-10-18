"""Real SCI/thesis artifact use and adversarial ownership/source combinations.

Uses the global random paperassist_system_test schema, temporary assets, real
authentication and local Word renderer. Providers are synthetic boundaries.
"""
from tests.helpers.legacy_plans import seed_legacy_plan
from tests.helpers.statistics import statistics_post
from copy import deepcopy
from io import BytesIO
import json
from zipfile import ZipFile

import pytest
from openpyxl import Workbook

from app.adapters.figure_workbench_store import read_bundle
from app.adapters.storage import ProjectStore
from app.core.config import get_data_dir
from app.db.database import database_connection
from app.domain.figure_workbench.execution import run_figure_workbench_task, run_figure_explanation_task
from app.domain.model_usage.service import ModelUsageService
from app.domain.report_collections.execution import run_collection_word_task
from tests.api.test_analysis import client
from tests.api.test_dataset_analysis import version
from tests.domain.test_correlation_plan_contracts import research, selection
from tests.helpers.analysis_plan import run_plan, review_plan, plan_decision, decide_plan
from tests.helpers.tasks import task_owner
from tests.integration.test_batch05_figure_execution import FigureExplanationProvider
from tests.integration.test_batch06_pipeline import IndependentV2LineProvider, checked_policy
from tests.integration.test_dataset_preparation import run, review, decide, decision
from tests.integration.test_project_ownership import account_client


class ProjectLineProvider(IndependentV2LineProvider):
    """The old single-call fixture uses one response ID; each project needs its own."""
    def receipt(self):
        receipt = super().receipt()
        receipt['response_id'] = receipt['response']['id'] = 'resp_batch08_plot_' + self.result['id'].replace('-', '')
        receipt['request_id'] = 'req_batch08_plot_' + self.result['id'].replace('-', '')
        return receipt


class ProjectExplanationProvider(FigureExplanationProvider):
    def __init__(self, result):
        super().__init__()
        self.result = result

    def create(self, **kwargs):
        receipt = super().create(**kwargs)
        receipt['response_id'] = receipt['response']['id'] = 'resp_batch08_prose_' + self.result['id'].replace('-', '')
        receipt['request_id'] = 'req_batch08_prose_' + self.result['id'].replace('-', '')
        return receipt


def plan_for(client, base, prepared, *, expected=0, method='pearson'):
    chosen = selection()
    chosen.update(sheet_name=prepared['source']['sheet_name'], method=method, units={'A': '', 'B': ''})
    chosen['assumptions']['relationship_form'] = 'linear' if method == 'pearson' else 'monotonic'
    request = dict(schema_version=3, dataset_id=prepared['id'], expected_setup_revision=expected,
        selection=chosen, research_request=research(), recommendation_ref=None)
    response = seed_legacy_plan(client, base + '/analysis-plans', json=request,
                           headers={'Idempotency-Key': f'plan-{expected}-{method}'})
    assert response.status_code == 202, response.text
    task = response.json()
    assert run_plan(task)['status'] == 'waiting_confirmation'
    accepted = decide_plan(client, task, plan_decision(review_plan(client, task)), f'approve-{task["id"]}')
    assert accepted.status_code == 202, accepted.text
    assert run_plan(accepted.json())['status'] == 'succeeded'
    result = statistics_post(client, base + '/analysis-runs', json={'expected_revision': expected + 1})
    assert result.status_code == 200, result.text
    return result.json(), review_plan(client, task)['result'], request


def prepared_source(client, project_type):
    project = client.post('/api/v1/projects', json=dict(name=f'Batch08 {project_type}',
        research_topic='Synthetic source and artifact permission proof', project_type=project_type))
    assert project.status_code == 201, project.text
    project = project.json()
    assert project['project_type'] == project_type
    book = Workbook()
    book.active.title = 'Synthetic'
    for row in [['X', 'Y', 'Projection'], [1, 2, 9], [2, 4, 8], [3, 6, 7], [4, None, 6], [None, 10, 5]]:
        book.active.append(row)
    stream = BytesIO()
    book.save(stream)
    book.close()
    upload = client.post(f'/api/v1/projects/{project["id"]}/files',
        files={'file': ('batch08-synthetic.xlsx', stream.getvalue())})
    assert upload.status_code == 201, upload.text
    file = upload.json()['file']
    base = f'/api/v1/projects/{project["id"]}/files/{file["id"]}'
    raw = version(client, base)
    defaults = client.get(base + '/dataset-versions/' + raw['id'] + '/preparation-defaults')
    assert defaults.status_code == 200, defaults.text
    task = client.post(base + '/dataset-preparations',
        json={'dataset_id': raw['id'], 'recipe': defaults.json()['recipe']},
        headers={'Idempotency-Key': 'prepare'}).json()
    assert run(task)['status'] == 'waiting_confirmation'
    view = review(client, task)
    recipe = deepcopy(view['recipe'])
    for field in recipe['fields']:
        field['unit'] = dict(status='confirmed', value='')
    revised = decide(client, task, decision(view, 'revise', recipe), 'prepare-units')
    assert revised.status_code == 202, revised.text
    assert run(revised.json())['status'] == 'waiting_confirmation'
    accepted = decide(client, task, decision(review(client, task)), 'prepare-confirm')
    assert accepted.status_code == 202, accepted.text
    assert run(accepted.json())['status'] == 'succeeded'
    prepared = review(client, task)['result']
    result, plan, request = plan_for(client, base, prepared)
    return dict(project=project, file=file, base=base, raw=raw, prepared=prepared,
                result=result, plan=plan, plan_request=request, original=stream.getvalue())


def complete_artifacts(client, monkeypatch, project_type):
    source = prepared_source(client, project_type)
    project, result = source['project']['id'], source['result']
    run_url = source['base'] + '/analysis-runs/' + result['id']
    work_url = run_url + '/figure-workbench'
    config = {'figure_kind': 'line', 'language': 'en', 'projection': {'x_column': 'A', 'y_column': 'C'}}
    saved = client.post(work_url + '/configurations', json={'config': config})
    assert saved.status_code == 200, saved.text
    saved = saved.json()
    vid = saved['version']['id']
    check = client.post(work_url + f'/versions/{vid}/check')
    assert check.status_code == 200, check.text
    confirmed = client.post(work_url + f'/versions/{vid}/confirm',
        json={'approved': True, 'input_sha256': check.json()['input_sha256']})
    assert confirmed.status_code == 200, confirmed.text
    preview = client.post(work_url + f'/versions/{vid}/external-preview').json()
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for', checked_policy)
    usage = ModelUsageService(task_owner(client))
    for scope, key in [('user', task_owner(client)), ('project', project)]:
        if usage.get_budget(scope, key)['revision'] == 0:
            usage.set_budget(scope, key, 5000000, 0)
    request = {'idempotency_key': 'batch08-figure', 'external_processing': {
        'confirmed': True, 'payload_sha256': preview['payload_sha256']}}
    submitted = client.post(work_url + f'/versions/{vid}/generate', json=request)
    assert submitted.status_code == 202, submitted.text
    task = submitted.json()['task']
    provider = ProjectLineProvider(result, pending=False)
    for _ in range(5):
        task = run_figure_workbench_task(task['id'], task['revision'], provider_factory=lambda: provider)
        assert task is not None
        if task['status'] in ('succeeded', 'failed'):
            break
    assert task['status'] == 'succeeded', task
    figure_id = task['result_figure_id']
    explanation_preview = client.post(work_url + f'/figures/{figure_id}/explanation-preview')
    assert explanation_preview.status_code == 200, explanation_preview.text
    explanation_request = {'idempotency_key': 'batch08-explanation', 'external_processing': {
        'confirmed': True, 'payload_sha256': explanation_preview.json()['payload_sha256']}}
    response = client.post(work_url + f'/figures/{figure_id}/explanations', json=explanation_request)
    assert response.status_code == 202, response.text
    task = response.json()['task']
    prose = ProjectExplanationProvider(result)
    task = run_figure_explanation_task(task['id'], task['revision'], provider_factory=lambda: prose)
    assert task is not None and task['status'] == 'succeeded', task
    assets = ProjectStore(get_data_dir(), owner_id=task_owner(client))
    bundle = read_bundle(assets, project, figure_id, task['result_explanation_id'])
    collection_url = f'/api/v1/projects/{project}/report-collections'
    body = {'title': f'Batch08 {project_type} report', 'language': 'en', 'automatic': True,
        'items': [{'figure_id': figure_id, 'explanation_id': task['result_explanation_id']}]}
    response = client.post(collection_url, json=body, headers={'Idempotency-Key': 'batch08-report'})
    assert response.status_code == 201, response.text
    collection = response.json()
    build = collection['versions'][0]['requests'][0]
    assert build['status'] == 'queued'
    done = run_collection_word_task(build['task_id'], 1)
    assert done is not None and done['status'] == 'succeeded', done
    collection = client.get(collection_url + '/' + collection['id']).json()
    report = collection['versions'][0]['requests'][0]['report']
    report_url = collection_url + f'/{collection["id"]}/reports/{report["id"]}/download'
    response = client.get(report_url)
    assert response.status_code == 200, response.text
    return {**source, 'work_url': work_url, 'config': config, 'configuration': saved,
        'projection': confirmed.json(), 'bundle': bundle, 'provider': provider, 'prose': prose,
        'collection_url': collection_url, 'collection': collection, 'collection_body': body,
        'report': report, 'report_url': report_url, 'docx': response.content,
        'figure_request': request, 'explanation_request': explanation_request, 'word_task': build['task_id']}


def guarded_reads(case):
    base, work, collection = case['base'], case['work_url'], case['collection']
    return [base + '/download', base + '/dataset-versions/' + case['raw']['id'] + '/download',
        case['prepared']['download_url'], base + '/analysis-plans/' + case['plan']['id'],
        base + '/analysis-result', work,
        work + '/figures/' + case['bundle']['figure']['id'] + '/png',
        work + '/figures/' + case['bundle']['figure']['id'] + '/package',
        case['collection_url'] + '/' + collection['id'],
        case['collection_url'] + f'/{collection["id"]}/versions/{collection["current_version_id"]}/preview',
        case['report_url']]


def frozen_rows():
    with database_connection() as db:
        return {table: [dict(row) for row in db.execute('SELECT * FROM ' + table + ' ORDER BY id').fetchall()]
            for table in ('analysis_runs', 'figure_configurations', 'figure_config_versions',
                          'figure_projection_decisions', 'figure_projection_results', 'figures', 'explanations',
                          'report_collections', 'report_collection_versions', 'report_collection_items',
                          'report_build_requests', 'collection_reports', 'model_calls', 'model_budgets', 'tasks')}


def assert_scope_denied(actor, victim, owned, *, cross_user=False):
    """Reject known IDs both under the original project and a valid owned run."""
    project = victim['project']['id']
    other_project = owned['project']['id']
    prefix = f'/api/v1/projects/{project}'
    replacement = f'/api/v1/projects/{other_project}'
    evidence = []
    def denied(response, name):
        assert response.status_code in (404, 409), (name, response.status_code, response.text)
        assert 'detail' in response.json()
        evidence.append({'interface': name, 'status': response.status_code, 'code': response.json()['detail']['code']})
    for url in guarded_reads(victim):
        response = actor.get(url.replace(prefix, replacement, 1))
        denied(response, 'project_graft:' + url.split(prefix)[1])
    # Use a genuine accessible file/run, so rejection cannot be attributed only
    # to a missing parent file or a deliberately unknown ID.
    target_work = owned['base'] + '/analysis-runs/' + owned['result']['id'] + '/figure-workbench'
    vid = victim['configuration']['version']['id']
    fid = victim['bundle']['figure']['id']
    eid = victim['bundle']['explanation']['id']
    config_id = victim['configuration']['id']
    calls = [
        ('get', target_work + f'/figures/{fid}/png', {}),
        ('get', target_work + f'/figures/{fid}/package', {}),
        ('post', target_work + '/configurations', {'configuration_id': config_id, 'expected_revision': 1, 'config': victim['config']}),
        ('post', target_work + f'/versions/{vid}/check', {}),
        ('post', target_work + f'/versions/{vid}/confirm', {'approved': True, 'input_sha256': victim['projection']['result']['input_sha256']}),
        ('post', target_work + f'/versions/{vid}/external-preview', {}),
        ('post', target_work + f'/versions/{vid}/generate', victim['figure_request']),
        ('post', target_work + f'/figures/{fid}/explanation-preview', {}),
        ('post', target_work + f'/figures/{fid}/explanations', victim['explanation_request']),
        ('post', target_work + f'/versions/{vid}/reuse-explanation', {'source_explanation_id': eid}),
        ('post', owned['base'] + '/analysis-plans', {**victim['plan_request'], 'expected_setup_revision': 1}),
    ]
    for number, (method, url, body) in enumerate(calls):
        response = actor.request(method, url, **({'json': body, 'headers': {'Idempotency-Key': f'denied-{number}'}} if method == 'post' else {}))
        denied(response, 'valid_owned_parent:' + method + ':' + url.split(owned['base'])[1])
        if cross_user:
            direct = url.replace(owned['base'], victim['base']).replace(owned['result']['id'], victim['result']['id'])
            response = actor.request(method, direct, **({'json': body, 'headers': {'Idempotency-Key': f'direct-denied-{number}'}} if method == 'post' else {}))
            assert response.status_code == 404, (direct, response.text)
            denied(response, 'foreign_original:' + method + ':' + direct.split(victim['base'])[1])
    collections = replacement + '/report-collections'
    for number, item in enumerate(({'figure_id': fid}, {'figure_config_version_id': vid},
                                  {'figure_id': fid, 'explanation_id': eid})):
        response = actor.post(collections, json={**victim['collection_body'], 'items': [item]},
                              headers={'Idempotency-Key': f'foreign-item-{number}'})
        denied(response, 'collection_foreign_item:' + str(number))
    collection = victim['collection']
    for suffix, body in [(f'/{collection["id"]}/versions', {**victim['collection_body'], 'expected_revision': 1}),
                         (f'/{collection["id"]}/versions/{collection["current_version_id"]}/exports', {})]:
        response = actor.post(collections + suffix, json=body, headers={'Idempotency-Key': 'foreign-collection'})
        denied(response, 'foreign_collection:' + suffix)
    # Valid owned figures and collections prevent false confidence from an
    # earlier parent-project rejection when checking nested object bindings.
    own_figure = owned['bundle']['figure']['id']
    own_version = owned['configuration']['version']['id']
    response = actor.post(collections, json={**owned['collection_body'],
        'items': [{'figure_id': own_figure, 'explanation_id': eid}]},
        headers={'Idempotency-Key': 'owned-figure-foreign-explanation'})
    denied(response, 'owned_figure_foreign_explanation')
    response = actor.post(target_work + f'/versions/{own_version}/reuse-explanation',
                          json={'source_explanation_id': eid})
    denied(response, 'owned_version_reuse_foreign_explanation')
    own_collection = owned['collection']['id']
    foreign_version = collection['current_version_id']
    denied(actor.get(collections + f'/{own_collection}/versions/{foreign_version}/preview'), 'owned_collection_foreign_version_preview')
    denied(actor.post(collections + f'/{own_collection}/versions/{foreign_version}/exports',
        headers={'Idempotency-Key': 'owned-collection-foreign-version'}), 'owned_collection_foreign_version_export')
    denied(actor.get(collections + f'/{own_collection}/reports/{victim["report"]["id"]}/download'), 'owned_collection_foreign_report_download')
    return evidence


@pytest.mark.parametrize('project_type', ['sci', 'thesis'])
def test_two_project_types_use_frozen_artifacts_and_reject_cross_project_and_user(client, monkeypatch, postgres_schema, project_type, request):
    assert postgres_schema.schema.startswith('pa_test_')
    with database_connection() as db:
        assert db.execute('SELECT current_database() AS name').fetchone()['name'] == 'paperassist_system_test'
    case = complete_artifacts(client, monkeypatch, project_type)
    result, bundle = case['result'], case['bundle']
    assert result['statistics']['n'] == 3 and result['statistics']['coefficient'] == pytest.approx(1)
    assert result['analysis_context']['plan'] == case['plan']
    assert result['source']['dataset_id'] == case['prepared']['id']
    assert bundle['projection']['result']['audit']['valid_n'] == 4
    assert bundle['explanation']['engine']['id'] == 'figure_explanation_v2'
    assert len(bundle['explanation']['sections']) == 6
    assert case['provider'].posts == ['container', 'upload', 'response'] and len(case['prose'].posts) == 1
    for url in guarded_reads(case):
        assert client.get(url).status_code == 200, url
    assert client.get(case['base'] + '/download').content == case['original']
    with ZipFile(BytesIO(case['docx'])) as archive:
        assert [archive.read(name) for name in archive.namelist() if name.startswith('word/media/')] == [case['provider'].png]
        xml = archive.read('word/document.xml').decode()
        assert 'Statistical results' in xml and 'Six-section explanations' in xml
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls WHERE task_id=%s', (case['word_task'],)).fetchone()['n'] == 0

    sibling = complete_artifacts(client, monkeypatch, 'thesis' if project_type == 'sci' else 'sci')
    before = frozen_rows()
    same_user = assert_scope_denied(client, case, sibling)
    assert frozen_rows() == before
    with account_client(f'batch08-other-{project_type}@paperassist.local')[0] as other:
        foreign_source = complete_artifacts(other, monkeypatch, project_type)
        before = frozen_rows()
        for url in guarded_reads(case):
            response = other.get(url)
            assert response.status_code == 404 and response.json()['detail']['code'] == 'project_not_found', (url, response.text)
        cross_user = assert_scope_denied(other, case, foreign_source, cross_user=True)
        assert frozen_rows() == before
        assert case['project']['id'] not in {p['id'] for p in other.get('/api/v1/projects').json()}

    # Publishing a newer source, configuration, confirmed plan and collection
    # version never replaces the old source or its downloaded Word/PNG bytes.
    before = frozen_rows()
    newer_raw = version(client, case['base'], latest=1)
    assert newer_raw['id'] != case['raw']['id']
    changed = deepcopy(case['config'])
    changed['style'] = {'palette': 'gray'}
    response = client.post(case['work_url'] + '/configurations', json={
        'configuration_id': case['configuration']['id'], 'expected_revision': 1, 'config': changed})
    assert response.status_code == 200, response.text
    assert response.json()['version']['id'] != case['configuration']['version']['id']
    new_result, _, _ = plan_for(client, case['base'], case['prepared'], expected=1, method='spearman')
    assert new_result['id'] != result['id'] and new_result['selection']['method'] == 'spearman'
    response = client.post(case['collection_url'] + '/' + case['collection']['id'] + '/versions',
        json={**case['collection_body'], 'title': 'New explicitly saved report version', 'expected_revision': 1, 'automatic': False},
        headers={'Idempotency-Key': 'new-collection-version'})
    assert response.status_code == 201, response.text
    assert response.json()['current_version_id'] != case['collection']['current_version_id']
    assert client.get(case['report_url']).content == case['docx']
    assert client.get(case['work_url'] + '/figures/' + bundle['figure']['id'] + '/png').content == case['provider'].png
    old = read_bundle(ProjectStore(get_data_dir(), owner_id=task_owner(client)), case['project']['id'],
                      bundle['figure']['id'], bundle['explanation']['id'])
    assert old['result'] == result and old['figure'] == bundle['figure'] and old['explanation'] == bundle['explanation']
    after = frozen_rows()
    for table in ('analysis_runs', 'figure_config_versions', 'figures', 'explanations',
                  'report_collection_versions', 'collection_reports', 'model_calls'):
        by_id = {row['id']: row for row in after[table]}
        assert all(by_id[row['id']] == row for row in before[table]), table
    request.node.user_properties.append(('access_matrix', json.dumps({
        'project_type': project_type, 'same_user_cross_project': same_user,
        'cross_user': cross_user, 'cross_user_original_reads': len(guarded_reads(case)),
        'historical_word_png_and_frozen_rows_preserved': True}, ensure_ascii=False)))
