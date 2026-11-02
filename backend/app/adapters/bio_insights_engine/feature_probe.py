"""Synthetic actual sandboxed feature gate, with no old scientific model refits."""
import hashlib,json,os,struct,sys
from pathlib import Path
NAMES=('sequence-import','structure-import','extract','distribution','scatter')


def exercise(root):
    from .worker import actual_identity,warm_render_environment
    from .probe_transport import monitored_run
    from app.adapters.bio_insights_process import validate_result
    from app.domain.bio_insights.contracts import ResourceImportRequest,FigureConfig
    from app.domain.bio_insights.feature_contracts import FeatureExtractConfig
    root=Path(root);root.mkdir(parents=True,exist_ok=True);warm=root/'warm';warm.mkdir();warm_render_environment(warm)
    runtime=actual_identity();identity={k:runtime[k] for k in ('engine_version','code_digest','environment_digest','lock_sha256')}
    identity.update(project_id='synthetic-feature',task_id='synthetic-task',plan_version_id='synthetic-plan',source_digest='f'*64)
    observations={}
    def child(kind,config,sources,name,resource_id=None):
        from .transport import project_transport_payload
        dest=root/name;dest.mkdir();binding={**identity}
        if resource_id:binding['resource_version_id']=resource_id
        request=project_transport_payload(dict(schema_version=1,kind=kind,config=config,sources=sources,identity=binding,output_directory=str(dest),_runtime_identity=runtime))
        body=json.dumps(request,allow_nan=False).encode()
        process=monitored_run([sys.executable,'-I','-B',str(Path(__file__).with_name('worker.py')),str(os.getpid())],struct.pack('!I',len(body))+body,timeout=180)
        (root/(name+'-stderr.txt')).write_bytes(process.stderr)
        if process.returncode or not process.stdout.startswith(b'READY\n'):raise RuntimeError('feature_child_transport_failed')
        answer=json.loads(process.stdout[6:]);(root/(name+'-answer.json')).write_text(json.dumps(answer),encoding='utf-8')
        if 'result' not in answer:raise RuntimeError('feature_child_failed:'+json.dumps(answer))
        result=answer['result'];validate_result(result,dest,request)
        observations[name]=result.get('resources',{})
        (root/(name+'-request.json')).write_text(json.dumps(request,allow_nan=False),encoding='utf-8');(root/(name+'-result.json')).write_text(json.dumps(result,allow_nan=False),encoding='utf-8')
        return result
    frozen=[]
    for name,kind,fmt,content in [('sequence','sequence','fasta','>x\nACGTNN\n>y\nNN\n'),('structure','structure','pdb','ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C  \nATOM      2  CA  GLY A   2A      2.000   0.000   0.000  1.00 20.00           C  \n')]:
        raw=root/(name+'.'+fmt);raw.write_text(content,encoding='utf-8');sha=hashlib.sha256(raw.read_bytes()).hexdigest()
        source=dict(source_kind='original_file',source_id=name+'-file',role=fmt,sha256=sha,project_id='synthetic-feature',locator=dict(kind='object'),metadata={},members={'original_file':dict(path=str(raw),sha256=sha,size_bytes=raw.stat().st_size,format=fmt,role=fmt)})
        config=ResourceImportRequest(kind=kind,title=name,species_taxon_id=9606,namespace='local',release='fixture1',sequence_type='dna' if kind=='sequence' else None,nucleotide_encoding='T' if kind=='sequence' else None,structure_origin='experimental' if kind=='structure' else None,
            source=dict(institution='synthetic',name='fixture',description='synthetic engineering oracle'),usage=dict(basis='synthetic fixture',redistribution_allowed=True,scope='project'),files=[dict(file_id=name+'-file',sha256=sha,role=fmt,format=fmt)])
        result=child('bio_resource_import',config.model_dump(mode='json'),[source],name+'-import',name)
        frozen.append(dict(source_kind='bio_resource_version',source_id=name,role='feature_input',sha256='a'*64,project_id='synthetic-feature',locator=dict(kind='object'),metadata=dict(kind=kind),members={m['key']:m for m in result['outputs']}))
    cfg=FeatureExtractConfig(resource_source_ids=['sequence','structure'],structure_selections=[dict(resource_source_id='structure',model_id=1,chain_id='A')])
    result=child('bio_feature_extract',cfg.model_dump(mode='json'),frozen,'extract')
    data=json.loads(next(Path(m['path']).read_bytes() for m in result['outputs'] if m['key']=='feature_data'))
    seq=next(r for r in data['rows'] if r['original_id']=='x');structure=next(r for r in data['rows'] if r['feature_kind']=='structure')
    assert (seq['length'],seq['valid_count'],seq['gc_fraction'])==(6,4,.5)
    assert structure['centroid_x']==1.0 and structure['radius_of_gyration']==1.0
    upstream=dict(source_kind='bio_insight_result_version',source_id='result',role='result',sha256='b'*64,project_id='synthetic-feature',locator=dict(kind='object'),metadata=dict(kind='feature_extract',plan_config=cfg.model_dump(mode='json'),inference_scope='derived',provenance='system_computed'),members={m['key']:m for m in result['outputs']})
    for name in ('distribution','scatter'):
        figure=FigureConfig(result_source_id='result',figure_type='feature_'+name,x_column='length',y_column='gc_fraction' if name=='scatter' else None,formats=['png'])
        child('bio_insight_figure',figure.model_dump(mode='json'),[upstream],name)
    return dict(runtime_identity=runtime,checks=dict(feature_sequence=True,feature_structure=True,feature_figures=True),evidence_scope='synthetic_actual_feature_isolated_children_only',execution_resources=observations,peak_rss_kib=max(v['child_peak_rss_kib'] for v in observations.values()))


def validate_parent(root):
    from app.adapters.bio_insights_process import validate_result
    root=Path(root)
    for name in NAMES:
        request=json.loads((root/(name+'-request.json')).read_bytes());result=json.loads((root/(name+'-result.json')).read_bytes());validate_result(result,root/name,request)
    return dict(checks=dict(feature_parent_validation=True),validated_names=NAMES)

if __name__=='__main__':print(json.dumps(validate_parent(sys.argv[2]) if sys.argv[1]=='--validate-parent' else exercise(sys.argv[1]),sort_keys=True))
