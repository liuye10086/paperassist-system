"""Per-cluster all-gene rank sums with tie correction and cluster-wise BH."""
import numpy as np
from scipy.stats import rankdata, norm


def markers(counts, normalized, logged, clusters, ids):
    labels = sorted(set(clusters), key=int)
    if len(labels) == 1:
        return [], {'status':'not_computable', 'reason':'single_cluster'}
    if len(labels)>50 or len(labels)*len(ids)>1_000_000:
        raise ValueError('marker_budget_exceeded')
    rows=[]; N=logged.shape[0]
    logged=logged.tocsc()
    for label in labels:
        group = clusters == label; ng=int(group.sum()); nr=N-ng
        group_detection=np.asarray((counts[group]>0).mean(0)).ravel()
        rest_detection=np.asarray((counts[~group]>0).mean(0)).ravel()
        group_mean=np.asarray(normalized[group].astype('float64').mean(0)).ravel()
        rest_mean=np.asarray(normalized[~group].astype('float64').mean(0)).ravel()
        start=len(rows)
        for j, identifier in enumerate(ids):
            row={'cluster':label,'feature_id':identifier,'n_group':ng,'n_rest':nr,
                 'score':None,'p_value':None,'q_value':None,'effect_log2_normalized':None,
                 'detected_group':float(group_detection[j]),
                 'detected_rest':float(rest_detection[j]), 'reason':None}
            if min(ng,nr)<3:
                row['reason']='side_fewer_than_3'
            else:
                values=logged[:,j].toarray().ravel().astype(np.float64)
                _, frequencies=np.unique(values,return_counts=True)
                tie=np.sum(frequencies.astype(np.float64)**3-frequencies)
                variance=ng*nr/12*((N+1)-tie/(N*(N-1)))
                if variance<=0:
                    row['reason']='constant_gene'
                else:
                    score=(rankdata(values)[group].sum()-ng*(N+1)/2)/np.sqrt(variance)
                    row.update(score=float(score),p_value=float(2*norm.sf(abs(score))),
                               effect_log2_normalized=float(np.log2((group_mean[j]+1e-9)/(rest_mean[j]+1e-9))))
            rows.append(row)
        valid=[r for r in rows[start:] if r['p_value'] is not None]
        # Correction universe includes all tested genes, including undefined
        # constant tests (NA stays NA); never correct only selected Top markers.
        ordered=sorted(valid,key=lambda r:(r['p_value'],r['feature_id']))
        adjusted=np.minimum.accumulate(np.asarray([r['p_value']*len(ids)/(i+1) for i,r in enumerate(ordered)])[::-1])[::-1]
        for row,q in zip(ordered,adjusted): row['q_value']=float(min(q,1.))
    any_valid=any(r['p_value'] is not None for r in rows)
    return rows, {'status':'completed' if any_valid else 'not_computable','reason':None if any_valid else 'all_tests_undefined','correction':'BH_per_cluster_all_filtered_genes','tested_genes':len(ids)}
