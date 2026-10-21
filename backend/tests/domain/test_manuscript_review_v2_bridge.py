"""Compatibility projection is valid only for exact server-verified artifacts."""
from copy import deepcopy
import pytest
from tests.domain.test_manuscript_review import sample
from app.domain.manuscript_writing.context import normalize_sections
from app.domain.manuscripts.draft import flat_values
from app.domain.manuscript_review.checks import check_snapshot

@pytest.fixture(autouse=True)
def postgres_schema(): yield None

def fixture():
    snapshot=sample();snapshot['output_language']='zh-CN'
    snapshot['sections']=normalize_sections(snapshot)
    snapshot['writing_provenance']=dict(schema_version=2,review_id='science',language_review_id='language')
    p=snapshot['sections'][3]['paragraphs'][0]
    p.update(text='mean = 27.555; n = 12',numeric_bindings=[dict(kind='study',occurrence=0,source_alias='s1',fact_path='/overall/mean',value='27.555',evidence_id=None),dict(kind='study',occurrence=1,source_alias='s1',fact_path='/overall/n',value='12',evidence_id=None)])
    source=snapshot['sources'][0]
    rows=list(flat_values(dict(overall=source['content']['overall']),en=False))
    table=dict(id='t',number=1,title='统计表',columns=['项目','数值'],source_ids=['run'],rows=rows)
    original=deepcopy(table);table['rows'][0][0]='经人工核对的指标标签'
    snapshot['results_groups'][0]['tables']=[table]
    return snapshot,original

def context(snapshot,original):
    from app.domain.manuscript_review.writing_context import WritingCheckContext
    p=snapshot['sections'][3]['paragraphs'][0]
    return WritingCheckContext(paragraphs={p['id']:dict(paragraph=deepcopy(p),text=p['text'],aliases={'s1':'run'})},
        sources={s['id']:deepcopy(s) for s in snapshot['sources']},tables={'/results_groups/0/tables/0':dict(original=original,language='zh-CN',approved=deepcopy(snapshot['results_groups'][0]['tables'][0]))})

def errors(snapshot,authority=None):
    kwargs={} if authority is None else dict(writing_context=authority)
    return [i for i in check_snapshot(snapshot,**kwargs) if i['category']=='numeric' and i['severity']=='error']

def test_verified_v2_occurrences_and_exact_language_label_pass_existing_numeric_checks():
    snapshot,original=fixture()
    assert not errors(snapshot,context(snapshot,original))
    assert errors(snapshot), 'A provenance label alone must never authorize v2 facts or translations'

@pytest.mark.parametrize('change',['number','metric','alias','source','order','occurrence','text_order','table_number','table_label','table_source','table_order','table_metric','fake_provenance'])
def test_v2_compatibility_never_waives_exact_facts_or_table_identity(change):
    snapshot,original=fixture();authority=context(snapshot,original)
    p=snapshot['sections'][3]['paragraphs'][0];t=snapshot['results_groups'][0]['tables'][0]
    if change=='number':p['numeric_bindings'][0]['value']='999'
    if change=='metric':p['numeric_bindings'][0]['fact_path']='/overall/median'
    if change=='alias':p['numeric_bindings'][0]['source_alias']='s2'
    if change=='source':snapshot['sources'][0]['content']['overall']['mean']=999
    if change=='order':p['numeric_bindings'].reverse()
    if change=='occurrence':p['numeric_bindings'][0]['occurrence']=1
    if change=='text_order':p['text']='n = 12; mean = 27.555'
    if change=='table_number':t['rows'][0][1]='999'
    if change=='table_label':t['rows'][0][0]='未核验的翻译'
    if change=='table_source':t['source_ids']=[]
    if change=='table_order':t['rows'].reverse()
    if change=='table_metric':t['rows'][0][0]=t['rows'][1][0]
    if change=='fake_provenance':snapshot['writing_provenance']['language_review_id']='forged';authority=None
    assert errors(snapshot,authority)

def test_even_authoritative_paragraph_still_checks_explicit_equal_value_metric():
    snapshot,original=fixture()
    snapshot['sections'][3]['paragraphs'][0]['numeric_bindings'][0]['fact_path']='/overall/median'
    assert errors(snapshot,context(snapshot,original))

def test_authorized_table_labels_do_not_hide_an_invalid_original_table():
    snapshot,original=fixture();original['rows'].reverse()
    assert errors(snapshot,context(snapshot,original))


def test_exact_new_claim_evidence_numbers_use_reviewed_text_before_rendered_citations():
    snapshot,original=fixture();p=snapshot['sections'][3]['paragraphs'][0]
    text='A prior report included 45 participants.'
    p.update(text=text+' (1)',source_ids=[],numeric_bindings=[dict(kind='literature',occurrence=0,value='45',evidence_id='reviewed-new-claim-evidence',source_alias=None,fact_path=None)])
    authority=context(snapshot,original);authority.paragraphs[p['id']]['text']=text
    assert not errors(snapshot,authority)
    p['numeric_bindings'][0]['evidence_id']='unreviewed-evidence'
    assert errors(snapshot,authority)
