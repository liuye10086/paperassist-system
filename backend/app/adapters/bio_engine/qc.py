"""One-pass filtering and raw sparse QC; zeros are observed counts, never NA."""
import numpy as np


def quality_control(raw, features, barcodes, positions, config):
    raw_counts = np.asarray(raw.sum(axis=1)).ravel()
    detected = np.asarray((raw > 0).sum(axis=1)).ravel()
    fences={};extremes={}
    for name,values in [('counts',raw_counts),('genes',detected)]:
        q1,q3=np.quantile(values,[.25,.75]);lower=float(q1-1.5*(q3-q1));upper=float(q3+1.5*(q3-q1))
        fences[name]={'lower':lower,'upper':upper,'rule':'global_1.5_IQR_descriptive_candidate_only'}
        extremes[name]=(values<lower)|(values>upper)
    expression = np.asarray([t == 'Gene Expression' for t in features['feature_types']])
    expressed = raw[:, expression]
    counts = np.asarray(expressed.sum(axis=1)).ravel()
    genes = np.asarray((expressed > 0).sum(axis=1)).ravel()
    position_map = {p['barcode']: p for p in positions}
    tissue = np.asarray([position_map.get(b, {}).get('in_tissue') for b in barcodes], dtype=object)
    exclusions = set(config.get('exclude_barcodes', []))
    mt_ids = config.get('mitochondrial_feature_ids')
    if mt_ids is not None and not set(mt_ids).issubset(features['feature_ids']): raise ValueError('unknown_mitochondrial_feature')
    mt_reason = 'mitochondrial_rule_unconfirmed' if mt_ids is None else None
    mt_fraction = None
    if mt_ids is not None:
        mt_counts = np.asarray(raw[:, np.asarray([i in mt_ids for i in features['feature_ids']])].sum(axis=1)).ravel()
        mt_fraction = np.divide(mt_counts, raw_counts, out=np.full(raw.shape[0], np.nan), where=raw_counts > 0)
    if config.get('max_mt_fraction') is not None and mt_fraction is None: raise ValueError('mitochondrial_rule_unconfirmed')
    if not exclusions.issubset(set(barcodes)):
        raise ValueError('unknown_exclusion_barcode')
    reasons = [[] for _ in barcodes]
    for i, barcode in enumerate(barcodes):
        if counts[i] < config.get('min_counts', 1): reasons[i].append('min_counts')
        if genes[i] < config.get('min_genes', 1): reasons[i].append('min_genes')
        if config.get('max_counts') is not None and counts[i]>config['max_counts']: reasons[i].append('max_counts')
        if config.get('max_mt_fraction') is not None and mt_fraction[i]>config['max_mt_fraction']: reasons[i].append('max_mt_fraction')
        if config.get('in_tissue_only', False) and tissue[i] != 1: reasons[i].append('not_in_tissue')
        if barcode in exclusions: reasons[i].append('explicit_exclusion')
    initial = np.asarray([not r for r in reasons])
    feature_nonzero = np.asarray((raw[initial] > 0).sum(axis=0)).ravel()
    feature_mask = expression & (feature_nonzero >= config.get('min_gene_spots', 3))
    remaining = np.asarray(raw[:, feature_mask].sum(axis=1)).ravel()
    for i in np.flatnonzero(initial & (remaining == 0)): reasons[i].append('zero_after_gene_filter')
    mask = np.asarray([not r for r in reasons])
    filtered=raw[mask][:,feature_mask].tocsr()
    return dict(raw_counts=raw_counts, raw_detected=detected, raw_zero_fraction=1-detected/raw.shape[1],
                extreme_counts=extremes['counts'],extreme_genes=extremes['genes'],extreme_fences=fences,
                feature_counts=np.asarray(raw.sum(0)).ravel(), feature_nonzero=np.asarray((raw>0).sum(0)).ravel(),
                obs_mask=mask, feature_mask=feature_mask, reasons=reasons, in_tissue=tissue,
                mt_fraction=mt_fraction, mt_reason=mt_reason,
                filtered_counts=filtered,filtered_total=np.asarray(filtered.sum(1)).ravel(),
                filtered_detected=np.asarray((filtered>0).sum(1)).ravel(),
                stages={'raw_observations':raw.shape[0], 'raw_features':raw.shape[1],
                        'expression_features':int(expression.sum()), 'spot_threshold_kept':int(initial.sum()),
                        'gene_threshold_kept':int(feature_mask.sum()), 'final_spots':int(mask.sum())})
