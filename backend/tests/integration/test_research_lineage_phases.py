"""Full synthetic publication exercises raw ancestry with independent phases."""
from copy import deepcopy
import pytest

from tests.api.test_projects import client


def processed(client, monkeypatch, tmp_path):
    from tests.integration.test_bio_analysis_wait import create, run, confirm
    base, created, staging, _ = create(client, monkeypatch, tmp_path)
    waiting = run(created['task'], staging)
    assert waiting['status'] == 'waiting_confirmation'
    queued = confirm(client, base, created, client.get(base+'/bio-analysis-runs/'+created['id']).json())
    assert queued.status_code == 202, queued.text
    done = run(queued.json(), staging)
    assert done['status'] == 'succeeded', done
    value = client.get(base+'/bio-processed-datasets/'+done['result_bio_processed_dataset_version_id']).json()
    return base, value


def test_report_diamond_public_freezes_and_five_stages_have_fresh_proofs(client, monkeypatch, tmp_path):
    from app.domain.source_byte_verification import VerificationPhase
    from app.domain.research_results.contracts import ResearchReportRequest
    from app.domain.research_results.execution import run_research_report_task
    from app.adapters.research_report_render import render_report
    from tests.integration.test_research_validation_efficiency import report_service
    base, value = processed(client, monkeypatch, tmp_path)
    sources = [dict(source_kind='bio_processed_dataset_version', source_id=value['id'])]
    sources += [dict(source_kind='bio_analysis_artifact', source_id=m['id']) for m in value['members'] if m['format']=='tsv']
    response = client.post(base+'/research-findings', json=dict(title='Lineage diamond', sources=sources),
                           headers={'Idempotency-Key':'phase-diamond-finding'})
    assert response.status_code == 201, response.text
    finding = response.json();project = base.rsplit('/',1)[-1];service = report_service(project)
    request = ResearchReportRequest(title='Complete immutable tables', finding_version_id=finding['id'])
    phases = [];original_close = VerificationPhase.close
    def record_close(self):
        if not self._closed:phases.append(self.receipt())
        return original_close(self)
    monkeypatch.setattr(VerificationPhase, 'close', record_close)
    with service.store.connection() as db:
        content, bindings, payload = service.freeze(db, project, request)
        saved = deepcopy((content, bindings, payload))
        content['finding']['content']['title'] = 'caller mutation'
        assert service.freeze(db, project, request) == saved
        # Original raw() path performs the original independent complete reads.
        # Compare every frozen field and every table byte against that path.
        from app.adapters.bio_analysis_store import BioAnalysisStore
        with monkeypatch.context() as old_path:
            old_path.setattr(BioAnalysisStore, '_raw_lineage_in_phase',
                lambda self, db, project, source, **kwargs: self.raw(db, project, source))
            assert service.freeze(db, project, request) == saved
    nonempty = [p for p in phases if p['full_reads']]
    assert len(nonempty) == 2
    assert all(p['full_reads']==4 and p['proof_hits']==12 for p in nonempty)
    assert payload['table_raws'] and all(isinstance(raw, bytes) for raw in payload['table_raws'])
    assert all('phase' not in str(source.model_dump()) for source in bindings)
    response = client.post(base+'/research-reports', json=request.model_dump(mode='json'),
                           headers={'Idempotency-Key':'phase-diamond-report'})
    assert response.status_code == 201, response.text
    report = response.json();phases.clear()
    done = run_research_report_task(report['task_id'], report['task']['revision'], engine=render_report,
                                   staging_directory=tmp_path/'report-stage')
    assert done['status'] == 'succeeded', done
    nonempty = [p for p in phases if p['full_reads']]
    # Initial, prepare, admission, pre-publication and final settlement all fresh.
    assert len(nonempty) >= 5
    assert all(p['full_reads']==4 and p['proof_hits']==12 for p in nonempty)
    assert sum(p['verified_bytes'] for p in nonempty) >= 5*nonempty[0]['verified_bytes']


def test_warm_raw_proof_does_not_bypass_locator_cycle_depth_or_source_sha(client, monkeypatch, tmp_path):
    from app.domain.source_byte_verification import VerificationPhase
    from app.domain.research_results.sources import ResearchSourceReader
    from app.core.exceptions import StorageError
    from tests.integration.test_research_validation_efficiency import report_service
    base, value = processed(client, monkeypatch, tmp_path)
    project = base.rsplit('/',1)[-1];assets = report_service(project).assets
    reader = ResearchSourceReader(assets)
    member = next(m for m in value['members'] if m['key']=='observations')
    selection = dict(source_kind='bio_analysis_artifact', source_id=member['id'])
    cases = [({'locator':{'kind':'row','column':'missing','row_key':{'barcode':'AA-1'}}}, ()),
             ({'sha256':'0'*64}, ()),
             ({}, (('bio_analysis_artifact',member['id']),)),
             ({}, tuple(('original_file',str(i)) for i in range(16)))]
    with reader.store.connection() as db:
        for change, chain in cases:
            with VerificationPhase(db, assets, project) as phase:
                reader._read_source_in_phase(project,selection,db=db,phase=phase)
                assert phase.receipt()['full_reads']==4
                with pytest.raises(StorageError):
                    reader._read_source_in_phase(project,{**selection,**change},db=db,phase=phase,chain=chain)
                with pytest.raises(StorageError):phase.check(db,assets,project)


def test_b04_actual_matrix_consumers_hash_again_while_unconsumed_lineage_reuses_proof(client, monkeypatch, tmp_path):
    from pathlib import Path
    from app.domain.source_byte_verification import VerificationPhase, RAW_MATRIX_KEYS
    from app.domain.bio_insights.sources import InsightSourceReader
    from app.core.exceptions import StorageError
    from tests.integration.test_research_validation_efficiency import report_service
    base, value = processed(client, monkeypatch, tmp_path)
    project = base.rsplit('/',1)[-1];assets = report_service(project).assets
    reader = InsightSourceReader(assets)
    selection = dict(source_kind='bio_processed_dataset_version', source_id=value['id'],
                     sha256=value['manifest_sha256'], role='processed')
    with reader.store.connection() as db:
        _, _, members = reader.bio.raw(db,project,value['source']['raw_source'])
        matrix_paths = {str(reader.bio.raw_store.objects.path(m['object_key'])) for m in members if m['key'] in RAW_MATRIX_KEYS}
        calls = [];original_verify = InsightSourceReader._verify
        def observe(path, record, progress=None):
            if str(path) in matrix_paths:calls.append(str(path))
            return original_verify(path,record,progress)
        monkeypatch.setattr(InsightSourceReader, '_verify', staticmethod(observe))
        for lineage_only in (False, True):
            calls.clear()
            with VerificationPhase(db,assets,project) as phase:
                first = reader._resolve_in_phase(db,project,selection,phase=phase,lineage_only=lineage_only)
                first['metadata']['observations'][0]['barcode']='caller mutation'
                second = reader._resolve_in_phase(db,project,selection,phase=phase,lineage_only=lineage_only)
                assert second['metadata']['observations'][0]['barcode']!='caller mutation'
                assert len(calls)==(0 if lineage_only else 6)
                assert phase.receipt()['full_reads']==4
        with VerificationPhase(db,assets,project) as phase:
            reader._resolve_in_phase(db,project,selection,phase=phase,lineage_only=False)
            path=Path(sorted(matrix_paths)[0]);raw=path.read_bytes()
            path.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
            # Ancestor proof may hit, but actual scientific input _leaf hashes.
            with pytest.raises(StorageError):
                reader._resolve_in_phase(db,project,selection,phase=phase,lineage_only=False)
