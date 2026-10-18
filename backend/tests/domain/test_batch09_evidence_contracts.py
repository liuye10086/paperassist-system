import pytest
from pydantic import ValidationError
from app.domain.external_evidence.contracts import EvidenceRequest


def request(**changes):
    return dict(file_id='file', source_kind='original', document_version_id=None,
                ocr_review_version_id=None, item_ids=[], title='External evidence',
                source_description='', intended_use='reference', original_data='unavailable',
                user_note='', limitations='Original data not supplied', previous_version_id=None,
                **changes)


def test_original_evidence_is_a_declaration_not_a_computation():
    value=EvidenceRequest.model_validate(request(),strict=True)
    assert value.original_data=='unavailable' and value.source_description==''


@pytest.mark.parametrize('changes', [
    {'document_version_id':'parse'}, {'item_ids':['block']}, {'source_kind':'computed'},
    {'intended_use':'verified_statistics'}, {'previous_version_id':''},
    {'title':'  '}, {'item_ids':['a','a']}, {'original_data':'verified'},
])
def test_external_evidence_rejects_false_or_unbound_claims(changes):
    body=request();body.update(changes)
    with pytest.raises(ValidationError):EvidenceRequest.model_validate(body,strict=True)
