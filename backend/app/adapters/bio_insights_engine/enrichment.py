"""Offline ORA and one joint-null GSEApy prerank on explicit versioned resources."""
from collections import defaultdict
import hashlib
import json
import numpy as np
from scipy.stats import hypergeom,false_discovery_control
from app.domain.bio_insights.contracts import OraConfig,GseaPrerankConfig
from .bulk_enrichment import (
    BULK_MAPPING_FIELDS, bulk_mapper, bulk_ranking, bulk_resource_references, bulk_result_status,
    gene_set_universe, load_bulk_result, map_ora_selection, ora_selection, ora_skip_reason,
)
from .evidence import source_numeric,load_result,numeric
from .inputs import document,iter_table
from .mapping import ExplicitMapper,resource_document


_GSEA_BASE_BYTES = 256 * 1024**2
_GSEA_ADMISSION_BYTES = 1536 * 1024**2


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
    result_sources=[_source(payload['sources'],sid,'bio_insight_result_version') for sid in config.result_source_ids]
    bulk = config.bulk_enrichment is not None
    if bulk:
        bulk_result=load_bulk_result(result_sources[0],config.bulk_enrichment,config.contrast_ids)
        results=[bulk_result]
        references=bulk_resource_references(bulk_result,resources,maps)
        universes={source['source_id']:gene_set_universe(data) for source,data in resources}
        mappers={rid:bulk_mapper(bulk_result,reference,maps) for rid,reference in references.items()}
        coverage=[]
    else:
        results=[load_result(source) for source in result_sources]
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
            if bulk:
                selection=ora_selection(contrast,config)
            else:
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
                reason=None
                if bulk:
                    mapper=mappers[rid]
                    bg,fg,scope_coverage=map_ora_selection(selection,mapper,universes[rid],context,mapping_rows,exclusions)
                    reason=ora_skip_reason(scope_coverage,config.min_size)
                else:
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
                    if reason is not None:
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
                if bulk:
                    if reason is None and not set_record['term_hits']:
                        reason='no_eligible_terms'
                    set_record['not_applicable_reason']=reason
                    scope_coverage.update(not_applicable_reason=reason, resource_gene_count=len(universes[rid]),
                                          eligible_term_count=len(set_record['term_hits']))
                    coverage.append(scope_coverage)
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
    _mapping_outputs(writer,mapping_rows,exclusions,term_exclusions,classifications,bulk=bulk)
    methods={'name':'ORA_hypergeometric_right_tail','correction':'BH_contrast_direction_collection',
             'merge_collections':config.merge_collections,'family':families,'q_column':config.q_column,
             'q_threshold':config.q_threshold,'minimum_absolute_effect':config.minimum_absolute_effect,
             'direction':config.direction,'min_size':config.min_size,'max_size':config.max_size,
             'background':'explicit_fixed_file' if explicit_background is not None else 'complete_predeclared_tested_gene_universe',
             'many_to_one_mapping':'deduplicate_target_genes_with_original_mapping_rows','upstream':upstream,
             'resources':[_resource_identity(s,d) for s,d in resources],
             'classification_counts_mutually_exclusive':False,'mapping_excluded_count':len(exclusions)}
    significant=sum(r['q_value']<=.05 for r in rows)
    summary={'row_count':len(rows),'empty_foregrounds':empty,'eligible_term_family_complete':True,
             'significant_terms':significant,'result_member_key':'enrichment_results',
             'family':families,'excluded_terms':len(term_exclusions)}
    if bulk:
        methods['background']='complete_tested_gene_universe_intersected_with_collection'
        bulk_result_status(bulk_result,references,coverage,summary,methods,significant)
    return {'summary':summary,
            'methods':methods,'inference_scope':'derived','provenance':{'system_computed':True,'upstream':upstream,
                       'resources':methods['resources'],'mapping_sources':[s['source_id'] for s in maps]}}


def _resource_identity(source,data):
    return {'resource_id':source['source_id'],'sha256':source['sha256'],'kind':data['kind'],'species_taxon_id':data['species_taxon_id'],
            'namespace':data['namespace'],'release':data['release'],'usage':data['usage'],'source':data.get('source')}


def _mapping_outputs(writer,mapping_rows,exclusions,term_exclusions,classifications,*,bulk=False):
    fields=['result_source_id','contrast_id','resource_id','original_id','target_id','reason']
    if bulk:
        fields.extend(BULK_MAPPING_FIELDS)
    writer.table('mapping_rows',mapping_rows,fields)
    writer.table('mapping_exclusions',exclusions,['result_source_id','contrast_id','resource_id','feature_id','reason'])
    writer.table('term_exclusions',term_exclusions,['result_source_id','contrast_id','resource_id','term_id','background_size','reason'])
    writer.table('functional_classification',classifications,
                 ['result_source_id','contrast_id','resource_id','category','background_gene_count','foreground_gene_count','mutually_exclusive'])


def _gsea_working_bytes(rank_count, term_count, permutation_count, membership_count):
    """Estimate the peak for the locked 64-bit GSEApy 1.3.1 permutation path."""
    if not term_count:
        return _GSEA_BASE_BYTES

    # algorithm.rs gene_permutation retains every DynamicEnum through stats.rs
    # GSEAResult::stat. Each clone owns an index vector and a HashMap<usize, usize>.
    # Rust's hash table grows in powers of two at 7/8 load (16 bytes + a control byte per bucket).
    buckets_needed = (8 * rank_count + 6) // 7
    buckets = 1 << (max(4, buckets_needed) - 1).bit_length()
    shuffle_count = permutation_count + 1  # Includes the observed order.
    permutation_maps = shuffle_count * (8 * rank_count + 17 * buckets + 256)

    # Prerank constructs every f64 tag vector for one term at a time. These
    # vectors overlap the permutation maps, completed summaries and ES scratch.
    tag_vectors = shuffle_count * (8 * rank_count + 64)
    curves = 8 * rank_count * term_count
    null_scores = 8 * permutation_count * term_count
    family_overhead = 64 * membership_count + 512 * term_count
    scoring_peak = permutation_maps + tag_vectors + curves + null_scores + 48 * rank_count + 8 * shuffle_count

    # During joint correction the tag vectors are gone. The original ES nulls
    # coexist with the growing normalized null vector. Budget up to 3x its
    # contents for a vector reallocation, plus per-term normalization/FWER scratch.
    correction_peak = permutation_maps + curves + 4 * null_scores + 32 * permutation_count

    # The PyO3 summaries getter clones the native summaries. Keep the previous
    # conservative curve allowance, space for a Python curve, and the null copies.
    export_peak = 5 * curves + 40 * rank_count + 4 * null_scores
    return _GSEA_BASE_BYTES + family_overhead + max(scoring_peak, correction_peak, export_peak)


def _gsea(payload,config,writer):
    resources,maps=_resources(payload,config)
    source=_source(payload['sources'],config.result_source_id,'bio_insight_result_version')
    bulk=config.bulk_enrichment is not None
    if bulk:
        result=load_bulk_result(source,config.bulk_enrichment,[config.contrast_id])
        references=bulk_resource_references(result,resources,maps)
        universes={source['source_id']:gene_set_universe(data) for source,data in resources}
        target_references=references.values()
    else:
        result=load_result(source)
        target_references=[data for _,data in resources]
    if not result['tested_universe_complete']:raise ValueError('complete_ranking_required_top_table_forbidden')
    if config.ranking_column not in {'statistic','wald_statistic','effect_value'}:raise ValueError('explicit_signed_statistic_required')
    selected=result.pop('rows') if bulk else [r for r in result['rows'] if r['contrast_id']==config.contrast_id and r['tested']]
    if not selected:raise ValueError('ranking_contrast_empty')
    if len(selected)>100000:raise ValueError('ranking_gene_budget_exceeded')
    # A joint null needs one common namespace and one frozen ranked vector.
    targets={(d['species_taxon_id'],d['namespace']) for d in target_references}
    if len(targets)!=1:raise ValueError('joint_gsea_requires_common_target_namespace')
    taxon,target_namespace=next(iter(targets))
    mapping_rows=[];exclusions=[];term_exclusions=[];classifications=[]
    context={'result_source_id':result['source']['source_id'],'contrast_id':config.contrast_id,'resource_id':'joint'}
    if bulk:
        mapper=bulk_mapper(result,next(iter(references.values())),maps)
        ranking,coverage=bulk_ranking(selected,mapper,universes,context,mapping_rows,exclusions)
        del selected
    else:
        mapper=ExplicitMapper(result['species_taxon_id'],result['namespace'],taxon,target_namespace,maps)
        mapped=defaultdict(list)
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
    ranking_reason=None
    if len(ranking)<2 or not any(r['statistic']!=0 for r in ranking):
        ranking_reason='ranking_all_zero_or_insufficient'
        if not bulk:raise ValueError(ranking_reason)
    elif bulk and len({r['statistic'] for r in ranking}) == 1:
        ranking_reason='ranking_all_equal'
    for i,row in enumerate(ranking):row['rank']=i
    genes=[r['feature_id'] for r in ranking];scores=[r['statistic'] for r in ranking];gene_set=set(genes)
    score_by_gene=dict(zip(genes,scores))
    terms={};term_metadata={};n_memberships=0
    for source,data in resources:
        rid=source['source_id'];categories=defaultdict(set)
        eligible_before=len(terms)
        for term in data['terms']:
            members=sorted(set(term['genes'])&gene_set);K=len(members)
            reason=ranking_reason
            if reason is None and (not config.min_size<=K<=config.max_size or K==len(genes)):
                reason='term_rank_size_outside_bounds'
            if reason is None and config.weight>0 and not any(score_by_gene[gene]!=0 for gene in members):
                if not bulk:raise ValueError('gsea_term_zero_weight:'+rid+'::'+term['term_id'])
                reason='gsea_term_zero_weight'
            if reason is not None:
                term_exclusions.append({'result_source_id':result['source']['source_id'],'contrast_id':config.contrast_id,
                    'resource_id':rid,'term_id':term['term_id'],'background_size':K,'reason':reason})
                continue
            key=rid+'::'+term['term_id']
            if key in terms:raise ValueError('collection_term_id_collision')
            terms[key]=members;term_metadata[key]=(source,data,term);n_memberships+=K
            categories[term.get('namespace','unknown')].update(members)
            for subset in term.get('subsets',[]):categories['subset:'+subset].update(members)
        for category,members in sorted(categories.items()):
            classifications.append({'result_source_id':result['source']['source_id'],'contrast_id':config.contrast_id,
                                    'resource_id':rid,'category':category,'background_gene_count':len(members),
                                    'foreground_gene_count':None,'mutually_exclusive':False})
        if bulk:
            eligible_count=len(terms)-eligible_before
            coverage['resources'][rid].update(eligible_term_count=eligible_count,
                not_applicable_reason=None if eligible_count else ranking_reason or 'no_eligible_terms')
    if len(terms)>10000:raise ValueError('gsea_eligible_set_budget_exceeded')
    estimate = _gsea_working_bytes(len(genes), len(terms), config.permutation_num, n_memberships)
    if estimate > _GSEA_ADMISSION_BYTES:
        raise MemoryError(
            f'gsea_resource_budget_exceeded: estimated {estimate} bytes for {len(genes)} ranks, '
            f'{len(terms)} eligible terms and {config.permutation_num} permutations '
            f'(limit {_GSEA_ADMISSION_BYTES} bytes)'
        )
    work=(len(genes)+n_memberships)*config.permutation_num
    if work>2000000000:raise ValueError('gsea_resource_budget_exceeded')
    result_rows=[];curves=[]
    if terms:
        # This is exactly the locked GSEApy 1.3.1 Prerank.run permutation
        # entrypoint. One complete family is fitted together; native summaries
        # retain the joint null/curves. Avoid to_df(), which additionally keeps
        # every full running curve as Python float lists in public .results.
        from gseapy.gse import prerank_rs
        if bulk:
            # Native GSEApy interprets '__' as a collection separator. Opaque,
            # membership-ordered keys keep its single joint null independent of labels.
            ordered = sorted(terms, key=lambda key: (terms[key], key))
            native_to_public = {f'term{i:08d}': key for i, key in enumerate(ordered)}
            native_terms = {native: terms[key] for native, key in native_to_public.items()}
        else:
            native_terms = terms
            native_to_public = {key: key for key in terms}
        summaries=prerank_rs(genes,scores,native_terms,config.weight,config.min_size,config.max_size,
            config.permutation_num,1,config.seed).summaries
        if len(summaries)!=len(terms) or {s.term for s in summaries}!=set(native_terms):raise ValueError('gsea_eligible_family_incomplete')
        for observed in sorted(summaries,key=lambda s:native_to_public[s.term]):
            key=native_to_public[observed.term];source,data,term=term_metadata[key]
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
    _mapping_outputs(writer,mapping_rows,exclusions,term_exclusions,classifications,bulk=bulk)
    tied=1-len(set(scores))/len(scores) if scores else None
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
    summary={'row_count':len(result_rows),'ranking_size':len(ranking),'eligible_set_count':len(terms),
             'eligible_term_family_complete':True,'empty_eligible_sets':not bool(terms),
             'result_member_key':'enrichment_results','excluded_terms':len(term_exclusions)}
    if bulk:
        methods['native_term_key_policy']='membership_ordered_opaque_v1'
        coverage['not_applicable_reason']=None if terms else ranking_reason or 'no_eligible_terms'
        significant=sum(r['fdr_q_value'] is not None and r['fdr_q_value']<=.05 for r in result_rows)
        bulk_result_status(result,references,[coverage],summary,methods,significant)
    return {'summary':summary,
            'methods':methods,'inference_scope':'derived','provenance':{'system_computed':True,
                       'result_source_id':result['source']['source_id'],'source_sha256':result['source']['sha256'],
                       'upstream_inference_scope':result['inference_scope'],'resources':methods['resources'],
                       'species_taxon_id':result['species_taxon_id'],'source_namespace':result['namespace'],
                       'target_namespace':target_namespace,'reference_version':result['reference_version']}}
