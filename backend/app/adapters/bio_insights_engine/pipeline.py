"""One output envelope for six typed offline B04 operations."""
from pathlib import Path
from app.adapters.bio_engine.manifest import Writer, clean
from .transport import project_transport_payload,hydrate_single_cell_annotations

ENGINE_VERSION='bio_insights_v1.0.0'


def portable(value):
    if isinstance(value,dict):return {key:portable(item) for key,item in value.items() if key not in ('path','output_directory','_runtime_identity')}
    if isinstance(value,list):return [portable(item) for item in value]
    return value


def run(payload):
    transported=project_transport_payload(payload)
    payload=hydrate_single_cell_annotations(transported)
    from .comparison import run_comparison
    from .result_import import run_result_import
    from .resources import run_resource_import
    from .enrichment import run_enrichment
    from .candidates import run_candidates
    from .figures import run_figure
    from .feature_extract import run_feature_extract
    from .integration import run_integration
    dispatch={'bio_comparison':run_comparison,'bio_result_import':run_result_import,'bio_resource_import':run_resource_import,
              'bio_enrichment':run_enrichment,'bio_candidate':run_candidates,'bio_insight_figure':run_figure,'bio_feature_extract':run_feature_extract,'bio_integration':run_integration}
    if payload['kind']=='bio_integration' and payload['config'].get('schema_version')==2:
        from .single_cell_topics import run_topics
        dispatch['bio_integration']=run_topics
    if payload['kind']=='bio_candidate' and payload['config'].get('schema_version')==2:
        from .external_evidence import run_external_evidence
        dispatch['bio_candidate']=run_external_evidence
    if payload['kind']=='bio_comparison' and payload['config'].get('schema_version')==2:
        from .quantitative import run_quantitative
        dispatch['bio_comparison']=run_quantitative
    if payload['kind']=='bio_comparison' and payload['config'].get('schema_version')==3:
        from .qpcr import run_qpcr
        dispatch['bio_comparison']=run_qpcr
    if payload['kind']=='bio_comparison' and payload['config'].get('schema_version')==4:
        from .microbiome import run_microbiome
        dispatch['bio_comparison']=run_microbiome
    if payload['kind']=='bio_comparison' and payload['config'].get('schema_version')==5:
        from .single_cell_composition import run_composition
        dispatch['bio_comparison']=run_composition
    if payload.get('schema_version')!=1 or payload.get('kind') not in dispatch:raise ValueError('unsupported_insight_task')
    writer=Writer(payload['output_directory']);writer.identity=payload['identity']
    result=clean(dispatch[payload['kind']](payload,writer))
    if not all(isinstance(result.get(key),dict) for key in ('summary','methods')):raise ValueError('invalid_engine_result')
    if isinstance(result.get('provenance'),dict):
        result['provenance_details']=result['provenance']
        result['provenance']='external_result' if payload['kind']=='bio_result_import' else 'system_computed'
    scopes=set()
    for source in payload['sources']:
        meta=source.get('metadata',{});scopes.update(meta.get('upstream_inference_scopes',[]))
        if meta.get('inference_scope') in ('spot_exploratory','donor_inference','sample_exploratory','sample_inference','external_result'):scopes.add(meta['inference_scope'])
    if result['inference_scope'] in ('spot_exploratory','donor_inference','sample_exploratory','sample_inference','external_result'):scopes.add(result['inference_scope'])
    result['methods']['upstream_inference_scopes']=sorted(scopes)
    result['methods']['data_driven_grouping']=bool(payload['config'].get('data_driven_grouping') or
        any(s.get('metadata',{}).get('data_driven_grouping') is True for s in payload['sources']))
    writer.json('methods',result['methods'])
    writer.json('recipe',portable(transported))
    manifest=dict(schema_version=1,engine_version=ENGINE_VERSION,kind=payload['kind'],identity=payload['identity'],
                  summary=result['summary'],methods=result['methods'],inference_scope=result['inference_scope'],
                  provenance=result['provenance'],provenance_details=result.get('provenance_details',{}),source_bindings=portable(transported['sources']),
                  members=[{k:v for k,v in item.items() if k!='path'} for item in writer.artifacts])
    writer.json('manifest',manifest)
    return dict(schema_version=1,engine_version=ENGINE_VERSION,kind=payload['kind'],identity=payload['identity'],status='completed',
                outputs=writer.artifacts,manifest=manifest,**result)
