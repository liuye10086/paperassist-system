import pytest

from tests.api.test_projects import client, create_project


def test_public_batch_file_resolves_private_object_key_without_losing_scope_or_hash(client):
    from tests.api.test_file_batches import register
    from app.adapters.task_store import DatasetTaskAssets
    from app.core.config import get_data_dir
    from app.core.exceptions import StorageError
    from app.db.database import database_connection, get_database_config
    project = create_project(client)
    base, batch, item, content = register(client, project)
    uploaded = client.post(base+'/'+batch['id']+'/items/'+item['client_id'],
                           files={'file': (item['filename'], content)})
    assert uploaded.status_code == 202, uploaded.text
    with database_connection() as db:
        owner = db.execute('SELECT owner_id FROM projects WHERE id=%s', (project['id'],)).fetchone()['owner_id']
    assets = DatasetTaskAssets(owner, get_database_config(), get_data_dir())
    record = assets.file(project['id'], uploaded.json()['file_id'])
    assert 'object_key' not in record
    assert assets.original(record) == content
    assert 'object_key' not in record
    with pytest.raises(StorageError): assets.original({**record, 'sha256': '0'*64})
    with pytest.raises(StorageError): assets.original({**record, 'size_bytes': record['size_bytes']+1})
    with pytest.raises(StorageError):
        DatasetTaskAssets('different-owner', get_database_config(), get_data_dir()).original(record)
    other = create_project(client)
    with pytest.raises(StorageError): assets.original({**record, 'project_id': other['id']})
