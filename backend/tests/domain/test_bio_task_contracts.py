from pydantic import TypeAdapter
from app.domain.tasks.contracts import TaskType
from app.domain.file_lifecycle.references import file_ids, frozen_references
from tests.api.test_projects import client


def test_bio_import_is_a_public_task_type():
    assert TypeAdapter(TaskType).validate_python('bio_import')=='bio_import'


def test_bio_frozen_source_ids_remain_bio_sources():
    snapshot={'kind':'bio_import','dataset_id':'d','files':[{'id':'f','sha256':'a'*64}],
              'source_file_ids':['f'], 'source':{'kind':'bio_dataset_version','dataset_id':'d','version_id':'v','project_id':'p'}}
    assert 'f' in file_ids(snapshot)
    refs=set(frozen_references(snapshot))
    assert ('bio_dataset_versions','v') in refs
    assert ('dataset_versions','d') not in refs


def test_corrupt_candidate_has_no_approve_action_in_workspace(client):
    from tests.integration.test_bio_import_publication import create_import,run
    from app.db.database import database_connection
    from app.adapters.bio_objects import BioObjects
    from app.core.config import get_data_dir
    _,created,_,_=create_import(client)
    task=run(created['task'])
    assert task['status']=='waiting_confirmation',task
    before=client.get('/api/v1/tasks/'+task['id']+'/workspace')
    assert before.status_code==200,before.text
    assert before.json()['allowed_actions']==['approve']
    with database_connection() as db:
        state=db.execute('SELECT state_json FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()['state_json']
    record=state['candidate']
    path=BioObjects(get_data_dir()).path(record['object_key'])
    path.write_bytes(b'x'*record['size_bytes'])
    after=client.get('/api/v1/tasks/'+task['id']+'/workspace')
    assert after.status_code==200,after.text
    assert after.json()['allowed_actions']==[]
