import pytest
from pydantic import ValidationError
from app.domain.bioinformatics.single_cell_contracts import SingleCellParameters


def test_batch2_defaults_and_library_override_inheritance():
    value=SingleCellParameters(min_counts=10,max_counts=100,library_qc_overrides=[dict(library_id='L1',min_counts=20)])
    assert value.doublet.enabled is False and value.decontx.enabled is False
    assert value.library_qc_overrides[0].min_counts==20
    assert value.library_qc_overrides[0].max_counts is None


@pytest.mark.parametrize('params,reason',[
    ({'library_qc_overrides':[{'library_id':'L1'},{'library_id':'L1'}]},'duplicate_library_qc'),
    ({'min_counts':20,'library_qc_overrides':[{'library_id':'L1','max_counts':10}]},'library_qc_threshold_conflict'),
    ({'library_qc_overrides':[{'library_id':'L1','max_mt_fraction':0.1}]},'library_qc_mitochondrial_rule'),
    ({'doublet':{'exclude_predicted':True}},'doublet_exclusion_requires_enabled'),
    ({'doublet':{'enabled':True,'expected_rate':1.1}},'expected_rate'),
])
def test_batch2_invalid_parameters(params,reason):
    with pytest.raises(ValidationError,match=reason):SingleCellParameters(**params)


def test_recipe_library_references_use_original_import_declarations():
    from app.domain.bioinformatics.single_cell_contracts import validate_library_qc_libraries
    params=SingleCellParameters(library_qc_overrides=[dict(library_id='original')])
    validate_library_qc_libraries(params,[dict(library_id='original',donor='old')])
    with pytest.raises(ValueError,match='unknown_library_qc_override'):
        validate_library_qc_libraries(params,[dict(library_id='edited',donor='new')])
