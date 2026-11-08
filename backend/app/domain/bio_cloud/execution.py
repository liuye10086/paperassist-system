"""One fenced execution slice; remote waiting uses the existing durable outbox."""
import csv
import io
import logging
from threading import Event, Thread
from urllib.parse import urlsplit

from app.adapters.task_execution_store import TaskExecutionStore, LeaseLost
from app.adapters.task_store import TaskStore, DatasetTaskAssets
from app.core.exceptions import StorageError
from app.domain.bioinformatics.contracts import digest
from .contracts import WorkflowProfile, build_parameters
from .provider import ProviderError, PROVIDER_RUN_STATES, provider_run_id
from . import service as cloud

logger = logging.getLogger(__name__)


def run_parameters(snapshot):
    inputs = snapshot['inputs']
    uris = {read:[f"s3://{v['bucket']}/{v['object_key']}" for v in inputs if v['read']==read] for read in ('R1','R2')}
    return build_parameters(WorkflowProfile.model_validate(snapshot['profile']),
        samplesheet_uri=f"s3://{snapshot['cloud']['input_bucket']}/{snapshot['samplesheet_key']}",
        fastq_r1=uris['R1'][0],fastq_r2=uris['R2'][0],sample_id=snapshot['request']['sample_id'])


def samplesheet(snapshot):
    output = io.StringIO(newline='')
    writer = csv.writer(output,lineterminator='\n')
    writer.writerow(['sample','fastq_1','fastq_2'])
    inputs = {(v['lane'],v['chunk'],v['read']):v for v in snapshot['inputs']}
    for lane,chunk in sorted({(v['lane'],v['chunk']) for v in snapshot['inputs']}):
        pair = [inputs[(lane,chunk,read)] for read in ('R1','R2')]
        writer.writerow([snapshot['request']['sample_id'],*[f"s3://{v['bucket']}/{v['object_key']}" for v in pair]])
    return output.getvalue().encode('utf-8')


def output_prefix(snapshot, uri):
    value = urlsplit(uri or '')
    prefix = value.path.lstrip('/')
    if (value.scheme!='s3' or value.netloc!=snapshot['cloud']['output_bucket'] or value.query or value.fragment
            or not prefix.startswith(snapshot['output_prefix']) or any(p in ('.','..') for p in prefix.split('/'))):
        raise cloud.error('output_invalid', '远端输出不在本任务授权的结果目录内。')
    return prefix.rstrip('/')+'/'


def load(repository, lease):
    with repository.connection() as db:
        task = repository.require_lease(db,lease)
        repository.require_owner(db,task)
        row = db.execute('SELECT * FROM bio_cloud_runs WHERE task_id=%s',(task['id'],)).fetchone()
        if row is None or row['snapshot_json']!=task['input_snapshot'] or digest(task['input_snapshot'])!=task['input_digest']:
            raise cloud.error('input_changed', '冻结的云任务输入不一致，已停止执行。')
        return task,dict(row)


def finish(repository, lease, status, code=None, *, task_status=None):
    with repository.connection(write=True) as db:
        task = repository.require_lease(db,lease)
        db.execute('UPDATE bio_cloud_runs SET status=%s,error_code=%s,updated_at=clock_timestamp() WHERE task_id=%s',(status,code,task['id']))
        repository._finish(db,task,task_status or ('succeeded' if status=='completed' else 'cancelled' if status=='cancelled' else 'failed'),code)
        return TaskStore.public_task(task)


def pause_unknown(repository, lease):
    with repository.connection(write=True) as db:
        task = repository.require_lease(db,lease)
        pause_unknown_in_transaction(repository,db,task)
        return TaskStore.public_task(task)


def pause_unknown_in_transaction(repository, db, task):
    """Also used by the serialized expired-attempt recovery transaction."""
    revision = task['revision']
    task.update(status='waiting_confirmation',reason_code='submission_unknown',error_code='bio_cloud_submission_unknown',
                revision=revision+1,updated_at=repository.now(db))
    TaskStore.finish_attempt(db,task)
    TaskStore.update_task(db,task,revision)
    TaskStore.append_event(db,task,'waiting')
    db.execute("UPDATE bio_cloud_runs SET status='submission_unknown',error_code='bio_cloud_submission_unknown',updated_at=clock_timestamp() WHERE task_id=%s",(task['id'],))


def receipt(repository, row, response):
    try:
        run_id = provider_run_id(response.get('run_id'))
    except ProviderError:
        raise ProviderError('invalid_submission_receipt',uncertain=True)
    uri = response.get('run_output_uri')
    if uri:
        output_prefix(row['snapshot_json'],uri)
    # A late but genuine receipt may be saved after lease expiry. It never publishes
    # artifacts or changes a newer request identity; the next fenced slice resumes it.
    with repository.connection(write=True) as db:
        current = db.execute('SELECT * FROM bio_cloud_runs WHERE id=%s FOR UPDATE',(row['id'],)).fetchone()
        if current['request_token']!=row['request_token'] or current['snapshot_json']!=row['snapshot_json']:
            raise LeaseLost()
        if current['provider_run_id'] not in (None,run_id):
            raise cloud.error('reconciliation_invalid','远端回执与已保存任务身份冲突。')
        if current['provider_run_id']==run_id:
            # Reconciliation and a delayed StartRun receipt may arrive together.
            # Never roll back a later polling or terminal state.
            return
        db.execute("UPDATE bio_cloud_runs SET provider_run_id=%s,provider_state=%s,run_output_uri=%s,status='pending',error_code=NULL,updated_at=clock_timestamp() WHERE id=%s",
                   (run_id,response.get('status') or 'PENDING',uri,row['id']))


def execute(repository, lease, service, provider):
    task,row = load(repository,lease)
    snapshot = row['snapshot_json']
    if not row['provider_run_id']:
        if row['submitted_at'] is not None or row['status'] in ('submitting','submission_unknown'):
            return pause_unknown(repository,lease)
        if row['cancel_requested']:
            return finish(repository,lease,'cancelled')
        # Object identity must still match the confirmed multipart completion.
        for item in snapshot['inputs']:
            current = provider.head_input(item['object_key'])
            expected = item['receipt_json']
            if any(current.get(k)!=expected.get(k) for k in ('size_bytes','etag','version_id','checksum_sha256')):
                return finish(repository,lease,'failed','bio_cloud_input_changed')
        provider.put_samplesheet(snapshot['samplesheet_key'],samplesheet(snapshot))
        parameters = run_parameters(snapshot)
        with repository.connection(write=True) as db:
            task = repository.require_lease(db,lease)
            current = db.execute('SELECT * FROM bio_cloud_runs WHERE id=%s FOR UPDATE',(row['id'],)).fetchone()
            if current['cancel_requested']:
                # Commit no submission intent; cancellation is finalized below.
                cancel = True
            else:
                cancel = False
                if current['submitted_at'] is not None:
                    raise LeaseLost()
                db.execute("UPDATE bio_cloud_runs SET status='submitting',submitted_at=clock_timestamp(),updated_at=clock_timestamp() WHERE id=%s",(row['id'],))
        if cancel:
            return finish(repository,lease,'cancelled')
        try:
            response = provider.submit_run(WorkflowProfile.model_validate(snapshot['profile']), request_id=row['request_token'],
                task_id=task['id'],output_prefix=snapshot['output_prefix'],parameters=parameters)
            receipt(repository,row,response)
        except ProviderError as exc:
            if exc.uncertain:
                return pause_unknown(repository,lease)
            return finish(repository,lease,'failed','bio_cloud_remote_failed')
        except StorageError:
            # Malformed/mis-scoped success still does not prove no paid run exists.
            return pause_unknown(repository,lease)
        return repository.defer(lease,seconds=15)
    response = provider.get_run(row['provider_run_id'])
    if row['cancel_requested'] and response.get('status') in ('PENDING','STARTING','RUNNING'):
        try:
            provider.cancel_run(row['provider_run_id'])
        except ProviderError:
            # A completion/cancellation race may reject CancelRun. Read the
            # existing run before deciding whether a request retry is needed.
            response = provider.get_run(row['provider_run_id'])
            if response.get('status') in ('PENDING','STARTING','RUNNING'):
                raise
        else:
            response = provider.get_run(row['provider_run_id'])
    if response.get('run_id') != row['provider_run_id']:
        raise cloud.error('output_invalid','远端任务身份不一致。')
    state = response.get('status')
    if state not in PROVIDER_RUN_STATES:
        return finish(repository,lease,'blocked','bio_cloud_provider_unavailable')
    uri = response.get('run_output_uri') or row['run_output_uri']
    if state=='COMPLETED':
        output_prefix(snapshot,uri)
    status = {'PENDING':'pending','STARTING':'pending','RUNNING':'running','STOPPING':'cancelling',
              'COMPLETED':'collecting','CANCELLED':'cancelled','FAILED':'failed','DELETED':'failed'}[state]
    with repository.connection(write=True) as db:
        repository.require_lease(db,lease)
        db.execute("UPDATE bio_cloud_runs SET provider_state=%s,status=%s,run_output_uri=%s,poll_failures=CASE WHEN %s='COMPLETED' THEN poll_failures ELSE 0 END,updated_at=clock_timestamp() WHERE id=%s",(state,status,uri,state,row['id']))
    if state=='CANCELLED':
        return finish(repository,lease,'cancelled')
    if state in ('FAILED','DELETED'):
        return finish(repository,lease,'failed','bio_cloud_remote_failed')
    if state=='COMPLETED':
        if row['cancel_requested']:
            # A completion/cancel race is reported honestly; no success artifact is
            # silently discarded and no new run is created. Collect completed outputs.
            pass
        from .outputs import collect_outputs
        collect_outputs(repository,lease,service,provider,row,uri)
        return finish(repository,lease,'completed')
    return repository.defer(lease,seconds=30)


def run_bio_cloud_task(task_id, task_revision, *, config=None, directory=None):
    repository = TaskExecutionStore(config=config,directory=directory)
    lease = repository.claim(task_id,task_revision,task_type='bio_cloud_run')
    if lease is None:
        return None
    stop = Event()
    def heartbeat():
        while not stop.wait(10):
            try:
                if not repository.heartbeat(lease):
                    return
            except Exception:
                return
    thread = Thread(target=heartbeat,daemon=True,name='bio-cloud-lease')
    thread.start()
    provider = None
    try:
        task,row = load(repository,lease)
        service = cloud.CloudService(DatasetTaskAssets(task['user_id'],repository.config,repository.assets.directory))
        settings = service.ready_settings()
        if any(getattr(settings,k)!=v for k,v in row['snapshot_json']['cloud'].items()):
            return finish(repository,lease,'blocked','bio_cloud_configuration_changed')
        provider = cloud.create_provider(settings)
        return execute(repository,lease,service,provider)
    except LeaseLost:
        return None
    except ProviderError:
        try:
            task,row = load(repository,lease)
            if not row['provider_run_id'] and row['submitted_at'] is not None:
                return pause_unknown(repository,lease)
            with repository.connection(write=True) as db:
                repository.require_lease(db,lease)
                db.execute('UPDATE bio_cloud_runs SET poll_failures=poll_failures+1,error_code=%s WHERE id=%s',('bio_cloud_provider_unavailable',row['id']))
            if row['poll_failures']>=5:
                return finish(repository,lease,'blocked','bio_cloud_polling_failed')
            return repository.defer(lease,seconds=min(300,15*2**row['poll_failures']))
        except LeaseLost:
            return None
    except StorageError as exc:
        try:
            return finish(repository,lease,'blocked',exc.code)
        except LeaseLost:
            return None
    except Exception:
        # Preserve leases and durable intent for recovery; don't conceal an unknown
        # database commit or convert it into a fresh billable StartRun.
        logger.warning('cloud execution interrupted task_id=%s',task_id)
        return None
    finally:
        stop.set()
        thread.join(timeout=1)
        if provider is not None:
            provider.close()
