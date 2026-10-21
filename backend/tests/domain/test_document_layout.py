"""Pure layout contracts: no business database is needed."""
import importlib

import pytest
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def api():
    return importlib.import_module('app.domain.document_layout')


def test_layout_contract_exists():
    assert importlib.util.find_spec('app.domain.document_layout') is not None


@pytest.mark.parametrize('expression', [
    r'x_i^2+\alpha', r'\frac{a}{b}', r'\sqrt{x}', r'\sqrt[3]{x}',
    r'\sum_{i=1}^{n}{x_i}', r'\int_{0}^{1}{x^2 dx}',
    r'\matrix{a & b \\ c & d}', r'\cases{x & x>0 \\ 0 & x=0}',
    r'\aligned{a=b \\ c=d}',
])
def test_supported_equations_parse(expression):
    assert api().parse_expression(expression)


@pytest.mark.parametrize('expression', [
    r'\input{secret}', r'\frac{a}', 'x^^2', 'x}', r'\matrix{a & b \\ c}',
    '{' * 14 + 'x' + '}' * 14, 'x' * 2001, '',
    '\\matrix{' + ' & '.join(['x'] * 7) + '}',
    '\\aligned{' + r' \\ '.join(['x'] * 9) + '}',
    r'x^\sum', r'x_\int', r'\sum_\sum{x}', r'x^\sum{y}',
])
def test_formula_errors_have_safe_position(expression):
    from app.core.exceptions import StorageError
    with pytest.raises(StorageError) as error:
        api().parse_expression(expression)
    assert error.value.code == 'layout_formula_invalid'
    assert isinstance(error.value.params['position'], int)


def test_grouped_nested_nary_remains_supported():
    assert api().parse_expression(r'x^{\sum_{i=1}^{n}{x_i}}')


def test_contract_rejects_unknown_fields_duplicates_and_limits():
    LayoutOptions = api().LayoutOptions
    formula = {'id': 'eq1', 'anchor_id': 'source:0', 'expression': 'x'}
    for value in [
        {'surprise': True}, {'formulas': [formula, formula]},
        {'formulas': [{**formula, 'id': f'e{i}'} for i in range(41)]},
        {'references': [{'anchor_id': 'a', 'target_id': 'b'}] * 61},
        {'landscape_anchor_ids': [str(i) for i in range(17)]},
        {'toc': {'depth': 4}}, {'pagination': {'mode': 'roman_front'}},
        {'headings': [{'anchor_id': 'a', 'level': '1'}]},
    ]:
        with pytest.raises(ValidationError):
            LayoutOptions.model_validate(value)
    assert LayoutOptions.model_validate({'formulas': [formula]}).formulas[0].expression == 'x'
