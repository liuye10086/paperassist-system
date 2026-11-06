"""Offline SingleR reference and ordered annotation result contracts."""
import hashlib
import json
import os
from pathlib import Path

import numpy as np
from scipy import sparse


REFERENCE_ROOT=Path('/opt/paperassist-single-cell-r/share/paperassist-reference')
REFERENCE_ID='monaco_immune_1.0.0'


def validate_expression(expression,cells,genes):
    if (not sparse.isspmatrix_csr(expression) or expression.shape!=(len(cells),len(genes))
            or not cells or not genes or len(set(cells))!=len(cells) or len(set(genes))!=len(genes)
            or any(not isinstance(x,str) or not x for x in [*cells,*genes])):
        raise ValueError('r_annotation_axis_invalid')
    expression.check_format(full_check=True)
    if expression.dtype.kind not in 'fiu' or not np.isfinite(expression.data).all() or np.any(expression.data<0):
        raise ValueError('r_annotation_expression_invalid')
    if expression.nnz>2**31-1 or max(expression.shape)>2**31-1:raise ValueError('r_sparse_index_limit')


def resolve_reference(config,root=REFERENCE_ROOT):
    if (config.get('reference_id')!=REFERENCE_ID or config.get('species')!='Homo sapiens'
            or config.get('gene_id_type')!='ensembl_gene_id' or config.get('label_level','main') not in ('main','fine')
            or set(config)-{'reference_id','species','gene_id_type','label_level'}):
        raise ValueError('r_annotation_reference_incompatible')
    folder=root/REFERENCE_ID
    try:
        metadata=json.loads((folder/'reference.json').read_text(encoding='utf-8'))
        path=folder/'reference.rds'
        digest=hashlib.sha256()
        with path.open('rb') as handle:
            for chunk in iter(lambda:handle.read(1024*1024),b''):digest.update(chunk)
    except (OSError,ValueError) as exc:raise ValueError('r_annotation_reference_unavailable') from exc
    if digest.hexdigest()!=metadata.get('sha256'):raise ValueError('r_annotation_reference_checksum_mismatch')
    if (metadata.get('reference_id')!=REFERENCE_ID or metadata.get('species')!=config['species']
            or metadata.get('gene_id_type')!=config['gene_id_type'] or metadata.get('version')!='1.0.0'
            or not metadata.get('source') or not metadata.get('license') or not metadata.get('gene_ids')
            or len(set(metadata['gene_ids']))!=len(metadata['gene_ids'])):
        raise ValueError('r_annotation_reference_metadata_invalid')
    return dict(path=path,metadata=metadata,label_level=config.get('label_level','main'))


def match_genes(genes,metadata):
    reference=set(metadata['gene_ids'])
    common=[gene for gene in genes if gene in reference]
    return dict(policy='exact_stable_id_intersection_no_symbol_inference_no_version_stripping',
                test_genes=len(genes),reference_genes=len(reference),matched_test_genes=len(common),
                unmatched_test_genes=len(genes)-len(common),common_gene_ids=common)


def validate_result(cells,candidates,pruned,scores,score_labels,delta_next,delta_median):
    scores=np.asarray(scores,dtype='float64')
    delta_next=np.asarray(delta_next,dtype='float64');delta_median=np.asarray(delta_median,dtype='float64')
    n=len(cells);labels=set(score_labels)
    if (scores.shape!=(n,len(score_labels)) or len(labels)!=len(score_labels) or len(labels)<2
            or len(candidates)!=n or len(pruned)!=n or set(candidates)-labels
            or set(pruned)-labels-{''} or delta_next.shape!=(n,) or delta_median.shape!=(n,)
            or not np.isfinite(scores).all() or not np.isfinite(delta_next).all() or not np.isfinite(delta_median).all()):
        raise ValueError('r_annotation_result_invalid')
    ranks=np.argsort(-scores,axis=1,kind='stable')
    return dict(cells=list(cells),candidate_labels=list(candidates),
                pruned_labels=[label or 'unknown' for label in pruned],
                label_status=['candidate' if label else 'unknown' for label in pruned],
                scores=scores,score_labels=list(score_labels),delta_next=delta_next,delta_median=delta_median,
                candidate_ranks=[[score_labels[index] for index in row] for row in ranks],
                score_semantics='initial_Spearman_correlation_quantile_not_probability; candidate_label_is_fine_tuned',
                delta_next_semantics='best_minus_next_score_after_fine_tuning',
                delta_median_semantics='assigned_label_initial_score_minus_median_initial_score')


def reference_catalog(root=None):
    """Operator-configured local metadata only; Worker still verifies the RDS checksum."""
    root=Path(root or os.environ.get('PAPERASSIST_SINGLE_CELL_REFERENCE_ROOT',REFERENCE_ROOT))
    entry=dict(reference_id=REFERENCE_ID,species='Homo sapiens',species_taxon_id=9606,
               gene_id_type='ensembl_gene_id',label_levels=['main','fine'],version='1.0.0',
               source='celldex MonacoImmuneData; ExperimentHub EH3496/EH3497',
               license='celldex GPL-3; upstream publication CC-BY-4.0',available=False,
               reason='r_annotation_reference_unavailable')
    try:
        metadata=json.loads((root/REFERENCE_ID/'reference.json').read_text(encoding='utf-8'))
        if (metadata.get('reference_id')!=REFERENCE_ID or metadata.get('version')!='1.0.0'
                or metadata.get('species')!='Homo sapiens' or metadata.get('gene_id_type')!='ensembl_gene_id'
                or len(str(metadata.get('sha256','')))!=64):raise ValueError('reference_metadata_invalid')
        entry.update({key:metadata[key] for key in ('source','license','sha256','samples') if key in metadata})
        entry.update(available=True,reason=None,availability_scope='published_metadata; Worker verifies reference bytes before execution')
    except (OSError,ValueError):pass
    return [entry]
