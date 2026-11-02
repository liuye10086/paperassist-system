"""Small actual sandboxed microbiome/figure gate; no accepted old model fits."""
import csv,hashlib,json,os,struct,sys
from pathlib import Path
NAMES=('diversity','composition','alpha','pcoa')

def exercise(root):
    from .worker import actual_identity,warm_render_environment,warm_microbiome_environment
    from .probe_transport import monitored_run
    from app.adapters.bio_insights_process import validate_result
    from app.adapters.bio_engine.tabular_assays import import_tabular
    from app.domain.bio_insights.microbiome_contracts import MicrobiomeConfig
    from app.domain.bio_insights.contracts import FigureConfig
    root=Path(root);root.mkdir(parents=True,exist_ok=True);warm=root/'warm';warm.mkdir();warm_render_environment(warm);warm_microbiome_environment()
    runtime=actual_identity();identity={k:runtime[k] for k in ('engine_version','code_digest','environment_digest','lock_sha256')};identity.update(project_id='synthetic',task_id='synthetic-microbiome',plan_version_id='synthetic-plan',source_digest='f'*64)
    samples=['S'+str(i+1) for i in range(6)];x=[10,20,40,60,80,100];files=[]
    for name,role,content in [('matrix','quantitative_matrix','feature_id\t'+'\t'.join(samples)+'\nF1\t'+'\t'.join(map(str,x))+'\nF2\t'+'\t'.join(str(100-v) for v in x)+'\n'),('samples','sample_metadata','sample_id\tgroup\tunit\n'+''.join(s+'\t'+('A' if i<3 else 'B')+'\t'+s+'\n' for i,s in enumerate(samples))),('taxonomy','feature_metadata','feature_id\tKingdom\tPhylum\tGenus\nF1\tBacteria\tP\tG1\nF2\tBacteria\tP\tNA\n')]:
        path=root/(name+'.tsv');path.write_text(content,encoding='utf-8');files.append(dict(id=name,filename=path.name,role=role,path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),size_bytes=path.stat().st_size,format='tsv'))
    cfg=dict(workflow_version='bio_import_v3',file_ids=[f['id'] for f in files],assay='microbiome',name='synthetic microbiome',expected_dataset_revision=0,tables=[dict(file_id=f['id'],role=f['role'],format='tsv') for f in files],feature_id_column='feature_id',sample_columns=samples,scale=dict(kind='raw_counts',unit='counts',upstream_method='synthetic fixed oracle',namespace='taxonomy',reference_version='fixed'))
    rawdir=root/'raw';rawdir.mkdir();raw=import_tabular(dict(config=cfg,files=files,output_directory=str(rawdir)))
    source=dict(source_kind='bio_processed_dataset_version',source_id='processed',role='processed',sha256='a'*64,project_id='synthetic',locator=dict(kind='object'),members={},raw=dict(manifest=raw['manifest'],members={m['key']:m for m in raw['outputs']}),metadata=dict(assay='microbiome',observations=[],source_file_ids=['matrix','samples','taxonomy'],raw_dataset_version_id='raw'))
    config=MicrobiomeConfig(processed_source_id='processed',abundance_scale='counts',measurement_pipeline='synthetic',classification_database='synthetic',classification_version='1',host_identity='synthetic host',feature_identity='microbial taxa',taxonomy_columns=['Kingdom','Phylum','Genus'],aggregate_rank='Genus',group_column='group',unit_column='unit',design='independent',independence_confirmed=True,independence_basis='synthetic independent samples',beta_inference=True,permutations=19,contrasts=[dict(contrast_id='A_B',name='A-B',numerator='A',denominator='B')],family_contrast_ids=['A_B'])
    def child(kind,config,sources,name):
        from .transport import project_transport_payload
        dest=root/name;dest.mkdir();request=project_transport_payload(dict(schema_version=1,kind=kind,config=config,sources=sources,identity=identity,output_directory=str(dest),_runtime_identity=runtime));body=json.dumps(request,allow_nan=False).encode()
        process=monitored_run([sys.executable,'-I','-B',str(Path(__file__).with_name('worker.py')),str(os.getpid())],struct.pack('!I',len(body))+body,timeout=180)
        (root/(name+'-stderr.txt')).write_bytes(process.stderr)
        if process.returncode or not process.stdout.startswith(b'READY\n'):raise RuntimeError('microbiome_child_transport_failed')
        answer=json.loads(process.stdout[6:])
        (root/(name+'-answer.json')).write_text(json.dumps(answer),encoding='utf-8')
        if 'result' not in answer:raise RuntimeError('microbiome_child_failed:'+json.dumps(answer))
        result=answer['result'];validate_result(result,dest,request)
        (root/(name+'-request.json')).write_text(json.dumps(request,allow_nan=False),encoding='utf-8');(root/(name+'-result.json')).write_text(json.dumps(result,allow_nan=False),encoding='utf-8');return result
    result=child('bio_comparison',config.model_dump(mode='json'),[source],'diversity')
    upstream=dict(source_kind='bio_insight_result_version',source_id='result',role='result',sha256='b'*64,project_id='synthetic',locator=dict(kind='object'),members={m['key']:m for m in result['outputs']},metadata=dict(kind='comparison',plan_config=config.model_dump(mode='json'),inference_scope='sample_inference',provenance='system_computed'))
    for name in NAMES[1:]:
        figure=FigureConfig(result_source_id='result',figure_type='microbiome_'+name,feature_ids=['shannon'] if name=='alpha' else [],formats=['png'])
        plotted=child('bio_insight_figure',figure.model_dump(mode='json'),[upstream],name)
        assert any(m['format']=='png' for m in plotted['outputs'])
    return dict(runtime_identity=runtime,checks=dict(microbiome_diversity=True,microbiome_beta=True,microbiome_figures=True),evidence_scope='synthetic_actual_microbiome_isolated_children_only')

def validate_parent(root):
    from app.adapters.bio_insights_process import validate_result
    root=Path(root)
    for name in NAMES:
        request=json.loads((root/(name+'-request.json')).read_bytes());result=json.loads((root/(name+'-result.json')).read_bytes());validate_result(result,root/name,request)
    return dict(checks=dict(microbiome_parent_validation=True),validated_names=NAMES)
if __name__=='__main__':print(json.dumps(validate_parent(sys.argv[2]) if sys.argv[1]=='--validate-parent' else exercise(sys.argv[1]),sort_keys=True))
