"""Offline ORA and one joint-null GSEApy prerank on explicit versioned resources."""
from collections import Counter,defaultdict
import hashlib
import json
import math
import numpy as np
import pandas as pd
from scipy.stats import hypergeom,false_discovery_control
from app.domain.bio_insights.contracts import OraConfig,GseaPrerankConfig
from .evidence import source_numeric,load_result,numeric
from .inputs import document,iter_table
from .mapping import ExplicitMapper,resource_document


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _source(sources,sid,kind):
    matches=[s for s in sources if s['source_id']==sid and s['source_kind']==kind]
    if len(matches)!=1:raise ValueError('enrichment_source_identity_invalid')
    return matches[0]


def _gene_ids(member):
    if member['format']=='json':
        data=document(member);values=data.get('feature_ids') if isinstance(data,dict) else data
        if not isinstance(values,list):raise ValueError('gene_list_invalid')
    else:
        values=[]
        for _,row in iter_table(member,format=member['format']):
            if 'feature_id' not in row:raise ValueError('gene_list_feature_column_required')
            values.append(row['feature_id'])
    if len(values)>1000000 or any(not isinstance(v,str) or not v for v in values):raise ValueError('gene_list_invalid')
    return values


def _map_set(values,mapper,context,mapping_rows,exclusions):
    result=set()
    for original in sorted(set(values)):
        target,reason=mapper.map_id(original)
        mapping_rows.append({**context,'original_id':original,'target_id':target,'reason':reason})
        if reason:exclusions.append({**context,'feature_id':original,'reason':reason})
        else:result.add(target)
    return result


def _resources(payload,config):
    for values in (config.resource_source_ids,config.mapping_source_ids):
        if len(values)!=len(set(values)):raise ValueError('duplicate_enrichment_resource_selection')
    resources=[]
    for sid in config.resource_source_ids:
        source=_source(payload['sources'],sid,'bio_resource_version');data=resource_document(source)
        if data['kind']!='gene_sets':raise ValueError('enrichment_gene_sets_required')
        if not isinstance(data.get('terms'),list) or len(data['terms'])>50000:raise ValueError('enrichment_resource_term_limit')
        term_ids=[t['term_id'] for t in data['terms']]
        if len(term_ids)!=len(set(term_ids)):raise ValueError('duplicate_resource_term_id')
        resources.append((source,data))
    maps=[_source(payload['sources'],sid,'bio_resource_version') for sid in config.mapping_source_ids]
    return resources,maps


def run_enrichment(payload,writer):
    if payload.get('schema_version')!=1 or payload.get('kind')!='bio_enrichment':raise ValueError('enrichment_payload_invalid')
    config_payload=payload['config']
    if config_payload.get('kind')=='ora':return _ora(payload,OraConfig.model_validate(config_payload),writer)
    if config_payload.get('kind')=='gsea_prerank':return _gsea(payload,GseaPrerankConfig.model_validate(config_payload),writer)
    raise ValueError('enrichment_kind_invalid')


def _ora(payload,config,writer):
    if len(config.result_source_ids)!=len(set(config.result_source_ids)) or len(config.contrast_ids)!=len(set(config.contrast_ids)):
        raise ValueError('duplicate_ora_result_or_contrast')
    resources,maps=_resources(payload,config)
    results=[load_result(_source(payload['sources'],sid,'bio_insight_result_version')) for sid in config.result_source_ids]
    rows=[];mapping_rows=[];exclusions=[];term_exclusions=[];sets=[];classifications=[];upstream=[];empty=0
    explicit_background=None
    if config.background_source_id:
        matches=[s for s in payload['sources'] if s['source_id']==config.background_source_id]
        if len(matches)!=1 or config.background_member_key not in matches[0]['members']:raise ValueError('explicit_background_source_invalid')
        explicit_background=_gene_ids(matches[0]['members'][config.background_member_key])
    explicit_foreground=None
    if config.foreground_member_key:
        matches=[s for s in payload['sources'] if config.foreground_member_key in s['members']]
        if len(matches)!=1:raise ValueError('explicit_foreground_source_ambiguous')
        explicit_foreground=_gene_ids(matches[0]['members'][config.foreground_member_key])
    family_members=defaultdict(list)
    for result in results:
        sid=result['source']['source_id']
        upstream.append({'result_source_id':sid,'inference_scope':result['inference_scope'],'methods':result['manifest'].get('methods',{}),
                         'source_sha256':result['source']['sha256'],'species_taxon_id':result['species_taxon_id'],
                         'namespace':result['namespace'],'reference_version':result['reference_version']})
        for cid in config.contrast_ids:
            contrast=[row for row in result['rows'] if row['contrast_id']==cid]
            if not contrast:raise ValueError('selected_contrast_missing')
            tested=[row for row in contrast if row['tested']]
            if explicit_background is None:
                if not result['tested_universe_complete']:raise ValueError('complete_background_required_for_top_table')
                background=[row['feature_id'] for row in tested]
            else:background=explicit_background
            if not background:raise ValueError('empty_background')
            foreground=[]
            if explicit_foreground is not None:foreground=explicit_foreground
            else:
                for row in tested:
                    q=source_numeric(result['source'],row.get(config.q_column));effect=source_numeric(result['source'],row.get('effect_value'))
                    if q is not None and not 0<=q<=1:raise ValueError('source_q_out_of_range')
                    if q is None or effect is None:
                        exclusions.append({'result_source_id':sid,'contrast_id':cid,'resource_id':'','feature_id':row['feature_id'],
                                           'reason':'missing_selected_q_or_effect'})
                        continue
                    direction=config.direction=='both' or config.direction=='up' and effect>0 or config.direction=='down' and effect<0
                    if q<=config.q_threshold and abs(effect)>=config.minimum_absolute_effect and direction:foreground.append(row['feature_id'])
            for source,data in resources:
                rid=source['source_id'];context={'result_source_id':sid,'contrast_id':cid,'resource_id':rid}
                mapper=ExplicitMapper(result['species_taxon_id'],result['namespace'],data['species_taxon_id'],data['namespace'],maps)
                bg=_map_set(background,mapper,context,mapping_rows,exclusions)
                fg=_map_set(foreground,mapper,context,mapping_rows,exclusions)
                if not bg:raise ValueError('empty_mapped_background')
                if not fg<=bg:raise ValueError('foreground_must_be_background_subset')
                if not fg:empty+=1
                family_id=_hash({'result':sid,'contrast':cid,'direction':config.direction,
                                 'collections':config.resource_source_ids if config.merge_collections else [rid]})
                N,n=len(bg),len(fg)
                set_record={**context,'family_id':family_id,'direction':config.direction,'background':sorted(bg),'foreground':sorted(fg),
                            'mapping':mapper.identity(),'N':N,'n':n,'term_hits':[]}
                categories=defaultdict(set)
                for term in data['terms']:
                    members=set(term['genes'])&bg;K=len(members);hits=sorted(members&fg);k=len(hits)
                    if not config.min_size<=K<=config.max_size:
                        term_exclusions.append({**context,'term_id':term['term_id'],'background_size':K,
                                                'reason':'zero_background_overlap' if K==0 else 'term_background_size_outside_bounds'})
                        continue
                    p=float(hypergeom.sf(k-1,N,K,n)) if n else 1.
                    row_key=_hash({**context,'term_id':term['term_id'],'direction':config.direction})
                    row={'row_key':row_key,**context,'term_id':term['term_id'],'collection_term_id':rid+'::'+term['term_id'],
                         'term_name':term.get('name',term['term_id']),'namespace':term.get('namespace','unknown'),
                         'resource_release':data['release'],'resource_sha256':source['sha256'],'direction':config.direction,
                         'family_id':family_id,'N':N,'n':n,'K':K,'k':k,'GeneRatio':f'{k}/{n}','BgRatio':f'{K}/{N}',
                         'gene_ratio':k/n if n else None,'background_ratio':K/N,'enrichment_ratio':(k/n)/(K/N) if n else None,
                         'p_value':p,'q_value':None,'hits':hits,'reason':'empty_foreground' if n==0 else None,
                         'source_q_column':config.q_column,'source_inference_scope':result['inference_scope'],
                         'method':'hypergeometric_right_tail','p_value_underflow':p==0}
                    rows.append(row);family_members[family_id].append(row)
                    set_record['term_hits'].append({'row_key':row_key,'term_id':term['term_id'],'hits':hits})
                    categories[term.get('namespace','unknown')].update(members)
                    for subset in term.get('subsets',[]):categories['subset:'+subset].update(members)
                for category,genes in sorted(categories.items()):
                    classifications.append({**context,'category':category,'background_gene_count':len(genes),
                                            'foreground_gene_count':len(genes&fg),'mutually_exclusive':False})
                sets.append(set_record)
    if len(rows)>500000:raise ValueError('ora_result_budget_exceeded')
    families={}
    for family,items in family_members.items():
        q=false_discovery_control([r['p_value'] for r in items],method='bh')
        for row,value in zip(items,q):row['q_value']=float(value)
        families[family]={'family_size':len(items),'collections':sorted({r['resource_id'] for r in items}),
                          'contrast_ids':sorted({r['contrast_id'] for r in items}),'direction':config.direction}
    fields=list(rows[0]) if rows else ['row_key','result_source_id','contrast_id','resource_id','term_id','term_name','N','n','K','k','p_value','q_value','reason']
    writer.table('enrichment_results',rows,fields);writer.json('ora_sets',{'schema_version':1,'families':sets})
    _mapping_outputs(writer,mapping_rows,exclusions,term_exclusions,classifications)
    methods={'name':'ORA_hypergeometric_right_tail','correction':'BH_contrast_direction_collection',
             'merge_collections':config.merge_collections,'family':families,'q_column':config.q_column,
             'q_threshold':config.q_threshold,'minimum_absolute_effect':config.minimum_absolute_effect,
             'direction':config.direction,'min_size':config.min_size,'max_size':config.max_size,
             'background':'explicit_fixed_file' if explicit_background is not None else 'complete_predeclared_tested_gene_universe',
             'many_to_one_mapping':'deduplicate_target_genes_with_original_mapping_rows','upstream':upstream,
             'resources':[_resource_identity(s,d) for s,d in resources],
             'classification_counts_mutually_exclusive':False,'mapping_excluded_count':len(exclusions)}
    return {'summary':{'row_count':len(rows),'empty_foregrounds':empty,'eligible_term_family_complete':True,
                       'significant_terms':sum(r['q_value']<=.05 for r in rows),'result_member_key':'enrichment_results',
                       'family':families,'excluded_terms':len(term_exclusions)},
            'methods':methods,'inference_scope':'derived','provenance':{'system_computed':True,'upstream':upstream,
                       'resources':methods['resources'],'mapping_sources':[s['source_id'] for s in maps]}}


def _resource_identity(source,data):
    return {'resource_id':source['source_id'],'sha256':source['sha256'],'kind':data['kind'],'species_taxon_id':data['species_taxon_id'],
            'namespace':data['namespace'],'release':data['release'],'usage':data['usage'],'source':data.get('source')}


def _mapping_outputs(writer,mapping_rows,exclusions,term_exclusions,classifications):
    writer.table('mapping_rows',mapping_rows,['result_source_id','contrast_id','resource_id','original_id','target_id','reason'])
    writer.table('mapping_exclusions',exclusions,['result_source_id','contrast_id','resource_id','feature_id','reason'])
    writer.table('term_exclusions',term_exclusions,['result_source_id','contrast_id','resource_id','term_id','background_size','reason'])
    writer.table('functional_classification',classifications,
                 ['result_source_id','contrast_id','resource_id','category','background_gene_count','foreground_gene_count','mutually_exclusive'])


def _gsea(payload,config,writer):
    import gseapy
    resources,maps=_resources(payload,config)
    result=load_result(_source(payload['sources'],config.result_source_id,'bio_insight_result_version'))
    if not result['tested_universe_complete']:raise ValueError('complete_ranking_required_top_table_forbidden')
    if config.ranking_column not in {'statistic','wald_statistic','effect_value'}:raise ValueError('explicit_signed_statistic_required')
    selected=[r for r in result['rows'] if r['contrast_id']==config.contrast_id and r['tested']]
    if not selected:raise ValueError('ranking_contrast_empty')
    if len(selected)>100000:raise ValueError('ranking_gene_budget_exceeded')
    # A joint null needs one common namespace and one frozen ranked vector.
    targets={(d['species_taxon_id'],d['namespace']) for _,d in resources}
    if len(targets)!=1:raise ValueError('joint_gsea_requires_common_target_namespace')
    taxon,target_namespace=next(iter(targets))
    mapper=ExplicitMapper(result['species_taxon_id'],result['namespace'],taxon,target_namespace,maps)
    mapping_rows=[];exclusions=[];term_exclusions=[];classifications=[];mapped=defaultdict(list)
    context={'result_source_id':result['source']['source_id'],'contrast_id':config.contrast_id,'resource_id':'joint'}
    for row in selected:
        original=row['feature_id'];score=numeric(row.get(config.ranking_column))
        target,reason=mapper.map_id(original)
        if score is None:reason='ranking_value_missing'
        mapping_rows.append({**context,'original_id':original,'target_id':target,'reason':reason})
        if reason:exclusions.append({**context,'feature_id':original,'reason':reason})
        else:mapped[target].append((row,score))
    ranking=[]
    for target,items in sorted(mapped.items()):
        if len(items)!=1:
            for row,_ in items:exclusions.append({**context,'feature_id':row['feature_id'],'reason':'many_to_one_ranking_conflict'})
        else:
            row,score=items[0];ranking.append({'feature_id':target,'statistic':score,'source_feature_id':row['feature_id'],'source_row_key':row['row_key']})
    ranking.sort(key=lambda r:(-r['statistic'],r['feature_id']))
    if len(ranking)<2 or not any(r['statistic']!=0 for r in ranking):raise ValueError('ranking_all_zero_or_insufficient')
    for i,row in enumerate(ranking):row['rank']=i
    genes=[r['feature_id'] for r in ranking];scores=[r['statistic'] for r in ranking];gene_set=set(genes)
    score_by_gene=dict(zip(genes,scores))
    terms={};term_metadata={};n_memberships=0
    for source,data in resources:
        rid=source['source_id'];categories=defaultdict(set)
        for term in data['terms']:
            members=sorted(set(term['genes'])&gene_set);K=len(members)
            if not config.min_size<=K<=config.max_size or K==len(genes):
                term_exclusions.append({'result_source_id':result['source']['source_id'],'contrast_id':config.contrast_id,
                    'resource_id':rid,'term_id':term['term_id'],'background_size':K,'reason':'term_rank_size_outside_bounds'})
                continue
            if config.weight>0 and not any(score_by_gene[gene]!=0 for gene in members):
                raise ValueError('gsea_term_zero_weight:'+rid+'::'+term['term_id'])
            key=rid+'::'+term['term_id']
            if key in terms:raise ValueError('collection_term_id_collision')
            terms[key]=members;term_metadata[key]=(source,data,term);n_memberships+=K
            categories[term.get('namespace','unknown')].update(members)
            for subset in term.get('subsets',[]):categories['subset:'+subset].update(members)
        for category,members in sorted(categories.items()):
            classifications.append({'result_source_id':result['source']['source_id'],'contrast_id':config.contrast_id,
                                    'resource_id':rid,'category':category,'background_gene_count':len(members),
                                    'foreground_gene_count':None,'mutually_exclusive':False})
    if len(terms)>10000:raise ValueError('gsea_eligible_set_budget_exceeded')
    # Keep the existing conservative transient-curve admission budget. Native
    # summaries still own all curves; only one term is materialized in Python.
    estimate=256*1024**2+len(genes)*len(terms)*40+len(terms)*config.permutation_num*16
    work=(len(genes)+n_memberships)*config.permutation_num
    if estimate>1536*1024**2 or work>2000000000:raise ValueError('gsea_resource_budget_exceeded')
    result_rows=[];curves=[]
    if terms:
        # This is exactly the locked GSEApy 1.3.1 Prerank.run permutation
        # entrypoint. One complete family is fitted together; native summaries
        # retain the joint null/curves. Avoid to_df(), which additionally keeps
        # every full running curve as Python float lists in public .results.
        from gseapy.gse import prerank_rs
        summaries=prerank_rs(genes,scores,terms,config.weight,config.min_size,config.max_size,
            config.permutation_num,1,config.seed).summaries
        if len(summaries)!=len(terms) or {s.term for s in summaries}!=set(terms):raise ValueError('gsea_eligible_family_incomplete')
        for observed in sorted(summaries,key=lambda s:s.term):
            key=observed.term;source,data,term=term_metadata[key]
            es,nes,p,fdr,fwer=[numeric(getattr(observed,name)) for name in ['es','nes','pval','fdr','fwerp']]
            hits=list(map(int,observed.hits));res=np.asarray(observed.run_es,dtype=float)
            if res.shape!=(len(genes),) or not np.isfinite(res).all():raise ValueError('gsea_curve_invalid')
            if any(not 0<=i<len(genes) for i in hits):raise ValueError('gsea_hit_index_invalid')
            peak=int(np.argmax(res) if es>=0 else np.argmin(res))
            leading=[genes[i] for i in hits if i<=peak] if es>=0 else [genes[i] for i in hits if i>=peak]
            row_key=_hash({'result':result['source']['source_id'],'contrast':config.contrast_id,'resource':source['source_id'],'term':term['term_id']})
            row={'row_key':row_key,'result_source_id':result['source']['source_id'],'contrast_id':config.contrast_id,
                 'resource_id':source['source_id'],'term_id':term['term_id'],'collection_term_id':key,
                 'term_name':term.get('name',term['term_id']),'namespace':term.get('namespace','unknown'),
                 'resource_release':data['release'],'resource_sha256':source['sha256'],'es':es,'nes':nes,
                 'nominal_p_value':p,'fdr_q_value':fdr,'fwer_p_value':fwer,'q_value':None,
                 'set_size':len(terms[key]),'ranking_size':len(genes),'leading_edge':leading,'hit_indices':hits,
                 'source_inference_scope':result['inference_scope'],'method':'GSEApy_prerank_permutation',
                 'permutation_num':config.permutation_num,'p_zero_resolution_note':'zero empirical count; nominal resolution 1/permutation_num' if p==0 else None}
            result_rows.append(row)
            curves.append({k:row[k] for k in ['row_key','resource_id','term_id','es','nes','nominal_p_value','fdr_q_value','fwer_p_value','leading_edge','hit_indices']}|{'weight':config.weight})
    writer.table('enrichment_results',result_rows,list(result_rows[0]) if result_rows else ['row_key','resource_id','term_id','es','nes','nominal_p_value','fdr_q_value','fwer_p_value','reason'])
    writer.table('gsea_ranking',ranking,['rank','feature_id','statistic','source_feature_id','source_row_key'])
    writer.json('gsea_curves',{'schema_version':1,'rank_member_key':'gsea_ranking','rank_zero_based':True,'terms':curves})
    _mapping_outputs(writer,mapping_rows,exclusions,term_exclusions,classifications)
    tied=1-len(set(scores))/len(scores)
    methods={'name':'GSEApy_1.3.1_prerank','method':'permutation','native_entrypoint':'gseapy.gse.prerank_rs',
             'running_curve_materialization':'one_term_at_a_time_from_complete_native_family','correction':'GSEA_joint_null_FDR_not_BH',
             'permutation_num':config.permutation_num,'weight':config.weight,'min_size':config.min_size,'max_size':config.max_size,
             'threads':1,'seed':config.seed,'ascending':None,'no_plot':True,'ranking_column':config.ranking_column,
             'ranking_order':'statistic_descending_stable_id_ascending','tied_rank_fraction':tied,
             'tied_rank_fraction_definition':'1 - number_unique_scores / ranking_size','complete_input_universe':True,
             'mapping':mapper.identity(),'many_to_one_mapping':'exclude_all_conflicting_target_ranks',
             'eligible_collections_joint_null':config.resource_source_ids,'estimated_working_bytes':estimate,'estimated_work_units':work,
             'resources':[_resource_identity(s,d) for s,d in resources],'upstream_inference_scope':result['inference_scope'],
             'upstream_methods':result['manifest'].get('methods',{}),'exclusions':len(exclusions),
             'zero_empirical_p_note':'Preserved as zero; not evidence of infinite significance.'}
    return {'summary':{'row_count':len(result_rows),'ranking_size':len(ranking),'eligible_set_count':len(terms),
                       'eligible_term_family_complete':True,'empty_eligible_sets':not bool(terms),
                       'result_member_key':'enrichment_results','excluded_terms':len(term_exclusions)},
            'methods':methods,'inference_scope':'derived','provenance':{'system_computed':True,
                       'result_source_id':result['source']['source_id'],'source_sha256':result['source']['sha256'],
                       'upstream_inference_scope':result['inference_scope'],'resources':methods['resources'],
                       'species_taxon_id':result['species_taxon_id'],'source_namespace':result['namespace'],
                       'target_namespace':target_namespace,'reference_version':result['reference_version']}}
