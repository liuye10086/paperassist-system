"""Analyst task admissions use the exact published worksheet lineage."""
from fastapi.testclient import TestClient

from app.db.database import database_connection
from app.main import app
from tests.api.test_customer_workspace import create_customer_project, sign_in
from tests.api.test_dataset_analysis import version
from tests.api.test_excel import workbook_bytes
from tests.api.test_project_assignments import assign
from tests.integration.test_batch07_quality_pipeline import quality_task
from tests.integration.test_batch09_filter_pipeline import accept, filtering
from tests.integration.test_research_plan import research


def test_assigned_plans_and_recommendations_follow_published_quality_lineage():
    owner, admin, analyst = (TestClient(app) for _ in range(3))
    sign_in(owner, 'table-owner@example.test', 'customer')
    sign_in(admin, 'table-admin@example.test', 'admin')
    analyst_id = sign_in(analyst, 'table-analyst@example.test', 'analyst')
    project = create_customer_project(owner)
    assert assign(admin, project, analyst_id, 0).status_code == 200
    uploaded = owner.post(project + '/files', files={'file': ('worksheet.xlsx', workbook_bytes())})
    assert uploaded.status_code == 201, uploaded.text
    file = uploaded.json()['file']['id']
    base = project + '/files/' + file
    raw = version(analyst, base)
    defaults = analyst.get(base + '/dataset-versions/' + raw['id'] + '/preparation-defaults').json()
    prepared = analyst.post(base + '/dataset-preparations', headers={'Idempotency-Key': 'prepare'},
                            json={'dataset_id': raw['id'], 'recipe': defaults['recipe']})
    original, _, _ = accept(analyst, prepared.json())

    def plan(source, key):
        return analyst.post(project + '/analysis-plans', headers={'Idempotency-Key': key}, json={
            'schema_version': 5, 'input_kind': 'data', 'file_id': file, 'dataset_id': source['id'],
            'expected_setup_revision': 0, 'selection': None, 'research_request': research(),
        })

    def recommendation(source, key):
        path = base + '/analysis-recommendations'
        body = {'schema_version': 5, 'dataset_id': source['id'], 'sheet_name': source['source']['sheet_name'],
                'candidate_columns': ['B'], 'output_language': 'en', 'research_summary': ''}
        preview = analyst.post(path + '/preview', json=body)
        assert preview.status_code == 200, preview.text
        metadata = preview.json()
        body['external_processing'] = {'version': 1, 'confirmed': True, 'source_digest': metadata['source_digest'],
                                       'labels': {item['key']: item['value'] for item in metadata['labels']}}
        return analyst.post(path, headers={'Idempotency-Key': key}, json=body)

    pending, _ = quality_task(analyst, base, original)
    for create in (plan, recommendation):
        response = create(original, 'pending-qc')
        assert response.status_code == 409, response.text
        assert response.json()['detail']['code'] == 'analysis_quality_required'
    with database_connection() as db:
        assert db.execute("SELECT count(*) AS n FROM tasks WHERE task_type IN ('analysis_plan','analysis_recommendation')").fetchone()['n'] == 0

    quality, _, _ = accept(analyst, pending)
    recipe = {'conditions': [{'column': 2, 'kind': 'number', 'operator': 'gt', 'value': '2'}],
              'reason': 'Synthetic subset', 'unit_acknowledged': True}
    sibling_task, _ = filtering(analyst, base, original, key='sibling', recipe=recipe)
    sibling, _, _ = accept(analyst, sibling_task)
    child_task, _ = filtering(analyst, base, quality, key='child', recipe=recipe)
    child, _, _ = accept(analyst, child_task)
    v3_task, _ = quality_task(analyst, base, sibling, key='v3-quality')
    v3_quality, _, _ = accept(analyst, v3_task)
    listed = analyst.get(base + '/prepared-dataset-versions').json()['items']
    assert {item['id']: item['quality_confirmed'] for item in listed} == {
        original['id']: False, sibling['id']: False, quality['id']: True, child['id']: True, v3_quality['id']: True,
    }
    for source in (original, sibling):
        blocked = plan(source, 'unchecked-' + source['id'])
        assert blocked.status_code == 409 and blocked.json()['detail']['code'] == 'analysis_quality_required'
    for source in (quality, child, v3_quality):
        admitted = plan(source, source['id'])
        assert admitted.status_code == 202, admitted.text
        assert plan(source, source['id']).json()['id'] == admitted.json()['id']
    wrong_sheet = analyst.post(base + '/analysis-recommendations/preview', json={
        'schema_version': 5, 'dataset_id': child['id'], 'sheet_name': '空表', 'candidate_columns': ['B'],
        'output_language': 'en', 'research_summary': ''})
    assert wrong_sheet.status_code == 422
    other_file = owner.post(project + '/files', files={'file': ('other.xlsx', workbook_bytes())}).json()['file']['id']
    wrong_file = analyst.post(project + '/analysis-plans', headers={'Idempotency-Key': 'wrong-file'}, json={
        'schema_version': 5, 'input_kind': 'data', 'file_id': other_file, 'dataset_id': child['id'],
        'expected_setup_revision': 0, 'selection': None, 'research_request': research(),
    })
    assert wrong_file.status_code == 404
    admitted = recommendation(child, 'quality-recommendation')
    assert admitted.status_code == 202, admitted.text
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
