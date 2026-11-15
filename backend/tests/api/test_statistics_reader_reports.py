"""Fixed statistics reports through the formal HTTP and export entry points."""
from io import BytesIO
import json
from zipfile import ZipFile

import pytest

from app.db.database import database_connection
from tests.api.test_projects import create_project
from tests.api.test_reader_report_narratives import reader_policy  # noqa: F401
from tests.integration.test_reports import client, cloud, report_ready, writer  # noqa: F401


def selection_for(base, file, result, figure, explanation):
    project = base.split('/')[4]
    return project, dict(kind='analysis', file_id=file['id'], analysis_run_id=result['id'],
                         figure_id=figure['id'], explanation_id=explanation['id'])


def call_count():
    with database_connection() as db:
        return db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']


def prepare(client, project, selection, language='zh-CN', key='statistics-prepare', **changes):
    return client.post(f'/api/v1/projects/{project}/statistics-reader-reports/prepare',
                       json={'title': '统计结果' if language == 'zh-CN' else 'Statistical results',
                             'language': language, 'selection': selection, **changes},
                       headers={'Idempotency-Key': key})


def test_prepare_requires_a_project_owned_existing_run(client):
    project = create_project(client)['id']
    response = prepare(client, project, dict(kind='analysis', file_id='missing-file', analysis_run_id='missing-run',
                                              figure_id=None, explanation_id=None))
    assert response.status_code == 404 and response.json()['detail']['code'] == 'research_source_not_found'


def test_saved_explanation_exports_exact_png_without_creating_a_model_call(client, cloud, writer, tmp_path):
    from app.adapters.research_report_render import render_report
    from app.domain.research_results.execution import run_research_report_task
    from app.adapters.storage import get_project_store

    base, file, result, figure, explanation, _ = report_ready(client)
    project, selection = selection_for(base, file, result, figure, explanation)
    scope = f'/api/v1/projects/{project}'
    endpoint = scope + '/statistics-reader-reports'
    count = call_count()
    prepared = prepare(client, project, selection)
    assert prepared.status_code == 201, prepared.text
    view = prepared.json()
    assert view['source']['source_kind'] == 'statistics_report_context'
    assert view['selection'] == selection
    assert view['local_reuse']['available'] is True
    assert view['local_reuse']['origin'] == 'saved_explanation_reuse'
    model_preview = client.post(scope + '/research-report-narratives/preview', json=view['report'])
    assert model_preview.status_code == 200, model_preview.text
    assert model_preview.json()['figures'][0]['number'] == 1
    for fetched in (prepare(client, project, selection), prepare(client, project, selection, key='another-key'),
                    client.get(endpoint + '/requests/statistics-prepare'), client.get(endpoint + '/' + view['id'])):
        assert fetched.status_code == 200, fetched.text
        assert fetched.json() == view
    assert prepare(client, project, selection, title='不同标题').status_code == 409
    assert prepare(client, project, selection, 'en', key='wrong-language').status_code in (409, 422)
    assert prepare(client, project, selection | {'explanation_id': 'missing'}, key='wrong-dependency').status_code in (404, 409)
    other = create_project(client)['id']
    assert prepare(client, other, selection).status_code == 404
    assert client.get(f'/api/v1/projects/{other}/statistics-reader-reports/' + view['id']).status_code == 404
    exported = client.post(scope + '/research-reports', json=view['report'], headers={'Idempotency-Key': 'local-export'})
    assert exported.status_code == 201, exported.text
    created = exported.json()
    done = run_research_report_task(created['task_id'], created['task']['revision'],
                                    engine=render_report, staging_directory=tmp_path / 'render')
    assert done['status'] == 'succeeded', done
    listing = client.get(endpoint + '/' + view['id'] + '/reports')
    assert listing.status_code == 200, listing.text
    published, = listing.json()['items']
    assert published['id'] == created['id']
    members = {m['role']: client.get(m['download_url']) for m in published['members']}
    assert set(members) == {'docx', 'xlsx', 'zip'}
    assert all(response.status_code == 200 for response in members.values())
    original_png = get_project_store().figure_png(figure)
    with ZipFile(BytesIO(members['zip'].content)) as archive:
        assert archive.read('analysis.docx') == members['docx'].content
        assert archive.read('results.xlsx') == members['xlsx'].content
        assert archive.read('figures/figure_01/selected_png.png') == original_png
        assert any(name.endswith('/rebuild_projection.py') for name in archive.namelist())
    from PIL import Image
    with ZipFile(BytesIO(members['docx'].content)) as archive:
        image, = [name for name in archive.namelist() if name.startswith('word/media/')]
        with Image.open(BytesIO(archive.read(image))) as displayed, Image.open(BytesIO(original_png)) as original:
            assert displayed.size == original.size
            assert displayed.convert('RGB').tobytes() == original.convert('RGB').tobytes()
    from docx import Document
    prose = '\n'.join(paragraph.text for paragraph in Document(BytesIO(members['docx'].content)).paragraphs)
    assert '复用已核对引用的历史图解' in prose
    for token in ('field_path', 'setup_revision', 'execution_contract', result['id'], file['sha256']):
        assert token not in prose
    from openpyxl import load_workbook
    with BytesIO(members['xlsx'].content) as stream:
        workbook = load_workbook(stream, read_only=True, data_only=False)
        sheets = {sheet.title: list(sheet.values) for sheet in workbook}
        workbook.close()
    assert ('指标或项目', '数值或内容', '单位', '可用性') == sheets['分析01 总体摘要'][0]
    assert any(value[0] == '最小值' and value[1] == '0.0' and value[2] == 'mg/L' for value in sheets['分析01 总体摘要'])
    assert any(value[1] == 'NA' and value[3] for value in sheets['分析01 分组结果'][1:])
    assert ('分析类型', '描述统计与箱线图', None, None) in sheets['分析01 分析选项']
    cells = {str(cell) for rows in sheets.values() for row in rows for cell in row if cell is not None}
    for token in ('field_path', 'raw_type', 'raw_value', 'setup_revision', 'exclude_selected_missing', 'descriptive_boxplot',
                  result['id'], file['sha256'], figure['sha256']):
        assert all(token not in value for value in cells)
    with database_connection() as db:
        row = db.execute('SELECT content_json FROM research_report_versions WHERE id=%s', (published['id'],)).fetchone()
        record = row['content_json']['reader_report']
        assert record['origin'] == 'saved_explanation_reuse'
        assert 'model_call_id' not in record
        assert record['binding_sha256'] == model_preview.json()['binding_sha256']
        assert record['sources'][0]['explanation_id'] == explanation['id']
        assert len(record['narrative']) == 7
        assert len(record['figures']) == 1
    replay = client.post(scope + '/research-reports', json=view['report'], headers={'Idempotency-Key': 'second-export'})
    assert replay.status_code == 200 and replay.json()['id'] == published['id']
    assert call_count() == count

    # The local record is authorized by the saved prepare receipt. Merely
    # citing the same statistics source does not waive the standard R1 gate.
    unprepared = client.post(scope + '/research-findings',
                             json=dict(title='Separate finding', sources=[{key: view['source'][key] for key in
                                                                           ('source_kind', 'source_id', 'sha256')}]),
                             headers={'Idempotency-Key': 'unprepared-finding'})
    assert unprepared.status_code == 201, unprepared.text
    reply = client.post(scope + '/research-reports',
                        json=view['report'] | {'finding_version_id': unprepared.json()['id']},
                        headers={'Idempotency-Key': 'unprepared-export'})
    assert reply.status_code == 409 and reply.json()['detail']['code'] == 'reader_report_narrative_required'


def test_result_without_selected_figure_can_be_fixed_but_requires_explicit_reader_narrative(client, cloud, writer, reader_policy):
    base, file, result, figure, explanation, _ = report_ready(client)
    project, selection = selection_for(base, file, result, figure, explanation)
    scope = f'/api/v1/projects/{project}'
    assert prepare(client, project, selection | {'explanation_id': None}, key='half-selection').status_code == 422
    response = prepare(client, project, selection | {'figure_id': None, 'explanation_id': None})
    assert response.status_code == 201, response.text
    view = response.json()
    assert view['local_reuse']['available'] is False
    preview = client.post(scope + '/research-report-narratives/preview', json=view['report'])
    assert preview.status_code == 200, preview.text
    assert preview.json()['figures'] == []
    exported = client.post(scope + '/research-reports', json=view['report'], headers={'Idempotency-Key': 'missing-local'})
    assert exported.status_code == 409, exported.text
    assert exported.json()['detail']['code'] == 'reader_report_narrative_required'


def saved_artifact(done, kind):
    assert done['status'] == 'succeeded', done
    table, column = ('figures', 'figure_json') if kind == 'figure' else ('explanations', 'explanation_json')
    with database_connection() as db:
        row = db.execute(f'SELECT {column} FROM {table} WHERE id=%s', (done['result_' + kind + '_id'],)).fetchone()
    return json.loads(row[column])


def prepare_descriptive_en(client):
    from tests.api.test_analysis import selection
    from tests.domain.test_correlation_plan_contracts import research
    from tests.helpers.statistics import statistics_post
    from tests.integration.test_comparison_plan import approve, make_plan
    from tests.integration.test_correlation_plan import prepared_correlations

    base, file, prepared = prepared_correlations(
        client, rows=[['Concentration', 'Group'], [0, 'A'], [1, 'A'], [2, 'A'], [None, 'B'], [4, 'B']])
    declaration = dict(research(), output_language='en')
    chosen = selection(sheet_name=prepared['source']['sheet_name'], group_column=None, unit='')
    task, _ = make_plan(client, base, prepared, chosen, declaration, key='descriptive-reader')
    approve(client, task)
    response = statistics_post(client, base + '/analysis-runs', json={'expected_revision': 1})
    assert response.status_code == 200, response.text
    return base, file, response.json()


def seed_statistics_reader_selection(client, kind, language):
    """Build real test statistics/artifacts, with explicit synthetic provider responses."""
    from tests.integration.test_boxplot_execution import SyntheticPlotProvider
    from tests.integration.test_comparison_artifact_chain import (
        ComparisonPlotProvider, comparison_task, result_for as comparison_result,
    )
    from tests.integration.test_correlation_artifact_chain import (
        ModernExplanationProvider, ModernPlotProvider, finish_plot, modern_task, result_for as correlation_result,
    )
    from tests.integration.test_explanation_execution import run as run_explanation
    from tests.integration.test_modeling_artifact_chain import (
        ModelingPlotProvider, artifact_task, result_for as modeling_result,
    )

    if kind == 'descriptive':
        if language == 'zh-CN':
            return report_ready(client)[:5]
        base, file, result = prepare_descriptive_en(client)

        class EnglishBoxplotProvider(SyntheticPlotProvider):
            def receipt(self):
                value = super().receipt()
                annotations = value['response']['output'][1]['content'][0]['annotations']
                annotations[0]['filename'] = '/mnt/data/figure.png'
                return value

            def download(self, file_id, container_id, limit, *, policy):
                raw = super().download(file_id, container_id, limit, policy=policy)
                if file_id == 'cfile_png':
                    return raw
                value = json.loads(raw)
                value.pop('analysis_run_id')
                value.pop('source_sha256')
                value.update({key: self.payload[key] for key in ('schema_version', 'figure_kind', 'language', 'plot_config')})
                return json.dumps(value).encode()

        task_factory, provider = modern_task, EnglishBoxplotProvider(result, pending=False)
    elif kind == 'correlation':
        base, file, result = correlation_result(client, language)
        task_factory, provider = modern_task, ModernPlotProvider()
    elif kind == 'group_comparison':
        base, file, result = comparison_result(client, 'welch_t', language)
        task_factory, provider = comparison_task, ComparisonPlotProvider()
    else:
        method = {'regression': 'ols', 'roc': 'roc_auc', 'survival': 'kaplan_meier'}[kind]
        base, file, result = modeling_result(client, method, language)
        task_factory, provider = artifact_task, ModelingPlotProvider()
    plot_task, _ = task_factory(client, base, file, result, 'boxplot')
    figure = saved_artifact(finish_plot(plot_task, provider), 'figure')
    task, _ = task_factory(client, base, file, result, 'explanation', figure)
    explanation = saved_artifact(run_explanation(task, ModernExplanationProvider()), 'explanation')
    return base, file, result, figure, explanation


@pytest.mark.parametrize('language', ('zh-CN', 'en'))
@pytest.mark.parametrize('kind', ('descriptive', 'correlation', 'group_comparison', 'regression', 'roc', 'survival'))
def test_six_statistics_types_and_both_languages_reuse_exact_saved_material(client, cloud, writer, language, kind):
    base, file, result, figure, explanation = seed_statistics_reader_selection(client, kind, language)
    project, selection = selection_for(base, file, result, figure, explanation)
    before = call_count()
    response = prepare(client, project, selection, language)
    assert response.status_code == 201, response.text
    view = response.json()
    assert view['local_reuse']['available'] is True
    report = client.post(f'/api/v1/projects/{project}/research-reports', json=view['report'],
                         headers={'Idempotency-Key': 'bilingual-reader'})
    assert report.status_code == 201, report.text
    snapshot = report.json()['content']
    assert snapshot['language'] == language
    assert snapshot['figures'][0]['document_image']['sha256'] == figure['sha256']
    assert snapshot['reader_report']['sources'][0]['explanation_id'] == explanation['id']
    assert all(snapshot['reader_report']['narrative'].values())
    assert set(snapshot['reader_report']['figures'][0]) == {
        'number', 'title', 'reading', 'observations', 'interpretation', 'limitations', 'caption'}
    assert call_count() == before


def seed_ordered_collection(client, monkeypatch, *, automatic=False):
    """Persist two distinct figures/runs and an ordered version in the test schema."""
    from app.adapters.collection_store import CollectionStore
    from app.domain.report_collections.contracts import CollectionRequest
    from tests.api.test_analysis_writing_handoff import next_run
    from tests.api.test_collection_writing_handoff import second_plot
    from tests.api.test_review_figure_adoptions import actual_plot

    first = actual_plot(client, monkeypatch)
    second = second_plot(first, next_run(client, first), monkeypatch)
    project = first['project']
    items = [dict(figure_id=item['figure']['id'], explanation_id=explain_collection_item(item, monkeypatch),
                  caption=caption) for item, caption in ((second, 'Second run author caption'), (first, 'First run author caption'))]
    repository = CollectionStore(first['workbench'].assets)
    state = repository.create(project, CollectionRequest(title='Ordered statistics', language='en', items=items, automatic=automatic),
                              'ordered-statistics')
    return dict(project_id=project, repository=repository, state=state, items=items, runs=[second, first],
                selection=dict(kind='collection', collection_id=state['id'], collection_version_id=state['current_version_id']))


def explain_collection_item(item, monkeypatch):
    from app.adapters.figure_workbench_store import read_bundle
    from app.adapters.report_store import digest
    from app.domain.figure_workbench.contracts import GenerateFigure
    from app.domain.figure_workbench.execution import run_figure_explanation_task
    from app.domain.figure_workbench.explanation_v5 import sentence_draft_v5
    from app.domain.figure_workbench.explanations import build_payload
    from app.domain.figure_workbench.tasks import prompt_version, submit
    from tests.integration.test_explanation_execution import SyntheticProvider

    def policy(payload, explanation=False):
        assert explanation
        model = 'test-explanation'
        return dict(policy=dict(model=model, prompt_version=prompt_version(payload, explanation=True), max_output_tokens=10000,
                                timeout_seconds=15, tools=[], output_format='analysis_explanation_v1',
                                price=dict(version='synthetic-only', model=model, input_micro_usd_per_million=100,
                                           cached_input_micro_usd_per_million=50, output_micro_usd_per_million=200)),
                    input_token_allowance=100000, task_limit_micro_usd=500000)

    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for', policy)
    workbench, project, figure = item['workbench'], item['project'], item['figure']
    payload = build_payload(read_bundle(workbench.assets, project, figure['id']))
    task = submit(workbench, project, item['file']['id'], item['result']['id'], item['config_id'],
                  GenerateFigure(idempotency_key='r3-explanation-' + figure['id'],
                                 external_processing=dict(confirmed=True, payload_sha256=digest(payload))),
                  figure_id=figure['id'])['task']

    class Provider(SyntheticProvider):
        def receipt(self):
            receipt = super().receipt()
            response_id = 'resp_r3_explanation_' + figure['id']
            receipt.update(response_id=response_id)
            receipt['response']['id'] = response_id
            sent = self.posts[0][1]
            draft = sentence_draft_v5(sent)
            receipt['response']['output'][0]['content'][0]['text'] = json.dumps(draft)
            return receipt

    provider = Provider()
    for _ in range(5):
        task = run_figure_explanation_task(task['id'], task['revision'], provider_factory=lambda: provider)
        if task['status'] in ('succeeded', 'failed'):
            break
    assert task['status'] == 'succeeded', task
    return task['result_explanation_id']


def test_collection_keeps_order_and_exact_dependencies_after_a_new_version(client, monkeypatch, tmp_path):
    from app.adapters.research_report_render import render_report
    from app.domain.research_results.execution import run_research_report_task

    fixture = seed_ordered_collection(client, monkeypatch)
    project, selected, state, items = (fixture[key] for key in ('project_id', 'selection', 'state', 'items'))
    second, first = fixture['runs']
    before = call_count()
    early = prepare(client, project, selected, 'en')
    assert early.status_code == 201, early.text
    first_view = early.json()
    assert [run['id'] for run in first_view['source']['supporting_sources']] == [second['result']['id'], first['result']['id']]
    update = client.post(f'/api/v1/projects/{project}/report-collections/{state["id"]}/versions',
                         json=dict(title='Reordered statistics', language='en', items=items[::-1], automatic=False, expected_revision=1),
                         headers={'Idempotency-Key': 'reverse-statistics'})
    assert update.status_code in (200, 201), update.text
    swapped = selected | {'collection_version_id': update.json()['current_version_id']}
    next_view = prepare(client, project, swapped, 'en', key='reverse-prepare')
    assert next_view.status_code == 201, next_view.text
    assert next_view.json()['id'] != first_view['id']
    assert [source['id'] for source in next_view.json()['source']['supporting_sources']] == [first['result']['id'], second['result']['id']]
    assert prepare(client, project, selected, 'en').json() == first_view
    assert prepare(client, project, selected, 'zh-CN', key='wrong-collection-language').status_code == 422
    report = client.post(f'/api/v1/projects/{project}/research-reports', json=first_view['report'],
                         headers={'Idempotency-Key': 'original-order'})
    assert report.status_code == 201, report.text
    content = report.json()['content']
    assert [f['document_image']['sha256'] for f in content['figures']] == [second['figure']['sha256'], first['figure']['sha256']]
    summary_order = list(dict.fromkeys(t['source']['source_id'] for t in content['tables']))
    assert summary_order == [second['result']['id'], first['result']['id']]
    assert sum('Saved projection' in t['key'] for t in content['tables']) == 2
    assert ['Second run author caption' in f['interpretation'] for f in content['reader_report']['figures']] == [True, False]
    assert 'figure projection used' in content['reader_report']['figures'][0]['observations']
    job = report.json()
    done = run_research_report_task(job['task_id'], job['task']['revision'], engine=render_report,
                                    staging_directory=tmp_path / 'ordered-render')
    assert done['status'] == 'succeeded', done
    path = f'/api/v1/projects/{project}/statistics-reader-reports/{first_view["id"]}/reports/{job["id"]}'
    package = client.get(path + '/members/zip/download')
    assert package.status_code == 200, package.text
    with ZipFile(BytesIO(package.content)) as archive:
        assert archive.read('figures/figure_01/selected_png.png') == second['png']
        assert archive.read('figures/figure_02/selected_png.png') == first['png']
    assert call_count() == before


def test_collection_without_resolved_dependencies_creates_no_context_or_model_call(client, monkeypatch):
    from tests.integration.test_batch05_collection_pipeline import pending_collection
    _, _, project, _, _, _, state = pending_collection(client, monkeypatch)
    before = call_count()
    selection = dict(kind='collection', collection_id=state['id'], collection_version_id=state['current_version_id'])
    response = prepare(client, project, selection, 'en')
    assert response.status_code == 422, response.text
    assert response.json()['detail']['code'] == 'research_source_incomplete'
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM statistics_report_context_versions').fetchone()['n'] == 0
    assert call_count() == before


def test_file_retention_owner_erasure_and_customer_permission(client, cloud, writer):
    from app.auth.service import create_user
    from app.domain.account_deletion import delete_account
    from app.maintenance.research_results_audit import audit_research_task_sources
    from tests.api.test_admin_operations import PASSWORD
    from tests.integration.test_project_ownership import account_client

    base, file, result, figure, explanation, _ = report_ready(client)
    project, selection = selection_for(base, file, result, figure, explanation)
    prepared = prepare(client, project, selection)
    assert prepared.status_code == 201, prepared.text
    assessment = client.get(base + '/lifecycle/assessment', params={'action': 'delete'})
    assert assessment.status_code == 200, assessment.text
    assert {'code': 'research_results_history_retained'} in assessment.json()['reasons']
    assert assessment.json()['physical_deletion_available'] is False
    stranger, _ = account_client('statistics-stranger@paperassist.local', role='analyst')
    customer, _ = account_client('statistics-customer@paperassist.local', role='customer')
    try:
        project_context = f'/api/v1/projects/{project}/statistics-reader-reports'
        assert prepare(stranger, project, selection).status_code == 404
        assert customer.get(project_context + '/' + prepared.json()['id']).status_code == 403
        assert prepare(customer, project, selection).status_code == 403
    finally:
        stranger.close()
        customer.close()
    with database_connection() as db:
        owner = db.execute('SELECT owner_id FROM projects WHERE id=%s', (project,)).fetchone()['owner_id']
        checks = audit_research_task_sources(db)
        context = next(check for check in checks if check['table'] == 'statistics_report_context_versions')
        assert context['rows'] == 1 and context['invalid'] == 0
    operator = create_user('statistics-admin@paperassist.local', PASSWORD, 'admin')
    assert delete_account(operator['id'], owner, 1)['deleted']
    with database_connection() as db:
        from app.db.statistics_report_context_schema import TABLE_NAMES
        assert all(not db.execute('SELECT 1 FROM ' + table + ' WHERE project_id=%s', (project,)).fetchone()
                   for table in TABLE_NAMES)
