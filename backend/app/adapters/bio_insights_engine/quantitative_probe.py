"""Actual isolated V2 comparisons and sample figures; synthetic engineering gate."""
import hashlib,json,os,struct,sys
from pathlib import Path


def exercise(root):
    from .worker import actual_identity,warm_render_environment
    from .probe_transport import monitored_run
    from app.adapters.bio_engine.tabular_assays import import_tabular,run_tabular,_rows
    from app.adapters.bio_insights_process import validate_result
    from app.domain.bioinformatics.tabular_contracts import BioImportRequestV3
    from app.domain.bio_insights.quantitative_contracts import QuantitativeComparisonConfig
    from app.domain.bio_insights.contracts import FigureConfig
    import numpy as np
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    warm=root/'warm';warm.mkdir();warm_render_environment(warm)
    runtime=actual_identity();identity={k:runtime[k] for k in ('engine_version','environment_digest','code_digest','lock_sha256')}
    identity.update(plan_version_id='synthetic-gate-plan',source_digest='f'*64)
    def child(payload,name):
        dest=root/name;dest.mkdir();request={**payload,'schema_version':1,'identity':identity,'output_directory':str(dest),'_runtime_identity':runtime}
        from .transport import project_transport_payload
        request=project_transport_payload(request);body=json.dumps(request,allow_nan=False).encode()
        process=monitored_run([sys.executable,'-I','-B',str(Path(__file__).with_name('worker.py')),str(os.getpid())],struct.pack('!I',len(body))+body,timeout=1800)
        (root/(name+'-stderr.txt')).write_bytes(process.stderr)
        if process.returncode or not process.stdout.startswith(b'READY\n'):raise RuntimeError('quantitative_child_transport_failed')
        answer=json.loads(process.stdout[6:])
        if 'result' not in answer:raise RuntimeError('quantitative_child_failed:'+json.dumps(answer))
        (root/(name+'-request.json')).write_text(json.dumps(request,allow_nan=False),encoding='utf-8')
        (root/(name+'-result.json')).write_text(json.dumps(answer['result'],allow_nan=False),encoding='utf-8')
        result=validate_result(answer['result'],dest,request)
        if result['resources']['child_peak_rss_kib']>2*1024**2:raise RuntimeError('science_rss_limit')
        return result
    checks={}
    for mode in ('continuous','bulk_counts'):
        directory=root/mode;directory.mkdir();samples=[g+str(i) for g in ('B','A') for i in range(4)]
        rng=np.random.default_rng(511);matrix=rng.negative_binomial(12,.4,size=(30,8)).astype('int64')+1;matrix[:4,:4]*=3
        if mode=='bulk_counts':matrix[0]=0
        content='feature_id,'+','.join(samples)+'\n'+''.join('f'+str(j)+','+','.join(map(str,row))+'\n' for j,row in enumerate(matrix))
        if mode=='continuous':content=content.replace(str(matrix[0,0])+',','NA,',1)
        files=[]
        for role,body in [('quantitative_matrix',content),('sample_metadata','sample_id,condition,biological_unit_id,pair_id,sample_role\n'+''.join(f'{s},{s[0]},{s},pair{s[1]},biological\n' for s in samples))]:
            path=directory/(role+'.csv');path.write_text(body,encoding='utf-8');files.append(dict(id=role,role=role,filename=path.name,path=str(path),size_bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        assay='bulk_rna_counts' if mode=='bulk_counts' else 'proteomics'
        cfg=BioImportRequestV3(workflow_version='bio_import_v3',assay=assay,file_ids=[f['id'] for f in files],name='synthetic quantitative gate',expected_dataset_revision=0,
            tables=[dict(file_id=f['id'],role=f['role'],format='csv') for f in files],feature_id_column='feature_id',sample_columns=samples,
            scale=dict(kind='raw_counts' if mode=='bulk_counts' else 'intensity',unit='count' if mode=='bulk_counts' else 'AU',upstream_method='synthetic gate only',namespace='synthetic_feature',reference_version='fixed'))
        rawdir=directory/'raw';rawdir.mkdir();raw_result=import_tabular(dict(files=files,config=cfg.model_dump(),output_directory=str(rawdir)))
        raw=dict(manifest=raw_result['manifest'],members={m['key']:m for m in raw_result['outputs']})
        procdir=directory/'processed';procdir.mkdir();processed=run_tabular(dict(raw=raw,config={},identity=identity,mode='compute',output_directory=str(procdir)))
        members={m['key']:m for m in processed['outputs']};sid='p-'+mode
        source=dict(source_kind='bio_processed_dataset_version',source_id=sid,sha256='a'*64,role='processed',members=members,raw=raw,
            metadata=dict(canonical_dataset_id='raw-'+mode,observation_level='sample',assay=assay,namespace='synthetic_feature',reference_version='fixed',species_taxon_id=None,
                scale=cfg.scale.model_dump(),layers=processed['manifest']['layers'],observations=[{**r,'processed_version_id':sid,'retained':r['kept']=='True'} for r in _rows(members['samples'])]))
        config=QuantitativeComparisonConfig(mode=mode,design='independent',method='deseq2_wald' if mode=='bulk_counts' else 'welch_t',analysis_layer='raw_counts' if mode=='bulk_counts' else 'analysis',
            contrasts=[dict(contrast_id='B_A',name='B/A',groups=[dict(label=g,sample_keys=[dict(processed_version_id=sid,sample_id=s) for s in samples if s[0]==g]) for g in ('B','A')])],
            family_contrast_ids=['B_A'],namespace='synthetic_feature',reference_version='fixed',design_basis='synthetic gate',data_driven_grouping=False,independence_confirmed=True,independence_basis='synthetic numeric units only',inference_unit='biological',inference_goal='inference')
        result=child(dict(kind='bio_comparison',config=config.model_dump(),sources=[source]),mode+'-comparison')
        assert result['summary']['row_count']==30 and result['summary']['actual_units'][0]['n_numerator']==4
        if mode=='bulk_counts':
            convergence=_rows(next(m for m in result['outputs'] if m['key']=='model_convergence'))
            assert {'_LFC_converged','_genewise_converged','_MAP_converged'}<=convergence[0].keys()
            assert convergence[0]['tested']=='False' and convergence[0]['_LFC_converged']==''
        checks['quantitative_counts' if mode=='bulk_counts' else 'quantitative_continuous']=True
        if mode=='continuous':
            upstream=dict(source_kind='bio_insight_result_version',source_id='result',sha256='b'*64,role='result',members={m['key']:m for m in result['outputs']},
                metadata=dict(kind='comparison',inference_scope=result['inference_scope'],provenance='system_computed',upstream_inference_scopes=[result['inference_scope']]))
            sample_figure_types=[]
            for figure_type in ('distribution','heatmap'):
                fig=FigureConfig(figure_type=figure_type,result_source_id='result',processed_source_id=sid,sample_groups=config.contrasts[0].groups,
                    feature_ids=['f0'] if figure_type=='distribution' else [],contrast_id='B_A',formats=['png','tiff','svg'])
                plotted=child(dict(kind='bio_insight_figure',config=fig.model_dump(),sources=[upstream,source]),'sample-'+figure_type)
                assert len([m for m in plotted['outputs'] if m['role']=='figure'])==3
                sample_figure_types.append(figure_type)
            checks['quantitative_sample_figure']=True
    return dict(code_digest=runtime['code_digest'],runtime_identity=runtime,checks=checks,sample_figure_types=sample_figure_types)


def validate_parent(root):
    """Run in the ordinary worker interpreter, without renderer imports."""
    from app.adapters.bio_insights_process import validate_result
    root=Path(root);names=['continuous-comparison','bulk_counts-comparison','sample-distribution','sample-heatmap']
    for name in names:
        payload=json.loads((root/(name+'-request.json')).read_bytes())
        result=json.loads((root/(name+'-result.json')).read_bytes())
        validate_result(result,root/name,payload)
    return dict(parent_validation=True,validated_names=names,sample_figure_types=['distribution','heatmap'],
        checks=dict(quantitative_continuous=True,quantitative_counts=True,quantitative_sample_figure=True))


if __name__=='__main__':
    if sys.argv[1]=='--validate-parent':answer=validate_parent(Path(sys.argv[2]).absolute())
    else:answer=exercise(Path(sys.argv[1]).absolute())
    print(json.dumps(answer,sort_keys=True))
