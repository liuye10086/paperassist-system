"""Bounded previews of immutable quantitative leaves; no scientific computation."""
import io,json
import numpy as np
from app.domain.bioinformatics.contracts import conflict


def dense_preview(manifest,members,objects,features_page,observations_page,layer=None):
    leaves={m['key']:m for m in members}
    def document(key):return json.loads(objects.read(leaves[key]))
    def array(key):return np.load(io.BytesIO(objects.read(leaves[key])),allow_pickle=False)
    if manifest['schema_version']==3:
        samples=document('samples_index')['sample_ids'];features=document('features_index');ids=features['feature_ids']
        names=features['display_names'];kinds=features['feature_kinds'];values=array('matrix_values');missing=array('matrix_missing');scale=manifest['scale']
    else:
        layer='analysis' if layer in (None,'log1p') else layer
        value_layers=manifest.get('value_layers') or {}
        if layer in value_layers:
            layer_spec=value_layers[layer]
            axes=document('raw_axes')
            if layer_spec.get('axis')=='raw':
                samples=list(axes['sample_ids']);ids=list(axes['feature_ids'])
                names=list(axes['display_names']);kinds=list(axes['feature_kinds'])
            else:
                filtered=document('filtered_axes')
                samples=list(filtered['sample_ids']);ids=list(filtered['feature_ids'])
                names=list(filtered['display_names']);kinds=list(filtered['feature_kinds'])
            values=array(layer_spec['values']);missing=array(layer_spec['missing']);scale=layer_spec.get('semantic',layer)
        else:
            if layer not in ('analysis','display') or layer not in manifest['layers']:raise conflict('bio_recipe_invalid')
            axes=document('raw_axes');om=array('observation_mask');fm=array('feature_mask')
            samples=[s for s,yes in zip(axes['sample_ids'],om) if yes];ids=[f for f,yes in zip(axes['feature_ids'],fm) if yes]
            names=[f for f,yes in zip(axes['display_names'],fm) if yes];kinds=[f for f,yes in zip(axes['feature_kinds'],fm) if yes]
            values=array(layer+'_values');missing=array(layer+'_missing');scale=manifest['layers'][layer]
    if values.shape!=(len(samples),len(ids)) or missing.shape!=values.shape or missing.dtype.kind!='b':raise conflict('bio_output_invalid')
    f0,o0=(features_page-1)*40,(observations_page-1)*20;f1=min(f0+40,len(ids));o1=min(o0+20,len(samples))
    selected=[[None if missing[o,f] else values[o,f].item() for f in range(f0,f1)] for o in range(o0,o1)]
    return dict(features=[dict(id=ids[f],symbol=names[f],feature_type=kinds[f]) for f in range(f0,f1)],observations=samples[o0:o1],values=selected,
        features_total=len(ids),observations_total=len(samples),features_page=features_page,observations_page=observations_page,observation_level='sample',scale=scale,layer=layer or 'raw')
