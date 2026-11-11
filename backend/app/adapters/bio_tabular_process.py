"""Parent validation for the explicit raw V3 and processed V2 contracts."""
import json
import hashlib
from contextlib import contextmanager
from pathlib import Path
from zipfile import BadZipFile
import numpy as np
from app.domain.bioinformatics.tabular_contracts import ENGINE_VERSION,PARSER_VERSION,validate_recipe
from app.adapters.bio_analysis_process import invalid
from app.adapters.bio_engine.tabular_writer import ArtifactSink, TabularWriter, validate_matrix_json


class _ReconciliationWriter(TabularWriter):
    """Hash canonical derived bytes without writing a second copy of user data."""
    def __init__(self):
        self.artifacts=[]

    @contextmanager
    def _sink(self,key,fmt,role):
        sink = ArtifactSink(None, 256 * 1024**2)
        yield sink
        self.artifacts.append(sink.record(key, fmt, role))

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


def _verify_shared_layers(array, raw, om, fm, layers, value_layers, params):
    """Compare one mapped layer at a time with bounded rows from the raw counts."""
    retained = np.flatnonzero(om)
    width = int(fm.sum())
    shape = (len(retained), width)
    totals = np.array([raw[i, fm].astype(np.float64).sum() for i in retained])
    if (totals <= 0).any():
        raise ValueError('empty_count_library')
    library = totals / np.median(totals)
    factors = np.ones(len(retained))
    if params.normalization in ('display_library_size', 'vst'):
        factors = library
    elif params.normalization == 'median':
        medians = np.empty(len(retained))
        for j, i in enumerate(retained):
            values = raw[i, fm]
            if (values <= 0).any():
                raise ValueError('median_requires_positive_values')
            medians[j] = np.median(values.astype(np.float64))
        factors = medians / np.median(medians)

    for name, expected_shape in {value_layers['raw']['missing']: raw.shape,
                                 value_layers['filtered']['missing']: shape}.items():
        mask = array(name)
        if mask.dtype.kind != 'b' or mask.shape != expected_shape or mask.any():
            raise ValueError('tabular_layer_mask_mismatch')
        del mask
    mapped_raw = array(value_layers['raw']['values'])
    if mapped_raw.shape != raw.shape or mapped_raw.dtype != raw.dtype:
        raise ValueError('tabular_layer_axis_mismatch')
    for observed, expected in zip(mapped_raw, raw, strict=True):
        if not np.array_equal(observed, expected):
            raise ValueError('tabular_raw_layer_mismatch')
    del mapped_raw

    keys = {name: value_layers[name]['values'] for name in ('filtered', 'normalized', 'vst')
            if value_layers[name]['values'] != value_layers['raw']['values']}
    if layers['analysis']['values'] == 'analysis_values':
        keys['analysis'] = 'analysis_values'
    for name, key in keys.items():
        mapped = array(key)
        dtype = np.dtype('int64') if name == 'filtered' else np.dtype('float64')
        if mapped.shape != shape or mapped.dtype != dtype:
            raise ValueError('tabular_layer_axis_mismatch')
        for j, i in enumerate(retained):
            expected = raw[i, fm]
            if name in ('normalized', 'vst'):
                expected = expected.astype(np.float64) / library[j]
                if name == 'vst':
                    expected = 2 * np.sqrt(expected + 3/8)
            elif name == 'analysis':
                expected = expected.astype(np.float64) / factors[j]
                if params.transform == 'log1p':
                    expected = np.log1p(expected)
                elif params.transform != 'none':
                    if (expected <= 0).any():
                        raise ValueError('log_requires_positive_values')
                    expected = {'log2': np.log2, 'ln': np.log, 'log10': np.log10}[params.transform](expected)
            matches = (np.array_equal(mapped[j], expected) if name == 'filtered'
                       else np.allclose(mapped[j], expected, rtol=1e-12, atol=1e-12))
            if not matches:
                raise ValueError('tabular_layer_value_mismatch')
        del mapped
    analysis = array(layers['analysis']['values'])
    complete = np.empty(width, dtype=bool)
    block_width = max(1, 1024**2 // (max(1, shape[0]) * analysis.itemsize))
    for start in range(0, width, block_width):
        block = slice(start, start + block_width)
        complete[block] = np.var(analysis[:, block], axis=0) > 0
    return factors, np.ones(width, dtype=bool), complete


def validate_tabular_result(result,directory,payload,mode):
    from app.adapters.bio_analysis_process import validate_artifacts
    from app.adapters.bio_engine.tabular_assays import (
        SHARED_LAYER_LAYOUT, _OBJECT_FORMATS, _iter_rows, _rows, filtered_matrix, import_tabular,
        inclusion_rows, layer_layout, load_tabular, transformed, verify_analysis_object,
    )
    from app.adapters.bio_engine.tabular_transport import take_import_manifest
    try:
        peak=result.get('resources',{}).get('child_peak_rss_kib')
        if peak is not None and (type(peak) is not int or peak<0 or peak*1024>2*1024**3):raise ValueError('science_rss_limit')
        if mode == 'import_v3' and 'transport_manifest' in result:
            if 'manifest' in result:raise ValueError('ambiguous_import_manifest')
            result = result.copy()
            result['manifest'] = take_import_manifest(result.pop('transport_manifest'), directory)
        outputs=validate_artifacts(result['outputs'],directory,formats={'npy','npz','json','tsv','csv','png','svg','tiff','txt','py','lock'},
                                   json_validators={'sample_clustering_data':validate_matrix_json})
        members={m['key']:m for m in outputs}
        def doc(key):return json.loads(Path(members[key]['path']).read_bytes())
        def array(key):return np.load(members[key]['path'],allow_pickle=False,mmap_mode='r')
        def table_matches(key,rows,fields=None):
            writer=_ReconciliationWriter();writer.table(key,rows,fields)
            if any(members[key][k]!=writer.artifacts[0][k] for k in ('sha256','size_bytes')):raise ValueError()
        def finite_axis_table(key,axis,ids,columns,*,collect=False):
            expected_columns = {axis,*columns}
            values = []
            for row, identifier in zip(_iter_rows(members[key]),ids,strict=True):
                if set(row)!=expected_columns or row[axis]!=identifier:raise ValueError()
                numbers = np.asarray([float(row[column]) for column in columns])
                if not np.isfinite(numbers).all():raise ValueError()
                if collect:
                    values.append(numbers)
            return np.asarray(values)
        if mode=='import_v3':
            manifest = result['manifest']
            if manifest['schema_version']!=3 or result['parser_version']!=PARSER_VERSION or manifest['parser_version']!=PARSER_VERSION:raise ValueError()
            if manifest['members']!=[{k:v for k,v in m.items() if k!='path'} for m in outputs]:raise ValueError()
            config=payload['config'];sources={f['id'] for f in payload['files']}
            if manifest['import_config']!=config or manifest['assay']!=config['assay']:raise ValueError()
            if any(m['source_file_id'] not in sources or m['compression']!='none' or m['verification_state']!='verified' for m in outputs):raise ValueError()
            values,missing,samples,features=load_tabular({'manifest':manifest,'members':members})
            if samples!=config['sample_columns'] or result['n_features']!=values.shape[1] or result['n_observations']!=values.shape[0] or result['entry_count']!=values.size:raise ValueError()
            del values,missing
            # One bounded reread of each original table reconciles numerical values,
            # all metadata, row provenance, scale and member/source role bindings.
            expected=import_tabular(payload,_writer=_ReconciliationWriter())
            if manifest!=expected['manifest'] or any(result[k]!=expected[k] for k in ('n_features','n_observations','entry_count','checks')):raise ValueError()
            return result
        published_manifest = doc('manifest')
        if 'manifest_ref' in result:
            if result['manifest_ref'] != 'manifest' or {'manifest','summary','steps','effective_params'} & result.keys():
                raise ValueError('invalid_processed_manifest_reference')
            result = result.copy()
            result.pop('manifest_ref')
            result.update(manifest=published_manifest, summary=published_manifest['summary'],
                          steps=published_manifest['steps'], effective_params=published_manifest['params'])
        manifest = result['manifest']
        if (mode not in ('qc','compute') or result['engine_version']!=ENGINE_VERSION or manifest['engine_version']!=ENGINE_VERSION
            or manifest['schema_version']!=2 or manifest['identity']!=payload['identity'] or manifest['observation_level']!='sample'
            or manifest['summary']!=result['summary'] or manifest['steps']!=result['steps'] or published_manifest!=manifest):raise ValueError()
        if manifest['members']!=[{k:v for k,v in m.items() if k!='path'} for m in outputs if m['key']!='manifest']:raise ValueError()
        raw,missing,samples,features=load_tabular(payload['raw']);axes=doc('raw_axes')
        if axes!={'sample_ids':samples,**features}:raise ValueError()
        om=array('observation_mask');fm=array('feature_mask')
        if om.dtype.kind!='b' or fm.dtype.kind!='b' or om.shape!=(len(samples),) or fm.shape!=(len(features['feature_ids']),):raise ValueError()
        recipe=validate_recipe(payload.get('config',{}),payload['raw']['manifest'])
        params=recipe.model_dump()
        if manifest['params']!=params or result['effective_params']!=params or manifest['methods']['params']!=params:raise ValueError()
        excluded_samples,excluded_features=set(params['exclude_samples']),set(params['exclude_features'])
        if om.tolist()!=[s not in excluded_samples for s in samples] or fm.tolist()!=[f not in excluded_features for f in features['feature_ids']]:raise ValueError()
        if not om.any() or not fm.any() or not excluded_samples<=set(samples) or not excluded_features<=set(features['feature_ids']):raise ValueError()
        if doc('recipe')!=params or doc('methods')!=manifest['methods']:raise ValueError()
        if manifest['assay']!=payload['raw']['manifest']['assay'] or manifest['scale']!=payload['raw']['manifest']['scale'] or manifest['methods']['input_scale']!=manifest['scale']:raise ValueError()
        for key,mask,reason in (('samples',om,'explicit_sample_exclusion'),('features',fm,'explicit_feature_exclusion')):
            expected_rows=inclusion_rows(_iter_rows(payload['raw']['members'][key]),mask,reason)
            for observed, expected in zip(_iter_rows(members[key]),expected_rows,strict=True):
                expected['kept']=str(expected['kept'])
                if observed!=expected:raise ValueError()
        ids=features['feature_ids']
        selected_samples=[s for s,keep in zip(samples,om) if keep]
        selected_features=[f for f,keep in zip(ids,fm) if keep]
        if doc('filtered_axes')!=dict(sample_ids=selected_samples,feature_ids=selected_features,
                display_names=[x for x,keep in zip(features['display_names'],fm) if keep],
                feature_kinds=[x for x,keep in zip(features['feature_kinds'],fm) if keep]):raise ValueError()
        summary=dict(raw_observations=len(samples),retained_observations=int(om.sum()),excluded_observations=int((~om).sum()),
            raw_features=len(ids),retained_features=int(fm.sum()),excluded_features=int((~fm).sum()),shape=[int(om.sum()),int(fm.sum())],
            observation_level='sample',missing_values=int(missing.sum()),
            outlier_advisories=[],filter_rules={'sample':{'manual_exclusion_only':True,'automatic_exclusion':False,'rule':'exclude_samples from immutable recipe'},
                'feature':{'manual_exclusion_only':True,'automatic_exclusion':False,'rule':'exclude_features from immutable recipe'}},manual_exclusion_only=True)
        steps=[dict(key='qc',status='completed',reason=None),dict(key='filter',status='completed',reason=None)]
        sample_rows=_rows(payload['raw']['members']['samples']);sample_metadata={row.get('sample_id',''):row for row in sample_rows};raw_counts=manifest['assay']=='bulk_rna_counts';qc=[]
        for i,s in enumerate(samples):
            valid=~missing[i];measured=raw[i][valid];total=float(np.sum(measured)) if raw_counts else None
            distribution=dict(min=float(np.min(measured)) if len(measured) else None,q1=float(np.quantile(measured,.25)) if len(measured) else None,
                median=float(np.median(measured)) if len(measured) else None,q3=float(np.quantile(measured,.75)) if len(measured) else None,max=float(np.max(measured)) if len(measured) else None)
            metadata=sample_metadata.get(s,{})
            qc.append(dict(sample_id=s,condition=metadata.get('condition',''),batch=metadata.get('batch',''),donor=metadata.get('donor',''),biological_unit_id=metadata.get('biological_unit_id',''),
                missing_count=int(missing[i].sum()),zero_count=int(((raw[i]==0)&~missing[i]).sum()),measured_features=int(valid.sum()),detected_features=int(np.count_nonzero(measured>0)),
                zero_fraction=float(np.count_nonzero(measured==0)/len(measured)) if len(measured) else None,total_counts=total,library_size=total,
                expression_distribution=distribution,kept=bool(om[i]),exclusion_reason='' if om[i] else 'manual_exclusion',outlier_advisory=''))
        if raw_counts and qc:
            totals=np.asarray([row['total_counts'] for row in qc],dtype=float);center=float(np.median(totals));mad=float(np.median(np.abs(totals-center)))
            if mad>0:
                for row in qc:
                    score=abs(row['total_counts']-center)/(1.4826*mad)
                    if score>3:row['outlier_advisory']=f'library_size_robust_z>{score:.2f}'
        summary['outlier_advisories']=[dict(sample_id=row['sample_id'],advisory=row['outlier_advisory'],basis='library_size_robust_z') for row in qc if row['outlier_advisory']]
        if raw_counts and 'sample_qc_table' in manifest['summary']:
            summary['sample_qc_table'] = 'sample_qc'
        else:
            summary['qc_metrics'] = {
                metric: {row['sample_id']: row[metric] for row in qc}
                for metric in ('total_counts', 'detected_features', 'zero_fraction', 'expression_distribution')
            }
        table_matches('sample_qc',qc)
        table_matches('feature_qc',(dict(feature_id=f,missing_count=int(missing[:,j].sum()),measured_samples=int((~missing[:,j]).sum()),detected_samples=int(np.count_nonzero(raw[:,j]>0)),
            zero_fraction=float(np.count_nonzero(raw[:,j]==0)/len(raw[:,j])),kept=bool(fm[j]),exclusion_reason='' if fm[j] else 'manual_exclusion') for j,f in enumerate(ids)))
        layout=manifest.get('layer_layout')
        shared=layout==SHARED_LAYER_LAYOUT
        if layout is not None and (not shared or not raw_counts or mode!='compute'):
            raise ValueError('tabular_layer_layout_invalid')
        if mode=='compute':
            shape=(len(selected_samples),len(selected_features))
            layers,value_layers=layer_layout(recipe,payload['raw']['manifest'],raw.shape,shape,shared=shared)
            if manifest['layers']!=layers or manifest['value_layers']!=value_layers:raise ValueError()
            if shared:
                factors,no_missing,complete=_verify_shared_layers(array,raw,om,fm,layers,value_layers,recipe)
            else:
                filtered_missing=filtered_matrix(missing,om,fm)
                expected,factors=transformed(filtered_matrix(raw,om,fm),filtered_missing,recipe,payload['raw']['manifest'])
                for layer in layers.values():
                    observed=array(layer['values'])
                    if observed.shape!=expected.shape or not np.array_equal(array(layer['missing']),filtered_missing) or not np.allclose(observed,expected,rtol=1e-12,atol=1e-12):raise ValueError()
                for layer in value_layers.values():
                    if array(layer['values']).shape!=tuple(layer['shape']) or array(layer['missing']).shape!=tuple(layer['shape']):raise ValueError()
                no_missing=~filtered_missing.any(0)
                complete=no_missing&(np.var(expected,axis=0)>0)
                del expected,filtered_missing
            portable = {key: members[layer['values']]['path'] for key,layer in value_layers.items() if key != 'raw'}
            portable['raw'] = portable['filtered']
            object_format = verify_analysis_object(
                members['analysis_object']['path'], members['analysis_object_manifest']['path'],
                identity=manifest['identity'], params=params, sample_ids=selected_samples,
                feature_ids=selected_features, layers=portable,
            )
            if shared!=(object_format==_OBJECT_FORMATS[3]):raise ValueError()
            summary['layers']={'raw':'raw_counts' if raw_counts else manifest['scale']['kind'],
                'filtered':'filtered_counts' if raw_counts else 'filtered_input','normalized':'normalized_counts' if raw_counts else 'normalized_input',
                'analysis':manifest['layers']['analysis']['scale'],'display':manifest['layers']['display']['scale']}
            if raw_counts:summary['layers']['vst']='variance_stabilized_expression'
            summary['analysis_object']={'format':object_format,'round_trip':'verified_by_loader'}
            selection=array('pca_feature_mask')
            if selection.dtype.kind!='b' or not np.array_equal(selection,complete):raise ValueError()
            table_matches('normalization_factors',(dict(sample_id=s,factor=float(f)) for s,f in zip(selected_samples,factors)))
            table_matches('pca_feature_selection',(dict(feature_id=f,included=bool(complete[j]),reason='' if complete[j] else 'constant' if no_missing[j] else 'missing_values') for j,f in enumerate(selected_features)))
            n=len(selected_samples);status='completed' if n>=3 and complete.sum()>=2 else 'not_computable'
            reason=None if status=='completed' else 'insufficient_complete_nonconstant_features_or_samples'
            steps.extend([dict(key='transform',status='completed',reason=None),dict(key='pca',status=status,reason=reason),dict(key='sample_clustering',status=status,reason=reason)])
            if status=='completed':
                k=min(params['pca_components'],n-1,int(complete.sum()));summary['pca_components']=k
                columns=[f'pc{j+1}' for j in range(k)]
                finite_axis_table('pca_scores','sample_id',selected_samples,columns)
                finite_axis_table('pca_loadings','feature_id',(f for f,keep in zip(selected_features,complete) if keep),columns)
                variance=finite_axis_table('pca_variance_ratio','component',[str(j+1) for j in range(k)],['variance_ratio'],collect=True)
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
    except (KeyError,ValueError,TypeError,OSError,IndexError,BadZipFile) as exc:raise invalid() from exc
