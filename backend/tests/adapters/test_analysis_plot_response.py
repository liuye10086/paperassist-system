from copy import deepcopy
from io import BytesIO
import json
import pytest
from PIL import Image


def expected():
    return {'schema_version':2,'figure_kind':'scatter','language':'en','correlation_method':'pearson','mode':'pair',
        'title':'Figure 1','x_label':'A (cm)','y_label':'B (kg)','caption':'Complete records.',
        'variables':[{'column':'A','name':'A','unit':'cm'},{'column':'B','name':'B','unit':'kg'}],
        'statistics':{'n':4,'coefficient':0.0},'plot_config':{'regression_line':False,'inference_displayed':False}}


def png():
    stream=BytesIO(); Image.new('RGB',(1600,1000),'white').save(stream,format='PNG'); return stream.getvalue()


def parsed():
    return {'files':{'figure.png':'cfile_png','result.json':'cfile_json'},
        'provenance':{'response_id':'resp_test','container_id':'cntr_test','png_file_id':'cfile_png','result_file_id':'cfile_json'}}


def test_modern_parse_accepts_figure_png_only_after_completed_container_call():
    from app.domain.plot_response import parse_plot_response
    response={'id':'resp_test','status':'completed','output':[
        {'type':'code_interpreter_call','container_id':'cntr_test','status':'completed','code':'untrusted saved text'},
        {'type':'message','content':[{'annotations':[{'type':'container_file_citation','container_id':'cntr_test',
            'filename':name,'file_id':file} for name,file in parsed()['files'].items()]}]}]}
    assert parse_plot_response(response,'cntr_test',expected())['files']==parsed()['files']


@pytest.mark.parametrize('change,path', [('coefficient','statistics.coefficient'),('count','statistics.n'),('language','language'),
    ('label','variables.0.name'),('p_value','statistics.p_value')])
def test_modern_mismatches_return_bounded_diff_and_receipts(change,path):
    from app.domain.plot_response import download_plot, PlotVerificationError
    actual=deepcopy(expected())
    if change=='coefficient': actual['statistics']['coefficient']=0.5
    elif change=='count': actual['statistics']['n']=True
    elif change=='language': actual['language']='zh-CN'
    elif change=='label': actual['variables'][0]['name']='Wrong'
    else: actual['statistics']['p_value']=0.01
    class Provider:
        def download(self,file_id,*args,**kwargs): return png() if file_id=='cfile_png' else json.dumps(actual).encode()
    with pytest.raises(PlotVerificationError) as error: download_plot(parsed(),Provider(),None,expected())
    assert error.value.code=='plot_result_mismatch'
    assert any(item['path']==path for item in error.value.differences)
    assert error.value.provenance['response_id']=='resp_test'
    assert error.value.manifest['statistics']==actual['statistics']


def test_correlation_near_zero_allows_small_absolute_rounding_error():
    from app.adapters.openai_plot import validate_output
    actual=deepcopy(expected()); actual['statistics']['coefficient']=1e-14
    validate_output({'manifest':actual,'png':png()},expected())


def test_public_policy_configuration_derives_fixed_modern_contract_without_changing_money():
    from app.domain import plot_policy, explanation_policy
    plot={'policy':{'model':'synthetic','prompt_version':'openai_boxplot_v1','max_output_tokens':10000,
        'timeout_seconds':15,'tools':['code_interpreter'],'output_format':'text','price':{
            'version':'test','currency':'USD','model':'synthetic','input_micro_usd_per_million':1,
            'cached_input_micro_usd_per_million':1,'output_micro_usd_per_million':1,'cache_write_micro_usd_per_million':1}},
        'input_token_allowance':100000,'task_limit_micro_usd':1000000,'tool_reserve_micro_usd':1000,'tool_reserve_version':'test'}
    derived=plot_policy.derive_execution_policy(plot,{'schema_version':2})
    assert derived['policy']['prompt_version']=='openai_analysis_plot_v2'
    assert derived['policy']['price']==plot['policy']['price'] and derived['task_limit_micro_usd']==1000000
    explanation={key:value for key,value in plot.items() if not key.startswith('tool_')}
    explanation['policy']={**plot['policy'],'tools':[],'prompt_version':'analysis_explanation_v1','output_format':'analysis_explanation_v1'}
    derived=explanation_policy.derive_execution_policy(explanation,{'schema_version':2})
    assert derived['policy']['prompt_version']==derived['policy']['output_format']=='analysis_explanation_v2'
    assert derived['policy']['price']==plot['policy']['price']
