import copy
import json
import numpy as np
from app.adapters.bio_engine import plots
from app.adapters.bio_engine.manifest import Writer


def test_saved_markers_paginate_without_recomputing_or_changing_values(tmp_path):
    ids=[f'ENSG000000000{i:03d}' for i in range(43)]
    data=dict(feature_ids=ids,clusters=['0','1'],mean_log1p=np.arange(86).reshape(2,43).tolist(),detection_fraction=np.full((2,43),.5).tolist())
    original=copy.deepcopy(data)
    plots.marker_figures_from_saved(Writer(tmp_path),data,dict(kind='marker_dotplot',dpi=72,vmin=None,vmax=None),{ids[0]:'CD3D',ids[1]:'DUP',ids[2]:'DUP'})
    assert data==original
    pages=sorted(tmp_path.glob('marker_dotplot*_data.json'))
    assert len(pages)==3
    saved=[json.loads(p.read_text()) for p in pages]
    assert all(d['feature_ids']==ids and d['mean_log1p']==data['mean_log1p'] for d in saved)
    assert sorted(i for d in saved for i in d['display_feature_indices'])==list(range(43))
    assert all(len(d['display_feature_indices'])<=20 for d in saved)
    assert all(d['effective_color_limits']==[0.,85.] for d in saved)
    assert saved[0]['feature_labels'][0]=='CD3D'
    assert saved[0]['feature_labels'][1]==ids[1]
    assert saved[0]['feature_labels'][2]==ids[2]
    assert all(p.suffix!='.pdf' for p in tmp_path.iterdir())
