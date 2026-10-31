"""Frozen original external tables, without inventing counts or replacing original q."""
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from scipy.stats import false_discovery_control
from app.domain.bio_insights.contracts import ResultImportConfig
from .inputs import iter_table
from .tables import PARSER_VERSION


def _numeric(value, na_values, probability=False):
    if value is None or value in na_values: return None
    if not isinstance(value,str): raise ValueError('external_numeric_type_invalid')
    try: number=Decimal(value)
    except InvalidOperation as exc: raise ValueError('external_numeric_invalid') from exc
    if not number.is_finite() or probability and not 0<=number<=1: raise ValueError('external_probability_invalid' if probability else 'external_numeric_invalid')
    result=float(number)
    if not math.isfinite(result): raise ValueError('external_numeric_out_of_range')
    return result


def run_result_import(payload, writer):
    if payload.get('schema_version')!=1 or payload.get('kind')!='bio_result_import': raise ValueError('result_import_payload_invalid')
    config=ResultImportConfig.model_validate(payload['config'])
    matches=[s for s in payload['sources'] if s['source_kind']=='original_file' and s['source_id']==config.file_source_id]
    if len(matches)!=1: raise ValueError('external_file_source_invalid')
    source=matches[0]; metadata=source['metadata']; files=source['members']
    candidates=[key for key in ('original_file','original') if key in files]
    if len(candidates)!=1: raise ValueError('external_original_member_invalid')
    member=files[candidates[0]]
    if (metadata['parse_version_id']!=config.parse_version_id or metadata['parser_version']!=PARSER_VERSION
            or source['sha256']!=member['sha256']): raise ValueError('external_parse_version_mismatch')
    if member['format']=='xlsx' and metadata.get('sheet')!=config.sheet: raise ValueError('external_sheet_mismatch')
    columns={key:value for key,value in config.columns.model_dump().items() if value is not None}
    if len(set(columns.values()))!=len(columns): raise ValueError('external_column_mapping_duplicate')
    result=[]; exclusions=[]
    provenance={'external_result':True,'file_source_id':config.file_source_id,'file_sha256':member['sha256'],
                'parse_version_id':config.parse_version_id,'parser_version':PARSER_VERSION,'sheet':config.sheet,
                'declared_inference_scope':config.inference_scope,'identity':payload.get('identity',{}),
                'species_taxon_id':config.species_taxon_id,'namespace':config.namespace,'reference_version':config.reference_version}
    family_id=hashlib.sha256(json.dumps({'file':source['sha256'],'contrast':config.contrast_id,
                        'parse':config.parse_version_id},sort_keys=True).encode()).hexdigest()
    for number,cells in iter_table(member,format=member['format'],sheet=config.sheet,
            encoding=metadata.get('encoding','utf-8-sig'),delimiter=metadata.get('delimiter'),header_row=metadata.get('header_row',1)):
        if not set(columns.values())<=set(cells): raise ValueError('external_mapped_column_missing')
        original={name:cells[column] for name,column in columns.items()}
        feature=original['feature_id']
        if not isinstance(feature,str) or not feature.strip() or len(feature)>1000 or any(ord(c)<32 for c in feature):
            raise ValueError('external_feature_id_invalid')
        if 'contrast_id' in original and original['contrast_id']!=config.contrast_id:
            raise ValueError('external_contrast_not_selected')
        p=_numeric(original.get('p_value'),config.na_values,True)
        q=_numeric(original.get('q_value'),config.na_values,True)
        effect=_numeric(original.get('effect'),config.na_values)
        status=original.get('status')
        row_key=hashlib.sha256(json.dumps({'file_sha256':member['sha256'],'parse_version_id':config.parse_version_id,
                      'sheet':config.sheet,'row':number,'feature_id':feature,'contrast_id':config.contrast_id},sort_keys=True).encode()).hexdigest()
        row={'row_key':row_key,'feature_id':feature,'symbol':original.get('symbol'),
             'contrast_id':config.contrast_id,'numerator':config.numerator,'denominator':config.denominator,
             'observation_level':config.observation_level,'inference_scope':'external_result',
             'effect_name':config.effect_name,'effect_unit':config.effect_unit,'effect_value':effect,
             'statistic':None,'p_value':p,'q_within_contrast':None,'q_global_family':None,
             'original_p_value':original.get('p_value'),'original_q':original.get('q_value'),
             'original_effect':original.get('effect'),'original_direction':original.get('direction'),'original_status':status,
             'system_recomputed_q':None,'correction_family_id':family_id,'n_numerator':None,'n_denominator':None,
             'spots_numerator':None,'spots_denominator':None,'donors_numerator':None,'donors_denominator':None,
             'test_status':'external_result' if p is not None else 'not_computable',
             'reason':None if p is not None else 'external_p_missing','tested':True,
             'p_value_underflow':p==0 and original.get('p_value') is not None and Decimal(original['p_value'])!=0,
             'source_row':number,'source_cells':cells,'provenance':{**provenance,'row':number,'columns':columns}}
        result.append(row)
    if not result: raise ValueError('external_table_empty')
    duplicates={feature for feature,count in Counter(r['feature_id'] for r in result).items() if count>1}
    if duplicates and config.duplicate_policy=='error': raise ValueError('external_duplicate_feature_id')
    for row in result:
        if row['feature_id'] in duplicates:
            row.update(tested=False,test_status='excluded',reason='duplicate_feature_id')
            exclusions.append({'row_key':row['row_key'],'source_row':row['source_row'],'feature_id':row['feature_id'],'reason':'duplicate_feature_id'})
    family_rows=[r for r in result if r['tested']]
    if config.recompute_q:
        if not family_rows or not any(r['p_value'] is not None for r in family_rows): raise ValueError('external_no_valid_p_for_recomputation')
        values=[1 if row['p_value'] is None else row['p_value'] for row in family_rows]
        for row,value in zip(family_rows,false_discovery_control(values,method='bh')):
            if row['p_value'] is not None:row['system_recomputed_q']=float(value)
    family={'family_size':len(family_rows),'valid_p_values':sum(r['p_value'] is not None for r in family_rows),
            'na_p_values':sum(r['p_value'] is None for r in family_rows),'complete_tested_universe':config.complete_tested_universe,
            'recomputed':config.recompute_q,'method':'BH_NA_internal_one' if config.recompute_q else None}
    methods={'name':'external_result_import','original_method':config.original_method,
             'original_correction_scope':config.original_correction_scope,'no_model_fitted':True,
             'original_values_preserved':True,'system_q_is_original_q':False,
             'complete_tested_universe':config.complete_tested_universe,'system_recomputed_q':family,
             'declared_observation_level':config.observation_level,'declared_inference_scope':config.inference_scope}
    methods.update(species_taxon_id=config.species_taxon_id,namespace=config.namespace,reference_version=config.reference_version)
    writer.table('comparison_results',result);writer.table('import_exclusions',exclusions,['row_key','source_row','feature_id','reason'])
    writer.json('correction_families',{'external':family});writer.json('comparison_methods',methods)
    return {'summary':{'row_count':len(result),'feature_count':len({r['feature_id'] for r in result}),
                       'contrast_count':1,'result_member_key':'comparison_results','external_result':True,
                       'external_not_recomputed':not config.recompute_q,'tested_universe_complete':config.complete_tested_universe,
                       'family':{'external':family},'excluded_rows':len(exclusions),
                       'not_computable_rows':sum(r['p_value'] is None for r in result)},
            'methods':methods,'inference_scope':'external_result','provenance':provenance}
