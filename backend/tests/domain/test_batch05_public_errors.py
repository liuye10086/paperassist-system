from app.core.errors import safe_params, PUBLIC_CODES


def test_projection_reason_exposes_only_fixed_user_actionable_codes():
    assert 'figure_projection_invalid' in PUBLIC_CODES
    assert safe_params('figure_projection_invalid',{'reason':'duplicate_x','raw':'private content'}) == {'reason':'duplicate_x'}
    assert safe_params('figure_projection_invalid',{'reason':'raw private text'}) == {}
    assert safe_params('figure_projection_invalid',{'reason':{'payload':'private'}}) == {}
