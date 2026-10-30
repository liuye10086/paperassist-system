"""Detailed B02 failures survive safe task projection, without provider text."""
import pytest
from app.domain.tasks.errors import error_category, safe_error_code


@pytest.mark.parametrize('codes,category', [
    (['bio_isolation_unavailable'], 'configuration'),
    (['bio_analysis_timeout', 'bio_resource_exceeded'], 'temporary'),
    (['bio_analysis_not_found', 'bio_recipe_not_found', 'bio_mapping_not_found', 'bio_annotation_not_found',
      'bio_figure_not_found', 'bio_processed_not_found', 'bio_request_not_found', 'bio_input_integrity_changed',
      'bio_recipe_invalid', 'bio_mapping_invalid', 'bio_annotation_invalid', 'bio_confirmation_stale',
      'bio_result_not_ready', 'bio_h5_unsupported', 'bio_h5_matrix_mismatch', 'bio_insufficient_observations'], 'source'),
])
def test_spatial_failure_codes_remain_public_and_correctly_classified(codes, category):
    for code in codes:
        assert safe_error_code(code) == code
        assert error_category(code) == category
