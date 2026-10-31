import hashlib
import importlib
import json
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():yield None


def module():return importlib.import_module('app.adapters.bio_insights_process')


def member(root,key,content,fmt='json'):
    path=root/(key+'.'+fmt);path.write_bytes(content)
    return dict(key=key,path=str(path),format=fmt,role='table',size_bytes=len(content),sha256=hashlib.sha256(content).hexdigest())


def test_registered_members_are_checked_against_actual_bytes_and_directory(tmp_path):
    m=module(); record=member(tmp_path,'data',b'{"zero":0,"unknown":null}')
    assert m.validate_artifacts([record],tmp_path)==[record]
    for change in ({'sha256':'0'*64},{'size_bytes':True},{'path':str(tmp_path.parent/'else.json')},{'key':'../x'}):
        with pytest.raises(Exception):m.validate_artifacts([{**record,**change}],tmp_path)
    member(tmp_path,'extra',b'{}')
    with pytest.raises(Exception):m.validate_artifacts([record],tmp_path)


@pytest.mark.parametrize('content',[b'{"a":1,"a":2}',b'{"x":NaN}',b'{"x":Infinity}'])
def test_ambiguous_or_nonfinite_json_is_rejected(tmp_path,content):
    m=module();record=member(tmp_path,'data',content)
    with pytest.raises(Exception):m.validate_artifacts([record],tmp_path)


@pytest.mark.parametrize('content',[
    b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><image href="http://example.com/a.png"/></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg" onload="x()"/>',
])
def test_svg_is_not_a_script_or_external_resource_carrier(tmp_path,content):
    m=module();record=member(tmp_path,'plot',content,'svg')
    with pytest.raises(Exception):m.validate_artifacts([record],tmp_path)


def test_parent_rejects_wrong_manifest_identity_or_missing_members(tmp_path):
    from tests.domain.bio_insight_validation_fixtures import complete_import,import_payload
    m=module();payload=import_payload();result=complete_import(payload,tmp_path)
    assert m.validate_result(result,tmp_path,payload)==result
    with pytest.raises(Exception):m.validate_result(result,tmp_path,{**payload,'identity':{**payload['identity'],'task_id':'other'}})
    with pytest.raises(Exception):m.validate_result({**result,'outputs':[result['outputs'][-1]]},tmp_path,payload)


@pytest.mark.parametrize('fault',['scope','provenance','required_table','header','recipe','manifest_summary','source_bindings','methods_member','scientific_method','reported_peak_rss'])
def test_parent_rejects_semantically_incomplete_or_mislabeled_outputs(tmp_path,fault):
    from tests.domain.bio_insight_validation_fixtures import complete_import,import_payload,refresh,put
    payload=import_payload();result=complete_import(payload,tmp_path);result['_root']=str(tmp_path)
    if fault=='scope':result['inference_scope']=result['manifest']['inference_scope']='spot_exploratory'
    elif fault=='provenance':result['provenance']=result['manifest']['provenance']='system_computed'
    elif fault=='required_table':
        item=next(m for m in result['outputs'] if m['key']=='comparison_results');__import__('pathlib').Path(item['path']).unlink();result['outputs'].remove(item)
    elif fault=='header':put(result,'comparison_results',(['row_key','feature_id','p_value'],[{'row_key':'g1','feature_id':'g1','p_value':0}]),'tsv')
    elif fault=='recipe':put(result,'recipe',{**payload,'config':{**payload['config'],'numerator':'WRONG'}})
    elif fault=='manifest_summary':result['manifest']['summary']={'row_count':999}
    elif fault=='source_bindings':result['manifest']['source_bindings']=[{'source_id':'wrong'}]
    elif fault=='methods_member':put(result,'methods',{'name':'WRONG'})
    elif fault=='reported_peak_rss':result['resources']={'child_peak_rss_kib':2*1024**2+1}
    else:
        result['methods']={**result['methods'],'name':'WRONG'};result['manifest']['methods']=result['methods']
        put(result,'methods',result['methods']);put(result,'comparison_methods',result['methods'])
    refresh(result);result.pop('_root')
    with pytest.raises(Exception):module().validate_result(result,tmp_path,payload)


@pytest.mark.parametrize('field,value',[('kind','id_mapping'),('species_taxon_id',10090),('namespace','mouse_symbol'),
    ('release','wrong'),('usage',{'redistribution_allowed':True}),('input_files',[]),
    ('terms',[{'term_id':'t1','name':'invalid','namespace':'BP','genes':[42]}])])
def test_resource_document_must_match_fixed_configuration(tmp_path,field,value):
    from tests.domain.bio_insight_validation_fixtures import complete_resource,put,refresh
    payload,result=complete_resource(tmp_path)
    assert module().validate_result(result,tmp_path,payload)==result
    result['_root']=str(tmp_path)
    item=next(m for m in result['outputs'] if m['key']=='resource')
    resource=json.loads(__import__('pathlib').Path(item['path']).read_bytes());resource[field]=value
    put(result,'resource',resource);refresh(result);result.pop('_root')
    with pytest.raises(Exception):module().validate_result(result,tmp_path,payload)


def test_input_inventory_cannot_grant_arbitrary_nested_path(tmp_path):
    m=module(); record=member(tmp_path,'input',b'{}')
    payload={'kind':'bio_comparison','sources':[{'source_id':'s','members':{'a':record},'metadata':{'path':'/secret'}}]}
    with pytest.raises(Exception):m.input_records(payload)
    payload['sources'][0]['metadata']={}
    assert m.input_records(payload)==[record]


def test_host_never_falls_back_to_unsandboxed_science(tmp_path):
    m=module()
    if m.sys.platform=='linux':return
    with pytest.raises(Exception) as exc:m.execute_bio_insights({'kind':'bio_comparison'},tmp_path)
    assert exc.value.code=='bio_insights_environment_unavailable'
