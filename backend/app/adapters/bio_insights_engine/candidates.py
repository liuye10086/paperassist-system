"""Deterministic, inspectable candidate set recipes; no confidence inference."""
from collections import Counter,defaultdict
import hashlib
import json
import math
from app.domain.bio_insights.bulk_results import bulk_candidate_data, bulk_contrast_labels, is_reviewed_bulk
from .evidence import source_numeric


_CANDIDATE_FIELDS = ('rank','row_key','feature_id','same_direction_support_count','support_count','support_source_count','support_sources','conflict_count','direction_comparable','positive_sources','negative_sources','missing_sources',
    'unknown_direction_sources','distinct_input_groups','independence_verified','primary_source_id','primary_row_key','primary_q','primary_q_column',
    'primary_effect','effect_name','effect_unit','score','score_status','score_details','annotations','provenance','inference_scope')
_EVIDENCE_FIELDS = ('feature_id','source_id','contrast_id','source_group','supported','missing','direction','effect','q','q_column',
    'row_key','original_feature_id','numerator','denominator','inference_scope','observation_level')


def _sign(value):return None if value is None else 1 if value>0 else -1 if value<0 else 0


def _annotation_match(item,step):
    value=item.get('value') if item else None;op=step['annotation_operator'];target=step.get('annotation_value')
    if op=='unknown':return value is None
    if op=='known':return value is not None
    if value is None:return False
    if isinstance(value,bool)!=isinstance(target,bool):return False
    try:
        return {'eq':lambda:value==target,'ne':lambda:value!=target,'gt':lambda:value>target,'ge':lambda:value>=target,
                'lt':lambda:value<target,'le':lambda:value<=target}[op]()
    except (TypeError,KeyError):return False


def apply_recipe(evidence,steps,annotations):
    source_sets={key:set(rows) for key,rows in evidence.items()};current=set().union(*source_sets.values())
    universe=set(current);counts=[];exclusions=[];missing_requested=[]
    for index,step in enumerate(steps,1):
        before=set(current);operation=step['operation'];selected=step.get('source_ids') or list(evidence)
        incomparable=set()
        if len(set(selected))!=len(selected) or set(selected)-set(evidence):raise ValueError('unknown_candidate_source')
        if operation=='threshold':
            for source in selected:
                candidates=set()
                for feature in source_sets[source]:
                    row=evidence[source][feature];q=row.get(step.get('q_column'),row.get('q'));effect=row.get('effect')
                    if q is not None and q<=step['q_threshold'] and (step.get('minimum_absolute_effect') is None or effect is not None and abs(effect)>=step['minimum_absolute_effect']):
                        candidates.add(feature)
                source_sets[source]=candidates
            current&=set().union(*source_sets.values())
        elif operation in ('union','intersection','at_least_k'):
            sets=[source_sets[source] for source in selected]
            if operation=='union':wanted=set().union(*sets)
            elif operation=='intersection':wanted=set.intersection(*sets)
            else:
                k=step['k']
                if not 1<=k<=len(sets):raise ValueError('invalid_candidate_k')
                frequency=Counter(feature for group in sets for feature in group);wanted={f for f,n in frequency.items() if n>=k}
            current&=wanted
        elif operation=='same_direction':
            for feature in current:
                definitions=[tuple(evidence[source].get(feature,{}).get(key) for key in ('numerator','denominator','effect_name','effect_unit')) for source in selected]
                if any(any(value in (None,'') for value in definition) for definition in definitions) or len(set(definitions))!=1:
                    incomparable.add(feature)
            current={feature for feature in current if all(feature in source_sets[source] for source in selected)
                     and feature not in incomparable
                     and len({_sign(evidence[source][feature]['effect']) for source in selected})==1
                     and _sign(evidence[selected[0]][feature]['effect']) in (-1,1)}
        elif operation=='include':
            requested=set(step.get('feature_ids',[]));current&=requested
            missing_requested.extend(dict(step=index,feature_id=f,reason='absent_from_input_evidence') for f in sorted(requested-universe))
        elif operation=='exclude':current-=set(step.get('feature_ids',[]))
        elif operation=='annotation':
            current={feature for feature in current if _annotation_match(annotations.get(feature,{}).get(step['annotation_field']),step)}
        else:raise ValueError('unknown_candidate_operation')
        removed=sorted(before-current)
        reason='direction_conflict_or_unknown' if operation=='same_direction' else operation
        exclusions.extend(dict(step=index,feature_id=feature,reason='direction_not_comparable' if feature in incomparable else reason) for feature in removed)
        counts.append(dict(step=index,operation=operation,before_count=len(before),after_count=len(current),removed_count=len(removed),
                           source_counts={source:len(values) for source,values in source_sets.items()},parameters=step))
    return dict(selected=sorted(current),steps=counts,exclusions=exclusions,source_sets=source_sets,missing_requested_features=missing_requested)


def weighted_score(components,weights):
    missing=[w['item'] for w in weights if w.get('required',True) and components.get(w['item']) is None]
    available=[w for w in weights if components.get(w['item']) is not None]
    denominator=sum(w['weight'] for w in available)
    if any(not math.isfinite(float(components[w['item']])) or not 0<=components[w['item']]<=1 for w in available):
        raise ValueError('invalid_evidence_component')
    score=None if missing or denominator==0 else sum(components[w['item']]*w['weight'] for w in available)/denominator
    status='unavailable' if score is None else 'partial' if len(available)<len(weights) else 'complete'
    total=sum(w['weight'] for w in weights)
    return dict(score=score,score_status=status,available_weight=denominator,total_weight=total,
                weight_coverage=denominator/total if total else None,complete_score=score if status=='complete' else None,
                partial_score=score if status=='partial' else None,missing_required=missing,components=components,
                weights=weights,unknown_policy='required_unknown_yields_null; optional_unknown_excluded_and_weights_renormalized')


def dependency_groups(canonical):
    parent={source:source for source in canonical}
    def find(source):
        while parent[source]!=source:source=parent[source]
        return source
    for left in canonical:
        for right in canonical:
            if set(canonical[left])&set(canonical[right]):parent[find(right)]=find(left)
    groups=defaultdict(list)
    for source in canonical:groups[find(source)].append(source)
    source_group={}
    for values in groups.values():
        identifier=hashlib.sha256(json.dumps(sorted(values)).encode()).hexdigest()[:16]
        for source in values:source_group[source]=identifier
    return dict(source_group=source_group,groups=[sorted(values) for values in groups.values()],
                unknown_sources=sorted(k for k,v in canonical.items() if not v),independence_verified=False)


def default_ranking_key(row):
    return (-(row['same_direction_support_count']) if row['same_direction_support_count'] is not None else float('inf'),
            row['conflict_count'] if row['conflict_count'] is not None else float('inf'),
            row['primary_q'] if row['primary_q'] is not None else float('inf'),
            -abs(row['primary_effect']) if row['primary_effect'] is not None else float('inf'),row['feature_id'])


def _candidate_row_key(source_digest, feature_id):
    return hashlib.sha256((source_digest + ':' + feature_id).encode()).hexdigest()


def _run_bulk_candidates(config, source, source_digest, writer):
    from .inputs import iter_table

    source_id = source['source_id']
    metadata = source['metadata']
    member = source['members'].get('comparison_results')
    if (source['source_kind'] != 'bio_insight_result_version' or not is_reviewed_bulk(metadata)
            or not member or (member.get('format'), member.get('role')) != ('tsv', 'table')):
        raise ValueError('reviewed_bulk_comparison_required')
    selection = config.bulk_selection
    labels = bulk_contrast_labels(metadata).get(selection.contrast_id)
    if labels is None:
        raise ValueError('bulk_comparison_contrast_unknown')
    data = bulk_candidate_data(iter_table(member, format='tsv'), selection, labels)
    ranked = data['ranked']
    candidate_count = len(ranked)
    top_n = config.bulk_top_n
    displayed_count = min(top_n, candidate_count)
    groups = dependency_groups({source_id: metadata.get('canonical_dataset_ids', [])})
    source_group = groups['source_group'][source_id]
    selection_parameters = selection.model_dump(mode='json')
    frozen = dict(source_result_version_id=source_id, source_manifest_sha256=source['sha256'],
                  comparison_sha256=member['sha256'], numerator=labels[0], denominator=labels[1],
                  **selection_parameters, candidate_count=candidate_count, comparison_counts=data['counts'],
                  top_n=top_n, displayed_count=displayed_count)

    def candidate_rows(entries):
        for rank, row in enumerate(entries, 1):
            feature_id = row['feature_id']
            direction = row['direction']
            yield dict(rank=rank, row_key=_candidate_row_key(source_digest, feature_id),
                       feature_id=feature_id, symbol=row['symbol'], contrast_id=selection.contrast_id, direction=direction,
                       same_direction_support_count=1, support_count=1, support_source_count=1,
                       support_sources=[source_id], conflict_count=0, direction_comparable=True,
                       positive_sources=[source_id] if direction == 'up' else [],
                       negative_sources=[source_id] if direction == 'down' else [],
                       missing_sources=[], unknown_direction_sources=[], distinct_input_groups=1, independence_verified=False,
                       primary_source_id=source_id, primary_row_key=row['row_key'], primary_q=row[selection.q_column],
                       primary_q_column=selection.q_column, primary_effect=row['effect_value'], effect_name=row['effect_name'],
                       effect_unit=row['effect_unit'], score=None, score_status='not_requested',
                       score_details=dict(score=None, score_status='not_requested'), annotations={},
                       provenance='derived_candidate', inference_scope='derived')

    def evidence_rows():
        for row in ranked:
            yield dict(feature_id=row['feature_id'], source_id=source_id, contrast_id=selection.contrast_id,
                       source_group=source_group, supported=True, missing=False, direction=1 if row['direction'] == 'up' else -1,
                       effect=row['effect_value'], q=row[selection.q_column], q_column=selection.q_column, row_key=row['row_key'],
                       original_feature_id=row['feature_id'], numerator=row['numerator'], denominator=row['denominator'],
                       inference_scope=row['inference_scope'], observation_level=row['observation_level'], source_row=row['source_row'],
                       test_status=row['test_status'], q_within_contrast=row['q_within_contrast'],
                       q_global_family=row['q_global_family'], original_method_adjustment=row['original_method_adjustment'])

    candidate_fields = _CANDIDATE_FIELDS + ('symbol', 'contrast_id', 'direction')
    writer.table('candidate_results', candidate_rows(ranked), candidate_fields)
    writer.table('bulk_candidate_top', candidate_rows(ranked[:displayed_count]), candidate_fields)
    writer.table('candidate_evidence', evidence_rows(), _EVIDENCE_FIELDS + (
        'source_row', 'test_status', 'q_within_contrast', 'q_global_family', 'original_method_adjustment',
    ))
    writer.table('candidate_steps', [
        dict(step=1, operation='bulk_threshold', before_count=data['counts']['total'], after_count=candidate_count,
             removed_count=len(data['exclusions']), source_counts={source_id: candidate_count},
             parameters=selection_parameters),
    ], ['step','operation','before_count','after_count','removed_count','source_counts','parameters'])
    writer.table('candidate_exclusions', data['exclusions'], ['step','feature_id','reason','source_row','source_row_key'])
    writer.table('mapping_exclusions', [], ['source_id','source_row','feature_id','reason'])
    writer.table('missing_requested_features', [], ['step','feature_id','reason'])
    selected = [row['feature_id'] for row in ranked]
    writer.json('candidate_sets', {'source_sets': {source_id: selected}, 'selected': selected})
    writer.json('bulk_candidate_selection', frozen)
    reference = {field: metadata.get(field) for field in ('species_taxon_id','namespace','reference_version')}
    methods = dict(recipe=config.model_dump(mode='json'), source_contrasts=config.source_contrasts,
                   q_columns={source_id: selection.q_column}, dependencies=groups, bulk_selection=frozen,
                   ranking='selected q ASC, absolute MLE log2 fold change DESC, stable feature ID ASC',
                   warning='Support counts the fixed result source. Biological replication and confidence require separate evidence.',
                   **reference)
    summary = dict(candidate_count=candidate_count, empty_result=candidate_count == 0, source_count=1, step_count=1,
                   contrast_id=selection.contrast_id, top_n=top_n, displayed_count=displayed_count,
                   species_taxon_id=reference['species_taxon_id'], namespace=reference['namespace'])
    return dict(summary=summary, methods=methods, inference_scope='derived', provenance='system_computed')


def run_candidates(payload,writer):
    from app.domain.bio_insights.contracts import CandidateConfig
    from .inputs import document,iter_table
    config=CandidateConfig.model_validate(payload['config']);sources={s['source_id']:s for s in payload['sources']}
    if config.bulk_selection is not None:
        return _run_bulk_candidates(config, sources[config.primary_result_source_id], payload['identity']['source_digest'], writer)
    from .mapping import ExplicitMapper
    primary=sources[config.primary_result_source_id];target=primary['metadata'];mapping_sources=[sources[i] for i in config.mapping_source_ids]
    evidence={};exclusions=[];canonical={};q_columns={};annotations={};input_rows=0
    for sid in config.result_source_ids:
        source=sources[sid];meta=source['metadata'];canonical[sid]=meta.get('canonical_dataset_ids',[])
        mapper=ExplicitMapper(meta['species_taxon_id'],meta['namespace'],target['species_taxon_id'],target['namespace'],mapping_sources,
            allow_untyped_identity=meta.get('inference_scope') in ('sample_inference','sample_exploratory') and target.get('inference_scope') in ('sample_inference','sample_exploratory'))
        grouped=defaultdict(list);q_column='original_q' if meta.get('provenance')=='external_result' else 'q_within_contrast'
        for step in config.steps:
            if step.operation=='threshold' and sid in step.source_ids:q_column=step.q_column
        q_columns[sid]=q_column
        for number,row in iter_table(source['members']['comparison_results'],format='tsv'):
            input_rows+=1
            if input_rows>1_000_000:raise ValueError('candidate_input_row_limit')
            if row['contrast_id']!=config.source_contrasts[sid]:continue
            if row.get('tested','True').lower() not in ('true','1'):
                exclusions.append(dict(source_id=sid,source_row=number,feature_id=row['feature_id'],reason='not_in_tested_universe'));continue
            mapped,reason=mapper.map_id(row['feature_id'])
            if mapped is None:
                exclusions.append(dict(source_id=sid,source_row=number,feature_id=row['feature_id'],reason=reason));continue
            fields={name:source_numeric(source,row.get(name)) for name in ('q_within_contrast','q_global_family','original_q','system_recomputed_q')}
            if any(value is not None and not 0<=value<=1 for value in fields.values()):raise ValueError('invalid_candidate_q')
            grouped[mapped].append(dict(row_key=row['row_key'],source_row=number,original_feature_id=row['feature_id'],
                effect=source_numeric(source,row.get('effect_value')),q=fields[q_column],q_column=q_column,**fields,
                inference_scope=row.get('inference_scope'),observation_level=row.get('observation_level'),
                numerator=row.get('numerator'),denominator=row.get('denominator'),effect_name=row.get('effect_name'),effect_unit=row.get('effect_unit')))
        evidence[sid]={feature:rows[0] for feature,rows in grouped.items() if len(rows)==1}
        for feature,rows in grouped.items():
            if len(rows)>1:
                exclusions.extend(dict(source_id=sid,source_row=r['source_row'],feature_id=r['original_feature_id'],reason='many_to_one_or_duplicate_result_id') for r in rows)
    for aid in config.annotation_source_ids:
        resource=document(sources[aid]['members']['resource'])
        if resource['kind']!='feature_annotation' or resource.get('identity_compatible') is False:raise ValueError('annotation_resource_kind_mismatch')
        mapper=ExplicitMapper(resource['species_taxon_id'],resource['namespace'],target['species_taxon_id'],target['namespace'],mapping_sources)
        for row in resource['annotations']:
            feature,reason=mapper.map_id(row['feature_id'])
            if feature is None:
                exclusions.append(dict(source_id=aid,source_row=None,feature_id=row['feature_id'],reason=reason));continue
            field=row['field'];old=annotations.setdefault(feature,{}).get(field)
            item={**row,'resource_version_id':aid}
            if old and old!=item:raise ValueError('conflicting_candidate_annotation')
            annotations[feature][field]=item
    recipe=apply_recipe(evidence,[step.model_dump(mode='json') for step in config.steps],annotations)
    groups=dependency_groups(canonical);rows=[];matrix=[]
    for feature in recipe['selected']:
        support=[sid for sid in config.result_source_ids if feature in recipe['source_sets'][sid]]
        primary_row=evidence[config.primary_result_source_id].get(feature,{})
        signs={sid:_sign(evidence[sid].get(feature,{}).get('effect')) for sid in support}
        positive=[sid for sid,sign in signs.items() if sign==1];negative=[sid for sid,sign in signs.items() if sign==-1]
        group_signs=defaultdict(set)
        definitions={tuple(evidence[sid][feature].get(key) for key in ('numerator','denominator','effect_name','effect_unit')) for sid in support}
        comparable=len(definitions)==1 and all(all(value not in (None,'') for value in item) for item in definitions)
        for sid,sign in signs.items():
            if sign in (-1,1):group_signs[groups['source_group'][sid]].add(sign)
        group_positive=sum(value=={1} for value in group_signs.values());group_negative=sum(value=={-1} for value in group_signs.values())
        group_conflict=sum(len(value)>1 for value in group_signs.values());known=len(group_signs)
        conflict=group_conflict+min(group_positive,group_negative) if comparable else None
        supported_groups={groups['source_group'][sid] for sid in support}
        components=dict(support_fraction=len(supported_groups)/len(set(groups['source_group'].values())),
                        direction_agreement=max(group_positive,group_negative)/known if known and comparable else None,
                        primary_significance=1-primary_row['q'] if primary_row.get('q') is not None else None,
                        primary_absolute_effect=abs(primary_row['effect'])/(1+abs(primary_row['effect'])) if primary_row.get('effect') is not None else None)
        weighted=weighted_score(components,[w.model_dump() for w in config.weights]) if config.ranking_mode=='weighted' else {'score':None,'score_status':'not_requested','components':components}
        row=dict(row_key=_candidate_row_key(payload['identity']['source_digest'],feature),feature_id=feature,
            support_count=len(supported_groups),same_direction_support_count=max(group_positive,group_negative) if comparable else None,
            support_source_count=len(support),support_sources=support,conflict_count=conflict,direction_comparable=comparable,positive_sources=positive,negative_sources=negative,
            missing_sources=[sid for sid in config.result_source_ids if feature not in evidence[sid]],
            unknown_direction_sources=[sid for sid in support if signs[sid] is None],distinct_input_groups=len({groups['source_group'][sid] for sid in support}),
            independence_verified=False,primary_source_id=config.primary_result_source_id,primary_row_key=primary_row.get('row_key'),
            primary_q=primary_row.get('q'),primary_q_column=q_columns[config.primary_result_source_id],primary_effect=primary_row.get('effect'),
            effect_name=primary_row.get('effect_name'),effect_unit=primary_row.get('effect_unit'),score=weighted['score'],score_status=weighted['score_status'],score_details=weighted,
            annotations=annotations.get(feature,{}),provenance='derived_candidate',inference_scope='derived')
        rows.append(row)
        for sid in config.result_source_ids:
            item=evidence[sid].get(feature,{})
            matrix.append(dict(feature_id=feature,source_id=sid,contrast_id=config.source_contrasts[sid],source_group=groups['source_group'][sid],
                supported=sid in support,missing=not bool(item),direction=_sign(item.get('effect')),effect=item.get('effect'),q=item.get('q'),
                q_column=q_columns[sid],row_key=item.get('row_key'),original_feature_id=item.get('original_feature_id'),
                numerator=item.get('numerator'),denominator=item.get('denominator'),inference_scope=item.get('inference_scope'),
                observation_level=item.get('observation_level')))
    default=default_ranking_key
    rows.sort(key=(lambda row:({'complete':0,'partial':1,'unavailable':2}[row['score_status']],-row['score'] if row['score'] is not None else 0,*default(row))) if config.ranking_mode=='weighted' else default)
    for index,row in enumerate(rows,1):row['rank']=index
    writer.table('candidate_results',rows,_CANDIDATE_FIELDS)
    writer.table('candidate_evidence',matrix,_EVIDENCE_FIELDS)
    writer.table('candidate_steps',recipe['steps'],['step','operation','before_count','after_count','removed_count','source_counts','parameters'])
    writer.table('candidate_exclusions',recipe['exclusions'],['step','feature_id','reason'])
    writer.table('mapping_exclusions',exclusions,['source_id','source_row','feature_id','reason'])
    writer.table('missing_requested_features',recipe['missing_requested_features'],['step','feature_id','reason'])
    writer.json('candidate_sets',{'source_sets':{sid:sorted(values) for sid,values in recipe['source_sets'].items()},'selected':recipe['selected']})
    methods=dict(recipe=config.model_dump(mode='json'),source_contrasts=config.source_contrasts,q_columns=q_columns,dependencies=groups,
        ranking='same-direction dependency-group support DESC, conflict ASC, primary q ASC, abs primary effect DESC, stable ID ASC; unknown last',
        support_count_definition='distinct canonical input dependency groups; never verified biological independence',
        source_step_semantics='at_least_k counts selected result sources for consistency, not independent replication',
        same_direction_comparability='exact numerator, denominator, effect_name and effect_unit must match',
        weighted_components={'support_fraction':'support_dependency_groups / selected_dependency_groups','direction_agreement':'largest consistent-sign dependency-group count / dependency groups with a known nonzero sign; incomparable definitions yield null',
            'primary_significance':'1 - selected_primary_q','primary_absolute_effect':'abs(effect)/(1+abs(effect))'},
        weighted_unknown='required missing => null; optional missing removed from denominator; available weight reported',
        set_step_policy='ordered filters only; later union never reintroduces excluded genes',
        warning='Source support is not independent biological replication or a biological confidence probability.',
        species_taxon_id=target['species_taxon_id'],namespace=target['namespace'],reference_version=target['reference_version'])
    return dict(summary=dict(candidate_count=len(rows),source_count=len(evidence),step_count=len(config.steps),
        empty_result=len(rows)==0,species_taxon_id=target['species_taxon_id'],namespace=target['namespace']),methods=methods,
        inference_scope='derived',provenance='system_computed')
