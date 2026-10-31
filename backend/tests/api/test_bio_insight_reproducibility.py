"""Real scoped export/storage, with explicit synthetic lifecycle runtime proof."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import zipfile
import pytest
from tests.api.test_projects import client,create_project
from tests.api.test_bio_insight_publication import create_run,synthetic_engine


def fixed_fixture_runtime(monkeypatch):
    from app.domain.bio_insights.settings import engine_code_digest,engine_lock_digest,BioInsightsLimits
    from app.domain.bioinformatics.contracts import digest
    from app.domain.bio_insights.service import BioInsightsService
    from app.domain.bio_insights import reproducibility
    environment=dict(python='explicit synthetic export fixture, not numerical runtime validation',packages={'pydeseq2':'0.5.4','gseapy':'1.3.1'},
        native_libraries=[],lock_sha256=engine_lock_digest(),limits=BioInsightsLimits().model_dump())
    runtime=dict(engine_version='bio_insights_v1.0.0',code_digest=engine_code_digest(),environment_digest=digest(environment),lock_sha256=engine_lock_digest())
    monkeypatch.setattr(BioInsightsService,'_runtime',lambda self:runtime)
    monkeypatch.setattr(reproducibility,'environment_proof',lambda identity:dict(environment=environment,runtime_identity={'available':True,**runtime},
        evidence_scope='synthetic_lifecycle_export_fixture_only'))
    return runtime


def published(client,monkeypatch,tmp_path):
    from app.domain.bio_insights.execution import run_bio_insight_task
    monkeypatch.setattr('tests.api.test_bio_insight_publication.runtime',fixed_fixture_runtime)
    project,run=create_run(client,monkeypatch)
    done=run_bio_insight_task(run['task_id'],run['task_revision'],task_type='bio_result_import',engine=synthetic_engine,staging_directory=tmp_path/'stage')
    assert done['status']=='succeeded',done
    return project,done['result_bio_insight_result_version_id']


def verify_module(root):
    import sys
    spec=importlib.util.spec_from_file_location('exported_b04_reproduce',root/'reproduce.py')
    module=importlib.util.module_from_spec(spec);prior=sys.dont_write_bytecode
    try:sys.dont_write_bytecode=True;spec.loader.exec_module(module)
    finally:sys.dont_write_bytecode=prior
    return module


def test_formal_result_exports_frozen_inputs_code_lock_and_independent_verify(client,monkeypatch,tmp_path):
    project,identifier=published(client,monkeypatch,tmp_path)
    # Deployment carries app resources, not the repository's script directory.
    repository_scripts=Path(__file__).resolve().parents[3]/'script';read_bytes=Path.read_bytes
    def without_repository_scripts(path):
        if path.resolve().is_relative_to(repository_scripts):raise AssertionError('API cannot depend on repository script files')
        return read_bytes(path)
    monkeypatch.setattr(Path,'read_bytes',without_repository_scripts)
    response=client.get(f'/api/v1/projects/{project}/bio-insight-results/{identifier}/reproducibility-package')
    assert response.status_code==200,response.text
    directory=tmp_path/'package';directory.mkdir()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:archive.extractall(directory)
    package=json.loads((directory/'package.json').read_bytes())
    assert package['identity']['result_version_id']==identifier and package['synthetic_status']['status']=='unknown'
    assert package['baseline'] and (directory/'code/app/adapters/bio_insights_engine/worker.py').is_file()
    assert (directory/'reproduce.py').is_file() and (directory/'render_worker.py').is_file()
    result=verify_module(directory).verify_package(directory,manifest_sha256=response.headers['X-Reproducibility-Manifest-SHA256'])
    assert result['status']=='verified' and result['executed_analysis'] is False
    assert str(tmp_path).encode() not in (directory/'input/payload.json').read_bytes()
    other=create_project(client)['id']
    assert client.get(f'/api/v1/projects/{other}/bio-insight-results/{identifier}/reproducibility-package').status_code==404


def test_unavailable_frozen_environment_proof_never_exports_a_success_package(client,monkeypatch,tmp_path):
    project,identifier=published(client,monkeypatch,tmp_path)
    from app.domain.bio_insights import reproducibility
    from app.adapters.bio_insights_store import invalid
    monkeypatch.setattr(reproducibility,'environment_proof',lambda _:(_ for _ in ()).throw(invalid('bio_insights_environment_unavailable',422)))
    response=client.get(f'/api/v1/projects/{project}/bio-insight-results/{identifier}/reproducibility-package')
    assert response.status_code==422,response.text


def test_processed_source_proof_uses_formal_manifest_not_inner_member_with_same_key(client,monkeypatch,tmp_path):
    from tests.integration.test_bio_analysis_wait import create,run,confirm,payload_engine
    from app.domain.bioinformatics.contracts import canonical
    from app.db.database import database_connection
    from app.core.config import get_data_dir
    from app.adapters.storage import ProjectStore
    from app.domain.bio_insights.sources import InsightSourceReader
    from app.domain.bio_insights.reproducibility import BioInsightReproductionService
    from app.adapters.bio_insights_reproduction import ReproductionArchive
    def engine(payload,output,mode):
        result=payload_engine(payload,output,mode);content=canonical(result['manifest']);path=Path(output)/'manifest.json';path.write_bytes(content)
        result['outputs'].append(dict(key='manifest',path=str(path),role='manifest',format='json',size_bytes=len(content),sha256=hashlib.sha256(content).hexdigest()))
        return result
    base,created,staging,_=create(client,monkeypatch,tmp_path)
    assert run(created['task'],staging,engine)['status']=='waiting_confirmation'
    queued=confirm(client,base,created,client.get(base+'/bio-analysis-runs/'+created['id']).json());assert queued.status_code==202
    done=run(queued.json(),staging,engine);assert done['status']=='succeeded'
    project=base.rsplit('/',1)[-1];identifier=done['result_bio_processed_dataset_version_id']
    with database_connection() as db:
        owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(project,)).fetchone()['owner_id']
        sha=db.execute('SELECT manifest_sha256 FROM bio_processed_dataset_versions WHERE id=%s',(identifier,)).fetchone()['manifest_sha256']
    assets=ProjectStore(get_data_dir(),owner_id=owner);reader=InsightSourceReader(assets);service=BioInsightReproductionService(assets);archive=ReproductionArchive()
    try:
        with reader.store.connection() as db:
            source=reader.resolve(db,project,dict(source_kind='bio_processed_dataset_version',source_id=identifier,sha256=sha,role='processed'))
            assert source['members']['manifest']['sha256']!=source['sha256']
            before=dict(source['members']['manifest'])
            proof=service._processed_source_proof(db,project,source,archive)
        assert proof['proof']=='formal_manifest_bytes' and archive.records[proof['path']]['sha256']==source['sha256']
        assert source['members']['manifest']==before
    finally:archive.close()


def test_restricted_resource_bytes_are_external_and_can_only_be_supplied_with_matching_sha(client,monkeypatch,tmp_path):
    from app.domain.bio_insights.execution import run_bio_insight_task
    fixed_fixture_runtime(monkeypatch);project=create_project(client)['id'];base=f'/api/v1/projects/{project}'
    original=b'TERM_RESTRICTED\tSecret term\tPRIVATE1\tPRIVATE2\n'
    uploaded=client.post(base+'/bio-resource-files',files={'file':('private.gmt',original)},headers={'Idempotency-Key':'restricted-original'}).json()
    body=dict(kind='gene_sets',title='restricted test',species_taxon_id=9606,namespace='Ensembl',release='fixed-v1',
        source={'institution':'test lab','name':'provided test resource','description':'synthetic export permission fixture'},
        usage={'basis':'test owner only','scope':'project','redistribution_allowed':False},
        files=[{'file_id':uploaded['file_id'],'sha256':uploaded['sha256'],'role':'gmt','format':'gmt'}])
    response=client.post(base+'/bio-resources',json=body,headers={'Idempotency-Key':'restricted-resource'})
    assert response.status_code==202,response.text
    resource=response.json()
    from app.domain.bio_insights.contracts import ResourceImportRequest
    cfg=ResourceImportRequest.model_validate(body).model_dump(mode='json')
    files=[{k:f[k] for k in ('file_id','sha256','format','role')} for f in cfg['files']]
    data={k:cfg[k] for k in ('kind','species_taxon_id','namespace','release','source','usage','strip_ensembl_version')}
    data.update(schema_version=1,importer_version='bio_resource_import_v1',input_files=files,
        terms=[{'term_id':'TERM_RESTRICTED','name':'Secret term','namespace':'custom','genes':['PRIVATE1','PRIVATE2']}])
    def engine(payload,output):
        from tests.domain.bio_insight_validation_fixtures import put,portable,refresh
        methods={key:cfg[key] for key in ('release','source','usage')};methods.update(resource_kind='gene_sets',input_files=files)
        result=dict(_root=str(output),schema_version=1,status='completed',kind=payload['kind'],identity=payload['identity'],engine_version='bio_insights_v1.0.0',
            summary={'synthetic_export_fixture':True},methods=methods,inference_scope='derived',provenance='system_computed',outputs=[])
        put(result,'resource',data)
        put(result,'term_genes',(['term_id','term_name','namespace','feature_id'],[{'term_id':'TERM_RESTRICTED','term_name':'Secret term','namespace':'custom','feature_id':gene} for gene in ('PRIVATE1','PRIVATE2')]),'tsv')
        put(result,'resource_exclusions',(['row_number','feature_id','term_id','reason'],[]),'tsv')
        put(result,'functional_classification',(['category','gene_count','mutually_exclusive'],[]),'tsv')
        put(result,'methods',methods);put(result,'recipe',portable(payload))
        result['manifest']=dict(schema_version=1,kind=payload['kind'],identity=payload['identity'],engine_version='bio_insights_v1.0.0',summary=result['summary'],methods=methods,
            inference_scope='derived',provenance='system_computed',source_bindings=portable(payload['sources']),members=[])
        put(result,'manifest',{});refresh(result);result.pop('_root');return result
    done=run_bio_insight_task(resource['task_id'],resource['task']['revision'],task_type='bio_resource_import',engine=engine,staging_directory=tmp_path/'resource-stage')
    assert done['status']=='succeeded',done
    exported=client.get(base+'/bio-resources/'+resource['id']+'/reproducibility-package')
    assert exported.status_code==200,exported.text
    directory=tmp_path/'restricted-package';directory.mkdir()
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        assert all(b'PRIVATE1' not in archive.read(name) for name in archive.namelist())
        archive.extractall(directory)
    package=json.loads((directory/'package.json').read_bytes());assert package['required_resources'] and package['analysis_inputs_self_contained'] is False
    module=verify_module(directory)
    with pytest.raises(ValueError,match='Missing required resource'):module.verify_package(directory)
    supplied={};required={r['sha256'] for r in package['required_resources']}
    saved=client.get(base+'/bio-resources/'+resource['id']).json()
    for index,member in enumerate(saved['members']):
        if member['sha256'] not in required:continue
        downloaded=client.get(member['download_url']);assert downloaded.status_code==200
        path=tmp_path/('provided-'+str(index)+'.bin');path.write_bytes(downloaded.content);supplied[member['sha256']]=str(path)
    assert module.verify_package(directory,supplied,exported.headers['X-Reproducibility-Manifest-SHA256'])['status']=='verified'
