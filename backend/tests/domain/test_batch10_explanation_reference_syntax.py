"""Replay a synthetic real-model prefix error; never repair or publish its draft."""
import json
from pathlib import Path
import pytest
from app.core.exceptions import PlotError,StorageError
from app.domain.explanation_content import render_explanation,TOKEN,unsafe_prose
from app.domain.explanation_guards import unsafe_modern_prose
from app.domain.figure_workbench.explanation_facts import validate_draft
from app.domain.figure_workbench.explanations import instructions_for,INSTRUCTIONS,INSTRUCTIONS_V2


def fixture():
    return json.loads((Path(__file__).parents[1]/'fixtures/explanation_reference_prefix.json').read_text(encoding='utf-8'))


def test_real_synthetic_prefix_error_is_rejected_without_prose_guard_failure():
    data=fixture();payload=data['payload'];draft=data['draft']
    validate_draft(draft,payload)
    for text in draft.values():
        refs=TOKEN.findall(text)
        assert refs and all(ref.startswith('fact.') and ref not in payload['facts'] for ref in refs)
        assert all(ref[5:] in payload['facts'] for ref in refs)
        assert not unsafe_prose(TOKEN.sub('',text))
        assert not unsafe_modern_prose(TOKEN.sub('',text))
    with pytest.raises(PlotError,match='不存在的数据'):render_explanation(draft,payload)
    # Counterfactual stays in memory; the validator must not normalize model output.
    counterfactual={key:text.replace('{{fact.','{{') for key,text in draft.items()}
    validate_draft(counterfactual,payload)
    assert len(render_explanation(counterfactual,payload))==6
    assert fixture()['draft']==draft


def test_v3_instructions_supply_exact_valid_six_section_template():
    payload=fixture()['payload'];instructions=instructions_for(payload)
    assert '{{fact.key}}' not in instructions
    assert 'Never prepend fact. or facts.' in instructions
    marker='Exact-key JSON template for this payload:\n'
    assert marker in instructions
    template=json.loads(instructions.split(marker,1)[1])
    assert set(template)==set(payload['required_references'])
    for section,text in template.items():
        assert TOKEN.findall(text)==payload['required_references'][section]
        assert len(text)<=4000
    validate_draft(template,payload)
    assert len(render_explanation(template,payload))==6


def test_old_instruction_contracts_keep_their_original_bytes():
    payload=fixture()['payload']
    assert instructions_for({**payload,'figure_explanation_contract':2})==INSTRUCTIONS_V2
    assert instructions_for({**payload,'figure_explanation_contract':1})==INSTRUCTIONS


def test_instruction_template_rejects_an_impossible_section_before_submission():
    payload=fixture()['payload']
    keys=['projection_long_frozen_reference_'+str(index) for index in range(120)]
    payload['facts'].update({key:{'label':'Record','raw':1,'value':'1'} for key in keys})
    payload['required_references']['results']=keys
    assert len(payload['facts'])<500
    with pytest.raises(StorageError) as error:instructions_for(payload)
    assert error.value.code=='explanation_input_limit'
