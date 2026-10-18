from contextlib import contextmanager
from types import SimpleNamespace
import pytest

@pytest.fixture(autouse=True)
def postgres_schema():yield None

@pytest.mark.parametrize('kind',['figure','explanation'])
def test_cloud_publication_rechecks_writer_lease_after_verification(monkeypatch,kind):
    from app.domain.figure_workbench import execution
    from app.adapters.task_execution_store import LeaseLost
    calls=[];finished=[]
    class Repository:
        @contextmanager
        def connection(self,**kwargs):yield SimpleNamespace(execute=lambda *a,**k:SimpleNamespace(fetchone=lambda:None))
        def require_lease(self,db,lease):
            calls.append(True)
            if len(calls)>1:raise LeaseLost()
            return {'id':'task'}
        def _finish(self,*a):finished.append(True)
    monkeypatch.setattr(execution,'require_task_sources',lambda *a:None)
    monkeypatch.setattr(execution.TaskStore,'public_task',lambda task:task)
    figure=dict(id='figure',figure_config_version_id='version',analysis_run_id='run',engine={'id':'renderer'},sha256='a'*64,facts_sha256='b'*64)
    repo=Repository()
    if kind=='figure':
        store=SimpleNamespace(assets=SimpleNamespace(figure_png=lambda *a:b'png'))
        with pytest.raises(LeaseLost):execution._publish_figure(repo,None,store,figure)
    else:
        monkeypatch.setattr('app.domain.figure_workbench.explanations.validate_saved',lambda *a:None)
        monkeypatch.setattr('app.domain.figure_workbench.explanations.version_for',lambda *a:'v')
        with pytest.raises(LeaseLost):execution._publish_explanation(repo,None,{'figure':figure},{'id':'exp','figure_id':'figure','analysis_run_id':'run'})
    assert not finished
