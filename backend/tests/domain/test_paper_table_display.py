from types import SimpleNamespace

import pytest

from app.domain.manuscripts.paper_tables import _number_text


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


@pytest.mark.parametrize(('value', 'style', 'visible'), [
    ('-0.12625', '0.00%;[Red](0.00%);"—"', '(12.63%)'),
    ('0', '0.00%;[Red](0.00%);"—"', '—'),
    ('0.5055', '[>=0.6]0.0%;0.00%', '50.55%'),
    ('0.625', '[>=0.6]0.0%;0.00%', '62.5%'),
    ('0.625', '"范围;A "0.00%', '范围;A 62.50%'),
    ('0.625', r'0.00\%', '0.63%'),
    ('1234.5', '#,##0.00" mg"', '1,234.50 mg'),
    ('17', '0000', '0017'),
    ('-0.12625', '0.00%', '-12.63%'),
    ('0.5', '0.0#%', '50.0%'),
    ('0.625', 'General', '0.625'),
])
def test_custom_table_number_matches_worksheet_value_and_style(value, style, visible):
    assert _number_text(SimpleNamespace(value=value, number_format=style)) == visible
