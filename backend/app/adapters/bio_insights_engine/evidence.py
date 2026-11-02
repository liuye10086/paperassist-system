"""Read frozen complete result evidence without importing domain services."""
import math
from .inputs import document,iter_table


def numeric(value,na_values=('', 'NA', 'N/A', 'null')):
    if value is None or isinstance(value,str) and value in na_values:return None
    try:number=float(value)
    except (ValueError,TypeError):raise ValueError('result_numeric_invalid')
    if not math.isfinite(number):raise ValueError('result_numeric_nonfinite')
    return number


def source_numeric(source,value):
    """Parse using the immutable upstream import declaration, never caller defaults."""
    metadata=source.get('metadata',{})
    config=metadata.get('plan_config') or metadata.get('config')
    if not config and 'recipe' in source.get('members',{}):
        config=document(source['members']['recipe']).get('config')
    config=config or {}
    markers=config.get('na_values',[]) if config.get('kind')=='result_import' else ('','NA','N/A','null')
    # Empty cells also represent normalized nulls in system TSV members.
    return numeric(value,tuple(markers)+('',))


def true(value):
    if value in (True,'True','true','1'):return True
    if value in (False,'False','false','0'):return False
    raise ValueError('result_boolean_invalid')


def load_result(source):
    if source['source_kind']!='bio_insight_result_version':raise ValueError('result_source_invalid')
    members=source['members'];metadata=source['metadata']
    manifest=document(members['manifest']) if 'manifest' in members else metadata.get('manifest',{})
    config=metadata.get('plan_config') or metadata.get('config')
    if not config and 'recipe' in members:config=document(members['recipe']).get('config')
    if not isinstance(config,dict):raise ValueError('result_frozen_configuration_required')
    taxon=config.get('species_taxon_id');namespace=config.get('namespace');reference=config.get('reference_version')
    if type(taxon) is not int or not namespace or not reference:raise ValueError('result_explicit_species_namespace_reference_required')
    for name,value in [('species_taxon_id',taxon),('namespace',namespace),('reference_version',reference)]:
        if metadata.get(name) is not None and metadata[name]!=value:raise ValueError('result_reference_metadata_mismatch')
    if 'comparison_results' not in members:raise ValueError('complete_comparison_table_required')
    rows=[];keys=set()
    for number,row in iter_table(members['comparison_results'],format='tsv'):
        if not {'row_key','feature_id','contrast_id','tested','inference_scope'}<=set(row):raise ValueError('result_columns_missing')
        if not row['row_key'] or row['row_key'] in keys:raise ValueError('duplicate_result_row_key')
        keys.add(row['row_key']);row['tested']=true(row['tested']);row['_source_row']=number
        rows.append(row)
    summary=manifest.get('summary') or metadata.get('summary_json') or {}
    scope=manifest.get('inference_scope') or metadata.get('inference_scope')
    if scope not in ('spot_exploratory','donor_inference','sample_exploratory','sample_inference','external_result','derived'):
        raise ValueError('result_inference_scope_required')
    return {'source':source,'rows':rows,'summary':summary,'manifest':manifest,'config':config,
            'species_taxon_id':taxon,'namespace':namespace,'reference_version':reference,'inference_scope':scope,
            'tested_universe_complete':summary.get('tested_universe_complete') is True}
