"""Actual frozen qPCR Methods rendering; no computation, database or report rebuild."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

@pytest.fixture(autouse=True)
def postgres_schema():yield None

@pytest.mark.parametrize('language',['zh-CN','en'])
def test_real_frozen_qpcr_methods_has_own_bilingual_presentation(language):
    from app.adapters.research_method_text import present_method
    frozen=json.loads((Path(__file__).parents[1]/'fixtures/qpcr_saved_method.json').read_text(encoding='utf8'))
    method=frozen['method'];before=deepcopy(method)
    output=present_method(method,language,reference='parameters.json[0]')
    text='\n'.join([output['title'],*output['paragraphs']])
    assert 'qPCR' in output['title'] and 'PINK1' in text and 'UBC' in text
    assert 'BrainPhys' in text and 'N2B27' in text and 'BrainPhys_N2B27' in text
    assert 'biological_unit_id' in text and 'technical_replicate' in text
    assert 'delta_delta_cq' in text and 'within_plate_differences' in text
    assert 'paired_t' in text and 'BH' in text and '95%' in text
    assert 'parameters.json[0]' in text and method['source']['sha256'] in text
    for old in ('selected_spots','spots_numerator','donors_numerator','Frozen group membership counts spots','供体数见固定'):
        assert old not in text
    if language=='zh-CN':
        assert '技术孔不增加生物学 n' in text and '原作者' in text and '逐点' in text
        assert '同板完整配对差' in text and '分子组 − 分母组' in text
    else:
        assert 'technical wells do not increase biological n' in text
        assert 'original authors' in text and 'pointwise' in text
        assert 'complete same-plate pair differences' in text and 'numerator minus denominator' in text
    assert method==before
