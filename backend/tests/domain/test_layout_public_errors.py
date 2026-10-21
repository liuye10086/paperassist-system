from pathlib import Path
import runpy

import pytest
from app.core.errors import safe_params


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


@pytest.mark.parametrize('case,expected', [
    ('invalid', {'formula_id': 'badFormula', 'path': 'formulas.0.expression', 'position': 12}),
    ('wide', {'formula_id': 'badFormula', 'path': 'formulas.0.expression'}),
    ('target', {'path': 'references.0.target_id'}),
])
def test_real_engine_error_survives_public_serializer(case, expected):
    fixture = runpy.run_path(str(Path(__file__).parents[1] / 'fixtures/layout_public_error.py'))
    response = fixture['response_body'](case)
    assert response['detail']['params'] == expected


@pytest.mark.parametrize('code', ['layout_formula_invalid', 'layout_formula_too_wide', 'layout_target_invalid'])
@pytest.mark.parametrize('payload', [
    {'formula_id': '/server/private', 'path': '/server/private', 'position': True, 'reason': '/secret'},
    {'formula_id': 'a' * 33, 'path': 'formulas.0.secret', 'position': 2001},
    {'formula_id': {'private': 'x'}, 'path': ['formulas.0.expression'], 'position': '12'},
    {'formula_id': '\nprivate', 'path': 'formulas.40.expression', 'position': -1},
    {'path': 'references.60.kind', 'position': 2.5},
    {'path': 'headings.100.anchor_id'},
    {'path': 'landscape_anchor_ids.16'},
])
def test_layout_error_parameters_reject_unbounded_or_arbitrary_input(code, payload):
    assert safe_params(code, payload) == {}


@pytest.mark.parametrize('path', ['references.59.kind', 'headings.99.anchor_id',
                                  'landscape_anchor_ids.15', 'pagination.body_anchor_id', 'toc.depth'])
def test_target_error_path_is_a_bounded_public_setting(path):
    assert safe_params('layout_target_invalid', {'path': path, 'anchor_id': '/private'}) == {'path': path}


def test_layout_location_is_code_specific():
    assert safe_params('layout_source_invalid', {'formula_id': 'valid', 'path': 'formulas.0.expression', 'position': 12}) == {}
