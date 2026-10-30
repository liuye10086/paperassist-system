"""Each import workflow validates its own parser identity and canonical CSR."""
import pytest
from app.adapters.bio_parse_process import validate_parser_result
from app.adapters.bio_parser.visium import parse_visium_bundle
from app.domain.bioinformatics.parser_contracts import BioParseError
from app.domain.bioinformatics.settings import BioLimits
from tests.helpers.bio_fixtures import visium_bundle_bytes


def test_explicit_v2_parent_validation_preserves_the_v1_default(tmp_path):
    limits = BioLimits()
    result = parse_visium_bundle(visium_bundle_bytes(), tmp_path, limits).summary()
    assert validate_parser_result(result, tmp_path, limits, set()) == result
    result['parser_version'] = 'geo_visium_import_v2'
    result['manifest']['parser_version'] = 'geo_visium_import_v2'
    assert validate_parser_result(result, tmp_path, limits, set(), expected_parser_version='geo_visium_import_v2') == result
    with pytest.raises(BioParseError):
        validate_parser_result(result, tmp_path, limits, set())
