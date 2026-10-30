"""An unchecked or mismatching representation is never labelled passed."""
import pytest
from app.domain.bioinformatics.service import public_checks
from app.core.exceptions import StorageError


@pytest.mark.parametrize('state,expected', [('identical','passed'),('order_reindexed_equal','passed'),
    ('not_comparable','not_checked'),('mismatch','failed'),('future_unrecognized','not_checked')])
def test_equivalence_public_check_respects_actual_attestation(state, expected):
    value = public_checks({'representation_equivalence': {'status': state, 'comparator': 'csr_all_values_v1'}})[0]
    assert value['status'] == expected
    if expected == 'failed':
        assert value['blocking'] is True


def test_v2_selected_representation_is_bound_to_the_frozen_request():
    from app.domain.bioinformatics import contracts
    task={'input_snapshot':{'workflow_version':'bio_import_v2','matrix_representation':'10x_h5',
                           'compare_alternate':True,'files':[{'id':'source'}]}}
    member={'source_file_id':'source','source_member_name':'matrix.h5','sha256':'a'*64,
            'verification_state':'verified','format':'h5'}
    representation={'selected':'10x_h5','matrix_representation':'10x_h5','compare_alternate':True,
        'comparison':{'status':'identical'},'h5_internal_check':'verified',
        'chosen_source':{'source_file_id':'source','source_member_name':'matrix.h5','sha256':'a'*64}}
    result={'manifest':{'representation':representation},'outputs':[member]}
    contracts.validate_v2_representation(task,result)
    representation['selected']='mtx'
    with pytest.raises(StorageError):contracts.validate_v2_representation(task,result)
    representation['selected']='10x_h5'
    representation['comparison']['status']='mismatch'
    with pytest.raises(StorageError) as error:contracts.validate_v2_representation(task,result)
    assert error.value.code=='bio_h5_matrix_mismatch'


def test_v2_cannot_claim_a_source_member_that_was_not_preserved():
    from app.domain.bioinformatics import contracts
    task={'input_snapshot':{'workflow_version':'bio_import_v2','matrix_representation':'10x_h5',
                           'compare_alternate':False,'files':[{'id':'source'}]}}
    representation={'selected':'10x_h5','matrix_representation':'10x_h5','compare_alternate':False,
        'comparison':{'status':'not_comparable'},'h5_internal_check':'verified',
        'chosen_source':{'source_file_id':'source','source_member_name':'matrix.h5','sha256':'a'*64}}
    with pytest.raises(StorageError):
        contracts.validate_v2_representation(task,{'manifest':{'representation':representation},'outputs':[]})
