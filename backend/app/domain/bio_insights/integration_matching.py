"""Deterministic conservative matching; every source observation is audited."""
from collections import Counter,defaultdict

def match_samples(rows,left,right,left_axis,right_axis,*,inference):
    axes={left:set(left_axis),right:set(right_axis)}
    selected=[r for r in rows if r['dataset_version'] in axes]
    identities=Counter((r['dataset_version'],r['observation_id']) for r in selected)
    groups=defaultdict(list)
    for r in selected:groups[r['match_group']].append(r)
    candidates=[];audit=[]
    for group,items in sorted(groups.items()):
        sides=[[r for r in items if r['dataset_version']==sid] for sid in (left,right)]
        reason=None
        if any(len(side)!=1 for side in sides):reason='unpaired_or_many_to_one'
        elif any(identities[(r['dataset_version'],r['observation_id'])]!=1 for r in items):reason='duplicate_observation_mapping'
        elif any(r['observation_id'] not in axes[r['dataset_version']] for r in items):reason='observation_not_retained'
        elif any(r['relationship']=='independent_experiment' for r in items):reason='independent_experiments_not_pairable'
        elif sides[0][0].get('donor_id') and sides[1][0].get('donor_id') and sides[0][0]['donor_id']!=sides[1][0]['donor_id']:reason='donor_identity_conflict'
        elif inference and any(not r.get('independent_unit_verified') or not r.get('donor_id') for r in items):reason='independent_unit_unverified'
        if reason:
            audit.extend(dict(**r,reason=reason,included=False) for r in items)
        else:
            a,b=sides[0][0],sides[1][0]
            candidates.append(dict(match_group=group,left_observation_id=a['observation_id'],right_observation_id=b['observation_id'],donor_id=a.get('donor_id') or b.get('donor_id'),rows=items))
    donors=Counter(r['donor_id'] for r in candidates if r['donor_id'])
    matches=[]
    for pair in candidates:
        repeated=pair['donor_id'] and donors[pair['donor_id']]>1
        audit.extend(dict(**r,reason='repeated_donor_requires_frozen_selection' if repeated else 'matched',included=not bool(repeated)) for r in pair.pop('rows'))
        if not repeated:matches.append(pair)
    for sid,axis in axes.items():
        for obs in sorted(axis-{r['observation_id'] for r in selected if r['dataset_version']==sid}):
            audit.append(dict(dataset_version=sid,observation_id=obs,match_group=None,donor_id=None,included=False,reason='unmapped_observation'))
    return matches,audit


def object_decision(rows,pair,left_meta,right_meta,*,inference):
    chosen=[r for r in rows if (r['source_dataset_version'],r['source_id'],r['target_dataset_version'],r['target_id'])==(pair.left_source_id,pair.left_feature_id,pair.right_source_id,pair.right_feature_id)]
    if len(chosen)!=1:return None,'object_mapping_missing_or_duplicate'
    row=chosen[0]
    if row['decision']=='exclude':return row,'object_mapping_excluded'
    outgoing={r['target_id'] for r in rows if (r['source_dataset_version'],r['source_id'],r['target_dataset_version'])==(pair.left_source_id,pair.left_feature_id,pair.right_source_id)}
    incoming={r['source_id'] for r in rows if (r['target_dataset_version'],r['target_id'],r['source_dataset_version'])==(pair.right_source_id,pair.right_feature_id,pair.left_source_id)}
    ambiguous=row['ambiguity']!='none' or len(outgoing)>1 or len(incoming)>1
    if ambiguous and (row['decision']!='expand' or inference):return row,'ambiguous_mapping_inference_excluded'
    if row['source_species']!=row['target_species']:return row,'different_species_incomparable'
    for prefix,meta in [('source',left_meta),('target',right_meta)]:
        if meta.get('species_taxon_id') not in (None,row[prefix+'_species']):return row,'mapping_species_mismatch'
        if meta.get('namespace') not in (None,row[prefix+'_namespace']):return row,'mapping_namespace_mismatch'
        if row[prefix+'_version']!='unknown' and meta.get('reference_version') not in (None,row[prefix+'_version']):return row,'mapping_reference_mismatch'
    return row,None
