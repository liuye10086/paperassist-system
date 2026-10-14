"""Public batch metadata from persisted links, using disposable PostgreSQL assets."""
from uuid import uuid4

from sqlalchemy import event
import pytest

from app.db.database import database_connection, get_engine
from app.core.config import get_data_dir
from tests.api.test_projects import client, create_project, upload  # noqa: F401
from tests.api.test_excel import workbook_bytes
from tests.integration.test_project_ownership import account_client


def batch_files(client, project, count=3, uploaded=(1,), key='batch'):
    content = workbook_bytes()
    items = [{'client_id': str(uuid4()), 'filename': 'same.xlsx' if i < count - 1 else 'bad.csv',
              'size_bytes': len(content)} for i in range(count)]
    base = f"/api/v1/projects/{project['id']}/file-batches"
    response = client.post(base, headers={'Idempotency-Key': key}, json={'items': items})
    assert response.status_code == 201, response.text
    batch = response.json()
    files = []
    for i in uploaded:
        url = base + '/' + batch['id'] + '/items/' + items[i]['client_id']
        accepted = client.post(url, files={'file': ('same.xlsx', content)})
        assert accepted.status_code == 202, accepted.text
        assert client.post(url, files={'file': ('same.xlsx', content)}).json() == accepted.json()
        files.append(accepted.json()['file_id'])
    return batch, files


def snapshot():
    with database_connection() as db:
        tables = [row['tablename'] for row in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=current_schema()')]
        rows = {}
        for table in tables:
            records = [dict(row) for row in db.execute('SELECT * FROM ' + table)]
            if table == 'sessions':
                for record in records:
                    record.pop('last_seen_at')  # Authentication activity is not business metadata.
            rows[table] = sorted(map(repr, records))
    assets = {str(path.relative_to(get_data_dir())): path.read_bytes() for path in get_data_dir().rglob('*') if path.is_file()}
    return rows, assets


def test_summary_pages_details_purposes_legacy_and_ownership(client):
    project = create_project(client)
    batch, files = batch_files(client, project)
    second, more = batch_files(client, project, uploaded=(0, 1), key='second')
    historical = upload(client, project['id']).json()['file']
    base = f"/api/v1/projects/{project['id']}/files"
    expected = {files[0]: {'created_at': batch['created_at'], 'item_count': 3, 'item_position': 2},
                more[0]: {'created_at': second['created_at'], 'item_count': 3, 'item_position': 1},
                more[1]: {'created_at': second['created_at'], 'item_count': 3, 'item_position': 2}, historical['id']: None}
    before = snapshot()
    for size in (1, 2, 5):
        seen = {}
        for page in range(1, (4 + size - 1) // size + 1):
            response = client.get(base + f'?page={page}&page_size={size}')
            assert response.status_code == 200, response.text
            seen.update({item['id']: item['upload_batch'] for item in response.json()['items']})
        assert seen == expected
    for file_id, summary in expected.items():
        assert client.get(base + '/' + file_id + '/details').json()['upload_batch'] == summary
        assert client.get(base + '/' + file_id + '/download').content[:2] == b'PK'
    assert all('upload_batch' not in item for item in client.get(base).json())
    assert 'upload_batch' not in historical
    after = snapshot()
    for table in before[0]:
        assert after[0][table] == before[0][table], table
    assert after[1] == before[1]
    url = base + '/' + files[0]
    body = {'expected_revision': 1, 'purposes': ['paper']}
    saved = client.put(url + '/purposes', json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()['upload_batch'] == expected[files[0]]
    assert client.put(url + '/purposes', json=body).json() == saved.json()
    other_project = create_project(client, 'other')
    assert client.get(f"/api/v1/projects/{other_project['id']}/files/{files[0]}/details").status_code == 404
    with account_client('batch-metadata-other@example.test')[0] as other:
        assert other.get(base + '?page=1').status_code == 404
        assert other.get(url + '/details').status_code == 404
        assert other.put(url + '/purposes', json=body).status_code == 404


def test_page_uses_one_batch_query_and_rejects_broken_reverse_link(client):
    project = create_project(client)
    _, files = batch_files(client, project, count=6, uploaded=(0, 1, 2, 3, 4))
    base = f"/api/v1/projects/{project['id']}/files"
    queries = []
    def listen(conn, cursor, statement, parameters, context, executemany):
        if 'file_upload_batches' in statement and 'SELECT' in statement.upper():
            queries.append(statement)
    engine = get_engine()
    event.listen(engine, 'before_cursor_execute', listen)
    try:
        for size in (1, 5):
            queries.clear()
            response = client.get(base + f'?page=1&page_size={size}')
            assert all(item['upload_batch']['item_count'] == 6 for item in response.json()['items'])
            assert len(queries) == 1
    finally:
        event.remove(engine, 'before_cursor_execute', listen)
    with database_connection(write=True) as db:
        db.execute('UPDATE file_upload_items SET file_id=NULL WHERE file_id=%s', (files[0],))
    assert client.get(base + '/' + files[0] + '/details').json()['upload_batch'] is None


@pytest.mark.parametrize('boundary', ['project', 'owner'])
def test_summary_does_not_expose_batch_from_different_scope(client, boundary):
    project = create_project(client)
    batch, files = batch_files(client, project)
    other_project = create_project(client, 'other')
    with account_client('summary-scope@example.test')[0] as other:
        user_id = other.get('/api/v1/auth/me').json()['user']['id']
    with database_connection(write=True) as db:
        if boundary == 'project':
            db.execute('UPDATE file_upload_batches SET project_id=%s WHERE id=%s', (other_project['id'], batch['id']))
        else:
            db.execute('UPDATE file_upload_batches SET user_id=%s WHERE id=%s', (user_id, batch['id']))
    base = f"/api/v1/projects/{project['id']}/files"
    assert client.get(base + '?page=1').json()['items'][0]['upload_batch'] is None
    assert client.get(base + '/' + files[0] + '/details').json()['upload_batch'] is None
