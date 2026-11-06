"""Reuse a frozen parent's QC and count axes for explicit cell selection."""
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy import sparse


def inherit_subset(raw,features,cells,parent,selection):
    members=parent['members']
    for item in members.values():
        path=Path(item['path'])
        if path.is_symlink() or path.stat().st_size!=item['size_bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('subset_parent_hash_mismatch')
    def array(key):return np.load(members[key]['path'],allow_pickle=False)
    def document(key):return json.loads(Path(members[key]['path']).read_bytes())
    def table(key):
        return list(csv.DictReader(Path(members[key]['path']).read_text(encoding='utf-8').splitlines(),delimiter='\t')) if key in members else []
    def boolean(value):return value is True or value=='True' or value=='true'
    def number(value):return float(value) if value not in (None,'') else None
    axes=document('raw_axes');parent_mask=array('observation_mask');feature_mask=array('feature_mask')
    if (axes!=dict(barcodes=cells,**features) or parent_mask.dtype.kind!='b' or parent_mask.shape!=(len(cells),)
        or feature_mask.dtype.kind!='b' or feature_mask.shape!=(raw.shape[1],)):
        raise ValueError('subset_parent_axis_invalid')
    selected=selection['resolved_cell_ids'];chosen=set(selected)
    if not selected or len(chosen)!=len(selected) or not chosen<={c for c,keep in zip(cells,parent_mask) if keep}:
        raise ValueError('subset_selection_invalid')
    mask=np.array([c in chosen for c in cells],dtype=bool)
    shape=(int(parent_mask.sum()),int(feature_mask.sum()))
    def matrix(prefix):
        value=sparse.csr_matrix((array(prefix+'_data'),array(prefix+'_indices'),array(prefix+'_indptr')),shape=shape)
        value.check_format(full_check=True)
        return value
    parent_counts=matrix('counts')
    if parent_counts.dtype.kind not in 'iu' or (parent_counts!=raw[parent_mask][:,feature_mask]).nnz:
        raise ValueError('subset_parent_counts_mismatch')
    parent_rows=table('observations')
    if len(parent_rows)!=len(cells) or [r['barcode'] for r in parent_rows]!=cells or any(boolean(r['kept'])!=bool(keep) for r,keep in zip(parent_rows,parent_mask)):
        raise ValueError('subset_parent_observations_invalid')
    inherited={}
    for i,row in enumerate(parent_rows):
        inherited[i]={k:row.get(k) or None for k in ('doublet_status','doublet_prediction','doublet_reason','decontx_status','decontx_reason')}
        inherited[i].update(doublet_score=number(row.get('doublet_score')),decontx_contamination=number(row.get('decontx_contamination')),doublet_excluded=boolean(row.get('doublet_excluded')))
    counts=parent_counts[mask[parent_mask]].tocsr()
    corrected=matrix('decontx_counts')[mask[parent_mask]].tocsr() if 'decontx_counts_data' in members else None
    if corrected is not None and (not np.isfinite(corrected.data).all() or np.any(corrected.data<0) or (corrected-counts.astype('float64')).max()>1e-7):
        raise ValueError('subset_parent_correction_invalid')
    reasons=[(r.get('exclusion_reasons') or '').split(';') if r.get('exclusion_reasons') else [] for r in parent_rows]
    for i in np.flatnonzero(parent_mask&~mask):reasons[i]=['outside_parent_selection']
    library_ids=[r.get('library_id') or None for r in parent_rows]
    libraries=sorted({v for v in library_ids if v is not None})
    mt=[number(r.get('mt_fraction')) for r in parent_rows]
    parent_summary=parent['manifest']['summary']
    qc=dict(raw_counts=np.array([int(r['total_counts']) for r in parent_rows]),raw_detected=np.array([int(r['detected_genes']) for r in parent_rows]),
        raw_zero_fraction=np.array([float(r['zero_fraction']) for r in parent_rows]),
        extreme_counts=np.array([boolean(r['extreme_counts_candidate']) for r in parent_rows]),extreme_genes=np.array([boolean(r['extreme_genes_candidate']) for r in parent_rows]),
        extreme_fences=parent_summary.get('quality_hints',{}).get('fences',{}),
        feature_counts=np.asarray(raw.sum(0)).ravel(),feature_nonzero=np.asarray((raw>0).sum(0)).ravel(),
        obs_mask=mask,feature_mask=feature_mask,reasons=reasons,in_tissue=np.full(len(cells),None),
        mt_fraction=np.array([np.nan if v is None else v for v in mt]) if any(v is not None for v in mt) else None,
        mt_reason=parent_summary.get('mitochondrial_reason','mitochondrial_rule_unconfirmed'),
        library_qc=[dict(library_id=library,raw_cells=sum(v==library for v in library_ids),kept_cells=sum(v==library and bool(mask[i]) for i,v in enumerate(library_ids)),
            excluded_cells=sum(v==library and not bool(mask[i]) for i,v in enumerate(library_ids)),inherited_from_parent=True,
            exclusion_reason_counts={reason:sum(v==library and reason in reasons[i] for i,v in enumerate(library_ids)) for reason in sorted({r for row in reasons for r in row})}) for library in libraries],
        filtered_counts=counts,filtered_total=np.asarray(counts.sum(1)).ravel(),filtered_detected=np.asarray((counts>0).sum(1)).ravel(),
        stages=dict(raw_observations=raw.shape[0],raw_features=raw.shape[1],expression_features=sum(t=='Gene Expression' for t in features['feature_types']),
            spot_threshold_kept=int(parent_mask.sum()),gene_threshold_kept=int(feature_mask.sum()),final_spots=int(mask.sum()),parent_retained_cells=int(parent_mask.sum()),subset_selected_cells=int(mask.sum())))
    source=selection['parent_processed_source']
    algorithm_summary={**parent_summary.get('single_cell_algorithms',{}),'inherited_from_parent':True,'parent_processed_source':source}
    algorithms=dict(summary=algorithm_summary,versions=algorithm_summary.get('versions',{}),
        library_algorithms=[{**r,'execution':'inherited_parent_result','inherited_from_parent':True} for r in table('library_algorithms')],
        logs=['Capture-library QC, scDblFinder and decontX were inherited from parent; no capture model was run.'])
    provenance=dict(parent_processed_source=source,selection={k:selection.get(k,[]) for k in ('cluster_ids','cell_ids')},
        selected_cell_ids=[c for c,keep in zip(cells,mask) if keep],parent_retained_cells=int(parent_mask.sum()),selected_cells=int(mask.sum()),
        retained_features=int(feature_mask.sum()),qc='inherited_parent',capture_models_rerun=False,counts='parent_original_integer_counts',
        feature_filter='inherited_parent',biological_validation=False)
    return dict(qc=qc,algorithms=algorithms,algorithm_rows=inherited,decontx_counts=corrected,provenance=provenance,
        rows=[dict(cell_id=c,raw_index=i,parent_cluster=parent_rows[i].get('cluster'),parent_processed_dataset_version_id=source['processed_dataset_version_id']) for i,c in enumerate(cells) if mask[i]])
