"""Comparison category identities are bounded before decimal expansion."""
import pytest
from pydantic import ValidationError
from app.domain.comparison.contracts import GroupIdentity, canonical_number


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


@pytest.mark.parametrize('value', ['1e100000', '1e-100000', '9'*501])
def test_unbounded_numeric_category_is_rejected_before_expansion(value):
    with pytest.raises(ValueError):
        canonical_number(value)


def test_long_text_category_cannot_create_unreadable_frontend_selection():
    with pytest.raises(ValidationError):
        GroupIdentity(kind='text', value='x'*501)


@pytest.mark.parametrize('original,expected', [('1e2','100'),('1.00','1'),('-0e99999','0'),('1e-3','0.001')])
def test_bounded_numeric_canonicalization_retains_typed_identity(original,expected):
    assert canonical_number(original) == expected
