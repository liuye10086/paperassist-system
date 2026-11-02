"""Independent acceptance assertions anchored to retained, authorized input bytes."""
import csv
import hashlib
import json
import math


def locked_files(root,index_name,expected_sha):
    raw=(root/index_name).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==expected_sha,'Material index SHA differs'
    entries=json.loads(raw)
    if isinstance(entries,dict):entries=entries['sources']
    names=set()
    for entry in entries:
        path=(root/entry['path']).resolve()
        assert path.is_relative_to(root.resolve()),'Material path outside retained root'
        data=path.read_bytes()
        assert len(data)==entry['bytes'] and hashlib.sha256(data).hexdigest()==entry['sha256'],'Material bytes/SHA differ: '+entry['path']
        assert entry['path'] not in names,'Duplicate material path'
        names.add(entry['path'])
    return names


def lock_materials(root):
    names=locked_files(root,'retained-files.sha256.json','1803903819c928ed7ad2b531fb03b80665b74666eea82c283d778781ec4bab99')
    locked_files(root,'acquisition-manifest.json','c42b0e0b10d8b4e16419a640c5a3edb38f096b3d36e56d2eb9c4e63c4a5f830a')
    return names


def exact_table_set(entries,expected):
    ids=[e['source']['source_id'] for e in entries]
    assert expected and len(ids)==len(set(ids)) and set(ids)==set(expected),'Complete table source set differs'
    assert all(e['sha256']==expected[e['source']['source_id']]['sha256'] for e in entries),'Table SHA differs'


def result_axes(rows,expected,conditions,scope,paired):
    ids=[r['feature_id'] for r in rows]
    assert len(ids)==len(set(ids)) and set(ids)==set(expected),'Complete feature axis differs'
    for row in rows:
        a,b=expected[row['feature_id']]
        assert (row['contrast_id'],row['numerator'],row['denominator'],row['observation_level'],row['inference_scope'])==('primary',*conditions,'sample',scope),'Contrast/direction/scope differs'
        assert (int(row['n_numerator']),int(row['n_denominator']))==(a,b),'Actual feature n differs'
        assert json.loads(row['group_sizes'])==dict(zip(conditions,(a,b))),'Group n differs'
        assert (int(row['n_pairs'])==a) if paired else row['n_pairs'] in ('','NA'),'Actual complete pair count differs'


def read_table(path):
    with path.open(encoding='utf-8-sig',newline='') as handle:return list(csv.DictReader(handle,delimiter='\t'))


def verify_bh(rows,eligible):
    selected=[r for r in rows if r['feature_id'] in eligible]
    values=[1. if r['p_value'] in ('','NA') else float(r['p_value']) for r in selected]
    order=sorted(range(len(selected)),key=lambda i:values[i]);adjusted=[0.]*len(selected);last=1.
    for position in range(len(selected)-1,-1,-1):
        i=order[position];last=min(last,values[i]*len(selected)/(position+1));adjusted[i]=last
    expected={r['feature_id']:q for r,q in zip(selected,adjusted)}
    for row in rows:
        assert row['tested']==str(row['feature_id'] in eligible),'Tested universe differs from input threshold'
        for name in ('q_within_contrast','q_global_family'):
            if row['feature_id'] not in eligible or row['p_value'] in ('','NA'):assert row[name] in ('','NA')
            else:assert math.isclose(float(row[name]),expected[row['feature_id']],rel_tol=1e-12,abs_tol=1e-15),'Complete BH family differs'


def verify_comparison(profile,folder,config,result):
    original=read_table(profile['paths']['quantitative_matrix']);paired=config['design']=='paired';counts=config['mode']=='bulk_counts'
    groups=config['contrasts'][0]['groups'];conditions=[g['label'] for g in groups]
    samples={s['sample_id']:s for s in profile['samples']}
    keys=[[s['sample_id'] for s in g['sample_keys']] for g in groups]
    expected={}
    for row in original:
        observed=[[s for s in group if row[s]!='NA'] for group in keys]
        if paired:
            pairs=set(samples[s]['pair_id'] for s in observed[0])&set(samples[s]['pair_id'] for s in observed[1])
            ns=(len(pairs),len(pairs))
        else:ns=tuple(map(len,observed))
        expected[row['feature_id']]=ns
    scope='sample_inference' if counts else 'sample_exploratory'
    assert result['inference_scope']==scope
    rows=read_table(folder/'comparison_results.tsv');result_axes(rows,expected,conditions,scope,paired)
    methods=json.loads((folder/'comparison_methods.json').read_text(encoding='utf-8'))
    assert all(methods['config'][k]==v for k,v in config.items()),'Frozen comparison config differs'
    assert methods['name']==('PyDESeq2_0.5.4_Wald' if counts else config['method'])
    assert methods['analysis_layer']==config['analysis_layer'] and methods['inference_unit']==config['inference_unit']
    units=json.loads((folder/'comparison_design.json').read_text(encoding='utf-8'))['actual_units']
    assert len(units)==1 and units==result['summary']['actual_units']
    unit=units[0];biological=0 if config['inference_unit']=='technical' else len({samples[s].get('biological_unit_id') or samples[s].get('donor') for group in keys for s in group})
    assert unit['group_sizes']==dict(zip(conditions,map(len,keys))) and unit['biological_n']==biological
    assert unit['complete_pairs']==(len(keys[0]) if paired else 0)
    if counts:
        assert (unit['design_rank'],unit['residual_degrees_freedom'])==(5,3)
        diagnostics=json.loads((folder/'model_diagnostics.json').read_text(encoding='utf-8'));assert len(diagnostics)==1
        diagnostic=diagnostics[0]
        assert diagnostic['formula']=='~ donor + condition' and diagnostic['rank']==5 and diagnostic['residual_degrees_freedom']==3
        parameters=dict(size_factors_fit_type='ratio',fit_type='parametric',refit_cooks=False,cooks_filter=True,independent_filter=True,alpha=.05,lfc_shrinkage=False,n_cpus=1,minimum_total_counts=10)
        assert all(diagnostic['parameters'][k]==v for k,v in parameters.items()),'Model parameters differ'
        metadata=read_table(folder/'model_sample_metadata.tsv');ids={m['unit_id']:m['sample_id'] for m in metadata}
        assert len(ids)==len(metadata)==8 and set(ids.values())==set(keys[0]+keys[1])
        source={r['feature_id']:r for r in original};models=read_table(folder/'model_counts.tsv')
        assert len(models)==len(expected) and {r['feature_id'] for r in models}==set(expected)
        for row in models:
            assert row['contrast_id']=='primary'
            assert all(int(row[k])==int(source[row['feature_id']][v]) for k,v in ids.items()),'Model counts differ from original integers'
        for row in rows:
            low=sum(int(source[row['feature_id']][s]) for group in keys for s in group)<10
            if low:assert row['test_status']=='excluded' and row['reason']=='minimum_total_counts' and row['p_value'] in ('','NA')
    else:
        assert methods['layer']['normalization']==profile['params']['normalization'] and methods['layer']['transform']=='none'
    # The predeclared input threshold fixes the tested universe independently;
    # excluded low counts stay outside, while tested NA contributes one internally.
    eligible={r['feature_id'] for r in original if not counts or sum(int(r[s]) for group in keys for s in group)>=10}
    verify_bh(rows,eligible)
    return dict(complete_feature_ids=True,rows=len(rows),actual_feature_n=True,actual_units=unit,frozen_parameters=True,full_model_raw_counts=counts,independent_BH=True)


def verify_plot(folder,comparison_folder,processed_folder,config,source):
    data=json.loads((folder/'plot_data.json').read_text(encoding='utf-8'))
    metadata=json.loads((folder/'figure_metadata.json').read_text(encoding='utf-8'))
    assert all(metadata['config'][k]==v for k,v in config.items()),'Figure config differs'
    assert metadata['analysis_recomputed'] is False
    results=read_table(comparison_folder/'comparison_results.tsv')
    number=lambda x:None if x in ('','NA') else float(x)
    if config['figure_type']=='volcano':
        original={r['feature_id']:r for r in results};actual=data['rows']
        assert len(actual)==len(original) and {r['feature_id'] for r in actual}==set(original)
        for row in actual:
            src=original[row['feature_id']];q=number(src['q_within_contrast']);effect=number(src['effect_value'])
            assert row['row_key']==src['row_key'] and row['q_value']==q and row['effect_value']==effect
            assert row['displayed']==(q is not None and effect is not None)
            display=row['display_neg_log10_q']
            if q is None:
                assert display is None
                continue
            assert 0<=q<=1 and type(display) in (int,float) and math.isfinite(display)
            expected=-math.log10(max(q,1e-300))
            # Formal values use Linux libm; the Windows audit can differ by one
            # last bit. Only this derived coordinate allows two ULPs. Raw q,
            # effect, NA, zero and the explicit display floor remain exact.
            if q==1 or q<=1e-300:
                assert display==expected
            else:
                assert abs(display-expected)<=2*math.ulp(expected)
        return dict(all_result_points=True,rows=len(actual),q_floor_only_for_display=True,display_log10_max_ulps=2)
    import numpy as np
    axes=json.loads((processed_folder/'raw_axes.json').read_text(encoding='utf-8'))
    values=np.load(processed_folder/(config['analysis_layer']+'_values.npy'),allow_pickle=False)
    missing=np.load(processed_folder/(config['analysis_layer']+'_missing.npy'),allow_pickle=False)
    fi={f:i for i,f in enumerate(axes['feature_ids'])};si={s:i for i,s in enumerate(axes['sample_ids'])}
    features=config.get('feature_ids') or [r['feature_id'] for r in sorted(results,key=lambda r:(number(r['q_within_contrast']) is None,number(r['q_within_contrast']) or 0,r['feature_id']))[:config['top_n']]]
    assert data['feature_ids']==features and data['z_score'] is False
    assert data['source_id']==source['source_id'] and data['source_sha256']==source['sha256']
    expected={};group_counts=[]
    for group in config['sample_groups']:
        for f in features:
            measured=0
            for key in group['sample_keys']:
                i,j=si[key['sample_id']],fi[f];absent=bool(missing[i,j]);measured+=not absent
                expected[(key['processed_version_id'],key['sample_id'],f)]=(group['label'],absent,None if absent else float(values[i,j]))
            group_counts.append(dict(group=group['label'],feature_id=f,total_n=len(group['sample_keys']),measured_n=measured,missing_n=len(group['sample_keys'])-measured))
    assert data['groups']==group_counts
    assert len(data['rows'])==len(expected)
    for row in data['rows']:
        key=(row['processed_version_id'],row['sample_id'],row['feature_id'])
        assert expected.pop(key)==(row['group'],row['missing'],row['value']),'Individual sample plot value differs'
    assert not expected
    return dict(individual_samples=True,plot_cells=len(data['rows']),missing_and_actual_n=True,aggregation=False,implicit_transform=False)
