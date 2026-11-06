"""Explain stored CSR and the bounded float32 HVG block, without peak promises."""
from .analysis_settings import BioAnalysisLimits
from pydantic import Field


class SingleCellRAnalysisLimits(BioAnalysisLimits):
    memory_bytes: int = Field(default=4*1024**3,ge=1,le=4*1024**3)
    max_output_bytes: int = Field(default=1024**3,ge=1,le=1024**3)


def analysis_limits_for(*,single_cell=False,params=None):
    params=params or {}
    requested=single_cell and any(isinstance(params.get(tool),dict) and params[tool].get('enabled') is True for tool in ('doublet','decontx','harmony'))
    return SingleCellRAnalysisLimits() if requested else BioAnalysisLimits()


def memory_bounds(limits=None,*,single_cell=False,params=None):
    limits=limits or analysis_limits_for(single_cell=single_cell,params=params)
    return dict(rss_limit_bytes=limits.memory_bytes,address_space_limit_bytes=(5 if isinstance(limits,SingleCellRAnalysisLimits) else 3)*1024**3)


def resource_estimate(manifest, params=None, limits=None):
    params=params or {}
    limits=limits or analysis_limits_for(single_cell=True,params=params)
    shape=manifest.get('input_shape',{})
    cells=shape.get('observations');features=shape.get('features');nnz=manifest.get('stored_entries')
    valid=all(type(value) is int and value>=0 for value in (cells,features,nnz)) and cells>0 and features>0
    blockers=[]
    if not valid:
        blockers.append('single_cell_matrix_dimensions_unknown')
    else:
        for value,maximum,code in ((cells,limits.max_observations,'observations'),(features,limits.max_features,'features'),(nnz,limits.max_entries,'nnz')):
            if value>maximum:blockers.append('single_cell_'+code+'_limit')
    hvg=min(params.get('hvg_count',2000),features) if valid else None
    dense_values=cells*hvg if valid else None
    if dense_values is not None and dense_values>limits.max_dense_values:blockers.append('single_cell_dense_hvg_limit')
    return dict(matrix=dict(observations=cells,features=features,nnz=nnz),
        sparse_bytes=nnz*12+(cells+1)*8 if valid else None,
        dense_hvg_values=dense_values,dense_hvg_bytes=dense_values*4 if valid else None,
        hvg_count=hvg,requested_hvg_count=params.get('hvg_count',2000),configured_limits=limits.model_dump(),optional_r_limits=SingleCellRAnalysisLimits().model_dump(),
        blockers=blockers,estimate_only=True,peak_memory_bytes=None,
        basis=dict(sparse='raw CSR int64 data + int32 indices + int64 indptr',dense_hvg='raw observations × min(requested HVG, raw features) × float32; upper bound before QC/variance selection',
            excludes='normalization copies, scale/PCA workspaces, neighbors, plots, H5AD, interpreter, embedded R models and floating correction copies; not a process peak estimate'))
