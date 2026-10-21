"""PDF failures remain safe bilingual-code-compatible task projections."""
def test_pdf_public_error_categories():
    from app.domain.tasks.errors import safe_error_code,error_category
    expected={'pdf_renderer_unavailable':'configuration','pdf_conversion_timeout':'temporary','pdf_renderer_busy':'temporary',
        'pdf_conversion_failed':'output','pdf_input_invalid':'source','pdf_renderer_mismatch':'configuration'}
    for code,category in expected.items():
        assert safe_error_code(code)==code
        assert error_category(code)==category
