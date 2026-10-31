"""Complete synthetic lifecycle envelopes, explicitly not numerical evidence."""
import csv
import io
import hashlib
import json
from pathlib import Path


def portable(value):
    if isinstance(value,dict):return {k:portable(v) for k,v in value.items() if k not in ('path','output_directory','_runtime_identity')}
    if isinstance(value,list):return [portable(v) for v in value]
    return value


def refresh(result):
    outputs=result['outputs'];manifest=result['manifest']
    manifest['members']=[{k:v for k,v in m.items() if k!='path'} for m in outputs if m['key']!='manifest']
    item=next(m for m in outputs if m['key']=='manifest')
    content=json.dumps(manifest,ensure_ascii=False).encode();Path(item['path']).write_bytes(content)
    item.update(size_bytes=len(content),sha256=hashlib.sha256(content).hexdigest())


def put(result,key,value,fmt='json'):
    if fmt=='json':content=json.dumps(value,ensure_ascii=False).encode()
    else:
        fields,rows=value;stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fields,delimiter='\t',lineterminator='\n')
        writer.writeheader()
        for row in rows:writer.writerow({k:('' if v is None else json.dumps(v) if isinstance(v,(dict,list)) else v) for k,v in row.items()})
        content=stream.getvalue().encode()
    root=Path(result['_root']);path=root/(key+'.'+fmt);path.write_bytes(content)
    item=dict(key=key,format=fmt,role='table',path=str(path.resolve()),size_bytes=len(content),sha256=hashlib.sha256(content).hexdigest())
    previous=next((m for m in result['outputs'] if m['key']==key),None)
    if previous:previous.update(item)
    else:result['outputs'].append(item)


def complete_import(payload,output):
    from app.domain.bio_insights.contracts import ResultImportConfig
    config=ResultImportConfig.model_validate(payload['config']).model_dump(mode='json')
    methods=dict(name='external_result_import',original_method=config['original_method'],original_correction_scope=config['original_correction_scope'],
        no_model_fitted=True,original_values_preserved=True,system_q_is_original_q=False,
        complete_tested_universe=config['complete_tested_universe'],species_taxon_id=config['species_taxon_id'],
        namespace=config['namespace'],reference_version=config['reference_version'],upstream_inference_scopes=['external_result'],data_driven_grouping=False)
    result=dict(_root=str(output),schema_version=1,status='completed',engine_version='bio_insights_v1.0.0',kind=payload['kind'],
        identity=payload['identity'],summary={'synthetic_lifecycle_fixture':True,'row_count':2,'feature_count':2,'contrast_count':1,
        'tested_universe_complete':config['complete_tested_universe']},methods=methods,inference_scope='external_result',provenance='external_result',outputs=[])
    values=[]
    for i,feature in enumerate(['g1','g2']):
        row=dict(row_key=feature,feature_id=feature,p_value=0 if i==0 else None,original_q=None if i==0 else .2,
            symbol=feature,contrast_id=config['contrast_id'],numerator=config['numerator'],denominator=config['denominator'],
            observation_level=config['observation_level'],inference_scope='external_result',effect_name=config['effect_name'],
            effect_value=2 if i==0 else -2,effect_unit=config['effect_unit'],statistic=None,q_within_contrast=None,q_global_family=None,
            correction_family_id='synthetic-family',n_numerator=None,n_denominator=None,spots_numerator=None,spots_denominator=None,
            donors_numerator=None,donors_denominator=None,test_status='external_result' if i==0 else 'not_computable',
            reason=None if i==0 else 'external_p_missing',tested=True,provenance={'synthetic_lifecycle_fixture':True},
            original_p_value='0' if i==0 else 'NA',original_effect='2' if i==0 else '-2',system_recomputed_q=None,
            source_row=i+2,source_cells={'gene':feature,'effect':'2' if i==0 else '-2','p':'0' if i==0 else 'NA'})
        values.append(row)
    put(result,'comparison_results',(list(values[0]),values),'tsv')
    put(result,'import_exclusions',(['row_key','source_row','feature_id','reason'],[]),'tsv')
    put(result,'correction_families',{'external':{'family_size':2,'valid_p_values':1,'na_p_values':1,
        'complete_tested_universe':config['complete_tested_universe'],'recomputed':config['recompute_q'],'method':None}})
    put(result,'comparison_methods',methods);put(result,'methods',methods);put(result,'recipe',portable(payload))
    result['manifest']=dict(schema_version=1,engine_version=result['engine_version'],kind=payload['kind'],identity=payload['identity'],
        summary=result['summary'],methods=methods,inference_scope=result['inference_scope'],provenance=result['provenance'],
        provenance_details={},source_bindings=portable(payload['sources']),members=[])
    put(result,'manifest',{});refresh(result);result.pop('_root')
    return result


def import_payload():
    return {'schema_version':1,'kind':'bio_result_import','identity':{'task_id':'task','source_digest':'a'*64},'sources':[],
        'config':dict(kind='result_import',file_source_id='file',parse_version_id='parse',species_taxon_id=9606,
            namespace='ensembl',reference_version='v1',columns={'feature_id':'gene','effect':'effect','p_value':'p'},
            contrast_id='c',numerator='A',denominator='B',original_method='existing tool',original_correction_scope='unknown')}


def complete_resource(output):
    from app.domain.bio_insights.contracts import ResourceImportRequest
    config=ResourceImportRequest.model_validate({'kind':'gene_sets','title':'fixture','species_taxon_id':9606,'namespace':'ensembl','release':'v1',
        'source':{'institution':'synthetic','name':'synthetic','description':'lifecycle only'},
        'usage':{'basis':'synthetic','scope':'project','redistribution_allowed':False},
        'files':[{'file_id':'file1','sha256':'a'*64,'role':'gmt','format':'gmt'}]}).model_dump(mode='json')
    payload={'schema_version':1,'kind':'bio_resource_import','identity':{'task_id':'task','source_digest':'a'*64},'config':config,'sources':[]}
    files=[{k:f[k] for k in ('file_id','sha256','format','role')} for f in config['files']]
    methods={k:config[k] for k in ('release','source','usage')};methods.update(resource_kind='gene_sets',input_files=files)
    result=dict(_root=str(output),schema_version=1,status='completed',engine_version='bio_insights_v1.0.0',kind=payload['kind'],
        identity=payload['identity'],summary={'synthetic_lifecycle_fixture':True},methods=methods,inference_scope='derived',provenance='system_computed',outputs=[])
    data={k:config[k] for k in ('kind','species_taxon_id','namespace','release','source','usage','strip_ensembl_version')}
    data.update(schema_version=1,importer_version='bio_resource_import_v1',input_files=files,
                terms=[{'term_id':'t1','name':'t1','namespace':'BP','genes':['g1']}])
    put(result,'resource',data);put(result,'term_genes',(['term_id','term_name','namespace','feature_id'],
        [{'term_id':'t1','term_name':'t1','namespace':'BP','feature_id':'g1'}]),'tsv')
    put(result,'resource_exclusions',(['row_number','feature_id','term_id','reason'],[]),'tsv')
    put(result,'functional_classification',(['category','gene_count','mutually_exclusive'],[]),'tsv')
    put(result,'methods',methods);put(result,'recipe',portable(payload))
    result['manifest']=dict(schema_version=1,engine_version=result['engine_version'],kind=payload['kind'],identity=payload['identity'],
        summary=result['summary'],methods=methods,inference_scope='derived',provenance='system_computed',source_bindings=[],members=[])
    put(result,'manifest',{});refresh(result);result.pop('_root')
    return payload,result
