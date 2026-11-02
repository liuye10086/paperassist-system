"""HTTP/CSV/projection contract test; storage is fake, no database or science."""
from contextlib import nullcontext
from types import SimpleNamespace
import hashlib

import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def test_preview_retains_verified_sample_identity_and_rejects_mismatch(monkeypatch):
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient
    from app.api import research_results as api
    from app.adapters.storage import get_request_project_store
    from app.core.exceptions import StorageError
    from app.domain.research_results import insight_sources
    from app.domain.research_results.contracts import FrozenResearchSource
    from app.domain.research_results.sources import ResearchSourceReader
    raw=b'row_key\tfeature_id\tcontrast_id\tp_value\nopaque\tbovine\tprimary\t0\nmissing\trabbit\tprimary\tNA\n'
    digest=hashlib.sha256(raw).hexdigest()
    member=dict(id='member',result_version_id='result',key='comparison_results',role='table',format='tsv',sha256=digest,size_bytes=len(raw))
    row=dict(id='result',task_id='task',kind='comparison',inference_scope='sample_exploratory',provenance='system_computed',summary_json={},methods_json={},
        code_digest='b'*64,environment_digest='c'*64,manifest_sha256='d'*64)
    service=SimpleNamespace(require=lambda db,table,project,identifier:member if table.endswith('_members') else row,
        store=SimpleNamespace(require_task=lambda db,task:dict(status='succeeded')),
        _require_sources_in_phase=lambda *a,**kw:dict(config={'kind':'comparison','schema_version':2},sources=[],identity={}),
        objects=SimpleNamespace(read=lambda current:raw))
    monkeypatch.setattr(insight_sources,'BioInsightsService',lambda assets:service)
    monkeypatch.setattr(insight_sources,'checked_members',lambda *a,**kw:({},[member]))

    class Reader(ResearchSourceReader):
        def __init__(self,assets):
            self.assets=assets
            self.store=SimpleNamespace(connection=lambda:nullcontext(None),require_project=lambda *a:None)

        def read_source(self,project,selection,**kw):
            value=insight_sources.read_insight_source(self,None,project,selection,phase=None)
            return FrozenResearchSource(source_kind=selection.source_kind,source_id=selection.source_id,project_id=project,locator=selection.locator,**value)

    monkeypatch.setattr(api,'ResearchSourceReader',Reader)
    app=FastAPI();app.include_router(api.router)
    app.dependency_overrides[get_request_project_store]=lambda:None

    @app.exception_handler(StorageError)
    async def storage_error(request:Request,exc:StorageError):
        return JSONResponse({'code':exc.code},status_code=422)

    with TestClient(app) as client:
        source=dict(source_kind='bio_insight_result_member',source_id='member',sha256=digest,
            locator=dict(kind='row',table='comparison_results',row_key={'row_key':'opaque'},column='p_value'))
        url='/api/v1/projects/project/research-results/preview'
        old=client.post(url,json={'sources':[source]});assert old.status_code==200,old.text
        old_fact=old.json()['catalogs'][0]['facts'][0]
        source['locator']['row_key'].update(feature_id='bovine',contrast_id='primary')
        rich=client.post(url,json={'sources':[source]});assert rich.status_code==200,rich.text
        fact=rich.json()['catalogs'][0]['facts'][0]
        assert fact['locator']['row_key']==source['locator']['row_key']
        assert fact['raw_value']==old_fact['raw_value']=='0' and fact['verification_status']=='verified'
        source['locator']['row_key']['feature_id']='wrong'
        bad=client.post(url,json={'sources':[source]});assert bad.status_code==422 and bad.json()['code']=='research_locator_invalid'
        source['locator']['row_key']={'row_key':'missing','feature_id':'rabbit','contrast_id':'primary'}
        missing=client.post(url,json={'sources':[source]});assert missing.status_code==200,missing.text
        assert missing.json()['catalogs'][0]['facts'][0]['raw_value']=='NA'
        assert missing.json()['catalogs'][0]['facts'][0]['verification_status']=='missing'
        source['locator']['row_key']={'row_key':'opaque'}
        assert client.post(url,json={'sources':[source]}).json()['catalogs'][0]['facts'][0]==old_fact
