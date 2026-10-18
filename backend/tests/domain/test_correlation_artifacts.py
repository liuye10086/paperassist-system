from copy import deepcopy
import pytest


def result(language='en', mode='pair'):
    return {'id': 'run', 'file_id': 'file', 'filename': 'source.xlsx', 'source_sha256': 'a'*64,
        'schema_version': 3, 'result_type': 'correlation', 'setup_revision': 1,
        'analysis_plan': {'id': 'plan', 'sha256': 'b'*64},
        'analysis_context': {'plan': {'research_request': {'output_language': language, 'research_question': 'PRIVATE ORIGINAL'}}},
        'selection': {'task_type': 'correlation', 'sheet_name': 'PRIVATE SHEET', 'columns': ['A', 'B'],
                      'units': {'A':'cm','B':'kg'}, 'method': 'pearson', 'mode': mode},
        'variables': [{'column':'A','name':'PRIVATE NAME','unit':'cm'}, {'column':'B','name':'Weight','unit':'kg'}],
        'check': {'row_count': 5, 'valid_count': 4, 'excluded_count': 1, 'groups': [], 'issues':[], 'warnings':[]},
        'statistics': {'method':'pearson','mode':mode,'n':4, 'coefficient':0.8 if mode=='pair' else None,
            'matrix': [[1.0,0.8],[0.8,1.0]] if mode=='matrix' else None,
            'p_value': {'value':0.2 if mode=='pair' else None,'method':'pearson_beta_two_sided' if mode=='pair' else None,
                        'reason':None if mode=='pair' else 'exploratory_matrix'},
            'confidence_interval':{'low':-0.5 if mode=='pair' else None,'high':0.99 if mode=='pair' else None,
                'level':0.95,'method':'fisher_z' if mode=='pair' else None,'reason':None if mode=='pair' else 'exploratory_matrix'},
            'inference': {'alternative':'two-sided','rank_method':None,'permutation_type':None,'n_resamples':None,'seed':None,'exact':None},
            'warnings':[]}}


def confirmed(value, task_type='boxplot', summary=''):
    from app.domain.external_processing import freeze_confirmation, disclosure
    snapshot = {'result':value,'file':{'id':'file','filename':'source.xlsx'},'output_language':'en'}
    if task_type == 'explanation':
        snapshot['figure'] = {'id':'figure','title':'Figure 1. Correlation','sha256':'c'*64}
    preview = disclosure(snapshot, task_type, 'owner')
    labels = {item['key']:item['value'] for item in preview['labels']}
    labels['field:A'] = 'Height'
    if task_type == 'explanation': labels['research_summary'] = summary
    return freeze_confirmation(snapshot,task_type,'owner',
        {'version':4,'confirmed':True,'source_digest':preview['source_digest'],'labels':labels})


def test_modern_disclosure_requires_confirmed_summary_without_copying_original():
    from app.domain.external_processing import disclosure, normalize_confirmation
    value = result()
    snapshot = {'result':value,'file':{'filename':'source.xlsx'},'figure':{'title':'Figure 1'},'output_language':'en'}
    preview = disclosure(snapshot,'explanation','owner')
    assert preview['version'] == 4
    labels = {item['key']:item['value'] for item in preview['labels']}
    assert labels['research_summary'] == ''
    assert 'numeric_name' not in labels and labels['unit:A'] == 'cm'
    assert preview['summary']['figure_kind'] == 'scatter'
    normalize_confirmation({'version':4,'confirmed':True,'source_digest':'x','labels':{**labels,'research_summary':'line\n\tend'}})
    from app.core.exceptions import StorageError
    with pytest.raises(StorageError):
        normalize_confirmation({'version':4,'confirmed':True,'source_digest':'x','labels':{**labels,'research_summary':'bad\x01'}})


def test_modern_confirmation_rejects_non_string_label_key_as_public_error():
    from app.domain.external_processing import normalize_confirmation
    from app.core.exceptions import StorageError
    with pytest.raises(StorageError):
        normalize_confirmation({'version':4,'confirmed':True,'source_digest':'x','labels':{7:'bad'}})


@pytest.mark.parametrize('mode,kind', [('pair','scatter'),('matrix','correlation_heatmap')])
def test_cloud_material_only_contains_confirmed_labels_rows_and_deterministic_metadata(mode, kind):
    from app.domain.correlation_material import build_material
    value = result(mode=mode)
    external = confirmed(value)
    payload, expected = build_material(value, [[1.,2.],[2.,1.],[3.,4.],[4.,3.]], external=external)
    assert payload['values'] == [[1.,2.],[2.,1.],[3.,4.],[4.,3.]]
    assert payload['variables'][0] == {'column':'A','name':'Height','unit':'cm'}
    assert expected['statistics']['n'] == 4 and expected['figure_kind'] == kind
    assert set(expected['statistics']) == ({'n','coefficient'} if mode=='pair' else {'n','matrix'})
    assert not any(key in payload for key in ('statistics','analysis_run_id','source_sha256','research_summary'))
    assert 'PRIVATE' not in repr(payload)
    assert expected['plot_config']['inference_displayed'] is False
    if mode == 'matrix': assert expected['plot_config']['color_range'] == [-1.0,1.0]


def test_modern_explanation_sends_confirmed_summary_but_never_original_or_rows():
    from app.domain.external_material import explanation_material
    from app.domain.artifact_contracts import figure_renderer
    value = result()
    figure = {'id':'figure','analysis_run_id':'run','sha256':'c'*64,'source_sha256':'a'*64,
              'title':'Figure 1. Correlation','figure_number':1,'language':'en','engine':{'id':figure_renderer(value)}}
    external = confirmed(value,'explanation','Approved study summary')
    local, outbound = explanation_material(value,figure,external)
    assert outbound['research_summary'] == 'Approved study summary'
    assert outbound['facts']['variables.0.name']['value'] == 'Height'
    assert outbound['language'] == 'en'
    assert 'PRIVATE' not in repr(outbound)
    assert not any(key in outbound for key in ('values','source_sha256','analysis_run_id','figure_id','figure_sha256'))
    assert 'correlation.p_value' in local['facts']


def test_matrix_fact_catalogue_contains_all_coefficients_but_no_inference():
    from app.domain.explanation_content import build_payload
    payload = build_payload(result(mode='matrix'), {'id':'figure','title':'Figure 1','figure_number':1,'sha256':'c'*64})
    assert all(f'matrix.{row}.{column}' in payload['facts'] for row in range(2) for column in range(2))
    assert 'correlation.p_value' not in payload['facts']
    assert 'correlation.confidence_interval' not in payload['facts']


@pytest.mark.parametrize('prose', ['A statistically significant correlation.','This causes improvement.',
    'The coefficient is eight.','P value was small.','相关具有统计学意义。','证明存在因果关系。'])
def test_modern_draft_rejects_free_inference_causal_claims_and_number_words(prose):
    from app.domain.explanation_content import build_payload, render_explanation
    from app.core.exceptions import PlotError
    payload = build_payload(result(),{'id':'figure','title':'Figure 1','figure_number':1,'sha256':'c'*64})
    draft = {key:'Based on '+', '.join('{{'+ref+'}}' for ref in refs)+'.' for key,refs in payload['required_references'].items()}
    draft['interpretation'] += prose
    with pytest.raises(PlotError): render_explanation(draft,payload)


def test_modern_six_sections_render_in_english():
    from app.domain.explanation_content import build_payload, render_explanation
    payload = build_payload(result(),{'id':'figure','title':'Figure 1','figure_number':1,'sha256':'c'*64})
    draft = {key:'Based on '+', '.join('{{'+ref+'}}' for ref in refs)+'.' for key,refs in payload['required_references'].items()}
    sections=render_explanation(draft,payload)
    assert sections[0]['title']=='Analysis purpose'
    assert len(sections)==6 and '{{' not in sections[3]['text']


def test_english_cautious_limitations_are_allowed_but_unscoped_inference_is_not():
    from app.domain.explanation_content import build_payload,render_explanation
    payload=build_payload(result(),{'id':'figure','title':'Figure 1','figure_number':1,'sha256':'c'*64})
    draft={key:'Based on '+', '.join('{{'+ref+'}}' for ref in refs)+'.' for key,refs in payload['required_references'].items()}
    draft['interpretation']+=' Correlation does not establish causation. These data cannot prove treatment effectiveness.'
    assert render_explanation(draft,payload)[4]['text'].endswith('effectiveness.')
