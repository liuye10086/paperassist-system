"""Deterministic full evidence cross product. No biological score or inference."""
import csv,hashlib,json
from pathlib import Path

def read_json(source,key='original_file'):
    return json.loads(Path(source['members'][key]['path']).read_bytes())

def independent_support(candidate,evidence,request,sources):
    by_id={s['source_id']:s for s in sources};reasons=[]
    def fail(code):
        if code not in reasons:reasons.append(code)
    if not request:return dict(supported=False,reasons=['no_independent_analysis_requested'])
    evidence_source=by_id.get(request.get('evidence_source_id'),{})
    if not evidence_source.get('metadata',{}).get('locator_verification',{}).get('locator_verified'):fail('evidence_original_locator_unverified')
    needed=[request.get(k) for k in ('result_source_id','design_source_id','overlap_audit_source_id')]+request.get('material_source_ids',[])+[candidate['source_id']]
    if any(i not in by_id for i in needed) or not request.get('material_source_ids'):return dict(supported=False,reasons=['fixed_run_material_design_overlap_required'])
    result=by_id[request['result_source_id']];meta=result['metadata'];primary=by_id[candidate['source_id']]
    materials=[by_id[i] for i in request['material_source_ids']]
    if result['source_kind']!='bio_insight_result_version' or not meta.get('run_id') or meta.get('task_status')!='succeeded' or meta.get('provenance')!='system_computed' or meta.get('kind')!='comparison':fail('actual_completed_comparison_required')
    if any(s['source_kind']!='bio_processed_dataset_version' for s in materials):fail('independent_processed_material_required')
    primary_ids={primary['metadata'].get('canonical_dataset_id')}-{None}
    external_ids={s['metadata'].get('canonical_dataset_id') for s in materials}-{None}
    if not primary_ids or len(external_ids)!=len(materials) or primary_ids&external_ids:fail('same_or_unknown_material_identity')
    if external_ids!=set(meta.get('canonical_dataset_ids',[])):fail('result_material_lineage_mismatch')
    def donors(source):
        rows=[r for r in source['metadata'].get('observations',[]) if r.get('retained') not in (False,'false','False','0',0)]
        values=[r.get('donor') for r in rows]
        return set(values) if values and all(v not in (None,'','unknown') for v in values) else None
    a=donors(primary);parts=[donors(s) for s in materials];b=set().union(*(v or set() for v in parts))
    if not a or any(not v for v in parts) or a&b:fail('donor_overlap_unknown_or_shared')
    try:
        design=read_json(by_id[request['design_source_id']]);audit=read_json(by_id[request['overlap_audit_source_id']])
        if design.get('schema')!='independent_validation_design_v1' or set(design.get('material_source_ids',[]))!=set(request['material_source_ids']) or design.get('object_id')!=candidate['object_id'] or design.get('condition')!=candidate.get('condition') or design.get('species_taxon_id')!=candidate.get('species_taxon_id') or any(design.get(k)!=request.get(k) for k in ('numerator','denominator')):fail('independent_design_object_control_mismatch')
        if audit.get('schema')!='donor_overlap_audit_v1' or set(audit.get('primary_donor_ids',[]))!=(a or set()) or set(audit.get('validation_donor_ids',[]))!=b or not audit.get('identity_basis') or not audit.get('reviewer'):fail('overlap_audit_does_not_cover_materials')
    except (KeyError,ValueError,TypeError,OSError):fail('fixed_design_and_overlap_documents_required')
    if evidence.get('condition')!=candidate.get('condition') or evidence.get('species_taxon_id')!=candidate.get('species_taxon_id'):fail('evidence_condition_species_mismatch')
    try:
        rows=list(csv.DictReader(Path(result['members']['comparison_results']['path']).read_text(encoding='utf-8-sig').splitlines(),delimiter='\t'))
        selected=[r for r in rows if r.get('row_key')==request.get('result_row_key')]
        if len(selected)!=1:raise ValueError()
        row=selected[0]
        # This is the fixed run's complete processed lineage, not requester assertions.
        inputs=meta.get('comparison_inputs') or []
        actual={s['source_id']:s for s in inputs}
        declared={s['source_id']:s for s in materials}
        fields=('canonical_dataset_id','species_taxon_id','namespace','reference_version','observations')
        if not actual or len(actual)!=len(inputs) or set(actual)!=set(declared):fail('actual_processed_inputs_do_not_match_request')
        for sid,s in actual.items():
            supplied=declared.get(sid,{})
            if s.get('source_kind')!='bio_processed_dataset_version' or not s.get('sha256') or s.get('sha256')!=supplied.get('sha256') or any(s['metadata'].get(k)!=supplied.get('metadata',{}).get(k) for k in fields):fail('actual_processed_input_snapshot_mismatch')
        plan=meta.get('plan_config') or {}
        if plan.get('kind')!='comparison' or plan.get('schema_version',1)!=1:fail('actual_fixed_comparison_design_required')
        identity=('species_taxon_id','namespace','reference_version')
        if any(candidate.get(k) in (None,'','unknown') or meta.get(k)!=candidate.get(k) or plan.get(k)!=candidate.get(k) or any(s['metadata'].get(k)!=candidate.get(k) for s in inputs) for k in identity):fail('actual_result_object_identity_mismatch')
        if any(candidate['object_id'] not in (s['metadata'].get('feature_ids') or []) for s in inputs):fail('actual_result_feature_axis_mismatch')
        contrasts=[v for v in plan.get('contrasts',[]) if v.get('contrast_id')==row.get('contrast_id')]
        if len(contrasts)!=1:fail('actual_fixed_contrast_required')
        else:
            contrast=contrasts[0];observations={}
            for s in inputs:
                for obs in s['metadata'].get('observations') or []:
                    key=(s['source_id'],obs.get('barcode'))
                    if not key[1] or obs.get('processed_version_id')!=s['source_id'] or key in observations:fail('actual_observation_axis_unproven')
                    observations[key]=obs
            excluded={(v.get('processed_version_id'),v.get('barcode')) for v in plan.get('excluded_observations',[])}
            excluded_donors={v.get('donor') for v in plan.get('excluded_donors',[])}
            for side in ('numerator','denominator'):
                group=contrast.get(side,{})
                if group.get('label')!=request.get(side):fail('actual_fixed_object_control_mismatch')
                keys=[(v.get('processed_version_id'),v.get('barcode')) for v in group.get('observation_keys',[])]
                chosen=[observations[k] for k in keys if k in observations and k not in excluded and observations[k].get('donor') not in excluded_donors]
                if any(k not in observations for k in keys) or not chosen or any(o.get('retained') not in (True,'true','True','1',1) or o.get('condition')!=group.get('label') for o in chosen):fail('actual_condition_observations_unproven')
            if candidate.get('condition')!=contrast.get('numerator',{}).get('label'):fail('actual_candidate_condition_mismatch')
        if row.get('feature_id')!=candidate['object_id'] or any(row.get(k)!=request.get(k) for k in ('numerator','denominator')) or row.get('tested','').lower() not in ('true','1'):fail('fixed_result_object_control_mismatch')
        q=float(row['q_within_contrast']);effect=float(row['effect_value'])
        if not 0<=q<=request.get('q_threshold',.05) or candidate.get('expected_direction') not in ('up','down') or (effect>0)!= (candidate['expected_direction']=='up') or effect==0:fail('fixed_result_does_not_support_direction')
    except (KeyError,ValueError,TypeError,OSError):fail('fixed_result_row_required')
    return dict(supported=not reasons,reasons=reasons,run_id=meta.get('run_id'),result_source_id=request.get('result_source_id'),result_row_key=request.get('result_row_key'),material_source_ids=request.get('material_source_ids'),design_source_id=request.get('design_source_id'),overlap_audit_source_id=request.get('overlap_audit_source_id'))


def build_matrix(candidates,evidence_sources,support_requests,sources=None):
    sources=sources or evidence_sources;matrix=[];groups={};nodes=[];edges=[]
    # Same known cohort, study, datasets, donors, original bytes or dependency group merge.
    tokens={}
    for s in evidence_sources:
        e=s['metadata']['typed_evidence'];tokens[s['source_id']]=['group:'+e['dependency_group'],'study:'+e['study_id']]+['dataset:'+v for v in e.get('shared_dataset_ids',[])]+['donor:'+v for v in (e.get('shared_donor_ids') or [])]
        cohort=e.get('cohort_id')
        if isinstance(cohort,str) and cohort.strip() and cohort.strip().casefold()!='unknown':tokens[s['source_id']].append('cohort:'+cohort.strip())
        if s['metadata'].get('original_sha256'):tokens[s['source_id']].append('original:'+s['metadata']['original_sha256'])
    groups_of_ids=[]
    for sid,values in tokens.items():
        matching=[g for g in groups_of_ids if any(set(values)&set(tokens[i]) for i in g)]
        merged={sid}.union(*(set(g) for g in matching))
        groups_of_ids=[g for g in groups_of_ids if g not in matching]+[sorted(merged)]
    dependent=dict(groups=groups_of_ids,source_group={sid:hashlib.sha256(json.dumps(sorted(g)).encode()).hexdigest()[:16] for g in groups_of_ids for sid in g})
    for ids in dependent['groups']:
        key=dependent['source_group'][ids[0]];groups[key]=ids
        nodes.append(dict(id='group:'+key,kind='dependency_group',label=key,independence_verified=False))
    for s in evidence_sources:
        e=s['metadata']['typed_evidence'];sid=s['source_id'];nodes.append(dict(id='evidence:'+sid,kind='external_evidence',label=e['study_id']+' / '+e['evidence_type'],source_id=sid,sha256=s['sha256'],locators=e['locators'],biological_claim_status='source_reported'))
        edges.append(dict(source='group:'+dependent['source_group'][sid],target='evidence:'+sid,relation='dependent_source',directed=False))
    for c in candidates:
        nodes.append(dict(id='candidate:'+c['object_id'],kind='candidate',label=c['object_id'],source_id=c['source_id'],original_feature_id=c['feature_id']))
        for s in evidence_sources:
            e=s['metadata']['typed_evidence'];sid=s['source_id'];reason=None;status='unknown'
            matching=e['object_id']==c['object_id']
            if not matching:status='missing';reason='object_not_mentioned'
            elif c.get('species_taxon_id') is None or e.get('species_taxon_id') is None:reason='species_unknown'
            elif c['species_taxon_id']!=e['species_taxon_id']:status='not_applicable';reason='species_mismatch'
            elif not c.get('condition') or not e.get('condition'):reason='condition_unknown'
            elif c['condition']!=e['condition']:status='context';reason='condition_mismatch_no_generalization'
            elif e.get('disease_scope')=='descendant':status='context';reason='disease_descendant_not_direct'
            elif not s['metadata'].get('locator_verification',{}).get('locator_verified'):reason='original_locator_unverified'
            elif e.get('result_status')=='not_significant':status='not_significant';reason='not_significant_is_not_equivalence'
            elif e.get('result_status')=='unknown':reason='result_unknown'
            elif c.get('expected_direction') and e.get('effect_direction'):
                status='support' if c['expected_direction']==e['effect_direction'] else 'conflict'
            else:status='context';reason='source_statement_no_comparable_direction'
            request=next((r for r in support_requests if r['evidence_source_id']==sid and r['candidate_object_id']==c['object_id']),{})
            support=independent_support(c,e,request,sources) if matching else dict(supported=False,reasons=['object_not_mentioned'])
            row=dict(row_key=hashlib.sha256((c['object_id']+'\0'+sid).encode()).hexdigest(),feature_id=c['object_id'],original_feature_id=c['feature_id'],candidate_source_id=c['source_id'],source_id=sid,evidence_type=e['evidence_type'],status=status,reason=reason,source_group=dependent['source_group'][sid],dependency_group=e['dependency_group'],study_id=e['study_id'],cohort_id=e.get('cohort_id'),locators=e['locators'],source_statement=e['statement'] if matching else None,biological_claim_status='source_reported' if matching else 'unknown',human_review_status=e['human_review_status'],locator_verified=s['metadata'].get('locator_verification',{}).get('locator_verified',False),system_verified=False,independent_data_support=support['supported'],independence_check=support,evidence=e,candidate=c)
            matrix.append(row)
            edges.append(dict(source='evidence:'+sid,target='candidate:'+c['object_id'],relation=status,directed=False,row_key=row['row_key'],independent_data_support=support['supported']))
    rows=[]
    for c in candidates:
        subset=[r for r in matrix if r['feature_id']==c['object_id']]
        rows.append(dict(feature_id=c['object_id'],original_feature_id=c['feature_id'],candidate_source_id=c['source_id'],support_count=len({r['source_group'] for r in subset if r['status']=='support'}),conflict_count=len({r['source_group'] for r in subset if r['status']=='conflict'}),missing_count=sum(r['status']=='missing' for r in subset),context_count=sum(r['status']=='context' for r in subset),independent_support_count=sum(r['independent_data_support'] for r in subset),reference_version=c.get('reference_version'),reference_verified=False,score=None,provenance='source_linked_candidate',inference_scope='derived'))
    rows.sort(key=lambda r:(-r['support_count'],r['conflict_count'],r['feature_id']))
    for i,r in enumerate(rows,1):r.update(rank=i,row_key=hashlib.sha256(r['feature_id'].encode()).hexdigest())
    return dict(candidates=rows,matrix=matrix,dependency_groups=groups,nodes=nodes,edges=edges,independence_verified=False,missing_policy='unknown is not zero or negative; no real knockout unless an explicit source record exists')
