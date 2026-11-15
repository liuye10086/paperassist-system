"""R3 source phases keep the numeric budget out of render and failure writes."""
from contextlib import contextmanager
from types import SimpleNamespace
import sys

import pytest


@pytest.fixture(autouse=True)
def postgres_schema():yield None


@pytest.mark.skipif(sys.platform!='linux',reason='The production numerical scope requires Linux main thread')
@pytest.mark.parametrize('failure',('direct','wrapped','alarm'))
def test_one_validation_scope_is_bounded_and_exits_before_failure_persistence(monkeypatch,failure):
    from app.domain.statistics_reader_reports.validation import worker_verification,validate_sources
    from app.domain.fixed_statistics_runtime import scope_active,remaining_seconds
    from app.domain.statistics_execution.verification import should_recompute
    from app.domain.regression.common import NumericError
    from app.core.exceptions import StorageError
    calls=[]
    def verify():
        assert scope_active() and should_recompute()
        assert 0<remaining_seconds()<=60
        calls.append('source')
        if failure=='alarm':
            import signal,time
            signal.setitimer(signal.ITIMER_REAL,0.01)
            time.sleep(0.1)
            raise AssertionError('The real Linux deadline handler must interrupt this wait')
        try:raise NumericError('numeric_timeout','Injected complete-source deadline')
        except NumericError as exc:
            if failure=='wrapped':raise StorageError('database_configuration','Wrapped DB exception') from exc
            raise
    with worker_verification():
        assert not scope_active() and not should_recompute()
        with pytest.raises(StorageError) as caught:validate_sources(verify)
        assert caught.value.code=='numeric_timeout'
        assert caught.value.execution_receipt['error_code']=='numeric_timeout'
        assert not scope_active() and not should_recompute()
        # A second whole-source phase has its own unchanged 60s boundary;
        # no numerical scope remains around rendering or failure persistence.
        assert validate_sources(lambda:(scope_active(),should_recompute()))==(True,True)
        assert not scope_active()
    assert calls==['source']
    assert validate_sources(lambda:(scope_active(),should_recompute()))==(False,False)


@pytest.mark.skipif(sys.platform!='linux',reason='The production numerical scope requires Linux main thread')
@pytest.mark.parametrize('outer_rollback',(False,True))
def test_real_executor_records_timeout_and_allows_explicit_same_task_retry(monkeypatch,tmp_path,outer_rollback):
    from app.domain.statistics_reader_reports import legacy_exports as legacy
    from app.domain.statistics_reader_reports.validation import validate_sources
    from app.domain.research_results import execution
    from app.domain.fixed_statistics_runtime import scope_active
    from app.domain.regression.common import NumericError
    from app.adapters.task_store import TaskStore
    from app.core.exceptions import StorageError
    task=dict(id='task',project_id='project',user_id='owner',task_type='collection_word_report',
        status='running',revision=2,input_snapshot={'reader_export':{'policy':legacy.POLICY}},error_code=None)
    cp=dict(id='checkpoint',next_node='check',state_json={})
    class DB:
        def execute(self,*args):return self
        def fetchone(self):return task
    class Repo:
        config=None;assets=SimpleNamespace(directory=tmp_path)
        @contextmanager
        def connection(self,**kwargs):
            try:yield DB()
            except StorageError as error:
                if outer_rollback and error.code=='numeric_timeout':
                    raise StorageError('storage_unavailable','Injected rollback wrapper outside numeric scope') from error
                raise
        def claim(self,*args,**kwargs):return SimpleNamespace(task_id='task',attempt_no=1,lease_owner='lease')
        def require_lease(self,*args):return task
        def require_owner(self,*args):pass
        def now(self,db):return '2026-11-15T12:00:00+00:00'
        def heartbeat(self,*args):return True
        def fail(self,lease,code,**kwargs):
            assert not scope_active()
            task.update(status='failed',error_code=code,execution_receipt=kwargs.get('execution_receipt'))
            return dict(task)
    repo=Repo()
    def source(*args,**kwargs):
        def expired():raise NumericError('numeric_timeout','Injected validation deadline')
        return validate_sources(expired)
    monkeypatch.setattr(execution,'TaskExecutionStore',lambda **kwargs:repo)
    monkeypatch.setattr(execution,'service_for',lambda *args:SimpleNamespace(require_sources=source))
    monkeypatch.setattr(execution,'checkpoint_for',lambda *args:cp)
    monkeypatch.setattr(execution,'append_checkpoint',lambda *args,**kwargs:cp)
    monkeypatch.setattr(execution,'_staging',lambda *args:(tmp_path/'attempt',tmp_path/'output'))
    monkeypatch.setattr(execution,'_receipt',lambda *args:None)
    handled,result=legacy.dispatch('task',1,repo,staging_directory=tmp_path)
    assert handled and result['status']=='failed' and result['error_code']=='numeric_timeout'
    assert result['execution_receipt']['error_code']=='numeric_timeout'
    monkeypatch.setattr(execution,'source_current',lambda *args:not scope_active())
    assert execution.recovery_actions(DB(),task)==['retry']
    # The same timeout on an unrelated task does not acquire a new retry policy.
    assert execution.recovery_actions(DB(),{**task,'task_type':'research_report'})==[]
    events=[]
    monkeypatch.setattr(TaskStore,'update_task',lambda *args:events.append('update'))
    monkeypatch.setattr(TaskStore,'append_event',lambda *args:events.append('event'))
    monkeypatch.setattr(TaskStore,'enqueue',lambda *args:events.append('enqueue'))
    monkeypatch.setattr(TaskStore,'public_task',lambda value:dict(value))
    retried=execution.retry_in_transaction(object(),DB(),task,2)
    assert retried['id']=='task' and retried['status']=='queued' and retried['revision']==3
    assert events==['update','event','enqueue']
