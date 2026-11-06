"""Process revocation contract, separate from scientific algorithms."""
from threading import Event
import importlib
import inspect
import pytest

@pytest.fixture(autouse=True)
def postgres_schema(): yield None

@pytest.mark.parametrize('module,name',[('bio_analysis_process','execute_bio_analysis'),('bio_insights_process','execute_bio_insights')])
def test_process_accepts_revocation_before_any_environment_or_compute(module,name):
    function=getattr(importlib.import_module('app.adapters.'+module),name)
    assert 'cancel_event' in inspect.signature(function).parameters
    from app.adapters.task_execution_store import LeaseLost
    event=Event();event.set()
    with pytest.raises(LeaseLost):function({},'/unused',cancel_event=event)


def test_revocation_kills_only_matching_live_process_group(monkeypatch):
    import app.adapters.bio_child_cancel as module
    calls=[];event=Event()
    monkeypatch.setattr(module.signal,'SIGKILL',9,raising=False)
    monkeypatch.setattr(module,'process_birth',lambda pid:'birth')
    monkeypatch.setattr(module.os,'killpg',lambda pid,sig:calls.append(pid),raising=False)
    assert not module.terminate_revoked_child(123,'birth',event)
    event.set()
    assert not module.terminate_revoked_child(123,'other',event)
    assert module.terminate_revoked_child(123,'birth',event)
    assert calls==[123]


@pytest.mark.parametrize('kind',['bio_analysis','bio_figure','bio_annotation','bio_resource_import','bio_comparison','bio_result_import','bio_enrichment','bio_candidate','bio_insight_figure','bio_feature_extract','bio_integration'])
def test_only_active_local_bio_tasks_offer_cancel(kind):
    from app.domain.tasks.local_cancel import can_cancel
    from app.domain.tasks.waits import allowed_recovery_actions
    for status in ('queued','running'):
        assert allowed_recovery_actions(None,dict(task_type=kind,status=status))==['cancel']
    for status in ('cancelled','failed','succeeded','waiting_confirmation','waiting_input'):
        assert not can_cancel(dict(task_type=kind,status=status))
    assert not can_cancel(dict(task_type='bio_cloud_run',status='running'))
