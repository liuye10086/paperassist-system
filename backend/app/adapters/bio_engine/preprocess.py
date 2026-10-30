"""Frozen sparse normalize/log and Seurat-dispersion HVG selection."""
import numpy as np
import scanpy as sc
import anndata as ad


def normalize(counts,target_sum=10000):
    obj = ad.AnnData(counts.astype(np.float32))
    sc.pp.normalize_total(obj, target_sum=target_sum, exclude_highly_expressed=False, inplace=True)
    normalized = obj.X.tocsr().astype(np.float32)
    logged = normalized.copy()
    logged.data = np.log1p(logged.data).astype(np.float32)
    return normalized, logged


def high_variable(logged, ids, n_top=2000):
    obj = ad.AnnData(logged.copy())
    # Ask for all dispersion statistics, then explicitly resolve ties by stable ID.
    sc.pp.highly_variable_genes(obj, flavor='seurat', n_bins=20, n_top_genes=None,
                                min_mean=0, max_mean=np.inf, min_disp=-np.inf, max_disp=np.inf, inplace=True)
    mean = obj.var['means'].to_numpy()
    dispersion = obj.var['dispersions_norm'].to_numpy()
    variance = np.asarray(logged.power(2).mean(0)).ravel() - np.asarray(logged.mean(0)).ravel()**2
    eligible = np.isfinite(dispersion) & (variance > 1e-12)
    order = sorted(np.flatnonzero(eligible), key=lambda i: (-float(dispersion[i]), ids[i]))
    chosen = np.zeros(len(ids), dtype=bool); chosen[order[:min(n_top,len(order))]] = True
    return chosen, mean, dispersion
