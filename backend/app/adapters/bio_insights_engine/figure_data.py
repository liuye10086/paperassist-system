"""Read frozen plotting inputs without importing the rendering stack."""
from .evidence import numeric
from .inputs import iter_table


def rows(source,key):
    if key not in source['members']:raise ValueError('figure_source_member_missing')
    return [row for _,row in iter_table(source['members'][key],format='tsv')]


def contrast_rows(data,contrast):
    identities={r['contrast_id'] for r in data if r.get('contrast_id')}
    if contrast is None:
        if len(identities)>1:raise ValueError('figure_explicit_contrast_required')
        contrast=next(iter(identities),None)
    elif contrast not in identities and identities:raise ValueError('figure_contrast_unknown')
    return [r for r in data if not r.get('contrast_id') or r['contrast_id']==contrast]


def q_column(source,config):
    return config.q_column or ('original_q' if source['metadata'].get('provenance')=='external_result' else 'q_within_contrast')


def running_enrichment(values, hit_indices, weight, expected_es):
    import numpy as np

    ranking = np.asarray(values, dtype=float)
    hits = np.asarray(hit_indices, dtype=int)
    if (ranking.ndim != 1 or not np.isfinite(ranking).all() or not 0 < len(hits) < len(ranking)
            or len(set(hits)) != len(hits) or np.any(hits < 0) or np.any(hits >= len(ranking))):
        raise ValueError('invalid_gsea_curve_inputs')
    mass = np.abs(ranking[hits])**weight
    if not np.isfinite(mass).all() or mass.sum() <= 0:
        raise ValueError('gsea_hit_weights_not_computable')
    increments = np.full(len(ranking), -1/(len(ranking)-len(hits)), dtype=float)
    increments[hits] = mass/mass.sum()
    result = np.cumsum(increments)
    peak, trough = result.max(), result.min()
    observed = peak if abs(peak) > abs(trough) else trough
    if not np.isclose(observed, expected_es, rtol=1e-6, atol=1e-8):
        raise ValueError('gsea_curve_es_mismatch')
    return result.tolist()


def adjusted_enrichment_plot_data(source, config):
    member = 'enrichment_results'
    data = contrast_rows(rows(source, member), config.contrast_id)
    gsea = source['metadata'].get('kind') == 'gsea_prerank'
    qcol, xcol = ('fdr_q_value', 'nes') if gsea else ('q_value', 'gene_ratio')
    ranks = []
    seen = set()
    for row in data:
        key, term = row['row_key'], row['term_id']
        if not key or not term or key in seen:
            raise ValueError('enrichment_plot_identity_invalid')
        seen.add(key)
        q = numeric(row.get(qcol))
        if q is not None and not 0 <= q <= 1:
            raise ValueError('figure_invalid_q')
        if q is not None and numeric(row.get(xcol)) is not None:
            ranks.append((q, term, key))
    display = [key for _, _, key in sorted(ranks)[:config.top_n]]
    return dict(rows=data, displayed_row_keys=display, q_column=qcol, top_n=config.top_n,
                correction='GSEA joint-null FDR' if gsea else 'BH within frozen enrichment family',
                style=config.enrichment_style, sorting='adjusted_metric_asc_then_term_id_then_row_key',
                requested_top_n=config.top_n, displayed_count=len(display), omitted_count=len(data)-len(display),
                missing_count=len(data)-len(ranks), top_n_omitted_count=len(ranks)-len(display),
                source_id=source['source_id'], source_sha256=source['sha256'],
                source_members={member: source['members'][member]['sha256']})
