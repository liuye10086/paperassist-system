"""Real Linux plan profile, HTTP/worker split, and fail-closed numerical nodes."""
from tests.api.test_analysis import client,selection
from tests.helpers.analysis_plan import prepared_sample,run_plan,review_plan,decide_plan
from tests.integration.test_research_plan import research
from tests.test_batch09_research_flow import decision


def queued_numeric_plan(client):
    base,file,prepared=prepared_sample(client)
    body=dict(schema_version=5,input_kind='data',file_id=file['id'],dataset_id=prepared['id'],expected_setup_revision=0,selection=selection(numeric_column='D',group_column='C',unit='mg'),research_request=research(),evidence_version_ids=[])
    response=client.post(base+'/analysis-plans',json=body,headers={'Idempotency-Key':'profile-plan'})
    assert response.status_code==202,response.text
    task=response.json();assert run_plan(task)['status']=='waiting_input';view=review_plan(client,task)
    body={k:view[k] for k in ('input_version','checkpoint_id','wait_id','plan_revision')};body.update(expected_task_revision=view['task']['revision'],source_resolution=dict(confirmed=True,note='Current frozen file and prepared worksheet.'))
    supplied=client.post('/api/v1/tasks/'+task['id']+'/analysis-plan/source-decisions',json=body,headers={'Idempotency-Key':'profile-source'})
    assert supplied.status_code==202,supplied.text
    return base,supplied.json()


def test_plan_profile_is_real_linux_and_windows_http_approval_never_computes(client,monkeypatch):
    from app.domain.analysis_plan import profile
    from app.domain.regression.bounded import last_execution_receipt
    seen=[];actual=profile.compute_bounded
    def spy(kind,rows,options):
        seen.append(kind);return actual(kind,rows,options)
    monkeypatch.setattr(profile,'compute_bounded',spy)
    base,task=queued_numeric_plan(client)
    assert run_plan(task)['status']=='waiting_confirmation';view=review_plan(client,task)
    assert 'profile_numeric' in seen
    receipt=last_execution_receipt();assert receipt['isolation']=='linux_landlock_seccomp' and receipt['memory_hard_limit']==1073741824
    assert view['check']['data_check']['selected_fields'][0]['observed_max']==9.
    import sys
    def forbidden(*a,**k):raise AssertionError('Windows HTTP must not compute')
    with monkeypatch.context() as guarded:
        guarded.setattr(sys,'platform','win32');guarded.setattr(profile,'compute_bounded',forbidden)
        guarded.setattr('app.domain.analysis_plan.checks.build_check',forbidden)
        approved=decide_plan(client,task,decision(view),'profile-approve')
        assert approved.status_code==202,approved.text
    assert run_plan(approved.json())['status']=='succeeded'
    assert review_plan(client,task)['result']['source_resolution']['confirmed'] is True


def test_plan_profile_timeout_preserves_actual_receipt_and_never_publishes(client,monkeypatch):
    base,task=queued_numeric_plan(client)
    from app.domain.analysis_plan import profile
    from app.domain.regression.bounded import clear_compute_cache
    clear_compute_cache();actual=profile.compute_bounded
    monkeypatch.setattr(profile,'compute_bounded',lambda kind,rows,options:actual(kind,rows,options,timeout_seconds=.001))
    failed=run_plan(task)
    assert failed['status']=='failed' and failed['error_code']=='numeric_timeout',failed
    assert failed['execution_receipt']['nodes'][-1]['error_code']=='numeric_timeout'
    from app.db.database import database_connection
    with database_connection() as db:assert db.execute('SELECT count(*) AS n FROM confirmed_analysis_plans WHERE task_id=%s',(task['id'],)).fetchone()['n']==0
