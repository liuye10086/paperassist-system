"""Parent validation for the explicit raw V3 and processed V2 contracts."""
import json
import hashlib
from pathlib import Path
import numpy as np
from app.domain.bioinformatics.tabular_contracts import ENGINE_VERSION,PARSER_VERSION
from app.adapters.bio_analysis_process import invalid
from app.adapters.bio_engine.manifest import Writer


class _ReconciliationWriter(Writer):
    """Hash canonical derived bytes without writing a second copy of user data."""
    def __init__(self):
        self.artifacts=[]

    def add(self,key,content,fmt,role=None):
        item=dict(key=key,role=role or key,format=fmt,size_bytes=len(content),sha256=hashlib.sha256(content).hexdigest())
        self.artifacts.append(item)
        return item


def parse_bio_v3(frozen,output_directory,settings):
    from app.domain.bioinformatics.tabular_settings import runtime_identity
    from app.adapters.bio_analysis_process import execute_bio_analysis
    runtime=runtime_identity()
    if not runtime['available'] or any(frozen[k]!=runtime[k] for k in ('engine_version','environment_digest','code_digest')):raise invalid('bio_environment_unavailable')
    return execute_bio_analysis(dict(files=frozen['files'],config=frozen['tabular_config'],identity={k:runtime[k] for k in ('engine_version','environment_digest','code_digest')}),output_directory,mode='import_v3')


def validate_tabular_result(result,directory,payload,mode):
    from app.adapters.bio_analysis_process import validate_artifacts
    from app.adapters.bio_engine.tabular_assays import load_tabular,transformed,import_tabular,_rows,layer_scale
    from app.domain.bioinformatics.tabular_contracts import validate_recipe
    try:
        peak=result.get('resources',{}).get('child_peak_rss_kib')
        if peak is not None and (type(peak) is not int or peak<0 or peak*1024>2*1024**3):raise ValueError('science_rss_limit')
        outputs=validate_artifacts(result['outputs'],directory,formats={'npy','json','tsv','csv','png','svg','tiff','txt','py','lock'})
        members={m['key']:m for m in outputs};manifest=result['manifest']
        def doc(key):return json.loads(Path(members[key]['path']).read_bytes())
        def array(key):return np.load(members[key]['path'],allow_pickle=False)
        def table_matches(key,rows,fields=None):
            writer=_ReconciliationWriter();writer.table(key,rows,fields)
            if any(members[key][k]!=writer.artifacts[0][k] for k in ('sha256','size_bytes')):raise ValueError()
        def finite_axis_table(key,axis,ids,columns):
            rows=_rows(members[key])
            if [r[axis] for r in rows]!=ids or any(set(r)!={axis,*columns} for r in rows):raise ValueError()
            numbers=np.asarray([[float(r[c]) for c in columns] for r in rows])
            if not np.isfinite(numbers).all():raise ValueError()
            return numbers
        if mode=='import_v3':
            if manifest['schema_version']!=3 or result['parser_version']!=PARSER_VERSION or manifest['parser_version']!=PARSER_VERSION:raise ValueError()
            if manifest['members']!=[{k:v for k,v in m.items() if k!='path'} for m in outputs]:raise ValueError()
            config=payload['config'];sources={f['id'] for f in payload['files']}
            if manifest['import_config']!=config or manifest['assay']!=config['assay']:raise ValueError()
            if any(m['source_file_id'] not in sources or m['compression']!='none' or m['verification_state']!='verified' for m in outputs):raise ValueError()
            values,missing,samples,features=load_tabular({'manifest':manifest,'members':members})
            if samples!=config['sample_columns'] or result['n_features']!=values.shape[1] or result['n_observations']!=values.shape[0] or result['entry_count']!=values.size:raise ValueError()
            # One bounded reread of each original table reconciles numerical values,
            # all metadata, row provenance, scale and member/source role bindings.
            expected=import_tabular(payload,_writer=_ReconciliationWriter())
            if manifest!=expected['manifest'] or any(result[k]!=expected[k] for k in ('n_features','n_observations','entry_count','checks')):raise ValueError()
            return result
        if (mode not in ('qc','compute') or result['engine_version']!=ENGINE_VERSION or manifest['engine_version']!=ENGINE_VERSION
            or manifest['schema_version']!=2 or manifest['identity']!=payload['identity'] or manifest['observation_level']!='sample'
            or manifest['summary']!=result['summary'] or manifest['steps']!=result['steps'] or doc('manifest')!=manifest):raise ValueError()
        if manifest['members']!=[{k:v for k,v in m.items() if k!='path'} for m in outputs if m['key']!='manifest']:raise ValueError()
        raw,missing,samples,features=load_tabular(payload['raw']);axes=doc('raw_axes')
        if axes!={'sample_ids':samples,**features}:raise ValueError()
        om=array('observation_mask');fm=array('feature_mask')
        if om.dtype.kind!='b' or fm.dtype.kind!='b' or om.shape!=(len(samples),) or fm.shape!=(len(features['feature_ids']),):raise ValueError()
        params=validate_recipe(payload.get('config',{}),payload['raw']['manifest']).model_dump()
        if manifest['params']!=params or result['effective_params']!=params or manifest['methods']['params']!=params:raise ValueError()
        if om.tolist()!=[s not in params['exclude_samples'] for s in samples] or fm.tolist()!=[f not in params['exclude_features'] for f in features['feature_ids']]:raise ValueError()
        if not om.any() or not fm.any() or not set(params['exclude_samples'])<=set(samples) or not set(params['exclude_features'])<=set(features['feature_ids']):raise ValueError()
        if doc('recipe')!=params or doc('methods')!=manifest['methods']:raise ValueError()
        if manifest['assay']!=payload['raw']['manifest']['assay'] or manifest['scale']!=payload['raw']['manifest']['scale'] or manifest['methods']['input_scale']!=manifest['scale']:raise ValueError()
        for key,mask,reason in (('samples',om,'explicit_sample_exclusion'),('features',fm,'explicit_feature_exclusion')):
            original=_rows(payload['raw']['members'][key])
            if len(original)!=len(mask):raise ValueError()
            expected_rows=[{**row,'kept':str(bool(kept)),'exclusion_reason':'' if kept else reason} for row,kept in zip(original,mask)]
            if _rows(members[key])!=expected_rows:raise ValueError()
        ids=features['feature_ids']
        summary=dict(raw_observations=len(samples),retained_observations=int(om.sum()),excluded_observations=int((~om).sum()),
            raw_features=len(ids),retained_features=int(fm.sum()),excluded_features=int((~fm).sum()),shape=[int(om.sum()),int(fm.sum())],
            observation_level='sample',missing_values=int(missing.sum()))
        steps=[dict(key='qc',status='completed',reason=None),dict(key='filter',status='completed',reason=None)]
        table_matches('sample_qc',[dict(sample_id=s,missing_count=int(missing[i].sum()),zero_count=int(((raw[i]==0)&~missing[i]).sum()),
            measured_features=int((~missing[i]).sum()),library_size=sum(map(int,raw[i])) if manifest['assay']=='bulk_rna_counts' else None,kept=bool(om[i])) for i,s in enumerate(samples)])
        table_matches('feature_qc',[dict(feature_id=f,missing_count=int(missing[:,j].sum()),measured_samples=int((~missing[:,j]).sum()),kept=bool(fm[j])) for j,f in enumerate(ids)])
        if mode=='compute':
            expected,factors=transformed(raw[om][:,fm],missing[om][:,fm],params,payload['raw']['manifest'])
            if set(manifest['layers'])!={'analysis','display'}:raise ValueError()
            for prefix in ('analysis','display'):
                if not np.array_equal(array(prefix+'_missing'),missing[om][:,fm]) or not np.allclose(array(prefix+'_values'),expected,rtol=1e-12,atol=1e-12):raise ValueError()
                if manifest['layers'][prefix]!=dict(values=prefix+'_values',missing=prefix+'_missing',shape=list(expected.shape),**layer_scale(params,payload['raw']['manifest'])):raise ValueError()
            complete=~missing[om][:,fm].any(0)&(np.var(expected,axis=0)>0)
            selection=array('pca_feature_mask')
            if selection.dtype.kind!='b' or not np.array_equal(selection,complete):raise ValueError()
            selected_samples=np.asarray(samples)[om].tolist();selected_features=np.asarray(ids)[fm].tolist()
            table_matches('normalization_factors',[dict(sample_id=s,factor=float(f)) for s,f in zip(selected_samples,factors)])
            has_missing=missing[om][:,fm].any(0)
            table_matches('pca_feature_selection',[dict(feature_id=f,included=bool(complete[j]),reason='' if complete[j] else 'missing_values' if has_missing[j] else 'constant') for j,f in enumerate(selected_features)])
            n=len(selected_samples);status='completed' if n>=3 and complete.sum()>=2 else 'not_computable'
            reason=None if status=='completed' else 'insufficient_complete_nonconstant_features_or_samples'
            steps.extend([dict(key='transform',status='completed',reason=None),dict(key='pca',status=status,reason=reason),dict(key='sample_clustering',status=status,reason=reason)])
            if status=='completed':
                k=min(params['pca_components'],n-1,int(complete.sum()));summary['pca_components']=k
                columns=[f'pc{j+1}' for j in range(k)]
                finite_axis_table('pca_scores','sample_id',selected_samples,columns)
                finite_axis_table('pca_loadings','feature_id',np.asarray(selected_features)[complete].tolist(),columns)
                variance=finite_axis_table('pca_variance_ratio','component',[str(j+1) for j in range(k)],['variance_ratio'])
                if np.any(variance<0) or np.any(variance>1) or variance.sum()>1+1e-10:raise ValueError()
                clustering=_rows(members['sample_clustering'])
                if len(clustering)!=n or {r['sample_id'] for r in clustering}!=set(selected_samples) or [r['order'] for r in clustering]!=[str(i) for i in range(n)]:raise ValueError()
                from scipy.cluster.hierarchy import is_valid_linkage
                linked=array('sample_linkage')
                if linked.shape!=(n-1,4) or not np.isfinite(linked).all() or not is_valid_linkage(linked):raise ValueError()
            else:
                for key,field in [('pca_scores','sample_id'),('pca_loadings','feature_id'),('pca_variance_ratio','component'),('sample_clustering','sample_id')]:table_matches(key,[],[field,'reason'])
        elif manifest['layers']:raise ValueError()
        if result['summary']!=summary or result['steps']!=steps or manifest['methods']['steps']!=steps:raise ValueError()
        return result
    except (KeyError,ValueError,TypeError,OSError,IndexError) as exc:raise invalid() from exc
