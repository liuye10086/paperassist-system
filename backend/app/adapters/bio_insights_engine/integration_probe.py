"""Actual bounded sandbox tasks for matching, correlation, concordance and figures."""
import hashlib,json,os,struct,sys
from pathlib import Path
NAMES=('sample-import','object-import','integration','descriptive','network','flow')

def fixture_sources(root):
    import numpy as np
    from app.adapters.bio_engine.manifest import Writer
    root=Path(root);sources=[]
    for sid,samples,values in [('left',['a1','a2','a3','a4'],[1.,2.,3.,4.]),('right',['b3','b1','b2'],[6.,2.,4.])]:
        dest=root/('layer-'+sid);dest.mkdir();w=Writer(dest)
        descriptor=dict(values='analysis_values',missing='analysis_missing',shape=[len(samples),1],scale='author_provided_unit_unknown',unit='unknown',normalization='none',transform='none')
        w.array('analysis_values',np.asarray(values).reshape(-1,1));w.array('analysis_missing',np.zeros((len(samples),1),dtype=bool));w.array('observation_mask',np.ones(len(samples),dtype=bool));w.array('feature_mask',np.ones(1,dtype=bool))
        w.table('samples',[dict(sample_id=x) for x in samples]);w.table('features',[dict(feature_id='g')]);w.json('manifest',dict(schema_version=2,observation_level='sample',layers={'analysis':descriptor}))
        sources.append(dict(source_kind='bio_processed_dataset_version',source_id=sid,project_id='integration-fixture',sha256='a'*64,role='processed',locator={'kind':'object'},metadata=dict(observation_level='sample',species_taxon_id=9606,namespace='symbol',reference_version='fixture1',canonical_dataset_id='same-canonical',layers={'analysis':descriptor},observations=[dict(sample_id=s,retained=True) for s in samples]),members={m['key']:m for m in w.artifacts}))
    for sid,effects in [('result-left',[1.,1.,1.,None]),('result-right',[-2.,2.,-2.,2.])]:
        dest=root/sid;dest.mkdir();w=Writer(dest)
        w.table('comparison_results',[dict(row_key=sid+str(i),feature_id='g'+str(i),contrast_id='c',effect_value=e,q_within_contrast=.2 if i==2 else .01,tested=e is not None,numerator='A',denominator='B',effect_unit='log2fold') for i,e in enumerate(effects)])
        sources.append(dict(source_kind='bio_insight_result_version',source_id=sid,project_id='integration-fixture',sha256='b'*64,role='result',locator={'kind':'object'},metadata=dict(kind='comparison',summary_json={'tested_universe_complete':True},species_taxon_id=9606,namespace='symbol',reference_version='fixture1',canonical_dataset_ids=['same-canonical']),members={m['key']:m for m in w.artifacts}))
    return sources

def fixture_config():
    from app.domain.bio_insights.integration_contracts import IntegrationConfig
    return IntegrationConfig(processed_source_ids=['left','right'],sample_mapping_source_id='sample',object_mapping_source_id='object',pairs=[dict(pair_id='pair',left_source_id='left',left_feature_id='g',right_source_id='right',right_feature_id='g')],concordances=[dict(concordance_id='c',left_result_source_id='result-left',right_result_source_id='result-right',left_contrast_id='c',right_contrast_id='c',object_ids=['g0','g1','g2','g3'],direction_alignment='reverse',comparison_basis='explicit reversed controls')],mode='inference',mapping_confirmed=True,partial_subset_confirmed=True,independence_confirmed=True,independence_basis='synthetic unique donor fixture')

def exercise(root):
    from .worker import actual_identity,warm_render_environment
    from .probe_transport import monitored_run
    from .transport import project_transport_payload
    from app.adapters.bio_insights_process import validate_result
    from app.domain.bio_insights.contracts import ResourceImportRequest,FigureConfig
    from app.domain.bio_insights.integration_contracts import SAMPLE_COLUMNS,OBJECT_COLUMNS
    from app.adapters.bio_engine.manifest import Writer
    root=Path(root);root.mkdir(parents=True,exist_ok=True);warm=root/'warm';warm.mkdir();warm_render_environment(warm)
    runtime=actual_identity();identity={k:runtime[k] for k in ('engine_version','code_digest','environment_digest','lock_sha256')};identity.update(project_id='integration-fixture',task_id='task',plan_version_id='plan',source_digest='f'*64)
    resources={}
    def child(kind,config,sources,name,resource_id=None):
        dest=root/name;dest.mkdir();binding={**identity}
        if resource_id:binding['resource_version_id']=resource_id
        request=project_transport_payload(dict(schema_version=1,kind=kind,config=config,sources=sources,identity=binding,output_directory=str(dest),_runtime_identity=runtime))
        body=json.dumps(request,allow_nan=False).encode();process=monitored_run([sys.executable,'-I','-B',str(Path(__file__).with_name('worker.py')),str(os.getpid())],struct.pack('!I',len(body))+body,timeout=180)
        (root/(name+'-stderr.txt')).write_bytes(process.stderr)
        if process.returncode or not process.stdout.startswith(b'READY\n'):raise RuntimeError('integration_child_transport_failed')
        answer=json.loads(process.stdout[6:]);(root/(name+'-answer.json')).write_text(json.dumps(answer),encoding='utf-8')
        if 'result' not in answer:raise RuntimeError('integration_child_failed:'+json.dumps(answer))
        result=answer['result'];validate_result(result,dest,request);resources[name]=result.get('resources',{})
        (root/(name+'-request.json')).write_text(json.dumps(request,allow_nan=False),encoding='utf-8');(root/(name+'-result.json')).write_text(json.dumps(result,allow_nan=False),encoding='utf-8');return result
    sources=fixture_sources(root);raw=root/'raw';raw.mkdir();w=Writer(raw)
    rows=[dict(dataset_version=sid,observation_id=prefix+str(i),donor_id='d'+str(i),tissue='fixed',time='fixed',match_group=str(i),relationship='same_sample',basis='synthetic declared matching',independent_unit_verified=True) for sid,prefix in [('left','a'),('right','b')] for i in (1,2,3)]
    mapping=[dict(source_dataset_version='left',source_id='g',source_namespace='symbol',source_species=9606,source_version='fixture1',target_dataset_version='right',target_id='g',target_namespace='symbol',target_species=9606,target_version='fixture1',relationship='same_feature',basis='synthetic mapping',ambiguity='none',decision='include')]
    for name,kind,rows,columns in [('sample','sample_correspondence',rows,SAMPLE_COLUMNS),('object','object_correspondence',mapping,OBJECT_COLUMNS)]:
        member=w.table(name,rows,columns);raw_source=dict(source_kind='original_file',source_id=name+'-file',project_id='integration-fixture',sha256=member['sha256'],role=kind,locator={'kind':'object'},metadata={},members={'original_file':member})
        config=ResourceImportRequest(kind=kind,title=name,species_taxon_id=9606,namespace='symbol',release='fixture1',source=dict(institution='synthetic',name=name,description='engineering fixture'),usage=dict(basis='synthetic fixture',redistribution_allowed=True,scope='project'),files=[dict(file_id=name+'-file',sha256=member['sha256'],role=kind,format='tsv')])
        result=child('bio_resource_import',config.model_dump(mode='json'),[raw_source],name+'-import',name)
        sources.append(dict(source_kind='bio_resource_version',source_id=name,project_id='integration-fixture',sha256='c'*64,role='sample_mapping' if name=='sample' else 'object_mapping',locator={'kind':'object'},metadata={'kind':kind},members={m['key']:m for m in result['outputs']}))
    config=fixture_config();result=child('bio_integration',config.model_dump(mode='json'),sources,'integration')
    data=json.loads(next(Path(m['path']).read_bytes() for m in result['outputs'] if m['key']=='integration_data'))
    row=data['correlations'][0]
    assert row['matched_observation_count']==3 and row['independent_n']==3 and abs(row['coefficient']-1.)<1e-8
    assert any(r['observation_id']=='a4' and r['reason']=='unmapped_observation' for r in data['sample_audit'])
    assert [r['status'] for r in data['concordances']]==['support','conflict','below_threshold','unknown']
    assert data['dependency_groups']['groups']==[sorted(['left','right','result-left','result-right'])]
    descriptive=config.model_copy(update={'mode':'descriptive'});desc=child('bio_integration',descriptive.model_dump(mode='json'),sources,'descriptive')
    assert desc['summary']['independent_n'] is None
    upstream=dict(source_kind='bio_insight_result_version',source_id='integrated',project_id='integration-fixture',sha256='d'*64,role='result',locator={'kind':'object'},metadata=dict(kind='integration',plan_config=config.model_dump(mode='json'),inference_scope='derived',provenance='system_computed'),members={m['key']:m for m in result['outputs']})
    for name in ('network','flow'):
        cfg=FigureConfig(result_source_id='integrated',figure_type='integration_'+name,formats=['png'])
        figure=child('bio_insight_figure',cfg.model_dump(mode='json'),[upstream],name)
        plot=json.loads(next(Path(m['path']).read_bytes() for m in figure['outputs'] if m['key']=='plot_data'))
        assert plot['nodes']==data['nodes'] and plot['edges']==data['edges'] and plot['analysis_recomputed'] is False
    return dict(runtime_identity=runtime,checks=dict(integration_matching=True,integration_correlation=True,integration_concordance=True,integration_figures=True),evidence_scope='synthetic_actual_integration_isolated_children_only',execution_resources=resources,peak_rss_kib=max(v['child_peak_rss_kib'] for v in resources.values()))

def validate_parent(root):
    from app.adapters.bio_insights_process import validate_result
    root=Path(root)
    for name in NAMES:
        request=json.loads((root/(name+'-request.json')).read_bytes());result=json.loads((root/(name+'-result.json')).read_bytes());validate_result(result,root/name,request)
    return dict(checks=dict(integration_parent_validation=True),validated_names=NAMES)

if __name__=='__main__':print(json.dumps(validate_parent(sys.argv[2]) if sys.argv[1]=='--validate-parent' else exercise(sys.argv[1]),sort_keys=True))
