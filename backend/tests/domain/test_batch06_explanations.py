import copy
import pytest
from app.domain.figure_workbench import explanations as e
from app.core.exceptions import StorageError, PlotError
def bundle():
    return {'result':{'id':'r','check':{'valid_count':8}},'figure':{'id':'f','sha256':'a'*64,'facts_sha256':'b'*64,'language':'en','title':'Outcome','caption':'Descriptive records','figure_kind':'bar','source':{'kind':'prepared_dataset_version'},'analysis_run_id':'r'},'configuration':{'config':{'figure_kind':'bar','language':'en','projection':{},'style':{'title':'','caption':'','aliases':{},'display_order':[],'palette':'blue'}}},'projection':{'result':{'audit':{'valid_n':4,'population_n':5,'excluded_n':1},'method':{'kind':'bar'},'series':[{'group':None,'points':[{'category':'A','n':4,'value':1.0,'denominator':4,'sd':None,'reason':None}]}]}}}




def modern(kind='bar',lang='en'):
    b=bundle();f=b['figure'];f.update(figure_kind=kind,language=lang,engine={'id':'openai_figure_workbench_v2'},presentation={'schema_version':1,'axes':{'x':{'label':'Time','unit':'day'},'y':{'label':'Weight','unit':'kg'}},'statistical_notes':[]})
    b['projection']['result']['method'].update(kind=kind,aggregation='mean',bar_stat='mean',error_bars='sd')
    b['projection']['result']['series'][0]['points'][0]['reason']='insufficient_n_for_sd'
    return b


def draft(p):
    return {k:'; '.join('{{'+r+'}}' for r in refs) for k,refs in p['required_references'].items()}


@pytest.mark.parametrize('kind',['line','bar','violin'])
@pytest.mark.parametrize('lang',['en','zh-CN'])
def test_v2_axes_counts_methods_reasons_and_safe_design(kind,lang):
    b=modern(kind,lang);b['result']['analysis_context']={'plan':{'research_request':{'question':'PRIVATE QUESTION','study_design':'PRIVATE DESIGN','observation_structure':'repeated'}}}
    p=e.build_payload(b)
    assert p.get('figure_explanation_contract')==2
    assert p['facts']['axis.x.unit']['raw']=='day'
    assert p['facts']['axis.y.unit']['raw']=='kg'
    assert p['facts']['data.original_n']['raw']==8
    assert p['facts']['data.valid']['raw']==4
    assert 'PRIVATE' not in str(p)
    assert 'insufficient_n_for_sd' not in p['facts']['projection.0.point.0.reason']['value']
    assert p['facts']['design.structure']['raw']=='repeated'
    assert p['facts']['method.summary']['raw']!=b['figure']['caption']
    assert all(v['label']!=k.split('.')[-1] for k,v in p['facts'].items())


def test_v2_binding_limitations_and_payload_provenance():
    b=modern();p=e.build_payload(b);v=e.render(b,draft(p),{'model':'fake','model_call_id':'call','response_id':'response'})
    assert v['engine']['id']=='figure_explanation_v2'
    assert len(v['limitations'])>2
    e.validate_saved(b,v)
    for mutate in (lambda v:v.update(limitations=[]),lambda v:v['provenance'].update(input_sha256='bad'),lambda v:v['provenance'].update(prompt_version=e.VERSION)):
        bad=copy.deepcopy(v);mutate(bad)
        with pytest.raises(StorageError):e.validate_saved(b,bad)
    changed=copy.deepcopy(b);changed['figure']['presentation']['axes']['y']['unit']='g'
    with pytest.raises(StorageError):e.reuse(b,changed,v)


def test_legacy_version_and_explicit_v2_instructions():
    b=bundle();p=e.build_payload(b)
    assert e.VERSION=='figure_explanation_v1'
    assert e.version_for(b['figure'])==e.VERSION
    assert 'figure_explanation_contract' not in p
    assert e.instructions_for(p)==e.INSTRUCTIONS
    assert e.instructions_for(e.build_payload(modern()))!=e.INSTRUCTIONS


@pytest.mark.parametrize('text',['p < 0.05','causes improvement','according to Smith et al.','randomized trial','{{missing.fact}}'])
def test_v2_rejects_unfrozen_assertions(text):
    b=modern();p=e.build_payload(b);d=draft(p);d['interpretation']+=' '+text
    with pytest.raises(PlotError):e.render(b,d,{})


def test_unknown_design_never_infers_study_type_and_missing_sd_is_readable():
    b=modern('bar','zh-CN');p=e.build_payload(b)
    assert p['facts']['design.structure']['raw']=='unknown'
    assert '未提供' in p['facts']['design.status']['value']
    assert p['facts']['projection.0.point.0.reason']['value']=='有效记录不足两条，无法计算样本标准差。'
    b['projection']['result']['series'][0]['points'][0]['reason']='no_valid_values'
    assert e.build_payload(b)['facts']['projection.0.point.0.reason']['value']=='无有效数值，无法计算统计值。'


def test_v2_reuse_checks_compatibility_provenance_and_result_identity():
    b=modern();p=e.build_payload(b);v=e.render(b,draft(p),{'model_call_id':'c','response_id':'r'})
    new=copy.deepcopy(b);new['figure']['id']='f2';new['figure']['sha256']='e'*64
    new['configuration']['config']['style']['palette']='gray'
    reused=e.reuse(b,new,v);e.validate_saved(new,reused)
    for mutate in (lambda v:v['provenance'].update(compatibility_sha256='bad'),lambda v:v.update(analysis_run_id='other'),lambda v:v.update(source_sha256='bad')):
        bad=copy.deepcopy(reused);mutate(bad)
        with pytest.raises(StorageError):e.validate_saved(new,bad)


def test_legacy_payload_matches_independent_frozen_shape():
    from app.domain.external_processing import digest
    b=bundle();p=e.build_payload(b)
    assert digest(p)=='a7b057bd21c4e978376d52b8edbd3d1c910b623711b44994d5f732f6be48302b'


def test_v2_fact_limit_blocks_instead_of_truncating():
    b=modern();b['projection']['result']['series'][0]['points']*=100
    with pytest.raises(StorageError):e.build_payload(b)

def test_repeated_observations_are_an_explicit_saved_limitation():
    b=modern();b['result']['analysis_context']={'plan':{'research_request':{'observation_structure':'repeated'}}}
    p=e.build_payload(b);v=e.render(b,draft(p),{'model_call_id':'c','response_id':'r'})
    assert any('repeated' in text.lower() for text in v['limitations'])

def test_v2_saved_limitations_explicitly_exclude_pixel_verification():
    b=modern();p=e.build_payload(b);v=e.render(b,draft(p),{'model_call_id':'c','response_id':'r'})
    assert any('pixel' in text.lower() for text in v['limitations'])

@pytest.mark.parametrize('field,value',[('id','figure_explanation_v1'),('provider','forged'),('model','forged')])
def test_v2_engine_metadata_must_match_provenance(field,value):
    b=modern();p=e.build_payload(b);v=e.render(b,draft(p),{'model':'known','model_call_id':'c','response_id':'r'})
    v['engine'][field]=value
    with pytest.raises(StorageError):e.validate_saved(b,v)

def test_projection_retains_original_method_restrictions():
    b=modern();b['result']['result_type']='regression'
    p=e.build_payload(b);v=e.render(b,draft(p),{'model_call_id':'c','response_id':'r'})
    assert any('independent cloud model refit' in text for text in v['limitations'])

@pytest.mark.parametrize('text',[
    'All observations were independent.', 'The study was a clinical trial.', 'This was a double-blind study.',
    '所有观察相互独立。', '本研究为临床试验。', '本研究采用双盲设计。', '所有样本均独立。', '采用单盲研究。',
])
def test_v2_rejects_unbound_independence_trial_and_blinding(text):
    language='zh-CN' if any('\u4e00'<=c<='\u9fff' for c in text) else 'en'
    b=modern(lang=language);p=e.build_payload(b);d=draft(p);d['interpretation']+=' '+text
    with pytest.raises(PlotError):e.render(b,d,{})

@pytest.mark.parametrize('language,title',[('en','All observations were independent. The study was a clinical trial. This was a double-blind study.'),('zh-CN','所有观察独立，临床试验，双盲设计。')])
def test_v2_literal_fact_text_remains_data_under_design_guard(language,title):
    b=modern(lang=language);b['figure']['title']=title;p=e.build_payload(b)
    assert e.render(b,draft(p),{})['sections'][0]['text']==title


def test_v1_design_prose_guard_behavior_is_unchanged():
    b=bundle();p=e.build_payload(b);d=draft(p);d['interpretation']+=' All observations were independent. The study was a clinical trial. This was a double-blind study.'
    assert e.render(b,d,{})['engine']['id']==e.VERSION

@pytest.mark.parametrize('text',['本研究是前瞻性研究。','本研究是回顾性研究。','本研究是观察性研究。'])
def test_v2_rejects_unbound_chinese_observational_design(text):
    b=modern(lang='zh-CN');p=e.build_payload(b);d=draft(p);d['interpretation']+=' '+text
    with pytest.raises(PlotError):e.render(b,d,{})
