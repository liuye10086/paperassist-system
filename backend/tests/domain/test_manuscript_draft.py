"""Canonical frozen rendering survives PostgreSQL JSONB key ordering."""
import json
from app.domain.manuscripts.contracts import ManuscriptRequest
from app.domain.manuscripts.draft import freeze


def test_result_table_is_independent_of_json_object_key_order():
    source=dict(kind='analysis_run',id='run',file_id='file',role='computed_results',label='Saved result',sha256='a'*64,download_url='/saved',
        content=dict(result_type='correlation',statistics={'coefficient':0.5,'n':8,'p_value':{'value':None,'reason':'unavailable'}},
            check={'valid_count':8,'excluded_count':2},selection={'method':'pearson'},engine={'id':'frozen_engine'}))
    request=ManuscriptRequest(title='Canonical fact draft',output_language='en',sources=[{k:source[k] for k in ('kind','id','file_id','role')}],
        results_groups=[dict(id='main',title='Main',analysis_run_ids=['run'])])
    first=freeze(None,'project',request,frozen_sources=[source])
    assert first['results_groups'][0]['tables'][0]['title'].startswith('Table 1.')
    assert 'Table 1' in first['results_groups'][0]['paragraphs'][0]['text']
    assert 'n = 8' in first['results_groups'][0]['paragraphs'][0]['text']
    assert '0.5' in first['results_groups'][0]['paragraphs'][0]['text']
    roundtripped=json.loads(json.dumps(first,sort_keys=True))
    second=freeze(None,'project',request,frozen_sources=roundtripped['sources'])
    assert second==first


def test_english_saved_system_notes_and_algorithms_are_localized_without_translating_user_labels():
    source=dict(kind='analysis_run',id='run',file_id='file',role='computed_results',label='User variable X',sha256='a'*64,download_url='/saved',
        content=dict(result_type='correlation',statistics={'method':'pearson','mode':'pair','n':8,'coefficient':0.5,
            'p_value':{'value':0.1,'method':'pearson_beta_two_sided'},'confidence_interval':{'low':0.1,'high':0.8,'method':'fisher_z'},
            'warnings':['correlation_not_causation','small_sample']},check={'issues':['样本量较小，结果可能不稳定。']},
            selection={'method':'pearson'},engine={'id':'frozen_engine'},variables=[{'name':'用户原始变量','unit':''}]))
    request=ManuscriptRequest(title='English fact draft',output_language='en',sources=[{k:source[k] for k in ('kind','id','file_id','role')}],
        results_groups=[dict(id='main',title='Main',analysis_run_ids=['run'])])
    snapshot=freeze(None,'project',request,frozen_sources=[source])
    text=json.dumps(snapshot['results_groups'],ensure_ascii=False)
    assert '样本量较小' not in text
    for code in ('pearson_beta_two_sided','fisher_z','correlation_not_causation','small_sample'): assert code not in text
    assert 'Small-sample' in text
    assert '用户原始变量' in text
