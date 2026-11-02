"""Finite declared cross-layer associations and complete lineage exports."""
from collections import Counter
import hashlib,json,math
import numpy as np
from .inputs import document,read_array,iter_table
from .evidence import source_numeric,true
from .candidates import dependency_groups
from .comparison import adjust_families
from app.domain.correlation.kernel import compute_correlation,CorrelationError
from app.domain.bio_insights.integration_contracts import IntegrationConfig,normalize_correspondence,SAMPLE_COLUMNS,OBJECT_COLUMNS
from app.domain.bio_insights.integration_matching import match_samples,object_decision

def key(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def write_table(writer,name,rows,columns):
    for i,r in enumerate(rows):r['row_key']=key([name,i,{k:v for k,v in r.items() if k!='row_key'}])
    writer.table(name,rows,list(dict.fromkeys(['row_key']+list(columns)+sorted({k for r in rows for k in r}))))

def run_correspondence_import(payload,writer):
    c=payload['config'];spec=c['files'][0];source=next(s for s in payload['sources'] if s['source_id']==spec['file_id']);member=source['members']['original_file']
    if spec['sha256']!=member['sha256']:raise ValueError('correspondence_sha_changed')
    rows=normalize_correspondence(c['kind'],[r for _,r in iter_table(member,format='tsv')])
    data={k:c[k] for k in ('kind','species_taxon_id','namespace','release','source','usage')}
    data.update(rows=rows,input_files=[{k:spec[k] for k in ('file_id','sha256','format','role')}],stats={'row_count':len(rows)})
    write_table(writer,'correspondence_rows',rows,SAMPLE_COLUMNS if c['kind']=='sample_correspondence' else OBJECT_COLUMNS);writer.json('resource',data)
    return dict(summary=data['stats'],methods=dict(resource_kind=c['kind'],source=c['source'],usage=c['usage'],input_files=data['input_files'],matching='explicit declarations only; duplicates and ambiguity retained'),inference_scope='derived',provenance='system_computed')

def load_layer(source,layer):
    m=source['members'];manifest=document(m['manifest'])
    if manifest.get('schema_version')!=2 or manifest.get('observation_level')!='sample':raise ValueError('integration_requires_saved_sample_layer')
    samples=[r['sample_id'] for _,r in iter_table(m['samples'],format='tsv')]
    features=[r['feature_id'] for _,r in iter_table(m['features'],format='tsv')]
    om=read_array(m['observation_mask']);fm=read_array(m['feature_mask'])
    if om.dtype.kind!='b' or fm.dtype.kind!='b' or om.shape!=(len(samples),) or fm.shape!=(len(features),):raise ValueError('integration_layer_axes_invalid')
    samples=[v for v,keep in zip(samples,om) if keep];features=[v for v,keep in zip(features,fm) if keep]
    values=read_array(m[layer+'_values']);missing=read_array(m[layer+'_missing'])
    if len(samples)!=len(set(samples)) or len(features)!=len(set(features)) or values.shape!=(len(samples),len(features)) or missing.shape!=values.shape or missing.dtype.kind!='b':raise ValueError('integration_layer_shape_invalid')
    descriptor=manifest['layers'][layer]
    if source['metadata'].get('layers',{}).get(layer)!=descriptor:raise ValueError('integration_layer_scale_changed')
    return dict(samples=samples,features=features,values=values,missing=missing,layer=descriptor)

def correlate_pairs(inputs,*,method,inference):
    rows=[]
    for entry in inputs:
        r={k:v for k,v in entry.items() if k!='values'}
        r.update(matched_observation_count=len(entry['values']),independent_n=len(entry['values']) if inference else None,coefficient=None,p_value=None,q_value=None,reason=entry.get('reason'),p_method=None,confidence_interval=None,inference=None)
        if not r['reason']:
            try:
                value=compute_correlation(entry['values'],method=method,mode='pair' if inference else 'matrix',seed=1729)
                r.update(coefficient=value['coefficient'] if inference else value['matrix'][0][1],p_value=value['p_value']['value'],p_method=value['p_value']['method'],confidence_interval=value['confidence_interval'],inference=value['inference'],reason=None if inference else 'descriptive_independent_units_unverified')
            except CorrelationError as error:r['reason']=error.code
        rows.append(r)
    family=[dict(contrast_id='integration',tested=True,p_value=r['p_value']) for r in rows]
    if inference and any(r['p_value'] is not None for r in rows):
        adjust_families(family,['integration'])
        for r,f in zip(rows,family):r['q_value']=f['q_global_family']
    return rows

def classify_concordance(left_effect,right_effect,left_q,right_q,*,alignment='same',comparable=True,threshold=.05,minimum=0.):
    if not comparable or alignment=='incomparable':return 'incomparable'
    if any(v is None for v in (left_effect,right_effect,left_q,right_q)):return 'unknown'
    if left_q>threshold or right_q>threshold or abs(left_effect)<minimum or abs(right_effect)<minimum:return 'below_threshold'
    if not left_effect or not right_effect:return 'unknown'
    return 'support' if left_effect*right_effect*(-1 if alignment=='reverse' else 1)>0 else 'conflict'

def saved_pathway_members(source,row,ranking):
    if row is None:return [],[]
    ora=source['metadata']['kind']=='ora';field='hits' if ora else 'hit_indices'
    members=[];locators=[];leading=set(json.loads(row.get('leading_edge') or '[]'))
    for index,value in enumerate(json.loads(row.get(field) or '[]')):
        locator=dict(source_id=source['source_id'],member_key='enrichment_results',row_key=row['row_key'],field=field,element_index=index,membership_semantics='ora_foreground_hit' if ora else 'gsea_ranked_set_member')
        if ora:fid=value
        else:
            number,ranked=ranking[int(value)];fid=ranked['feature_id']
            locator.update(is_leading_edge=fid in leading,ranking_locator=dict(source_id=source['source_id'],member_key='gsea_ranking',row_number=number,rank=int(ranked['rank']),feature_id=fid,source_feature_id=ranked['source_feature_id'],source_row_key=ranked['source_row_key']))
        members.append(fid);locators.append(locator)
    return members,locators

def concordance_rows(config,sources,groups):
    out=[]
    for c in config.concordances:
        a=sources[c.left_result_source_id];b=sources[c.right_result_source_id]
        kinds=[s['metadata'].get('kind') for s in (a,b)];pathway=all(k in ('ora','gsea_prerank') for k in kinds)
        for s in (a,b):
            summary=s['metadata'].get('summary_json') or (document(s['members']['manifest']).get('summary',{}) if 'manifest' in s['members'] else {})
            if summary.get('eligible_term_family_complete' if pathway else 'tested_universe_complete') is not True:raise ValueError('concordance_requires_complete_saved_universe')
        member='enrichment_results' if pathway else 'comparison_results'
        if any(member not in s['members'] for s in (a,b)):raise ValueError('concordance_requires_complete_saved_results')
        tables=[];saved_rankings={}
        for s,cid in [(a,c.left_contrast_id),(b,c.right_contrast_id)]:
            records=[r for _,r in iter_table(s['members'][member],format='tsv') if r.get('contrast_id')==cid]
            axis='term_id' if pathway else 'feature_id';counts=Counter(r[axis] for r in records)
            tables.append({r[axis]:r for r in records if counts[r[axis]]==1})
            if pathway and s['metadata']['kind']=='gsea_prerank':saved_rankings[s['source_id']]={int(r['rank']):(number,r) for number,r in iter_table(s['members']['gsea_ranking'],format='tsv')}
        meta=[s['metadata'] for s in (a,b)]
        comparable=all(meta[0].get(k) is not None and meta[0].get(k)==meta[1].get(k) for k in ('species_taxon_id','namespace','reference_version'))
        if pathway:
            # Ordinary ORA is unsigned. GSEA requires the same frozen collection/background definition.
            comparable=comparable and kinds==['gsea_prerank','gsea_prerank']
            ma=document(a['members']['methods']);mb=document(b['members']['methods'])
            comparable=comparable and bool(ma.get('resources')) and ma.get('resources')==mb.get('resources')
            if comparable:
                rankings=[{r['feature_id'] for _,r in saved_rankings[s['source_id']].values()} for s in (a,b)]
                comparable=rankings[0]==rankings[1]
        for fid in c.object_ids:
            l=tables[0].get(fid);r=tables[1].get(fid)
            ef='nes' if pathway else 'effect_value'
            def number(s,row,col):return source_numeric(s,row.get(col)) if row else None
            le=number(a,l,ef);re=number(b,r,ef);lq=number(a,l,c.q_column);rq=number(b,r,c.q_column)
            if l and not pathway and not true(l.get('tested','false')):le=None
            if r and not pathway and not true(r.get('tested','false')):re=None
            status=classify_concordance(le,re,lq,rq,alignment=c.direction_alignment,comparable=comparable,threshold=c.q_threshold,minimum=c.minimum_absolute_effect)
            lm,ll=saved_pathway_members(a,l,saved_rankings.get(a['source_id'],{})) if pathway else ([],[])
            rm,rl=saved_pathway_members(b,r,saved_rankings.get(b['source_id'],{})) if pathway else ([],[])
            out.append(dict(concordance_id=c.concordance_id,object_id=fid,object_kind='pathway' if pathway else 'feature',status=status,left_effect=le,right_effect=re,left_q=lq,right_q=rq,left_source_id=c.left_result_source_id,right_source_id=c.right_result_source_id,left_row_key=l.get('row_key') if l else None,right_row_key=r.get('row_key') if r else None,member_key=member,left_members=lm,right_members=rm,left_member_locators=ll,right_member_locators=rl,direction_alignment=c.direction_alignment,comparison_basis=c.comparison_basis,left_numerator=l.get('numerator') if l else None,left_denominator=l.get('denominator') if l else None,right_numerator=r.get('numerator') if r else None,right_denominator=r.get('denominator') if r else None,left_effect_unit=l.get('effect_unit') if l else None,right_effect_unit=r.get('effect_unit') if r else None,dependency_group_count=len({groups['source_group'][c.left_result_source_id],groups['source_group'][c.right_result_source_id]}),independent_support=False,reason='ordinary_ORA_unsigned' if 'ora' in kinds else 'not_significant_is_not_equivalence' if status=='below_threshold' else 'no_effect_unit_addition'))
    return out

def run_integration(payload,writer):
    config=IntegrationConfig.model_validate(payload['config']);sources={s['source_id']:s for s in payload['sources']}
    if not config.mapping_confirmed:raise ValueError('mapping_confirmation_required')
    if len(sources)>10:raise ValueError('integration_source_limit')
    layers={sid:load_layer(sources[sid],config.analysis_layer) for sid in config.processed_source_ids}
    sample_rows=[];object_rows=[]
    for sid,kind in [(config.sample_mapping_source_id,'sample_correspondence'),(config.object_mapping_source_id,'object_correspondence')]:
        if sid:
            resource=document(sources[sid]['members']['resource'])
            if resource['kind']!=kind:raise ValueError('correspondence_resource_kind_mismatch')
            if kind=='sample_correspondence':sample_rows=resource['rows']
            else:object_rows=resource['rows']
    canonical={sid:s['metadata'].get('canonical_dataset_ids') or ([s['metadata']['canonical_dataset_id']] if s['metadata'].get('canonical_dataset_id') else []) for sid,s in sources.items() if s['source_kind'] in ('bio_processed_dataset_version','bio_insight_result_version')}
    groups=dependency_groups(canonical);inputs=[];audit=[];input_rows=[];mapping=[]
    for p in config.pairs:
        a,b=layers[p.left_source_id],layers[p.right_source_id]
        mapped,reason=object_decision(object_rows,p,sources[p.left_source_id]['metadata'],sources[p.right_source_id]['metadata'],inference=config.mode=='inference')
        mapping.append(dict(pair_id=p.pair_id,mapping=mapped,reason=reason))
        matches,ledger=match_samples(sample_rows,p.left_source_id,p.right_source_id,a['samples'],b['samples'],inference=config.mode=='inference')
        if not config.partial_subset_confirmed and any(not r['included'] for r in ledger):raise ValueError('partial_matching_requires_subset_confirmation')
        if config.mode=='inference' and any(r['reason'] in ('independent_unit_unverified','repeated_donor_requires_frozen_selection') for r in ledger):raise ValueError('independent_units_not_resolved')
        audit.extend(dict(pair_id=p.pair_id,**r) for r in ledger)
        values=[];included=[];excluded=[]
        if p.left_feature_id not in a['features'] or p.right_feature_id not in b['features']:reason=reason or 'feature_not_retained'
        for match in matches:
            value=None;why=reason
            if not why:
                i,j=a['samples'].index(match['left_observation_id']),b['samples'].index(match['right_observation_id']);x,y=a['features'].index(p.left_feature_id),b['features'].index(p.right_feature_id)
                if a['missing'][i,x] or b['missing'][j,y]:why='missing_value'
                elif not np.isfinite([a['values'][i,x],b['values'][j,y]]).all():why='nonfinite_value'
                else:value=[float(a['values'][i,x]),float(b['values'][j,y])]
            input_rows.append(dict(pair_id=p.pair_id,**match,left_value=value[0] if value else None,right_value=value[1] if value else None,included=value is not None,reason=why or 'included'))
            identity={k:match[k] for k in ('match_group','left_observation_id','right_observation_id','donor_id')}
            if value is not None:values.append(value);included.append(identity)
            else:excluded.append(dict(**identity,reason=why))
        excluded.extend({k:r.get(k) for k in ('dataset_version','observation_id','match_group','reason')} for r in ledger if not r['included'])
        inputs.append(dict(**p.model_dump(),values=values,included=included,excluded=excluded,reason=reason,method=config.method,left_layer=a['layer'],right_layer=b['layer']))
    correlations=correlate_pairs(inputs,method=config.method,inference=config.mode=='inference')
    concordances=concordance_rows(config,sources,groups)
    nodes={};edges=[]
    def node(identifier,kind,label,source_id,locator=None):nodes.setdefault(identifier,dict(node_id=identifier,node_type=kind,label=label,source_id=source_id,locator=locator,verification_status='frozen_source'))
    def edge(a,b,kind,weight=None,locator=None,directed=False):edges.append(dict(edge_id=key([a,b,kind,locator]),source_node_id=a,target_node_id=b,edge_type=kind,weight=weight,weight_meaning='correlation_coefficient' if kind=='correlation' else 'not_a_statistical_weight',directed=directed,locator=locator,verification_status='system_computed' if kind=='correlation' else 'source_declared'))
    for sid,s in sources.items():
        node('source:'+sid,'source',sid,sid)
        for lineage in canonical.get(sid,[]):
            node('lineage:'+lineage,'canonical_lineage',lineage,sid);edge('lineage:'+lineage,'source:'+sid,'processing_lineage',locator={'source_id':sid,'sha256':s['sha256']},directed=True)
    operation='operation:'+payload['identity']['plan_version_id']
    node(operation,'processing_operation','Frozen integration',payload['identity']['plan_version_id'])
    for sid in sources:edge('source:'+sid,operation,'integration_input',locator={'source_id':sid,'sha256':sources[sid]['sha256']},directed=True)
    for r in correlations:
        output_node='association:'+r['pair_id'];node(output_node,'processing_output',r['pair_id'],payload['identity']['plan_version_id'],{'member_key':'integration_correlations','pair_id':r['pair_id']})
        edge(operation,output_node,'computed_relation',locator={'member_key':'integration_correlations','pair_id':r['pair_id']},directed=True)
        ends=[]
        for side in ('left','right'):
            sid=r[side+'_source_id'];fid=r[side+'_feature_id'];identifier='object:'+sid+':'+fid;node(identifier,'feature',fid,sid);edge('source:'+sid,identifier,'contains',locator={'source_id':sid,'feature_id':fid},directed=True);ends.append(identifier)
        edge(*ends,'object_mapping',locator={'resource_id':config.object_mapping_source_id,'pair_id':r['pair_id']})
        if r['coefficient'] is not None:edge(*ends,'correlation',r['coefficient'],{'member_key':'integration_correlations','pair_id':r['pair_id']})
    for mapping_row in object_rows:
        ends=[]
        for prefix in ('source','target'):
            sid=mapping_row[prefix+'_dataset_version'];fid=mapping_row[prefix+'_id'];identifier='object:'+sid+':'+fid
            node(identifier,'feature',fid,sid);ends.append(identifier)
        edge(*ends,'declared_mapping_'+mapping_row['decision'],locator={'resource_id':config.object_mapping_source_id,'row_number':mapping_row['row_number'],'basis':mapping_row['basis'],'ambiguity':mapping_row['ambiguity']})
    for r in concordances:
        ends=[]
        for side in ('left','right'):
            sid=r[side+'_source_id'];identifier='object:'+sid+':'+r['object_id'];node(identifier,r['object_kind'],r['object_id'],sid);ends.append(identifier)
            edge('source:'+sid,identifier,'contains',locator={'source_id':sid,'member_key':r['member_key'],'row_key':r[side+'_row_key']},directed=True)
            for fid,locator in zip(r[side+'_members'],r[side+'_member_locators']):
                member_node='object:'+sid+':'+fid;node(member_node,'feature',fid,sid,locator)
                edge(identifier,member_node,'saved_pathway_member',locator=locator)
        edge(*ends,'concordance_'+r['status'],locator={'member_key':'integration_concordance','concordance_id':r['concordance_id'],'object_id':r['object_id']})
    edges=list({e['edge_id']:e for e in edges}.values())
    data=dict(correlations=correlations,concordances=concordances,sample_audit=audit,object_audit=mapping,input_rows=input_rows,nodes=list(nodes.values()),edges=edges,dependency_groups=groups,layout_seed=1729)
    for name,rows,cols in [('integration_correlations',correlations,['pair_id','coefficient','p_value','q_value','matched_observation_count','independent_n','reason']),('integration_concordance',concordances,['concordance_id','object_id','status']),('integration_sample_audit',audit,['pair_id','dataset_version','observation_id','included','reason']),('integration_object_audit',mapping,['pair_id','mapping','reason']),('integration_input_rows',input_rows,['pair_id','match_group','left_value','right_value','included','reason']),('integration_nodes',data['nodes'],['node_id','node_type','label','source_id','locator']),('integration_edges',edges,['edge_id','source_node_id','target_node_id','edge_type','weight','directed','locator'])]:write_table(writer,name,rows,cols)
    writer.json('integration_data',data)
    summary=dict(pair_count=len(correlations),computed_pair_count=sum(r['coefficient'] is not None for r in correlations),concordance_count=len(concordances),matched_observation_count=max((r['matched_observation_count'] for r in correlations),default=0),independent_n=max((r['independent_n'] or 0 for r in correlations),default=0) if config.mode=='inference' else None,node_count=len(nodes),edge_count=len(edges),mode=config.mode)
    methods=dict(recipe=config.model_dump(mode='json'),family=[r['pair_id'] for r in correlations],family_size=len(correlations),na_policy='predeclared NA tests use 1 internally in BH; output NA remains NA',correlation_kernel='fixed existing kernel; average ranks; n<=7 exact; 8..500 9999 permutations seed1729; >500 asymptotic; no Spearman CI',inference='descriptive_coefficients_only_no_inferential_calls' if config.mode=='descriptive' else 'explicit_verified_unique_donor_units',transform='none; frozen processed scales retained',dependency_groups=groups,independent_support=False,concordance='full saved tables; no effect-unit addition; unsigned ORA incomparable; non-significance is not equivalence',graph='correlation is undirected, not causation; processing arrows express provenance only',layout_seed=1729)
    return dict(summary=summary,methods=methods,inference_scope='derived',provenance='system_computed')
