"""Read-only comparison of immutable completed results; no scientific reruns."""
from collections import Counter
import csv
import io


def _ari(left, right):
    n=len(left)
    if n<2:return None
    choose=lambda x:x*(x-1)/2
    observed=sum(choose(v) for v in Counter(zip(left,right)).values())
    a=sum(choose(v) for v in Counter(left).values());b=sum(choose(v) for v in Counter(right).values())
    expected=a*b/choose(n);denominator=(a+b)/2-expected
    return (observed-expected)/denominator if denominator else 1.0


def compare_results(baseline, comparison):
    """Cell identities are comparable only inside the exact same raw snapshot."""
    if baseline['source']['processed_dataset_version_id']==comparison['source']['processed_dataset_version_id']:
        raise ValueError('distinct_results_required')
    if any(r['manifest'].get('assay')!='single_cell' for r in (baseline,comparison)):
        raise ValueError('single_cell_results_required')
    same=baseline['source']['raw_source']==comparison['source']['raw_source']
    def kept(r):return {x['barcode']:x for x in r['observations'] if str(x.get('kept','')).lower() in ('true','1')}
    a,b=kept(baseline),kept(comparison);common=sorted(a.keys()&b.keys()) if same else []
    labelled=[k for k in common if a[k].get('cluster') not in (None,'','NA') and b[k].get('cluster') not in (None,'','NA')]
    def identities(r,rows):
        donors=sorted({x['donor'] for x in rows.values() if x.get('donor') and x.get('donor_status')=='known'})
        unknown=sum(not x.get('donor') or x.get('donor_status')!='known' for x in rows.values())
        return dict(source=r['source'],task_id=r['task_id'],donors=donors,unknown_donor_cells=unknown,samples=sorted({x['sample_id'] for x in rows.values() if x.get('sample_id')}),cohort_identity='raw_source',params=r['manifest'].get('params',{}),subset=r['manifest'].get('subset') or r['manifest'].get('summary',{}).get('subset'))
    ai,bi=identities(baseline,a),identities(comparison,b)
    overlap=sorted(set(ai['donors'])&set(bi['donors']))
    status='same_source' if same else 'overlapping_donors' if overlap else 'unknown_donors' if ai['unknown_donor_cells'] or bi['unknown_donor_cells'] or not ai['donors'] or not bi['donors'] else 'independence_unverified'
    pa,pb=ai['params'],bi['params']
    ma={x['feature_id'] for x in baseline['markers'] if x.get('feature_id')};mb={x['feature_id'] for x in comparison['markers'] if x.get('feature_id')}
    return dict(baseline=ai,comparison=bi,parameter_changes={k:dict(baseline=pa.get(k),comparison=pb.get(k)) for k in sorted(pa.keys()|pb.keys()) if pa.get(k)!=pb.get(k)},
        cells=dict(baseline=len(a),comparison=len(b),common=len(common) if same else None,jaccard=len(common)/len(a.keys()|b.keys()) if same and (a or b) else None),
        clusters=dict(adjusted_rand_index=_ari([a[k]['cluster'] for k in labelled],[b[k]['cluster'] for k in labelled]) if same else None,common_labelled_cells=len(labelled),scope='shared_retained_cells_only'),
        markers=dict(baseline=len(ma),comparison=len(mb),common=len(ma&mb),jaccard=len(ma&mb)/len(ma|mb) if ma or mb else None,scope='exported_marker_feature_union_not_cluster_matched'),
        independence=dict(status=status,overlapping_donors=overlap,independent_validation=False),
        limitations=['Descriptive comparison of saved results; not biological validation.','Different source identities and disjoint donor labels do not establish independent cohorts.','Cluster comparison excludes cells without labels; marker overlap uses the exported feature union.'])


def load_comparison(store, project_id, baseline_id, comparison_id):
    from app.adapters.bio_analysis_store import BioAnalysisStore
    from app.adapters.bio_analysis_store import error
    adapter=BioAnalysisStore(store)
    with adapter.store.connection() as db:
        adapter.store.require_project(db,project_id)
        def load(identifier):
            row,manifest,members=adapter.processed_record(db,project_id,identifier)
            run=adapter.require(db,'bio_analysis_runs',project_id,row['run_id'])
            task=adapter.store.require_task(db,run['task_id'])
            if task['status']!='succeeded':raise error('bio_result_not_completed',409)
            def table(key):
                member=next((m for m in members if m['key']==key and m['format']=='tsv'),None)
                return list(csv.DictReader(io.StringIO(adapter.objects.read(member).decode('utf-8-sig')),delimiter='\t')) if member else []
            return dict(source=adapter.processed_source(row,manifest),task_id=run['task_id'],manifest=manifest,observations=table('observations'),markers=table('markers_top'))
        a,b=load(baseline_id),load(comparison_id)
    try:return compare_results(a,b)
    except ValueError as exc:raise error(str(exc),422) from exc


def repeat_context(recipe, manifest):
    return dict(params=recipe['params_json'],observation_map_version_id=recipe.get('observation_map_version_id'),design_version_id=recipe.get('design_version_id'),repeat_allowed=not bool(manifest.get('subset') or manifest.get('summary',{}).get('subset')))


def load_repeat_context(store, project_id, identifier):
    from app.adapters.bio_analysis_store import BioAnalysisStore,error
    adapter=BioAnalysisStore(store)
    with adapter.store.connection() as db:
        row,manifest,_=adapter.processed_record(db,project_id,identifier)
        if manifest.get('assay')!='single_cell':raise error('single_cell_results_required',422)
        recipe=adapter.require(db,'bio_analysis_recipe_versions',project_id,row['recipe_version_id'])
        return repeat_context(recipe,manifest)
