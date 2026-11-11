"""Verified dense sample axes and declared processed layers; never spot aliases."""
import numpy as np
from .inputs import verify_member,document,read_array
from app.adapters.bio_engine.tabular_assays import SHARED_LAYER_LAYOUT, filtered_matrix, layer_layout, load_tabular,_rows,transformed
from app.domain.bioinformatics.tabular_contracts import validate_recipe


def load_quantitative(source,config):
    sid=source['source_id'];members=source['members'];meta=source['metadata']
    for member in members.values():verify_member(member)
    raw,missing,samples,features=load_tabular(source['raw'])
    manifest=document(members['manifest'])
    if manifest['schema_version']!=2 or manifest['observation_level']!='sample':raise ValueError('quantitative_processed_required')
    if document(members['raw_axes'])!={'sample_ids':samples,**features}:raise ValueError('quantitative_raw_axes_mismatch')
    om=read_array(members['observation_mask']);fm=read_array(members['feature_mask'])
    if om.dtype.kind!='b' or fm.dtype.kind!='b' or om.shape!=(len(samples),) or fm.shape!=(len(features['feature_ids']),):raise ValueError('quantitative_mask_invalid')
    observations=[{**r,'processed_version_id':sid,'retained':bool(om[i])} for i,r in enumerate(_rows(members['samples']))]
    if [r['sample_id'] for r in observations]!=samples or observations!=meta['observations']:raise ValueError('sample_metadata_mismatch')
    annotations=_rows(members['features'])
    if [r['feature_id'] for r in annotations]!=features['feature_ids']:raise ValueError('feature_metadata_mismatch')
    if config.mode=='bulk_counts':
        if source['raw']['manifest']['assay']!='bulk_rna_counts' or raw.dtype!=np.dtype('int64') or missing.any() or np.any(raw<0):raise ValueError('raw_integer_counts_required')
        eligible=fm if config.bulk_model else np.ones(raw.shape[1],dtype=bool)
        values=filtered_matrix(raw,om,eligible);mask=filtered_matrix(missing,om,eligible)
        descriptor=dict(input_scale=source['raw']['manifest']['scale'],scale='raw_counts',unit='counts',normalization='none',transform='none',is_raw_integer_counts=True)
    else:
        prefix=config.analysis_layer;eligible=fm
        raw_manifest=source['raw']['manifest']
        params=validate_recipe(manifest['params'],raw_manifest)
        filtered_missing=filtered_matrix(missing,om,fm)
        shared=manifest.get('layer_layout')==SHARED_LAYER_LAYOUT
        if (manifest.get('layer_layout') is not None and not shared) or (shared and raw_manifest['assay']!='bulk_rna_counts'):
            raise ValueError('layer_scale_mismatch')
        layers,_=layer_layout(params,raw_manifest,raw.shape,filtered_missing.shape,shared=shared)
        descriptor=manifest['layers'][prefix]
        if descriptor!=layers[prefix]:raise ValueError('layer_scale_mismatch')
        values=read_array(members[descriptor['values']]);mask=read_array(members[descriptor['missing']])
        expected,_=transformed(filtered_matrix(raw,om,fm),filtered_missing,params,raw_manifest)
        if values.shape!=expected.shape or mask.dtype.kind!='b' or not np.array_equal(mask,filtered_missing) or not np.allclose(values,expected,rtol=1e-12,atol=1e-12):raise ValueError('processed_layer_mismatch')
        if meta['layers'][prefix]!=descriptor:raise ValueError('frozen_layer_metadata_mismatch')
    return dict(source=source,values=values,missing=mask,observations=observations,
        retained_keys=[(sid,s) for s,yes in zip(samples,om) if yes],feature_ids=[f for f,keep in zip(features['feature_ids'],eligible) if keep],
        raw_feature_ids=features['feature_ids'],annotations={r['feature_id']:r for r in annotations},layer=descriptor)
