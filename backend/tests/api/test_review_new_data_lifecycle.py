"""New review data must remain usable while frozen old sources stay protected."""
from io import BytesIO
from openpyxl import Workbook
import pytest
from tests.api.test_analysis import client
from tests.api.test_manuscript_review_v2_bridge import published
from tests.api.test_review_rounds import make_round


def upload_new_data(client, project):
    book = Workbook()
    book.active.append(['Synthetic measurement', 'Cohort'])
    for value in range(1, 14):
        book.active.append([value, 'A' if value < 8 else 'B'])
    content = BytesIO()
    book.save(content)
    book.close()
    response = client.post(f'/api/v1/projects/{project}/files', files={'file': ('SYNTHETIC-supplement.xlsx', content.getvalue())})
    assert response.status_code == 201, response.text
    return f'/api/v1/projects/{project}/files/' + response.json()['file']['id']


@pytest.mark.parametrize('has_round', [False, True])
def test_new_data_can_enter_public_preparation_after_published_review_sources(client, has_round):
    if has_round:
        url, _, _, _ = make_round(client)
        project = url.split('/')[4]
    else:
        root, _, _, _ = published(client)
        project = root.split('/')[4]
    base = upload_new_data(client, project)
    response = client.post(base + '/structure-versions', json={'expected_latest_version': 0}, headers={'Idempotency-Key': 'supplement-structure'})
    assert response.status_code == 202, response.text
    assert response.json()['task']['task_type'] == 'extract_dataset'


def test_corrupt_unresolved_manuscript_task_is_not_silently_ignored_for_new_data(client):
    from app.db.database import database_connection
    from psycopg.types.json import Jsonb
    root, _, _, _ = published(client)
    project = root.split('/')[4]
    with database_connection(write=True) as db:
        task = db.execute("SELECT * FROM tasks WHERE project_id=%s AND task_type='manuscript_draft' ORDER BY created_at LIMIT 1", (project,)).fetchone()
        snapshot = task['input_snapshot'] | {'project_id': 'damaged-project'}
        db.execute('UPDATE tasks SET input_snapshot=%s WHERE id=%s', (Jsonb(snapshot), task['id']))
    base = upload_new_data(client, project)
    response = client.post(base + '/structure-versions', json={'expected_latest_version': 0}, headers={'Idempotency-Key': 'corrupt-supplement'})
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] == 'source_conflict'


def test_project_literature_query_has_no_unrelated_local_file_dependency(client, monkeypatch):
    from tests.api.test_literature import project, create
    monkeypatch.setenv('PAPERASSIST_NCBI_ENABLED', '0')
    identity = project(client)
    search = create(client, identity)
    assert search.status_code == 202, search.text
    base = upload_new_data(client, identity)
    response = client.post(base + '/structure-versions', json={'expected_latest_version': 0}, headers={'Idempotency-Key': 'literature-supplement'})
    assert response.status_code == 202, response.text
