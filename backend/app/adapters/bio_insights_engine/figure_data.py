"""Read frozen plotting inputs without importing the rendering stack."""
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
