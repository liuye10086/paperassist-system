"""B04 fixed-process transport; validates bytes independently of the engine."""
import csv
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import signal
import struct
import sys
from threading import Event, Thread

from app.core.exceptions import StorageError
from app.domain.bio_insights.settings import BioInsightsLimits, INTERPRETER, runtime_identity
from app.domain.bio_insights.task_contracts import INSIGHT_TASKS

MAX_LEAF = 256 * 1024**2
MAX_TOTAL = 512 * 1024**2
MAX_JSON = 2 * 1024**2
FORMATS = {'json','tsv','csv','png','tiff','svg','txt','py','lock','fasta','pdb','mmcif','fasta.gz','pdb.gz','mmcif.gz'}


def invalid(code='bio_insights_output_invalid'):
    return StorageError(code,'差异与功能分析的输入、环境或结果未通过完整性检查；原材料已保留。',422)


def strict_json(content):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('duplicate_json_key')
            result[key]=value
        return result
    return json.loads(content,object_pairs_hook=pairs,
        parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite_json')))


def file_sha(path):
    sha=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024**2),b''):sha.update(chunk)
    return sha.hexdigest()


def input_records(payload):
    """Only declared member leaves grant Landlock access, never metadata paths."""
    sources=payload.get('sources')
    if type(sources) is not list or not 1<=len(sources)<=100:raise invalid('bio_insights_input_invalid')
    records=[];allowed=set()
    for source in sources:
        if type(source) is not dict:raise invalid('bio_insights_input_invalid')
        for container in (source,source.get('raw',{})):
            members=container.get('members',{})
            if type(members) is not dict:raise invalid('bio_insights_input_invalid')
            for member in members.values():
                if type(member) is not dict or 'path' not in member:raise invalid('bio_insights_input_invalid')
                records.append(member);allowed.add(id(member))
    def visit(value):
        if isinstance(value,dict):
            if 'path' in value and id(value) not in allowed:raise invalid('bio_insights_input_invalid')
            for nested in value.values():visit(nested)
        elif isinstance(value,list):
            for nested in value:visit(nested)
    visit(payload)
    if not 1<=len(records)<=BioInsightsLimits().max_input_members:raise invalid('bio_insights_input_invalid')
    return records


def validate_artifacts(outputs,directory):
    try:
        from PIL import Image
        from defusedxml.ElementTree import fromstring
        root=Path(directory).resolve()
        if Path(directory).is_symlink() or not root.is_dir() or type(outputs) is not list or not 1<=len(outputs)<=256:raise ValueError()
        keys=set();paths=set();total=0
        for item in outputs:
            key=item['key'];fmt=item['format'];path=Path(item['path']);size=item['size_bytes']
            if (type(key) is not str or not re.fullmatch(r'[a-z][a-z0-9_-]{0,99}',key) or key in keys
                    or fmt not in FORMATS or type(size) is not int or not 0<size<=MAX_LEAF
                    or not re.fullmatch(r'[0-9a-f]{64}',item['sha256']) or not isinstance(item['role'],str) or not 1<=len(item['role'])<=100
                    or not path.is_absolute() or path.is_symlink() or not path.is_file() or path.resolve().parent!=root
                    or path.name!=key+'.'+fmt or path.stat().st_size!=size or file_sha(path)!=item['sha256']):raise ValueError()
            total+=size
            if total>MAX_TOTAL:raise ValueError()
            if fmt=='json':strict_json(path.read_bytes())
            elif fmt in ('png','tiff'):
                with Image.open(path) as figure:
                    if figure.format!=fmt.upper() or max(figure.size)>4096 or figure.width*figure.height>16_000_000:raise ValueError()
                    figure.verify()
            elif fmt=='svg':
                if size>16*1024**2:raise ValueError()
                tree=fromstring(path.read_bytes())
                if tree.tag.rsplit('}',1)[-1]!='svg':raise ValueError()
                for element in tree.iter():
                    if element.tag.rsplit('}',1)[-1] in ('script','foreignObject','iframe','animate','set'):raise ValueError()
                    for name,value in element.attrib.items():
                        name=name.rsplit('}',1)[-1]
                        if name.lower().startswith('on'):raise ValueError()
                        if name in ('href','src') and not value.startswith('#'):
                            if element.tag.rsplit('}',1)[-1]!='image' or not value.startswith('data:image/png;base64,'):raise ValueError()
                            encoded=re.sub(r'\s+','',value.split(',',1)[1]);content=base64.b64decode(encoded,validate=True)
                            with Image.open(io.BytesIO(content)) as embedded:
                                if embedded.format!='PNG' or max(embedded.size)>4096 or embedded.width*embedded.height>16_000_000:raise ValueError()
                                embedded.verify()
                        if re.search(r'url\(\s*["\']?(?!#)',value,re.I):raise ValueError()
                    if element.tag.rsplit('}',1)[-1]=='style' and re.search(r'@import|url\(',element.text or '',re.I):raise ValueError()
            elif fmt in ('tsv','csv'):
                with path.open(encoding='utf-8',newline='') as stream:
                    reader=csv.reader(stream,delimiter='\t' if fmt=='tsv' else ',');header=next(reader)
                    if not header or len(set(header))!=len(header) or len(header)>512:raise ValueError()
                    for number,row in enumerate(reader,1):
                        if len(row)!=len(header) or number>10_000_000:raise ValueError()
            keys.add(key);paths.add(path.resolve())
        if paths!={path.resolve() for path in root.iterdir()}:raise ValueError()
        return outputs
    except (KeyError,ValueError,TypeError,OSError,StopIteration,OverflowError) as exc:raise invalid() from exc


def validate_result(result,directory,payload):
    try:
        if (type(result) is not dict or result['schema_version']!=1 or result['status']!='completed'
                or result['engine_version']!='bio_insights_v1.0.0' or result['kind']!=payload['kind']
                or result['identity']!=payload['identity'] or not all(type(result[k]) is dict for k in ('summary','methods','manifest'))
                or result['provenance'] not in ('system_computed','external_result')
                or result['inference_scope'] not in ('spot_exploratory','donor_inference','sample_exploratory','sample_inference','external_result','derived','visualization')):raise ValueError()
        if len(json.dumps(result,allow_nan=False).encode())>MAX_JSON:raise ValueError()
        outputs=validate_artifacts(result['outputs'],directory);items={m['key']:m for m in outputs}
        manifest=result['manifest']
        if ('manifest' not in items or strict_json(Path(items['manifest']['path']).read_bytes())!=manifest
                or manifest['identity']!=payload['identity'] or manifest['kind']!=payload['kind']):raise ValueError()
        expected=[{k:v for k,v in m.items() if k!='path'} for m in outputs if m['key']!='manifest']
        if manifest['members']!=expected:raise ValueError()
        _validate_scientific_contract(result,items,payload)
        return result
    except (KeyError,ValueError,TypeError,OSError) as exc:raise invalid() from exc


def _portable(value):
    if isinstance(value,dict):return {key:_portable(item) for key,item in value.items() if key not in ('path','output_directory','_runtime_identity')}
    if isinstance(value,list):return [_portable(item) for item in value]
    return value


def _validate_scientific_contract(result,items,payload):
    """A byte-valid envelope is not sufficient evidence of the requested science."""
    from app.domain.bio_insights.contracts import (ComparisonConfig,ResultImportConfig,OraConfig,
        GseaPrerankConfig,CandidateConfig,FigureConfig,ResourceImportRequest)
    resources=result.get('resources',{})
    if not isinstance(resources,dict):raise ValueError('execution_resource_metadata_invalid')
    if 'child_peak_rss_kib' in resources:
        peak=resources['child_peak_rss_kib']
        # Catch short RSS spikes reported by getrusage even if they fall between
        # the parent's live monitor samples and the process exits successfully.
        if type(peak) is not int or peak<0 or peak*1024>BioInsightsLimits().memory_bytes:
            raise ValueError('execution_reported_rss_exceeded')
    kind=payload['kind'];original=payload['config'];config_kind=original['kind']
    models={'bio_comparison':ComparisonConfig,'bio_result_import':ResultImportConfig,
            'bio_resource_import':ResourceImportRequest,'bio_candidate':CandidateConfig,'bio_insight_figure':FigureConfig}
    if kind=='bio_candidate' and original.get('schema_version')==2:
        from app.domain.bio_insights.evidence_contracts import EvidenceMatrixConfig
        models[kind]=EvidenceMatrixConfig
    if kind=='bio_integration':
        from app.domain.bio_insights.integration_contracts import IntegrationConfig
        models[kind]=IntegrationConfig
        if original.get('schema_version')==2:
            from app.domain.bio_insights.single_cell_topic_contracts import SingleCellTopicConfig
            models[kind]=SingleCellTopicConfig
    if kind=='bio_feature_extract':
        from app.domain.bio_insights.feature_contracts import FeatureExtractConfig
        models[kind]=FeatureExtractConfig
    if kind=='bio_enrichment':model={'ora':OraConfig,'gsea_prerank':GseaPrerankConfig}.get(config_kind)
    else:model=models.get(kind)
    quantitative=kind=='bio_comparison' and original.get('schema_version')==2
    qpcr=kind=='bio_comparison' and original.get('schema_version')==3
    composition=kind=='bio_comparison' and original.get('schema_version')==5
    if composition:
        from app.domain.bio_insights.single_cell_composition_contracts import SingleCellCompositionConfig
        model=SingleCellCompositionConfig
    microbiome=kind=='bio_comparison' and original.get('schema_version')==4
    if microbiome:
        from app.domain.bio_insights.microbiome_contracts import MicrobiomeConfig
        model=MicrobiomeConfig
    if quantitative:
        from app.domain.bio_insights.quantitative_contracts import QuantitativeComparisonConfig,quantitative_scope
        model=QuantitativeComparisonConfig
    if qpcr:
        from app.domain.bio_insights.qpcr_contracts import QpcrConfig
        model=QpcrConfig
    if model is None:raise ValueError('task_configuration_kind_invalid')
    config=model.model_validate(original).model_dump(mode='json')
    scope=('spot_exploratory' if config['mode']=='spot_exploratory' else 'donor_inference') if kind=='bio_comparison' else (
        'external_result' if kind=='bio_result_import' else 'visualization' if kind=='bio_insight_figure' else 'derived')
    if quantitative:scope=quantitative_scope(model.model_validate(config),[s['metadata']['assay'] for s in payload['sources'] if s['source_kind']=='bio_processed_dataset_version'])
    if composition:scope='sample_exploratory' if config['mode']=='descriptive' else 'donor_inference'
    topic=kind=='bio_integration' and original.get('schema_version')==2
    if topic:scope='donor_inference' if config['method']=='cellchat' and config['communication_mode']!='per_donor' else 'sample_exploratory'
    if qpcr:scope='sample_inference'
    if microbiome:scope='sample_inference' if config['contrasts'] or config['beta_inference'] else 'sample_exploratory'
    provenance='external_result' if kind=='bio_result_import' else 'system_computed'
    if result['inference_scope']!=scope or result['provenance']!=provenance:raise ValueError('scientific_scope_mismatch')
    manifest=result['manifest']
    for key in ('schema_version','engine_version','kind','identity','summary','methods','inference_scope','provenance'):
        if manifest.get(key)!=result[key]:raise ValueError('scientific_manifest_mismatch:'+key)
    if manifest.get('provenance_details',{})!=result.get('provenance_details',{}):raise ValueError('provenance_details_mismatch')
    from app.adapters.bio_insights_engine.transport import project_transport_payload
    transported=project_transport_payload(payload)
    if manifest.get('source_bindings')!=_portable(transported['sources']):raise ValueError('scientific_source_bindings_mismatch')
    def require(key,fmt):
        if key not in items or items[key]['format']!=fmt:raise ValueError('required_scientific_member_missing:'+key)
        return Path(items[key]['path'])
    def doc(key):return strict_json(require(key,'json').read_bytes())
    if doc('methods')!=result['methods'] or doc('recipe')!=_portable(transported):raise ValueError('methods_or_recipe_mismatch')
    if kind=='bio_candidate' and config.get('schema_version')==2:
        from app.adapters.bio_evidence_validation import validate_evidence
        validate_evidence(result,items,payload)
        return
    if topic:
        from app.adapters.bio_single_cell_topic_validation import validate_topic_result
        validate_topic_result(result,items,payload)
        return
    if kind=='bio_integration' or kind=='bio_resource_import' and config_kind in ('sample_correspondence','object_correspondence'):
        from app.adapters.bio_integration_validation import validate_integration
        validate_integration(result,items,payload)
        return
    if kind=='bio_feature_extract' or kind=='bio_resource_import' and config_kind in ('sequence','structure'):
        from app.adapters.bio_feature_validation import validate_feature
        validate_feature(result,items,payload)
        return
    if composition:
        from app.adapters.bio_insights_engine.single_cell_composition import validate_composition_result
        validate_composition_result(result,items,payload)
        return
    if microbiome:
        from app.adapters.bio_microbiome_validation import validate_microbiome
        validate_microbiome(result,items,payload)
        return
    if quantitative:
        from app.adapters.bio_quantitative_validation import validate_quantitative
        validate_quantitative(result,items,payload)
        return
    if qpcr:
        from app.adapters.bio_qpcr_validation import validate_qpcr
        validate_qpcr(result,items,payload)
        return
    def table(key,columns):
        with require(key,'tsv').open(encoding='utf-8',newline='') as stream:
            reader=csv.DictReader(stream,delimiter='\t',strict=True)
            if not set(columns)<=set(reader.fieldnames or []):raise ValueError('scientific_table_columns_missing:'+key)
            for row in reader:yield row
    def header(key,columns):
        # Exhaustion also validates the complete table, never only its first row.
        for _ in table(key,columns):pass
    if kind in ('bio_comparison','bio_result_import'):
        columns={'row_key','feature_id','contrast_id','numerator','denominator','observation_level','inference_scope',
            'effect_name','effect_value','effect_unit','statistic','p_value','q_within_contrast','q_global_family',
            'correction_family_id','n_numerator','n_denominator','spots_numerator','spots_denominator',
            'donors_numerator','donors_denominator','tested','test_status','reason','provenance'}
        if kind=='bio_result_import':columns.update({'original_p_value','original_q','original_effect','system_recomputed_q','source_row','source_cells'})
        elif scope=='spot_exploratory':columns.update({'mean_normalized_numerator','mean_normalized_denominator','detection_numerator','detection_denominator'})
        else:columns.update({'lfc_se','wald_statistic','base_mean'})
        contrasts={c['contrast_id']:c for c in config['contrasts']} if kind=='bio_comparison' else {config['contrast_id']:config}
        keys=set();count=0
        for row in table('comparison_results',columns):
            if not row['row_key'] or row['row_key'] in keys or row['contrast_id'] not in contrasts:raise ValueError('comparison_row_identity_invalid')
            keys.add(row['row_key']);count+=1;contrast=contrasts[row['contrast_id']]
            numerator=contrast['numerator']['label'] if kind=='bio_comparison' else contrast['numerator']
            denominator=contrast['denominator']['label'] if kind=='bio_comparison' else contrast['denominator']
            level=('spot' if scope=='spot_exploratory' else 'donor') if kind=='bio_comparison' else config['observation_level']
            if row['inference_scope']!=scope or row['observation_level']!=level or (row['numerator'],row['denominator'])!=(numerator,denominator):
                raise ValueError('comparison_row_scope_or_direction_mismatch')
        if result['summary'].get('row_count')!=count:raise ValueError('comparison_row_count_mismatch')
        if not isinstance(doc('correction_families'),dict):raise ValueError('correction_family_contract_invalid')
        comparison_methods=doc('comparison_methods')
        if not isinstance(comparison_methods,dict) or any(result['methods'].get(k)!=v for k,v in comparison_methods.items()):raise ValueError('comparison_methods_mismatch')
        if kind=='bio_result_import':
            header('import_exclusions',{'row_key','source_row','feature_id','reason'})
            for key in ('species_taxon_id','namespace','reference_version','original_method','original_correction_scope'):
                if result['methods'].get(key)!=config[key]:raise ValueError('external_method_metadata_mismatch')
            if (result['methods'].get('name')!='external_result_import' or result['methods'].get('no_model_fitted') is not True
                    or result['methods'].get('complete_tested_universe')!=config['complete_tested_universe']):raise ValueError('external_model_claim_invalid')
        else:
            parameters=({'continuity_correction':False,'ties':'average_rank_variance_correction','effect_pseudocount':1e-9}
                if scope=='spot_exploratory' else {'size_factors_fit_type':'poscounts','refit_cooks':False,'cooks_filter':True,
                    'independent_filter':False,'low_memory':True,'n_cpus':1,'lfc_shrinkage':False,'minimum_total_counts':config['minimum_total_counts']})
            method_name='two_sided_rank_sum_normal_tie_corrected' if scope=='spot_exploratory' else 'PyDESeq2_0.5.4_Wald'
            if (result['methods'].get('name')!=method_name or not isinstance(result['methods'].get('parameters'),dict)
                    or any(result['methods']['parameters'].get(k)!=v for k,v in parameters.items())):
                raise ValueError('comparison_fixed_method_mismatch')
            header('common_features',{'feature_id','symbol'});header('feature_exclusions',{'processed_version_id','feature_id','reason'})
            header('observation_exclusions',{'processed_version_id','barcode','reason'});design=doc('comparison_design')
            if design.get('executable') is not True or design.get('family')!=config['family_contrast_ids']:raise ValueError('comparison_design_output_invalid')
            if scope=='donor_inference':
                header('aggregation_units',{'contrast_id','unit_id','donor','condition','batch','spot_count','library_counts','observation_keys'})
                header('aggregation_members',{'contrast_id','unit_id','processed_version_id','barcode'})
                header('pseudobulk_counts',{'contrast_id','unit_id','feature_id','counts'})
                if not isinstance(doc('model_diagnostics'),list):raise ValueError('model_diagnostics_invalid')
    elif kind=='bio_resource_import':
        resource=doc('resource')
        for key in ('kind','species_taxon_id','namespace','release','source','usage','strip_ensembl_version'):
            if resource.get(key)!=config[key]:raise ValueError('resource_configuration_mismatch:'+key)
        expected_files=[{k:f[k] for k in ('file_id','sha256','format','role')} for f in config['files']]
        if (resource.get('schema_version')!=1 or resource.get('importer_version')!='bio_resource_import_v1'
                or resource.get('input_files')!=expected_files):raise ValueError('resource_input_identity_mismatch')
        methods=result['methods']
        for key in ('release','source','usage'):
            if methods.get(key)!=config[key]:raise ValueError('resource_method_metadata_mismatch')
        if methods.get('resource_kind')!=config['kind'] or methods.get('input_files')!=expected_files:raise ValueError('resource_method_kind_mismatch')
        if config['kind']=='gene_sets':
            if not isinstance(resource.get('terms'),list) or len(resource['terms'])>50000:raise ValueError('resource_terms_invalid')
            terms={};relations=0;genes=set()
            for term in resource['terms']:
                if (not isinstance(term,dict) or any(not isinstance(term.get(k),str) or not term[k] for k in ('term_id','name','namespace'))
                        or term['term_id'] in terms or not isinstance(term.get('genes'),list)
                        or any(not isinstance(g,str) or not g for g in term['genes']) or len(term['genes'])!=len(set(term['genes']))):
                    raise ValueError('resource_term_definition_invalid')
                terms[term['term_id']]={'name':term['name'],'namespace':term['namespace'],'remaining':set(term['genes'])}
                relations+=len(term['genes']);genes.update(term['genes'])
                if relations>5000000 or len(genes)>100000:raise ValueError('resource_relation_capacity_exceeded')
            for row in table('term_genes',{'term_id','term_name','namespace','feature_id'}):
                term=terms.get(row['term_id'])
                if (term is None or row['term_name']!=term['name'] or row['namespace']!=term['namespace']
                        or row['feature_id'] not in term['remaining']):raise ValueError('resource_term_table_mismatch')
                term['remaining'].remove(row['feature_id'])
            if any(t['remaining'] for t in terms.values()):raise ValueError('resource_term_table_incomplete')
            header('resource_exclusions',{'row_number','feature_id','term_id','reason'})
            header('functional_classification',{'category','gene_count','mutually_exclusive'})
        elif config['kind']=='id_mapping':
            if (resource.get('source_namespace'),resource.get('target_namespace'))!=(config['mapping_source_namespace'],config['mapping_target_namespace']):
                raise ValueError('resource_mapping_namespace_mismatch')
            if not isinstance(resource.get('mapping'),dict) or not isinstance(resource.get('ambiguous_source_ids'),list):raise ValueError('resource_mapping_invalid')
            header('mapping_rows',{'row_number','original_id','source_id','target_id'});header('mapping_exclusions',{'source_id','reason'})
        else:
            if not isinstance(resource.get('annotations'),list):raise ValueError('resource_annotations_invalid')
            header('annotations',{'feature_id','field','value','raw_value','value_type','unit','source','evidence_status'})
    elif kind=='bio_enrichment':
        base={'row_key','result_source_id','contrast_id','resource_id','term_id','term_name'}
        if config['kind']=='ora':
            header('enrichment_results',base|{'N','n','K','k','p_value','q_value'})
            if doc('ora_sets').get('schema_version')!=1:raise ValueError('ora_sets_invalid')
            if result['methods'].get('name')!='ORA_hypergeometric_right_tail':raise ValueError('ora_method_invalid')
            if result['methods'].get('correction')!='BH_contrast_direction_collection':raise ValueError('ora_correction_invalid')
            for key in ('merge_collections','q_column','q_threshold','minimum_absolute_effect','direction','min_size','max_size'):
                if result['methods'].get(key)!=config[key]:raise ValueError('ora_parameter_mismatch')
        else:
            header('enrichment_results',{'row_key','resource_id','term_id','es','nes','nominal_p_value','fdr_q_value','fwer_p_value'})
            header('gsea_ranking',{'rank','feature_id','statistic','source_feature_id','source_row_key'})
            curves=doc('gsea_curves')
            if curves.get('schema_version')!=1 or curves.get('rank_member_key')!='gsea_ranking' or curves.get('rank_zero_based') is not True:
                raise ValueError('gsea_curves_invalid')
            if (result['methods'].get('method')!='permutation' or result['methods'].get('threads')!=1
                    or result['methods'].get('no_plot') is not True or 'ascending' not in result['methods'] or result['methods']['ascending'] is not None
                    or result['methods'].get('correction')!='GSEA_joint_null_FDR_not_BH'):raise ValueError('gsea_method_invalid')
            for key in ('permutation_num','weight','seed','ranking_column','min_size','max_size'):
                if result['methods'].get(key)!=config[key]:raise ValueError('gsea_parameter_mismatch')
        header('mapping_rows',{'result_source_id','contrast_id','resource_id','original_id','target_id','reason'})
        header('mapping_exclusions',{'result_source_id','contrast_id','resource_id','feature_id','reason'})
        header('term_exclusions',{'result_source_id','contrast_id','resource_id','term_id','background_size','reason'})
        header('functional_classification',{'result_source_id','contrast_id','resource_id','category','background_gene_count','foreground_gene_count','mutually_exclusive'})
    elif kind=='bio_candidate':
        header('candidate_results',{'row_key','feature_id','rank','support_count','conflict_count','score','score_status','inference_scope','provenance'})
        header('candidate_evidence',{'feature_id','source_id','contrast_id','row_key','effect','q','q_column','inference_scope'})
        header('candidate_steps',{'step','operation','before_count','after_count','removed_count','source_counts','parameters'})
        header('candidate_exclusions',{'step','feature_id','reason'});header('mapping_exclusions',{'source_id','source_row','feature_id','reason'})
        header('missing_requested_features',{'step','feature_id','reason'})
        if doc('candidate_sets').keys()!={'source_sets','selected'} or result['methods'].get('recipe')!=config:raise ValueError('candidate_recipe_output_invalid')
    else:
        for fmt in config['formats']:require('figure_'+fmt,fmt)
        if not isinstance(doc('plot_data'),dict):raise ValueError('figure_plot_data_invalid')
        metadata=doc('figure_metadata')
        if metadata.get('config')!=config or result['methods'].get('config')!=config:raise ValueError('figure_configuration_mismatch')
        if any(result['methods'].get(k)!=v for k,v in metadata.items()) or metadata.get('analysis_recomputed') is not False:
            raise ValueError('figure_methods_invalid')
        if config.get('sample_groups'):
            from app.adapters.bio_insights_engine.quantitative_figures import validate_sample_plot
            validate_sample_plot(payload,doc('plot_data'))
        if config.get('figure_type','').startswith('evidence_'):
            from app.domain.bio_insights.evidence_graph import evidence_plot_data
            source=next(s for s in payload['sources'] if s['source_id']==config['result_source_id'])
            if doc('plot_data')!=evidence_plot_data(source,FigureConfig.model_validate(config)):raise ValueError('evidence_figure_data_mismatch')
        if config.get('figure_type','').startswith('integration_'):
            from app.domain.bio_insights.integration_graph import integration_plot_data
            source=next(s for s in payload['sources'] if s['source_id']==config['result_source_id'])
            if doc('plot_data')!=integration_plot_data(source,FigureConfig.model_validate(config)):raise ValueError('integration_figure_data_mismatch')
        if config.get('figure_type')=='qpcr_samples':
            from app.adapters.bio_insights_engine.qpcr_figures import qpcr_plot_data
            source=next(s for s in payload['sources'] if s['source_id']==config['result_source_id'])
            if doc('plot_data')!=qpcr_plot_data(source,FigureConfig.model_validate(config)):raise ValueError('qpcr_figure_data_mismatch')


def execute_bio_insights(payload,output_directory,*,cancel_event=None):
    from app.adapters.bio_child_cancel import require_not_revoked,terminate_revoked_child
    require_not_revoked(cancel_event)
    if sys.platform!='linux' or not Path(INTERPRETER).is_file():raise invalid('bio_insights_environment_unavailable')
    runtime=runtime_identity();limits=BioInsightsLimits();output=Path(output_directory).absolute()
    if payload.get('kind')=='bio_comparison' and payload.get('config',{}).get('schema_version')==5:
        from app.domain.bio_insights.settings import composition_runtime_identity
        runtime=composition_runtime_identity()
    if (payload.get('kind')=='bio_comparison' and payload.get('config',{}).get('schema_version')==3
            or payload.get('kind')=='bio_insight_figure' and payload.get('config',{}).get('figure_type')=='qpcr_samples'):
        from app.domain.bio_insights.settings import qpcr_runtime_identity
        runtime=qpcr_runtime_identity()
    if payload.get('kind')=='bio_comparison' and payload.get('config',{}).get('schema_version')==2:
        from app.domain.bio_insights.settings import quantitative_runtime_identity
        runtime=quantitative_runtime_identity()
    if payload.get('kind')=='bio_integration' and payload.get('config',{}).get('schema_version')==2:
        from app.domain.bio_insights.settings import topic_runtime_identity
        runtime=topic_runtime_identity(payload['config']['method'])
    elif payload.get('kind')=='bio_integration' or payload.get('kind')=='bio_resource_import' and payload.get('config',{}).get('kind') in ('sample_correspondence','object_correspondence') or payload.get('kind')=='bio_insight_figure' and payload.get('config',{}).get('figure_type','').startswith('integration_'):
        from app.domain.bio_insights.settings import integration_runtime_identity
        runtime=integration_runtime_identity()
    elif payload.get('kind')=='bio_feature_extract' or payload.get('kind')=='bio_resource_import' and payload.get('config',{}).get('kind') in ('sequence','structure') or payload.get('kind')=='bio_insight_figure' and payload.get('config',{}).get('figure_type','').startswith('feature_'):
        from app.domain.bio_insights.settings import feature_runtime_identity
        runtime=feature_runtime_identity()
    if not runtime.get('available'):raise invalid('bio_insights_environment_unavailable')
    if payload.get('kind') not in INSIGHT_TASKS:raise invalid('bio_insights_input_invalid')
    if output.is_symlink() or not output.is_dir() or any(output.iterdir()):raise invalid()
    try:
        for record in input_records(payload):
            path=Path(record['path']);size=record['size_bytes']
            if (not path.is_absolute() or path.is_symlink() or not path.is_file() or path.resolve().is_relative_to(output.resolve())
                    or type(size) is not int or not 0<size<=MAX_LEAF or path.stat().st_size!=size or file_sha(path)!=record['sha256']):raise ValueError()
        from app.adapters.bio_insights_engine.transport import project_transport_payload
        request={**project_transport_payload(payload),'output_directory':str(output),'_runtime_identity':runtime}
        data=json.dumps(request,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
        if len(data)>MAX_JSON:raise ValueError()
    except (KeyError,TypeError,ValueError,OSError) as exc:raise invalid('bio_insights_input_invalid') from exc
    stopped,exceeded=Event(),Event();threads=[];peak=[0]
    def started(pid):
        stat=Path(f'/proc/{pid}/stat');status=Path(f'/proc/{pid}/status');birth=stat.read_text().rsplit(')',1)[1].split()[19]
        def monitor():
            while not stopped.wait(.1):
                try:
                    if stat.read_text().rsplit(')',1)[1].split()[19]!=birth:return
                    if terminate_revoked_child(pid,birth,cancel_event):return
                    value=re.search(r'^VmRSS:\s+(\d+) kB$',status.read_text(),re.M)
                    rss=int(value.group(1))*1024 if value else 0;peak[0]=max(peak[0],rss)
                    if rss>limits.memory_bytes:exceeded.set();os.kill(pid,signal.SIGKILL);return
                except (OSError,ValueError,IndexError):return
        thread=Thread(target=monitor,daemon=True,name='bio-insights-rss');threads.append(thread);thread.start()
    from app.adapters.excel_process import _run_child
    command=[INTERPRETER,'-I','-B',str(Path(__file__).with_name('bio_insights_engine')/'worker.py'),str(os.getpid())]
    try:
        require_not_revoked(cancel_event)
        response=_run_child(command,struct.pack('!I',len(data))+data,timeout_seconds=limits.warmup_seconds+limits.compute_wall_seconds,
                            max_output_bytes=MAX_JSON,on_started=started)
    except StorageError as exc:
        require_not_revoked(cancel_event)
        code='bio_insights_resource_exceeded' if exceeded.is_set() or exc.code=='parse_resource_limit' else (
            'bio_insights_timeout' if exc.code=='parse_timeout' else 'bio_insights_environment_unavailable')
        raise invalid(code) from exc
    except OSError as exc:raise invalid('bio_insights_environment_unavailable') from exc
    finally:
        stopped.set()
        for thread in threads:thread.join(timeout=1)
    require_not_revoked(cancel_event)
    if type(response) is not dict:raise invalid()
    if set(response)=={'error'}:
        code=response['error'].get('code') if isinstance(response['error'],dict) else None
        if code not in ('bio_insights_input_invalid','bio_insights_output_invalid','bio_insights_environment_unavailable',
                        'bio_insights_isolation_unavailable','bio_insights_resource_exceeded','bio_insights_timeout','bio_insights_design_blocked',
                        'bio_insights_figure_layout_too_small'):
            code='bio_insights_output_invalid'
        raise invalid(code)
    if set(response)!={'result'}:raise invalid()
    result=validate_result(response['result'],output,payload)
    result['resources']={**result.get('resources',{}),'parent_peak_rss_bytes':peak[0]}
    return result
