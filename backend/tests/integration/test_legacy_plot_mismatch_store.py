"""Legacy mismatch evidence and its failed job status commit atomically."""
import json
import pytest
from tests.api.test_analysis import client
from tests.api.test_boxplot import cloud,prepared,seed_legacy,generate


def test_legacy_mismatch_transaction_preserves_bounded_evidence_and_figures(client,cloud):
    from app.adapters.storage import get_project_store
    from app.db.database import database_connection
    _,_,_,url=prepared(client);job=seed_legacy(client,url)
    store=get_project_store()
    assert hasattr(store,'record_legacy_plot_mismatch'),'A transactional legacy evidence writer is required.'
    difference=dict(path='overall.mean',expected=2.0,actual=12.0,reason='value_mismatch')
    updated=store.record_legacy_plot_mismatch(job['id'],differences=[difference,dict(path='rows.secret',actual='private-id')],
        manifest=dict(schema_version=1,overall={'mean':12.0,'fliers':['private-id']},rows=['private-id']),
        provenance=dict(response_id='resp_test',container_id='cntr_test',model='test-model',code=['private-id'],png_file_id='cfile_png'))
    assert updated['status']=='failed' and updated['message_code']=='plot_result_mismatch'
    assert updated['differences']==[difference] and updated['output_json']['differences']==[difference]
    assert updated['output_json']['status']=='mismatched'
    assert 'private-id' not in json.dumps(updated['output_json'])
    with database_connection() as db:
        saved=json.loads(db.execute('SELECT job_json FROM figure_jobs WHERE id=%s',(job['id'],)).fetchone()['job_json'])
        assert saved==updated
        assert db.execute('SELECT count(*) AS n FROM figures').fetchone()['n']==0
    assert client.get(url).json()['job']['differences']==[difference]
    preserved=generate(client,url)
    completed=store.figure_job(job['analysis_run_id'],'openai_boxplot_v1')
    before=json.dumps(completed,sort_keys=True)
    unchanged=store.record_legacy_plot_mismatch(completed['id'],differences=[difference],manifest={},provenance={})
    assert json.dumps(unchanged,sort_keys=True)==before
    assert client.get(url).json()['figure']==preserved


def test_legacy_mismatch_database_failure_rolls_back_status_and_evidence(client,cloud):
    from app.adapters.storage import get_project_store
    from app.db.database import database_connection,migration_connection
    from app.core.exceptions import StorageError
    _,_,_,url=prepared(client);job=seed_legacy(client,url);store=get_project_store()
    assert hasattr(store,'record_legacy_plot_mismatch'),'A transactional legacy evidence writer is required.'
    with migration_connection(write=True) as db:
        db.execute("CREATE FUNCTION reject_legacy_mismatch() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'test write failure'; END $$")
        db.execute('CREATE TRIGGER reject_legacy_mismatch BEFORE UPDATE ON figure_jobs FOR EACH ROW EXECUTE FUNCTION reject_legacy_mismatch()')
    try:
        with pytest.raises(StorageError):store.record_legacy_plot_mismatch(job['id'],differences=[],manifest={},provenance={})
    finally:
        with migration_connection(write=True) as db:
            db.execute('DROP TRIGGER reject_legacy_mismatch ON figure_jobs')
            db.execute('DROP FUNCTION reject_legacy_mismatch()')
    with database_connection() as db:
        saved=json.loads(db.execute('SELECT job_json FROM figure_jobs WHERE id=%s',(job['id'],)).fetchone()['job_json'])
        assert saved==job and 'differences' not in saved and 'output_json' not in saved
