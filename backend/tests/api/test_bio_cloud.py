"""Real PostgreSQL/API lifecycle with a fake remote provider; no cloud evidence."""
import base64
import hashlib
import io
import gzip
import pytest

from tests.api.test_projects import client, create_project


class Remote:
    def __init__(self):
        self.parts = {}
        self.objects = {}
        self.submissions = []
        self.state = 'RUNNING'
        self.fail_submit = False
        self.cancelled = False

    def close(self):
        pass

    def begin_upload(self, key):
        self.parts[key] = []
        return 'multipart-' + key.rsplit('/', 1)[-1]

    def sign_part(self, key, upload_id, number, checksum):
        return {'url': 'https://example.invalid/part', 'headers': {'x-amz-checksum-sha256': checksum}, 'expires_in': 900}

    def list_parts(self, key, upload_id):
        return self.parts[key]

    def complete_upload(self, key, upload_id, parts):
        self.objects[key] = dict(size_bytes=sum(p['size_bytes'] for p in parts), etag='composite-etag', version_id='v1', checksum_sha256=base64.b64encode(hashlib.sha256(b''.join(base64.b64decode(p['checksum_sha256']) for p in parts)).digest()).decode()+'-'+str(len(parts)), checksum_type='COMPOSITE')
        return self.objects[key]

    def head_input(self, key):
        return self.objects[key]

    def abort_upload(self, key, upload_id):
        self.cancelled = True

    def put_samplesheet(self, key, content):
        return 's3://input-bucket/' + key

    def submit_run(self, profile, **kwargs):
        self.submissions.append(kwargs)
        if self.fail_submit:
            from app.domain.bio_cloud.provider import ProviderError
            raise ProviderError('submission_unknown', uncertain=True)
        return dict(run_id='1234567', status='PENDING', arn='arn:aws:omics:ap-southeast-1:123456789012:run/1234567', uuid='remote', run_output_uri='s3://output-bucket/' + kwargs['output_prefix'] + 'run/')

    def get_run(self, run_id):
        from app.domain.bioinformatics.contracts import digest
        return dict(run_id=run_id, status=self.state, name=self.submissions[0]['task_id'],workflow_id='1234567',workflow_type='READY2RUN',workflow_version=None,
                    parameters_sha256=digest(self.submissions[0]['parameters']),run_output_uri='s3://output-bucket/' + self.submissions[0]['output_prefix'] + 'run/')

    def cancel_run(self, run_id):
        self.cancelled = True
        self.state = 'CANCELLED'

    def list_outputs(self, uri):
        self.output_data = {
            'matrix.mtx.gz': gzip.compress(b'%%MatrixMarket matrix coordinate integer general\n2 2 3\n1 1 1\n1 2 2\n2 2 3\n'),
            'features.tsv.gz': gzip.compress(b'g1\tGene1\tGene Expression\ng2\tGene2\tGene Expression\n'),
            'barcodes.tsv.gz': gzip.compress(b'c1\nc2\n'),
            'qc.json': b'{"synthetic_fixture":true}',
            'run.log': b'Synthetic transport fixture; not real STARsolo execution.\n',
        }
        prefix = uri.split('output-bucket/', 1)[1]
        return [dict(key=prefix+k,size_bytes=len(v),etag='output-etag') for k,v in self.output_data.items()]

    def stream_output(self, key, *, expected_etag=None):
        assert expected_etag == 'output-etag'
        return io.BytesIO(self.output_data[key.rsplit('/',1)[-1]])


def configure(monkeypatch):
    from app.domain.bio_cloud.settings import CloudSettings
    from app.domain.bio_cloud import service
    settings = CloudSettings(enabled=True, region='ap-southeast-1', input_bucket='input-bucket', output_bucket='output-bucket', role_arn='arn:aws:iam::123456789012:role/omics-run', profiles=[dict(
        id='fixture-starsolo', name='Fixture STARsolo', workflow_id='1234567', engine='starsolo', species='human', chemistries=['10x-3prime-v3'], reference_id='fixture-reference', account_verified=True, estimated_run_cost_usd=5.0,
        parameters={'input': '{samplesheet_uri}'}, outputs={'matrix':'matrix.mtx.gz','features':'features.tsv.gz','barcodes':'barcodes.tsv.gz','qc':'qc.json','log':'run.log'},
    )])
    remote = Remote()
    monkeypatch.setattr(service, 'load_settings', lambda: settings)
    monkeypatch.setattr(service, 'create_provider', lambda config: remote)
    return remote


def upload(client, base, remote, name, key):
    response = client.post(base + '/uploads', json={'filename': name, 'size_bytes': 32}, headers={'Idempotency-Key': key})
    assert response.status_code == 201, response.text
    item = response.json()
    checksum = base64.b64encode(hashlib.sha256(b'x' * 32).digest()).decode()
    signed = client.post(base + f"/uploads/{item['id']}/parts/1/sign", json={'checksum_sha256': checksum})
    assert signed.status_code == 200, signed.text
    object_key = next(k for k in remote.parts if item['id'] in k)
    remote.parts[object_key] = [dict(part_number=1, etag='etag', size_bytes=32, checksum_sha256=checksum)]
    finished = client.post(base + f"/uploads/{item['id']}/complete", json={})
    assert finished.status_code == 200, finished.text
    assert finished.json()['status'] == 'completed'
    return item['id']


def create_run(client, base, remote):
    r1 = upload(client, base, remote, 'sample_L001_R1_001.fastq.gz', 'read1')
    r2 = upload(client, base, remote, 'sample_L001_R2_001.fastq.gz', 'read2')
    body = dict(profile_id='fixture-starsolo', sample_id='sample', library_id='library', species='human', chemistry='10x-3prime-v3', donor_id='donor1', group='control',
                fastqs=[dict(upload_id=r1, read='R1', lane='L001', chunk=1), dict(upload_id=r2, read='R2', lane='L001', chunk=1)],
                external_processing_confirmed=True, budget_approved=True, budget_limit_usd='10.00')
    response = client.post(base + '/runs', json=body, headers={'Idempotency-Key':'run-key'})
    assert response.status_code == 202, response.text
    return response.json(), body


def test_capabilities_default_disabled_and_project_scoped(client, monkeypatch):
    monkeypatch.delenv('PAPERASSIST_BIO_CLOUD_CONFIG_FILE', raising=False)
    base = f"/api/v1/projects/{create_project(client)['id']}/bio-cloud"
    response = client.get(base + '/capabilities')
    assert response.status_code == 200, response.text
    assert response.json()['enabled'] is False
    assert response.json()['evidence']['real_data_verified'] is False
    assert 'access_key' not in response.text.lower()
    assert client.get('/api/v1/projects/not-owned/bio-cloud/capabilities').status_code == 404
    blocked = client.post(base + '/uploads', json={'filename':'r1.fastq.gz','size_bytes':32}, headers={'Idempotency-Key':'disabled'})
    assert blocked.status_code == 409


def test_cloud_upload_run_poll_and_cancel_are_persistent(client, monkeypatch):
    remote = configure(monkeypatch)
    base = f"/api/v1/projects/{create_project(client)['id']}/bio-cloud"
    run, body = create_run(client, base, remote)
    replay = client.post(base + '/runs', json=body, headers={'Idempotency-Key':'run-key'})
    assert replay.json()['id'] == run['id']
    conflict = client.post(base + '/runs', json={**body,'sample_id':'other'}, headers={'Idempotency-Key':'run-key'})
    assert conflict.status_code == 409
    from app.domain.bio_cloud.execution import run_bio_cloud_task
    run_bio_cloud_task(run['task']['id'], run['task']['revision'])
    current = client.get(base + '/runs/' + run['id']).json()
    assert current['provider_run_id'] == '1234567'
    assert len(remote.submissions) == 1
    run_bio_cloud_task(current['task']['id'], current['task']['revision'])
    current = client.get(base + '/runs/' + run['id']).json()
    assert current['status'] == 'running'
    assert len(remote.submissions) == 1
    cancel = client.post(base + '/runs/' + run['id'] + '/cancel', json={})
    assert cancel.status_code == 202, cancel.text
    current = client.get(base + '/runs/' + run['id']).json()
    run_bio_cloud_task(current['task']['id'], current['task']['revision'])
    current = client.get(base + '/runs/' + run['id']).json()
    assert remote.cancelled
    assert current['status'] == 'cancelled'
    assert current['task']['status'] == 'cancelled'
    assert len(remote.submissions) == 1


def test_submission_unknown_never_reposts_on_worker_recovery(client, monkeypatch):
    remote = configure(monkeypatch)
    remote.fail_submit = True
    base = f"/api/v1/projects/{create_project(client)['id']}/bio-cloud"
    run, _ = create_run(client, base, remote)
    from app.domain.bio_cloud.execution import run_bio_cloud_task
    run_bio_cloud_task(run['task']['id'], run['task']['revision'])
    current = client.get(base + '/runs/' + run['id']).json()
    assert current['status'] == 'submission_unknown'
    run_bio_cloud_task(current['task']['id'], current['task']['revision'])
    assert len(remote.submissions) == 1
    assert client.post(base + '/runs/' + run['id'] + '/retry', json={}).status_code == 409


def test_upload_rejects_changed_part_and_missing_mate(client, monkeypatch):
    remote = configure(monkeypatch)
    base = f"/api/v1/projects/{create_project(client)['id']}/bio-cloud"
    response = client.post(base + '/uploads', json={'filename':'r1.fastq.gz','size_bytes':32}, headers={'Idempotency-Key':'part'})
    assert response.status_code == 201, response.text
    uri = base + '/uploads/' + response.json()['id'] + '/parts/1/sign'
    a = base64.b64encode(hashlib.sha256(b'a').digest()).decode()
    b = base64.b64encode(hashlib.sha256(b'b').digest()).decode()
    assert client.post(uri, json={'checksum_sha256':a}).status_code == 200
    assert client.post(uri, json={'checksum_sha256':b}).status_code == 409
    assert client.post(base + '/uploads/' + response.json()['id'] + '/complete', json={}).status_code == 409
    body = dict(profile_id='fixture-starsolo', sample_id='sample', library_id='library', species='human', chemistry='10x-3prime-v3',
                fastqs=[dict(upload_id=response.json()['id'], read='R1', lane='L001', chunk=1)],
                external_processing_confirmed=True,budget_approved=True,budget_limit_usd='10')
    assert client.post(base + '/runs', json=body, headers={'Idempotency-Key':'bad-pair'}).status_code == 422


def test_completed_cloud_outputs_are_original_files_not_published_datasets(client, monkeypatch):
    remote = configure(monkeypatch)
    project = create_project(client)['id']
    base = f'/api/v1/projects/{project}/bio-cloud'
    run, _ = create_run(client, base, remote)
    from app.domain.bio_cloud.execution import run_bio_cloud_task
    run_bio_cloud_task(run['task']['id'],run['task']['revision'])
    current = client.get(base+'/runs/'+run['id']).json()
    remote.state = 'COMPLETED'
    run_bio_cloud_task(current['task']['id'],current['task']['revision'])
    current = client.get(base+'/runs/'+run['id']).json()
    assert current['status'] == 'completed', current
    assert {v['role'] for v in current['outputs']} >= {'matrix','features','barcodes','qc','log'}
    assert client.get(f'/api/v1/projects/{project}/bio-datasets').json()['items'] == []
    for item in current['outputs']:
        result = client.get(f"/api/v1/projects/{project}/files/{item['file_id']}/download")
        assert result.status_code == 200, result.text
        assert hashlib.sha256(result.content).hexdigest() == item['sha256']
    assessment=client.get(f"/api/v1/projects/{project}/files/{current['outputs'][0]['file_id']}/lifecycle/assessment").json()
    assert 'bio_history_retained' in {v['code'] for v in assessment['reasons']}
    assert 'integrity_unknown' not in {v['code'] for v in assessment['reasons']}
    assert len(remote.submissions) == 1


def test_unknown_submission_can_only_reconcile_matching_remote_identity(client, monkeypatch):
    remote = configure(monkeypatch)
    remote.fail_submit = True
    project = create_project(client)['id']
    base = f'/api/v1/projects/{project}/bio-cloud'
    run, _ = create_run(client,base,remote)
    from app.domain.bio_cloud.execution import run_bio_cloud_task
    run_bio_cloud_task(run['task']['id'],run['task']['revision'])
    original = remote.get_run
    remote.get_run = lambda run_id: {**original(run_id),'name':'another-task'}
    rejected = client.post(base+'/runs/'+run['id']+'/reconcile',json={'provider_run_id':'1234567'})
    assert rejected.status_code == 409, rejected.text
    remote.get_run = original
    recovered = client.post(base+'/runs/'+run['id']+'/reconcile',json={'provider_run_id':'1234567'})
    assert recovered.status_code == 202,recovered.text
    current = recovered.json()
    run_bio_cloud_task(current['task']['id'],current['task']['revision'])
    assert len(remote.submissions)==1
    assert client.get(base+'/runs/'+run['id']).json()['status']=='running'


def test_cloud_run_appears_in_existing_task_workspace(client,monkeypatch):
    remote = configure(monkeypatch)
    project = create_project(client)['id']
    run,_ = create_run(client,f'/api/v1/projects/{project}/bio-cloud',remote)
    response = client.get(f'/api/v1/projects/{project}/tasks')
    assert response.status_code == 200,response.text
    assert any(item['task']['id']==run['task']['id'] for item in response.json()['items'])
    from app.workers.dispatcher import dispatch_once
    from app.domain.tasks.execution import run_task
    published=[]
    assert dispatch_once(publish=published.append)==1
    assert published[0]['task_id']==run['task']['id']
    run_task(published[0]['task_id'],published[0]['task_revision'])
    assert len(remote.submissions)==1


def test_missing_initial_output_uri_keeps_remote_identity(client,monkeypatch):
    remote = configure(monkeypatch)
    original = remote.submit_run
    remote.submit_run = lambda *args,**kwargs: {**original(*args,**kwargs),'run_output_uri':None}
    base = f"/api/v1/projects/{create_project(client)['id']}/bio-cloud"
    run,_ = create_run(client,base,remote)
    from app.domain.bio_cloud.execution import run_bio_cloud_task
    run_bio_cloud_task(run['task']['id'],run['task']['revision'])
    current = client.get(base+'/runs/'+run['id']).json()
    assert current['provider_run_id']=='1234567'
    run_bio_cloud_task(current['task']['id'],current['task']['revision'])
    assert client.get(base+'/runs/'+run['id']).json()['status']=='running'
    assert len(remote.submissions)==1


def test_cancel_request_after_remote_completion_collects_truthful_result(client,monkeypatch):
    remote = configure(monkeypatch)
    base = f"/api/v1/projects/{create_project(client)['id']}/bio-cloud"
    run,_ = create_run(client,base,remote)
    from app.domain.bio_cloud.execution import run_bio_cloud_task
    run_bio_cloud_task(run['task']['id'],run['task']['revision'])
    current = client.post(base+'/runs/'+run['id']+'/cancel',json={}).json()
    remote.state='COMPLETED'
    run_bio_cloud_task(current['task']['id'],current['task']['revision'])
    assert client.get(base+'/runs/'+run['id']).json()['status']=='completed'
    assert not remote.cancelled


def test_multipart_completion_retries_same_session_after_lost_request(client,monkeypatch):
    from app.domain.bio_cloud.provider import ProviderError
    remote = configure(monkeypatch)
    original = remote.complete_upload
    attempts=[]
    def complete(key,upload_id,parts):
        attempts.append(upload_id)
        if len(attempts)==1:
            raise ProviderError('provider_request_failed')
        return original(key,upload_id,parts)
    original_head=remote.head_input
    def head(key):
        if key not in remote.objects: raise ProviderError('provider_request_failed')
        return original_head(key)
    remote.complete_upload=complete
    remote.head_input=head
    base = f"/api/v1/projects/{create_project(client)['id']}/bio-cloud"
    item=client.post(base+'/uploads',json={'filename':'r1.fastq.gz','size_bytes':32},headers={'Idempotency-Key':'r1'}).json()
    checksum=base64.b64encode(hashlib.sha256(b'x'*32).digest()).decode()
    client.post(base+f"/uploads/{item['id']}/parts/1/sign",json={'checksum_sha256':checksum})
    key=next(iter(remote.parts))
    remote.parts[key]=[dict(part_number=1,etag='etag',size_bytes=32,checksum_sha256=checksum)]
    assert client.post(base+f"/uploads/{item['id']}/complete",json={}).status_code==503
    recovered=client.post(base+f"/uploads/{item['id']}/complete",json={})
    assert recovered.status_code==200,recovered.text
    assert recovered.json()['status']=='completed'
    assert len(attempts)==2 and len(set(attempts))==1


def test_expired_cloud_worker_after_submit_intent_never_submits_again(client,monkeypatch):
    remote = configure(monkeypatch)
    base = f"/api/v1/projects/{create_project(client)['id']}/bio-cloud"
    run,_=create_run(client,base,remote)
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.domain.bio_cloud.execution import run_bio_cloud_task
    repository=TaskExecutionStore()
    lease=repository.claim(run['task']['id'],run['task']['revision'],task_type='bio_cloud_run')
    assert lease
    with repository.connection(write=True) as db:
        db.execute("UPDATE bio_cloud_runs SET status='submitting',submitted_at=clock_timestamp() WHERE id=%s",(run['id'],))
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 minute' WHERE task_id=%s",(run['task']['id'],))
    assert repository.recover_expired()==1
    current=client.get(base+'/runs/'+run['id']).json()
    run_bio_cloud_task(current['task']['id'],current['task']['revision'])
    assert client.get(base+'/runs/'+run['id']).json()['status']=='submission_unknown'
    assert remote.submissions==[]


def test_cancel_requeues_blocked_polling_without_new_compute(client,monkeypatch):
    from app.domain.bio_cloud.provider import ProviderError
    from app.domain.bio_cloud.execution import run_bio_cloud_task
    remote=configure(monkeypatch)
    base=f"/api/v1/projects/{create_project(client)['id']}/bio-cloud"
    current,_=create_run(client,base,remote)
    run_bio_cloud_task(current['task']['id'],current['task']['revision'])
    original=remote.get_run
    def unavailable(run_id): raise ProviderError('provider_request_failed')
    remote.get_run=unavailable
    for _ in range(6):
        current=client.get(base+'/runs/'+current['id']).json()
        run_bio_cloud_task(current['task']['id'],current['task']['revision'])
    current=client.get(base+'/runs/'+current['id']).json()
    assert current['status']=='blocked' and current['task']['status']=='failed'
    remote.get_run=original
    current=client.post(base+'/runs/'+current['id']+'/cancel',json={}).json()
    assert current['task']['status']=='queued'
    run_bio_cloud_task(current['task']['id'],current['task']['revision'])
    assert client.get(base+'/runs/'+current['id']).json()['status']=='cancelled'
    assert len(remote.submissions)==1


def test_repeated_receipt_does_not_roll_back_completed_run(client,monkeypatch):
    from app.domain.bio_cloud.execution import run_bio_cloud_task,receipt
    from app.adapters.task_execution_store import TaskExecutionStore
    remote=configure(monkeypatch)
    base=f"/api/v1/projects/{create_project(client)['id']}/bio-cloud"
    current,_=create_run(client,base,remote)
    run_bio_cloud_task(current['task']['id'],current['task']['revision'])
    repository=TaskExecutionStore()
    with repository.connection() as db:
        original=dict(db.execute('SELECT * FROM bio_cloud_runs WHERE id=%s',(current['id'],)).fetchone())
    current=client.get(base+'/runs/'+current['id']).json()
    remote.state='COMPLETED'
    run_bio_cloud_task(current['task']['id'],current['task']['revision'])
    receipt(repository,original,remote.get_run('1234567'))
    assert client.get(base+'/runs/'+current['id']).json()['status']=='completed'


def test_output_recovery_rejects_changed_remote_manifest(client,monkeypatch):
    from app.domain.bio_cloud.execution import run_bio_cloud_task
    from app.domain.bio_cloud.provider import ProviderError
    remote=configure(monkeypatch)
    base=f"/api/v1/projects/{create_project(client)['id']}/bio-cloud"
    current,_=create_run(client,base,remote)
    run_bio_cloud_task(current['task']['id'],current['task']['revision'])
    remote.state='COMPLETED'
    original_stream=remote.stream_output
    def stream(key,**kwargs):
        if key.endswith('features.tsv.gz'): raise ProviderError('provider_request_failed')
        return original_stream(key,**kwargs)
    remote.stream_output=stream
    current=client.get(base+'/runs/'+current['id']).json()
    run_bio_cloud_task(current['task']['id'],current['task']['revision'])
    original_list=remote.list_outputs
    remote.list_outputs=lambda uri:[{**v,'etag':'new-etag'} for v in original_list(uri)]
    remote.stream_output=lambda key,**kwargs: original_stream(key,expected_etag='output-etag')
    current=client.get(base+'/runs/'+current['id']).json()
    saved_outputs=current['outputs']
    run_bio_cloud_task(current['task']['id'],current['task']['revision'])
    current=client.get(base+'/runs/'+current['id']).json()
    assert current['status']=='blocked' and current['error_code']=='bio_cloud_output_invalid'
    assert current['outputs']==saved_outputs and saved_outputs


def test_cloud_task_can_publish_after_unrelated_synthetic_file_disposal(client,monkeypatch,tmp_path):
    from app.domain.storage_governance import deletion
    from app.adapters.storage import ProjectStore
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.core.config import get_data_dir
    from datetime import datetime,timedelta,timezone
    repository=TaskExecutionStore()
    with repository.connection() as db:
        owner=db.execute("SELECT id FROM users WHERE email='business-test@paperassist.local'").fetchone()['id']
    store=ProjectStore(get_data_dir(),owner_id=owner)
    created=deletion.create_disposable_fixture(store,evidence_directory=tmp_path/'cloud-guard-fixture',originals=[('disposable.xlsx',b'only a new test fixture')],temporary=[])
    monkeypatch.setattr(deletion,'current_utc',lambda:datetime.now(timezone.utc)+timedelta(hours=25))
    service=deletion.DeletionService(store)
    plan=service.preview(created['project_id'],scope_kind='file',file_id=created['files'][0]['id'],reason='Explicit new synthetic guard regression')
    result=service.execute(created['project_id'],plan['id'],confirmed_manifest_sha256=plan['manifest_sha256'],confirmation='delete_registered_synthetic_objects',key='synthetic-cloud-guard')
    assert result['deleted_object_count']==1
    remote=configure(monkeypatch)
    base=f"/api/v1/projects/{created['project_id']}/bio-cloud"
    current,_=create_run(client,base,remote)
    from app.domain.bio_cloud.execution import run_bio_cloud_task
    run_bio_cloud_task(current['task']['id'],current['task']['revision'])
    current=client.get(base+'/runs/'+current['id']).json()
    assert current['provider_run_id']=='1234567'
    remote.state='COMPLETED'
    run_bio_cloud_task(current['task']['id'],current['task']['revision'])
    assert client.get(base+'/runs/'+current['id']).json()['status']=='completed'


def test_run_requires_verified_price_and_sufficient_acknowledged_budget(client,monkeypatch):
    from app.domain.bio_cloud import service
    remote=configure(monkeypatch)
    base=f"/api/v1/projects/{create_project(client)['id']}/bio-cloud"
    _,body=create_run(client,base,remote)
    low=client.post(base+'/runs',json={**body,'budget_limit_usd':'0.01'},headers={'Idempotency-Key':'too-low'})
    assert low.status_code==409 and low.json()['detail']['code']=='bio_cloud_budget_exceeded'
    settings=service.load_settings()
    monkeypatch.setattr(service,'load_settings',lambda:settings.model_copy(update={'profiles':[settings.profiles[0].model_copy(update={'estimated_run_cost_usd':None})]}))
    missing=client.post(base+'/runs',json=body,headers={'Idempotency-Key':'no-price'})
    assert missing.status_code==409 and missing.json()['detail']['code']=='bio_cloud_price_unverified'
    assert remote.submissions==[]


@pytest.mark.parametrize('known_id',[True,False])
def test_exhausted_worker_recovery_preserves_cloud_recovery_routes(client,monkeypatch,known_id):
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.domain.bio_cloud.execution import run_bio_cloud_task
    remote=configure(monkeypatch)
    base=f"/api/v1/projects/{create_project(client)['id']}/bio-cloud"
    current,_=create_run(client,base,remote)
    if known_id:
        run_bio_cloud_task(current['task']['id'],current['task']['revision'])
        current=client.get(base+'/runs/'+current['id']).json()
    repository=TaskExecutionStore()
    assert repository.claim(current['task']['id'],current['task']['revision'],task_type='bio_cloud_run')
    with repository.connection(write=True) as db:
        if not known_id:
            db.execute("UPDATE bio_cloud_runs SET status='submitting',submitted_at=clock_timestamp() WHERE id=%s",(current['id'],))
        db.execute('UPDATE tasks SET retry_count=2 WHERE id=%s',(current['task']['id'],))
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 minute' WHERE task_id=%s",(current['task']['id'],))
    assert repository.recover_expired()==1
    after=client.get(base+'/runs/'+current['id']).json()
    assert after['status']==('blocked' if known_id else 'submission_unknown')
    if known_id:
        retry=client.post(base+'/runs/'+current['id']+'/retry',json={})
        assert retry.status_code==202 and retry.json()['task']['status']=='queued'
    else:
        assert after['task']['status']=='waiting_confirmation'
    assert len(remote.submissions)==int(known_id)
