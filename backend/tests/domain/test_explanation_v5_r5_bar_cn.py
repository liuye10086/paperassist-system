"""Original R5 bar receipt, point identity and complete Chinese directives."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from app.core.exceptions import PlotError
from app.domain.figure_workbench import explanations as e
from app.domain.figure_workbench.explanation_v5 import validate_draft_v5,sentence_draft_v5

F=json.loads((Path(__file__).parents[1]/'fixtures/figure_b07/real-v5-response-bar-zh.json').read_text(encoding='utf8'))

@pytest.fixture(autouse=True)
def postgres_schema():yield None

def check(text):
    draft=sentence_draft_v5(F['payload']);draft['results']+=' '+text
    validate_draft_v5(draft,F['payload'])

@pytest.mark.parametrize('section',F['draft'])
def test_original_bar_sections_accept_complete_bound_prose(section):
    draft=sentence_draft_v5(F['payload']);draft[section]=F['draft'][section]
    validate_draft_v5(draft,F['payload'])

def test_original_bar_render_saved_keeps_draft_identity_and_frozen_input():
    from app.domain.model_usage.gateway import input_digest
    payload=e.build_payload(F['bundle'])
    assert payload==F['payload'] and e.instructions_for(payload)==F['instructions']
    assert input_digest(instructions=F['instructions'],payload=payload)==F['model_input_digest']
    value=e.render(F['bundle'],F['draft'],{'model_call_id':'offline-r5-bar','response_id':F['source_response_id']})
    assert e.validate_saved(F['bundle'],value)==value and value['draft']==F['draft']
    for section in value['sections']:
        for item in section['evidence']:
            fact=payload['facts'][item['key']]
            assert item=={'key':item['key'],'label':fact['label'],'value':fact['value']}
            assert fact['label']+': '+fact['value'] in section['text']

@pytest.mark.parametrize('text',[
    '类别{{projection.0.point.0.category}}的投影记录数为{{projection.0.point.0.n}}，绘图统计值为{{projection.0.point.0.value}}。',
    '类别{{projection.0.point.0.category}}的投影记录数为{{projection.0.point.0.n}}，类别{{projection.0.point.1.category}}的绘图统计值为{{projection.0.point.1.value}}。',
    '另行报告的原统计有效记录数为{{data.original_n}}，不与投影记录口径混同。',
    '同时应注意{{limitation.1}}。',
    '研究背景的核查受到以下限制：{{limitation.2}}。',
    '研究背景仍存在以下核查限制：{{limitation.2}}。',
    '观察独立性的核查状态为{{limitation.3}}。',
    '科学推断须遵守以下边界：{{limitation.4}}。',
    '读取保存数值时应注意{{limitation.5}}。',
    '解释观察结构时应依据其核查状态：{{design.structure}}。',
])
def test_bound_category_scope_and_neutral_complete_directives(text):check(text)

@pytest.mark.parametrize('text',[
    '类别{{projection.0.point.0.category}}的投影记录数为{{projection.0.point.1.n}}。',
    '类别{{projection.0.point.0.category}}的投影记录数为{{projection.0.point.0.n}}，绘图统计值为{{projection.0.point.1.value}}。',
    '类别{{projection.0.point.0.category}}，保存的绘图统计值为{{projection.0.point.1.value}}。',
    '类别{{projection.0.point.0.category}}与{{projection.0.point.1.category}}的投影记录数为{{projection.0.point.1.n}}。',
    '类别{{projection.0.point.0.category}}的绘图统计值为{{projection.0.point.1.value}}。',
    '投影记录数为{{projection.0.point.0.n}}，不与投影记录口径混同。',
    '保存结果显示{{data.original_n}}。这些数量描述投影记录，不与投影记录口径混同。',
    '观察独立性的核查状态为{{limitation.5}}。',
    '已确认的观察独立性的核查状态为{{limitation.3}}。',
    '科学推断须遵守以下边界：{{limitation.4}}，因此证明因果。',
    '同时应注意{{limitation.1}}，独立性已验证。',
    '科学推断边界：{{limitation.4}}。',
    '核查状态：{{design.structure}}。',
    '以下限制：{{limitation.2}}。',
    '保存结果显示42条记录。',
    '类别{{projection.0.point.0.category}}的加权绘图统计值为{{projection.0.point.0.value}}。',
])
def test_wrong_point_scope_or_unsupported_claim_stays_rejected(text):
    with pytest.raises(PlotError):check(text)

@pytest.mark.parametrize('expired',[False,True])
def test_original_bar_known_receipt_worker_is_get_only(monkeypatch,expired):
    from tests.domain import test_explanation_v5_receipt_recovery as recovery
    monkeypatch.setattr(recovery,'FIXTURE',F)
    recovery.test_existing_worker_retrieves_same_receipt_without_reserving_or_posting(monkeypatch,expired)
