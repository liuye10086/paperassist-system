from copy import deepcopy

from app.domain.review_rounds.grounded import grounded_plans


def test_annotates_only_generated_position_slots_in_unchanged_initial_plan():
    from app.domain.review_rounds.grounded import initial_plan_locations

    raw = 'materials_and_methods/methods:purpose'
    note = '保留 📝 ' + raw
    source = dict(id='source', kind='document_version', content={'text': note})
    paragraph = dict(id='methods:purpose', text=note, source_ids=['source'], citations=[])
    snapshot = dict(title='标题', methods=[paragraph], sources=[source])
    seed = dict(id='item', original_text=note, locations=[], evidence_ids=[], needs=[], category='method')
    rules = {'handling_notes': {'method': note}}
    initial = grounded_plans(snapshot, [seed], [], rules=rules)[0]
    item = dict(seed, plan=initial['plan'], locations=[{'kind': 'paragraph', 'id': paragraph['id']}], evidence_ids=['source'])
    frozen = deepcopy(item)
    spans = initial_plan_locations(snapshot, [item], [])['item']
    assert [s['kind'] for s in spans] == ['paragraph', 'evidence', 'paragraph']
    assert [item['plan'][s['start']:s['end']] for s in spans] == [raw, 'source', raw]
    assert all(s['id'] == paragraph['id'] for s in spans if s['kind'] == 'paragraph')
    assert item == frozen
    assert initial_plan_locations(snapshot, [dict(item, plan=note + item['plan'])], []) == {}


def test_structure_order_marks_generated_section_and_paragraph_ids():
    from app.domain.review_rounds.grounded import initial_plan_locations

    snapshot = dict(title='稿件', methods=[dict(id='methods:purpose', text='正文 methods:purpose', source_ids=[], citations=[])])
    item = dict(id='structure', original_text='调整顺序', locations=[], evidence_ids=[], needs=[], category='structure')
    initial = grounded_plans(snapshot, [item], [])[0]
    spans = initial_plan_locations(snapshot, [dict(item, plan=initial['plan'])], [])['structure']
    assert [(s['kind'], initial['plan'][s['start']:s['end']]) for s in spans] == [
        ('paragraph', 'materials_and_methods/methods:purpose'), ('section', 'materials_and_methods'), ('paragraph', 'methods:purpose'),
    ]


def test_revision_display_counts_each_frozen_position_and_marks_every_evidence():
    p1 = dict(id='methods:purpose', text='方案文字', source_ids=['a','b'], citations=[])
    p2 = dict(p1, id='methods:study_design', text='步骤文字')
    sources = [dict(id=x, kind='document_version', label=x+'.docx', content={'text': x+' 是资料中的原文'}) for x in ('a','b')]
    snapshot = dict(title='合成', methods=[p1,p2], sources=sources)
    item = dict(id='opinion', original_text='修改方法', locations=[], evidence_ids=[], needs=[], category='method')
    raw = grounded_plans(snapshot,[item],[])[0]
    shown = grounded_plans(snapshot,[item],[],with_locations=True)[0]
    assert raw['plan'] == shown['plan']
    assert 'location_spans' not in raw and 'paragraph_number' not in raw['locations'][0]
    assert [loc['paragraph_number'] for loc in shown['locations']] == [1,2]
    assert [s['id'] for s in shown['location_spans']] == [p1['id'],p2['id'],'a','b',p1['id'],p2['id']]
    assert [s['label'] for s in shown['location_spans'] if s['kind']=='evidence'] == ['a.docx','b.docx']
