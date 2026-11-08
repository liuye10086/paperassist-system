"""An interrupted local snapshot write must be recoverable by the same request."""
import pytest
from tests.api.test_projects import client
from tests.api.test_single_cell_direct_start import ready_single_cell


@pytest.mark.parametrize('failure_point',['task_insert','snapshot_write'])
def test_snapshot_insert_failure_same_request_recovers_exact_local_bytes(client,ready_single_cell,monkeypatch,failure_point):
    from app.adapters.storage import ProjectStore
    from app.adapters.task_store import TaskStore
    from app.adapters.bio_objects import BioAnalysisObjects
    from app.core.config import get_data_dir
    from app.db.database import database_connection
    from app.domain.bioinformatics.analysis_service import BioAnalysisService
    from app.domain.bioinformatics.single_cell_contracts import SingleCellAnalysisStartRequest
    from app.domain.storage_governance.service import _key
    from pathlib import Path
    import hashlib,json
    fixture=ready_single_cell;project=fixture['source']['project_id']
    with database_connection() as db:owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(project,)).fetchone()['owner_id']
    service=BioAnalysisService(ProjectStore(get_data_dir(),owner_id=owner))
    request=SingleCellAnalysisStartRequest(name='Interrupted snapshot',raw_source=fixture['source'],params={'min_spots':1})
    original=TaskStore.insert_task
    def fail_once(db,task,**kwargs):
        if task['task_type']=='bio_analysis':raise RuntimeError('synthetic insert failure after snapshot write')
        return original(db,task,**kwargs)
    original_write=BioAnalysisObjects.write
    def fail_write(*args,**kwargs):raise RuntimeError('synthetic snapshot failure before byte write')
    if failure_point=='task_insert':monkeypatch.setattr(TaskStore,'insert_task',staticmethod(fail_once))
    else:monkeypatch.setattr(BioAnalysisObjects,'write',fail_write)
    with pytest.raises(RuntimeError,match='synthetic'):
        service.start_single_cell(project,request,'interrupted')
    intents=[json.loads(path.read_bytes()) for path in (Path(get_data_dir())/'.storage-intents').glob('*.json')]
    snapshots=[row for row in intents if row.get('kind')=='bio_analysis']
    assert len(snapshots)==1
    path=Path(get_data_dir())/snapshots[0]['object_key'];sha=snapshots[0]['sha256']
    content=path.read_bytes() if path.exists() else None
    assert (content is not None)==(failure_point=='task_insert')
    monkeypatch.setattr(TaskStore,'insert_task',staticmethod(original))
    monkeypatch.setattr(BioAnalysisObjects,'write',original_write)
    recovered=service.start_single_cell(project,request,'interrupted')
    assert recovered['task']['status']=='queued'
    if content is not None:assert path.read_bytes()==content
    assert hashlib.sha256(path.read_bytes()).hexdigest()==sha
    assert client.get(fixture['base']+'/bio-requests/interrupted?kind=run').json()['id']==recovered['id']
    with database_connection() as db:
        reservation=db.execute('SELECT * FROM storage_reservations WHERE project_id=%s AND object_key=%s',(project,_key(get_data_dir(),path))).fetchone()
        assert reservation['state']=='settled' and reservation['sha256']==sha
        assert db.execute('SELECT count(*) AS n FROM bio_analysis_runs WHERE project_id=%s',(project,)).fetchone()['n']==1
        assert db.execute('SELECT count(*) AS n FROM bio_analysis_recipe_versions WHERE project_id=%s',(project,)).fetchone()['n']==1
        assert db.execute("SELECT count(*) AS n FROM storage_reservations WHERE project_id=%s AND state='unknown'",(project,)).fetchone()['n']==0
