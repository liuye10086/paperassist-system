"""Standalone reference annotation of a saved unadjusted log1p matrix."""
import hashlib
import json
import time
from pathlib import Path

import numpy as np
from scipy import sparse

from app.adapters.bio_engine import ENGINE_VERSION
from app.adapters.bio_engine.manifest import Writer,clean


def run(payload):
    from app.adapters.single_cell_r.bridge import get_bridge
    started=time.monotonic();processed=payload['processed'];members=processed['members']
    if processed['manifest'].get('assay')!='single_cell':raise ValueError('annotation_requires_single_cell')
    for item in members.values():
        path=Path(item['path'])
        if path.is_symlink() or path.stat().st_size!=item['size_bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('annotation_source_hash_mismatch')
    def array(key):return np.load(members[key]['path'],allow_pickle=False)
    axes=json.loads(Path(members['raw_axes']['path']).read_bytes())
    mask=array('observation_mask');features=array('feature_mask')
    if mask.dtype.kind!='b' or features.dtype.kind!='b' or mask.shape!=(len(axes['barcodes']),) or features.shape!=(len(axes['feature_ids']),):
        raise ValueError('annotation_source_axis_invalid')
    cells=[v for v,keep in zip(axes['barcodes'],mask) if keep];genes=[v for v,keep in zip(axes['feature_ids'],features) if keep]
    expression=sparse.csr_matrix((array('log1p_data'),array('log1p_indices'),array('log1p_indptr')),shape=(len(cells),len(genes)))
    config=payload['config'];reference_config={key:config[key] for key in ('reference_id','species','gene_id_type','label_level') if key in config}
    bridge=get_bridge();result=bridge.classify(expression,cells,genes,reference_config,int(config.get('seed',0)))
    bridge.release_temporaries()
    if result['status']!='completed':raise ValueError('single_r_'+str(result.get('reason') or 'failed'))
    if result['cells']!=cells:raise ValueError('annotation_result_axis_invalid')
    writer=Writer(payload['output_directory'],max_output_bytes=1024**3);writer.identity=payload.get('identity',{})
    rows=[dict(barcode=cell,candidate_label=result['candidate_labels'][i],pruned_label=result['pruned_labels'][i],status=result['label_status'][i],
        delta_next=float(result['delta_next'][i]),delta_median=float(result['delta_median'][i]),
        ranked_candidates=';'.join(result['candidate_ranks'][i])) for i,cell in enumerate(cells)]
    writer.table('annotation_candidates',rows)
    score_labels=result['score_labels']
    writer.table('annotation_scores',[{'barcode':cell,**{label:float(result['scores'][i,j]) for j,label in enumerate(score_labels)}} for i,cell in enumerate(cells)],['barcode',*score_labels])
    writer.json('annotation_reference',dict(reference=result['reference'],matching=result['matching']))
    writer.add('annotation_tool_logs',('\n'.join(result.get('logs',[]))+'\n').encode(),'txt')
    writer.json('annotation_parameters',{**config,'input_layer':'log1p','expression_adjusted':False,'tool_versions':bridge.versions})
    reference={k:v for k,v in result['reference'].items() if k!='gene_ids'}
    matching={k:v for k,v in result['matching'].items() if k!='common_gene_ids'}
    summary=dict(cells=len(cells),labels=len(score_labels),score_labels=score_labels,
        pruned_cells=sum(v=='unknown' for v in result['pruned_labels']),candidate_only=True,biological_validation=False,
        input_layer='log1p',score_semantics=result.get('score_semantics','reference_similarity_not_probability'))
    steps=[dict(key='singler',status='completed',reason=None,params=config)]
    try:
        import resource
        peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except ImportError:peak=None
    resources=dict(wall_seconds=time.monotonic()-started,peak_rss_kib=peak,peak_rss_includes_warmup=True,max_rss_bytes=4*1024**3,max_address_space_bytes=5*1024**3,max_output_bytes=1024**3,max_member_bytes=256*1024**2)
    manifest=dict(schema_version=1,engine_version=ENGINE_VERSION,algorithm='SingleR',tool_version=bridge.versions['SingleR'],
        identity=payload.get('identity',{}),reference=reference,matching=matching,summary=summary,steps=steps,params=config,resources=resources,
        tables=[dict(key=key,label=key,status='completed',reason=None) for key in ('annotation_candidates','annotation_scores')],
        members=[{k:v for k,v in m.items() if k!='path'} for m in writer.artifacts])
    writer.json('manifest',manifest)
    return clean(dict(status='completed',engine_version=ENGINE_VERSION,manifest=manifest,summary=summary,steps=steps,outputs=writer.artifacts,
        checks=dict(source_hashes='verified',annotation_axis='verified'),effective_params=config))
