"""A cell-specific attestation extends the unchanged numerical runtime gate."""
import os
import json
from pathlib import Path
from .analysis_settings import runtime_identity as base_identity


def runtime_identity():
    base=base_identity()
    if not base['available']:return base
    from app.core.config import local_config
    path=os.environ.get('PAPERASSIST_SINGLE_CELL_RUNTIME_MANIFEST') or local_config().get('PAPERASSIST_SINGLE_CELL_RUNTIME_MANIFEST')
    blocked={**base,'available':False,'blockers':['bio_environment_unavailable'],'status':'single_cell_probe_not_verified'}
    if not path:return blocked
    try:
        p=Path(path)
        if p.is_symlink() or not p.is_file() or p.stat().st_size>65536:return blocked
        value=json.loads(p.read_bytes())
        if (set(value)!={'schema_version','gate_status','engine_version','environment_digest','code_digest','checks'} or value['schema_version']!=1 or value['gate_status']!='passed' or any(value[k]!=base[k] for k in ('engine_version','environment_digest','code_digest')) or value['checks']!={'h5ad_axes':True,'counts_equivalence':True,'cell_aggregation':True,'nonspatial_dispatch':True} or any(type(v) is not bool for v in value['checks'].values())):return blocked
        return {**base,'single_cell_checks':value['checks']}
    except (OSError,ValueError,TypeError,KeyError):return blocked
