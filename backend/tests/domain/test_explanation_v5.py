from copy import deepcopy
import json
import pytest
from app.core.exceptions import PlotError, StorageError
from app.domain.figure_workbench import explanations as e
from tests.domain.test_explanation_v5_history import GOLDENS

SOURCES=GOLDENS.parent/'source-bundles'

@pytest.fixture(autouse=True)
def postgres_schema():
    """Pure builders and guards; no DB, HTTP, numerical recomputation or model."""
    yield None

def bundles():
    return [json.loads(p.read_text(encoding='utf-8'))['bundle'] for p in GOLDENS.glob('*.json')]

def find(kind, lang='en', method=None):
    return deepcopy(next(b for b in bundles() if b['figure']['figure_kind']==kind and b['figure']['language']==lang and (method is None or b['result']['statistics']['method']==method)))

def narrative(payload):
    from app.domain.figure_workbench.explanation_v5 import sentence_draft_v5
    return sentence_draft_v5(payload)


def test_logistic_forest_explanation_projects_fixed_encoding_and_reference():
    bundle = find('forest', 'zh-CN', 'logistic')
    # The source may use text labels. Only the fitted model's normalized coding is part of the explanation.
    bundle['result']['selection']['positive'] = {'kind': 'text', 'value': 'source label kept local'}
    provenance = dict(model_call_id='offline', response_id='offline',
                      skills_trace={'skills': [{'name': 'statistical-reading', 'version': '1.2.1'}]})
    payload = e._artifact_payload(bundle, e.LATEST_VERSION, provenance)
    assert payload['facts']['method.outcome_encoding']['raw'] == {
        'column': 'A', 'name': 'Outcome', 'event': 1, 'non_event': 0,
    }
    assert payload['facts']['axis.x.reference']['raw'] == bundle['figure']['plot_config']['reference_line'] == 1
    assert 'method.outcome_encoding' in payload['required_references']['methods']
    assert 'axis.x.reference' in payload['required_references']['data']
    assert 'source label kept local' not in json.dumps(payload)

    draft = narrative(payload)
    draft['methods'] += ' 估计针对完整记录，而不是通过新增插补扩充的记录。'
    draft['paper_text'] = ('以{{scope.variables}}为范围，基于{{data.valid}}，采用{{purpose.kind}}呈现关联，'
                           '主要参数见{{modeling.coefficients.1.inference}}。{{limitation.0}}。')
    saved = e.render(bundle, draft, provenance)
    assert saved['draft'] == draft
    sections = {section['key']: section for section in saved['sections']}
    assert '新增插补扩充' not in sections['methods']['text']
    assert '主要参数见' in sections['paper_text']['text']
    assert 'method.outcome_encoding' in {fact['key'] for fact in sections['methods']['evidence']}
    paper_text = sections['paper_text']['text']
    assert paper_text.count('Exposure (B)') == 1
    assert '每增加 1 单位的比值比' in paper_text and '95% CI' in paper_text
    assert '仅绘制非截距项' in sections['data']['text']
    assert '基线概率' in sections['interpretation']['text']
    assert e.validate_saved(bundle, saved) == saved
    for invalid in (None, ' ', '字' * 4001):
        with pytest.raises(PlotError):
            e.render(bundle, {**draft, 'methods': invalid}, provenance)
    with pytest.raises(PlotError):
        e.render(bundle, {**draft, 'paper_text': draft['paper_text'].replace(
            'modeling.coefficients.1.inference', 'modeling.aic')}, provenance)
    provenance['skills_trace']['skills'][0]['version'] = '1.2.0'
    historical = e._artifact_payload(bundle, e.LATEST_VERSION, provenance)
    assert 'method.outcome_encoding' not in historical['facts']
    assert 'axis.x.reference' not in historical['facts']


@pytest.mark.parametrize(('language', 'bounds', 'wide'), [
    ('zh-CN', None, True),
    ('en', None, True),
    ('zh-CN', (8.8, 9.2), False),
    ('en', (None, None), False),
])
def test_logistic_forest_interprets_the_reported_or_interval(language, bounds, wide):
    from app.domain.figure_workbench.explanation_v5 import render_sections_v5

    bundle = find('forest', 'zh-CN', 'logistic')
    figure = bundle['figure']
    figure['language'] = language
    coefficients = bundle['result']['statistics']['coefficients']
    if bounds is not None:
        coefficients[0].update(or_ci_low=0.01, or_ci_high=100)
        coefficients[1].update(or_ci_low=bounds[0], or_ci_high=bounds[1])
        figure['statistics']['effects'][0].update(ci_low=bounds[0], ci_high=bounds[1])
    provenance = dict(model_call_id='offline', response_id='offline',
                      skills_trace={'skills': [{'name': 'statistical-reading', 'version': '1.2.1'}]})
    payload = e._artifact_payload(bundle, e.LATEST_VERSION, provenance)
    draft = narrative(payload)
    draft['paper_text'] = (
        'The figure uses {{purpose.kind}} to describe {{scope.variables}}. The analysis uses {{data.valid}}. '
        'The estimate is {{modeling.coefficients.1.inference}}. {{limitation.0}}.' if language == 'en' else
        '以{{scope.variables}}为范围，基于{{data.valid}}，采用{{purpose.kind}}呈现关联，'
        '主要参数见{{modeling.coefficients.1.inference}}。{{limitation.0}}。'
    )
    if not wide:
        draft['paper_text'] += (' The stored parameter is {{modeling.coefficients.0.inference}}.' if language == 'en'
                                else '保存的参数为{{modeling.coefficients.0.inference}}。')
    saved = e.render(bundle, draft, provenance)
    assert saved['draft'] == draft
    assert saved['payload_sha256'] == e.digest(payload)
    assert e.validate_saved(bundle, saved) == saved
    sections = {section['key']: section for section in saved['sections']}
    width = 'confidence interval for term B is wide' if language == 'en' else '参数 B 的 95% 比值比置信区间较宽'
    span = 'more than ten times' if language == 'en' else '超过下限的 10 倍'
    precision = 'limited precision' if language == 'en' else '估计精度有限'
    boundary = ('cannot replace validation in an independent sample' if language == 'en' else '无法替代独立样本验证')
    no_refit = 'without introducing an independent sample or refitting the model' if language == 'en' else '没有引入独立样本或重新拟合模型'
    for key in ('interpretation', 'paper_text'):
        section = sections[key]
        assert boundary in section['text'] and no_refit in section['text']
        assert all((phrase in section['text']) == wide for phrase in (width, span, precision))
        if wide:
            assert 'modeling.coefficients.1.inference' in {item['key'] for item in section['evidence']}
    if wide:
        assert '2.15086–37.6593' in sections['paper_text']['text']

    historical = deepcopy(saved)
    historical['provenance'].pop('section_renderer')
    historical['sections'] = render_sections_v5(draft, payload)
    assert all(boundary not in section['text'] for section in historical['sections'])
    assert e.validate_saved(bundle, historical) == historical
    for explanation in (saved, historical):
        reused = e.reuse(bundle, bundle, explanation)
        assert e.validate_saved(bundle, reused)['sections'] == explanation['sections']

    unverified = deepcopy(bundle)
    unverified['figure']['plot_config'].pop('verification_scope')
    unverified_sections = e.render(unverified, draft, provenance)['sections']
    assert all(boundary not in section['text'] for section in unverified_sections)


@pytest.mark.parametrize('language', ['en', 'zh-CN'])
def test_statistical_skills_render_a_compact_manuscript_from_frozen_facts(language, monkeypatch):
    from app.domain.figure_workbench import skill_approval

    monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', 'statistical_explanation')
    bundle = find('line', language)
    payload = e.build_payload(bundle)
    approved, base = skill_approval.prepare(payload, bundle, None, {})

    assert 'Validated sentence frames' not in base
    snapshot = approved['skills_snapshot']
    assert snapshot['trace']['skills'][0]['version'] == '1.2.1'
    assert approved['effective_instructions'] == base + '\n\n' + snapshot['instructions']
    manuscript = approved['payload']
    assert manuscript['facts'] == payload['facts']
    for section, refs in payload['required_references'].items():
        if section != 'paper_text':
            assert manuscript['required_references'][section] == refs
    draft = narrative(payload)
    draft['paper_text'] = (
        'We used {{purpose.kind}} to describe {{scope.variables}}. '
        'The plot includes {{data.valid}}, whereas the original analysis used {{data.original_n}}. '
        'The values rose from {{projection.0.coordinates}}. {{limitation.0}}.' if language == 'en' else
        '采用{{purpose.kind}}描述{{scope.variables}}。图中纳入{{data.valid}}。'
        '观测值从{{projection.0.coordinates}}上升。{{limitation.0}}。'
    )
    provenance = dict(model_call_id='offline', response_id='offline', skills_trace=snapshot['trace'])
    saved = e.render(bundle, draft, provenance)
    assert e.validate_saved(bundle, saved) == saved
    paper = saved['sections'][-1]
    assert '(1.0, 2.0)' in paper['text'] and '(5.0, 20.0)' in paper['text']
    assert 'Applicable limitation:' not in paper['text'] and '适用限制:' not in paper['text']
    coordinates = next(item for item in paper['evidence'] if item['key'] == 'projection.0.coordinates')
    assert coordinates['value'] == payload['facts']['projection.0.coordinates']['value']
    derived = e.reuse(bundle, bundle, saved)
    assert e.validate_saved(bundle, derived)['sections'] == saved['sections']

    for invalid in ('{{limitation.0}}', '999'):
        bad_paper = draft['paper_text'].replace('{{projection.0.coordinates}}', invalid)
        with pytest.raises(PlotError):
            e.render(bundle, {**draft, 'paper_text': bad_paper}, provenance)


@pytest.mark.parametrize('language', ['en', 'zh-CN'])
def test_legacy_statistical_skills_pack_retains_the_validated_sentence_frames(language, monkeypatch, tmp_path):
    from app.domain.figure_workbench import skill_approval
    from app.domain.runtime_skills import registry
    from tests.domain.test_runtime_skills import skill

    skill(tmp_path, 'statistical-reading')
    registry.publish(tmp_path)
    monkeypatch.setenv('PAPERASSIST_SKILLS_DIR', str(tmp_path))
    monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', 'statistical_explanation')
    bundle = find('line', language)
    payload = e.build_payload(bundle)
    approved, base = skill_approval.prepare(payload, bundle, None, {})
    rules = 'Use the supplied sentence frames for numerical results, record populations, and limitations.'
    assert rules in base
    assert 'Keep literal count labels, metric names, and participant terminology inside their bound facts' in base
    marker = 'Validated sentence frames for this payload:\n'
    supplied = json.loads(base.split(marker, 1)[1])
    assert supplied == narrative(payload)
    assert len(e.render(bundle, supplied, {'model_call_id': 'offline', 'response_id': 'offline'})['sections']) == 6
    assert approved['effective_instructions'].startswith(base + '\n\n')
    assert rules not in e.instructions_for(payload)

@pytest.mark.parametrize('bundle',bundles(),ids=lambda b:b['figure']['figure_kind']+'-'+b['figure']['language'])
def test_every_actual_kind_has_substantial_six_sentence_sections(bundle):
    assert e.LATEST_VERSION == 'figure_explanation_v5'
    payload=e.build_payload(bundle)
    assert payload['figure_explanation_contract']==5
    saved=e.render(bundle,narrative(payload),{'model_call_id':'offline','response_id':'offline'})
    assert e.validate_saved(bundle,saved)==saved
    assert len(saved['sections'])==6
    for s in saved['sections']:
        assert s['text'] and s['evidence']
        assert '{{' not in s['text']
    paper=saved['sections'][-1]
    assert set(payload['required_references']['results']).issubset({f['key'] for f in paper['evidence']})

@pytest.mark.parametrize('method',['ols','logistic'])
@pytest.mark.parametrize('lang',['zh-CN','en'])
def test_parameter_identity_and_applicable_scales(method,lang):
    b=find('forest','en' if method=='ols' else 'zh-CN');b['figure']['language']=lang
    p=e.build_payload(b)
    facts=[v for k,v in p['facts'].items() if k.startswith('modeling.coefficients.')]
    assert len(facts)==2
    assert ('Intercept' if lang=='en' else '截距') in facts[0]['value']
    assert 'Exposure' in facts[1]['value'] and 'B' in facts[1]['value'] and 'beta' in facts[1]['value']
    assert all('or_value' not in fact['value'] for fact in p['facts'].values())
    if method=='ols':assert 'or_value' not in json.dumps(p)
    assert ('OR' in facts[1]['value']) == (method=='logistic')
    forbidden=('r_squared','adjusted_r_squared','residual_sd') if method=='logistic' else ('log_likelihood','deviance','aic')
    assert not any('modeling.'+key in p['facts'] for key in forbidden)
    text=e.render(b,narrative(p),{'model_call_id':'x','response_id':'y'})['sections'][3]['text']
    assert 'Exposure' in text and ('Intercept' if lang=='en' else '截距') in text

@pytest.mark.parametrize('bad',['missing_term','wrong_column','missing_reference'])
def test_parameter_identity_cannot_be_guessed(bad):
    b=find('forest');c=b['result']['statistics']['coefficients'][1]
    if bad=='missing_term':c.pop('term')
    elif bad=='wrong_column':c['column']='Z'
    else:c.update(level={'kind':'text','value':'treated'},reference=None)
    with pytest.raises(StorageError):e.build_payload(b)

def test_literal_labels_and_dimensionless_units_survive_one_substitution():
    b=find('forest');literal='Exposure; {{data.valid}}.. ()'
    b['result']['variables'][1]['name']=literal
    b['figure']['presentation']['axes']['y']['unit']='0–1'
    p=e.build_payload(b);s=e.render(b,narrative(p),{'model_call_id':'x','response_id':'y'})['sections']
    assert literal in s[3]['text']
    assert p['facts']['axis.y.unit']['value']=='0–1'
    assert p['facts']['axis.x.unit']['value']=='Unit not specified'

@pytest.mark.parametrize('stat,error,expected,excluded',[
    ('count','none',(),('denominator','sd','reason')),
    ('proportion','none',('denominator',),('sd','reason')),
    ('mean','sd',('sd','reason'),('denominator',)),
])
def test_bar_only_applicable_facts(stat,error,expected,excluded):
    b=find('bar');r=b['projection']['result'];r['method'].update(bar_stat=stat,error_bars=error)
    for series in r['series']:series.update(sd=None,reason='insufficient_n_for_sd',denominator=4)
    p=e.build_payload(b)
    for key in expected:assert any(k.endswith('.'+key) for k in p['facts'])
    for key in excluded:assert not any(k.startswith('projection.') and k.endswith('.'+key) for k in p['facts'])
    notes=' '.join(e._limitations(b,e.LATEST_VERSION))
    if stat=='count':assert 'denominator' not in notes and 'standard deviation' not in notes
    if stat=='mean':assert 'cannot be computed' in json.dumps(p)

def test_line_preserves_every_coordinate_and_original_population():
    b=find('line');p=e.build_payload(b)
    for i,series in enumerate(b['projection']['result']['series']):
        assert p['facts'][f'projection.{i}.coordinates']['raw']['points']==series['points']
    assert p['facts']['data.original_n']['raw']==b['result']['check']['valid_count']
    assert any('different population' in n for n in e._limitations(b,e.LATEST_VERSION))

@pytest.mark.parametrize('mode',['fragments','title_n','no_verb','punctuation','independence','free_number','free_metric','causal'])
def test_v5_rejects_incomplete_or_unsafe_prose(mode):
    b=find('bar');p=e.build_payload(b);d=narrative(p)
    if mode=='fragments':d={k:'; '.join('{{'+r+'}}' for r in refs) for k,refs in p['required_references'].items()}
    elif mode=='title_n':d['paper_text']='{{figure.title}} {{data.valid}}.'
    elif mode=='no_verb':d['purpose']='The displayed context: '+' '.join('{{'+r+'}}' for r in p['required_references']['purpose'])+'.'
    elif mode=='punctuation':d['purpose']+='..'
    else:d['interpretation']+={'independence':' Independent observations were confirmed.','free_number':' There are 12 records.','free_metric':' The mean is high.','causal':' This causes improvement.'}[mode]
    with pytest.raises(PlotError):e.render(b,d,{'model_call_id':'x','response_id':'y'})

def test_new_figure_pair_only_accepts_v5_and_old_version_tampering_fails():
    b=find('bar');old=json.loads(next(p for p in GOLDENS.glob('*.json') if json.loads(p.read_text(encoding='utf-8'))['bundle']['figure']['id']==b['figure']['id']).read_text(encoding='utf-8'))['saved_explanation']
    bad=deepcopy(old);bad['engine']['id']='figure_explanation_v5'
    with pytest.raises(StorageError):e.validate_saved(b,bad)
    b['figure']['engine']['id']='openai_figure_workbench_v4';b['figure']['presentation']['schema_version']=3
    assert e.version_for(b['figure'])=='figure_explanation_v5'
    with pytest.raises(StorageError):e.version_for(b['figure'],version='figure_explanation_v4')

@pytest.mark.parametrize('lang',['en','zh-CN'])
@pytest.mark.parametrize('kind',['boxplot','scatter','correlation_heatmap','line','bar','violin','forest','roc_curve','kaplan_meier'])
def test_all_kinds_in_both_languages_and_no_owned_double_punctuation(kind,lang):
    b=find(kind);b['figure']['language']=lang
    b['result']['analysis_context']['plan']['research_request']['output_language']=lang
    p=e.build_payload(b)
    assert p['language']==lang
    s=e.render(b,narrative(p),{'model_call_id':'offline','response_id':'offline'})['sections']
    assert not any(token in section['text'] for section in s for token in ('..','。。','.。','。.', '()'))
    assert all(('This figure' in section['text'] or 'The ' in section['text'] or 'Interpreting ' in section['text']) if lang=='en' else any(c in section['text'] for c in '本保解') for section in s)

def test_categorical_parameter_reference_alias_and_wrong_term():
    b=find('forest');c=b['result']['statistics']['coefficients'][1]
    level={'kind':'text','value':'Treated'};reference={'kind':'text','value':'Control'}
    c.update(term='B:Treated',level=level,reference=reference)
    b['result']['selection']['covariates'][0].update(type='categorical',levels=[reference,level],reference=reference)
    b['configuration']['config']['style']['aliases']['B']='Public alias'
    p=e.build_payload(b);v=p['facts']['modeling.coefficients.1.inference']['value']
    assert all(x in v for x in ('Exposure','Public alias','B:Treated','Treated','Control'))
    c['term']='A:Treated'
    with pytest.raises(StorageError):e.build_payload(b)

def test_ungrouped_violin_has_explicit_axis_semantics():
    b=find('violin');b['figure']['presentation']['axes']['x']['label']=''
    p=e.build_payload(b)
    assert p['facts']['axis.x.label']['value']=='Not applicable (ungrouped)'

def test_roc_and_km_missing_quantities_keep_real_reasons_and_scientific_limits():
    b=find('roc_curve');b['result']['statistics']['confidence_interval'].update(low=None,high=None,reason='evaluation_role_not_independent')
    p=e.build_payload(b)
    assert 'independent' in p['facts']['modeling.confidence_interval']['value']
    assert any('external validation' in n for n in e._limitations(b,e.LATEST_VERSION))
    b=find('kaplan_meier');g=b['result']['statistics']['groups'][0];g.update(median=None,median_reason='not_reached')
    p=e.build_payload(b)
    assert 'not reached' in p['facts']['modeling.groups.0.median_reason']['value']
    assert any('censor' in n and 'log-rank' in n for n in e._limitations(b,e.LATEST_VERSION))

def test_v5_policy_keeps_existing_six_string_shape_and_rejects_tools():
    from app.domain.explanation_policy import derive_execution_policy,validate_execution_policy
    from tests.domain.test_explanation_policy import execution_policy
    p=e.build_payload(find('bar'));policy=execution_policy();policy['input_token_allowance']=1000000
    value=derive_execution_policy(policy,p)
    assert value['policy']['prompt_version']=='figure_explanation_v5'
    assert value['policy']['output_format']=='analysis_explanation_v2'
    bad=deepcopy(value);bad['policy']['tools']=['code_interpreter']
    with pytest.raises(StorageError):validate_execution_policy(bad,p)
    bad=deepcopy(value);bad['policy']['output_format']='text'
    with pytest.raises(StorageError):validate_execution_policy(bad,p)

@pytest.mark.parametrize('error',['none','sd'])
def test_mean_without_valid_values_always_keeps_reason(error):
    b=find('bar');r=b['projection']['result'];r['method'].update(bar_stat='mean',error_bars=error)
    for s in r['series']:
        for point in s.get('points',[s]):point.update(value=None,sd=None,reason='no_valid_values')
    p=e.build_payload(b)
    assert any(k.endswith('.reason') and 'No valid values' in f['value'] for k,f in p['facts'].items())

def test_successful_mean_sd_has_no_null_unavailable_reason():
    b=find('bar');r=b['projection']['result'];r['method'].update(bar_stat='mean',error_bars='sd')
    for s in r['series']:
        for point in s.get('points',[s]):point.update(value=4.,sd=1.,reason=None)
    p=e.build_payload(b)
    assert not any(k.startswith('projection.') and k.endswith('.reason') for k in p['facts'])

def test_model_diagnostics_remain_readable_and_parameter_name_not_duplicated():
    b=find('forest');p=e.build_payload(b)
    assert not any(x in p['facts']['modeling.diagnostics']['value'] for x in ('condition_number','gradient_max'))
    s=e.render(b,narrative(p),{'model_call_id':'offline','response_id':'offline'})['sections'][3]
    assert s['text'].count('Exposure')==1

def test_comparison_boundary_keeps_no_independent_inference_reproduction():
    from app.domain.figure_workbench.explanation_v5 import limitations_v5
    b=find('boxplot');b['result'].update(result_type='group_comparison',statistics={
        'method':'welch_t','design':'independent','family':{'policy':'none'},'confidence_interval':{'reason':None}})
    b['result']['selection'].update(design='independent',assumptions={'independent_units':True,'distribution':'normal','inference_confirmed':True})
    notes=limitations_v5(b)
    assert any('without independently reproducing local inference algorithms' in note for note in notes)

@pytest.mark.parametrize('kind',['forest','scatter','line'])
def test_independence_limit_is_semantically_unique(kind):
    b=find(kind);notes=e._limitations(b,e.LATEST_VERSION)
    assert sum(any(s in note for s in ('independence was not verified','independence was not programmatically verified','program does not prove them')) for note in notes)==1
    if kind=='line':
        assert sum('caus' in note for note in notes)==1

def test_successful_roc_interval_does_not_expose_irrelevant_null_reason():
    b=find('roc_curve');b['result']['statistics']['confidence_interval'].update(low=.5,high=1.,reason=None)
    p=e.build_payload(b)
    assert 'Unavailable or not supplied' not in p['facts']['modeling.confidence_interval']['value']

def test_reached_km_median_omits_only_inapplicable_missing_reason():
    b=find('kaplan_meier')
    for group in b['result']['statistics']['groups']:group.update(median=4.,median_reason=None)
    p=e.build_payload(b)
    assert not any(k.endswith('.median_reason') for k in p['facts'])
    assert any(k.endswith('.median') for k in p['facts'])

@pytest.mark.parametrize('path',list(SOURCES.glob('*.json')),ids=lambda p:p.name)
def test_all_actual_source_bundles_preview_v5_without_old_saved_explanation(path):
    source=json.loads(path.read_text(encoding='utf-8'))
    assert source['saved_explanation_included'] is False
    b=source['bundle'];p=e.build_payload(b)
    assert p['figure_explanation_contract']==5
    value=e.render(b,narrative(p),{'model_call_id':'offline-preview','response_id':'offline-preview'})
    assert e.validate_saved(b,value)==value
    assert len(value['sections'])==6

def test_actual_enline_scope_uses_projection_a_c_not_statistical_a_b():
    source=json.loads((SOURCES/'3be278aa-3ea5-4af9-b98e-4257c30f15fd.json').read_text(encoding='utf-8'))
    b=source['bundle'];p=e.build_payload(b)
    assert b['configuration']['config']['projection']['y_column']=='C'
    assert b['result']['variables'][1]=={'column':'B','name':'Y','unit':''}
    assert 'Observation' in p['facts']['scope.variables']['value']
    assert 'C' in p['facts']['scope.variables']['value']
    assert 'Y' not in p['facts']['scope.variables']['value']
    assert 'B' not in p['facts']['scope.variables']['value']
    sections=e.render(b,narrative(p),{'model_call_id':'offline','response_id':'offline'})['sections']
    for section in (sections[0],sections[-1]):
        assert 'Observation' in section['text']
        assert 'Y' not in section['text']
        assert 'B' not in section['text']
    assert p['facts']['data.original_n']['raw']==4
    assert p['facts']['data.valid']['raw']==5

@pytest.mark.parametrize('kind',['line','bar','violin'])
def test_projection_scope_uses_only_confirmed_roles_labels_and_units(kind):
    b=find(kind);b['result']['variables']=[{'column':'Z','name':'UNPLOTTED','unit':'wrong'}]
    rules=b['configuration']['config']['projection'];axes=b['figure']['presentation']['axes']
    rules.update(x_column='C' if kind=='line' else None,y_column='D' if kind!='bar' else None,category_column='C' if kind=='bar' else None)
    axes['x'].update(label='Confirmed category' if kind=='bar' else 'Confirmed x',unit='day')
    axes['y'].update(label='Confirmed value' if kind!='bar' else 'Record count',unit='0–1' if kind!='bar' else 'records')
    p=e.build_payload(b);v=p['facts']['scope.variables']['value']
    assert 'UNPLOTTED' not in v and 'wrong' not in v and 'Z' not in v
    assert 'Confirmed value' in v if kind!='bar' else 'Confirmed category' in v
    assert 'D' in v if kind!='bar' else 'C' in v
    assert '0–1' in v if kind!='bar' else 'records' in v

@pytest.mark.parametrize('lang',['en','zh-CN'])
def test_guard_rejects_predicate_followed_by_reference_fragment(lang):
    b=find('bar');b['figure']['language']=lang;p=e.build_payload(b);d=narrative(p)
    d['purpose']='This figure describes {{scope.variables}}. {{purpose.kind}}.' if lang=='en' else '本图用于描述{{scope.variables}}。 {{purpose.kind}}。'
    with pytest.raises(PlotError):e.render(b,d,{'model_call_id':'offline','response_id':'offline'})

@pytest.mark.parametrize('tail',[' . . ',' 。 。 ',' ; ; '])
def test_guard_rejects_spaced_repeated_punctuation(tail):
    b=find('bar');p=e.build_payload(b);d=narrative(p);d['purpose']+=tail
    with pytest.raises(PlotError):e.render(b,d,{'model_call_id':'offline','response_id':'offline'})

@pytest.mark.parametrize('lang',['en','zh-CN'])
def test_guard_accepts_bound_parenthetical_fact_without_modifying_literal_label(lang):
    b=find('bar');b['figure']['language']=lang;p=e.build_payload(b);d=narrative(p)
    d['purpose']='This figure describes {{scope.variables}} ({{purpose.kind}}).' if lang=='en' else '本图用于描述{{scope.variables}}（{{purpose.kind}}）。'
    value=e.render(b,d,{'model_call_id':'offline','response_id':'offline'})
    assert value['sections'][0]['text']

@pytest.mark.parametrize('lang',['en','zh-CN'])
def test_guard_checks_each_sentence_in_all_six_sections(lang):
    b=find('bar');b['figure']['language']=lang;p=e.build_payload(b)
    lead='This figure describes ' if lang=='en' else '本图用于描述'
    separator='. ' if lang=='en' else '。 '
    d={section:lead+separator.join('{{'+ref+'}}' for ref in refs)+separator.strip() for section,refs in p['required_references'].items()}
    with pytest.raises(PlotError):e.render(b,d,{'model_call_id':'offline','response_id':'offline'})

def test_guard_still_rejects_really_empty_parentheses():
    b=find('bar');p=e.build_payload(b);d=narrative(p);d['purpose']+=' ()'
    with pytest.raises(PlotError):e.render(b,d,{'model_call_id':'offline','response_id':'offline'})

@pytest.mark.parametrize('kind',['line','bar','violin'])
def test_projection_scope_includes_only_the_confirmed_group_role(kind):
    b=find(kind);b['configuration']['config']['projection']['group_column']='G'
    b['configuration']['config']['style']['aliases']['G']='Confirmed grouping'
    if kind=='violin':b['figure']['presentation']['axes']['x']['label']='Confirmed grouping'
    else:b['figure']['presentation']['legend']['title']='Confirmed grouping'
    p=e.build_payload(b);v=p['facts']['scope.variables']['value']
    assert 'Confirmed grouping' in v and 'G' in v
