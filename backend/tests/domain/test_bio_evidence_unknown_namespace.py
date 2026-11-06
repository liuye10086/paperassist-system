import pytest
from app.domain.bio_insights.evidence_contracts import EvidenceMatrixConfig
from app.domain.bio_insights.evidence_design import validate_evidence_design

@pytest.fixture(autouse=True)
def postgres_schema():
    yield None

def preview(candidate_namespace, source_namespace):
    config=EvidenceMatrixConfig(candidates=[dict(object_id='CCL19',feature_id='CCL19',source_id='processed',namespace=candidate_namespace,species_taxon_id=None,reference_version=None)],evidence_source_ids=['evidence'])
    sources=[dict(source_id='processed',metadata=dict(feature_ids=['CCL19'],namespace=source_namespace,species_taxon_id=None,reference_version=None)),dict(source_id='evidence',sha256='a'*64,metadata=dict(typed_evidence=dict(object_id='CCL19',evidence_type='expression_atlas',study_id='study',dependency_group='study',shared_dataset_ids=[],locators=[],statement='Source statement',human_review_status='not_reviewed')))]
    return config,validate_evidence_design(config,sources)

def test_unknown_namespace_preserved_without_inventing_species_or_reference():
    config,result=preview(None,None)
    assert result.executable
    candidate=config.candidates[0].model_dump()
    assert all(candidate[key] is None for key in ('namespace','species_taxon_id','reference_version'))
    row=result.evidence_matrix[0]
    assert row['candidate']['namespace'] is None
    assert row['status']=='unknown' and row['reason']=='species_unknown'
    assert not row['system_verified'] and not row['independent_data_support']

@pytest.mark.parametrize('candidate_namespace,source_namespace',[('gene_symbol','ensembl'),(None,'ensembl'),('gene_symbol',None)])
def test_known_or_missing_namespace_mismatch_stays_blocked(candidate_namespace,source_namespace):
    _,result=preview(candidate_namespace,source_namespace)
    assert not result.executable
    assert 'candidate_identity_mismatch' in [reason.code for reason in result.blocking_reasons]
