"""Fixed engineering inputs only; no real independent cohort or statistics."""
import copy
import pytest
from app.domain.bio_insights.external_matrix import independent_support, build_matrix


from tests.domain.test_bio_evidence_independence import bound_inputs


def test_complete_actual_input_binding_retains_positive_engineering_gate(bound_inputs):
    assert independent_support(*bound_inputs)['supported'] is True


@pytest.mark.parametrize('change', ['mouse','processed_version','primary_omitted','namespace','reference','condition','missing_lineage','observation_binding'])
def test_independent_gate_rejects_actual_result_input_mismatch(bound_inputs,change):
    c,e,request,sources=bound_inputs
    meta=sources[2]['metadata']; actual=meta['comparison_inputs'][0]
    if change=='mouse':
        meta['species_taxon_id']=meta['plan_config']['species_taxon_id']=actual['metadata']['species_taxon_id']=10090
    elif change=='processed_version':
        actual['source_id']='different-processed-version'
        for side in ('numerator','denominator'):
            meta['plan_config']['contrasts'][0][side]['observation_keys'][0]['processed_version_id']='different-processed-version'
        for row in actual['metadata']['observations']:row['processed_version_id']='different-processed-version'
    elif change=='primary_omitted':
        extra=copy.deepcopy(sources[0]);extra['metadata']['observations']=[dict(processed_version_id='primary',barcode='a',donor='D1',condition='tumor',retained=True)]
        extra['metadata']['feature_ids']=['ERBB2'];meta['comparison_inputs'].append(extra);meta['canonical_dataset_ids']=['A','B']
        meta['plan_config']['contrasts'][0]['numerator']['observation_keys'].append(dict(processed_version_id='primary',barcode='a'))
    elif change in ('namespace','reference'):
        key='reference_version' if change=='reference' else change
        meta[key]=meta['plan_config'][key]=actual['metadata'][key]='different'
    elif change=='condition':actual['metadata']['observations'][0]['condition']='different'
    elif change=='missing_lineage':del meta['comparison_inputs']
    elif change=='observation_binding':actual['metadata']['observations'][0]['donor']='unreported-D4'
    result=independent_support(c,e,request,sources)
    assert not result['supported'], result
    assert any(reason.startswith('actual_') or reason=='result_material_lineage_mismatch' for reason in result['reasons'])


@pytest.mark.parametrize('cohort,expected', [('SAME_FIXED_COHORT',1),(None,2),('',2),('unknown',2),(' UNKNOWN ',2)])
def test_only_explicit_known_same_cohort_merges_distinct_studies(cohort,expected):
    c=dict(object_id='ERBB2',feature_id='ERBB2',source_id='primary',species_taxon_id=9606,condition='tumor',expected_direction='up')
    sources=[]
    for i in range(2):
        e=dict(object_id='ERBB2',species_taxon_id=9606,condition='tumor',effect_direction='up',evidence_type='public_validation',study_id='study'+str(i),dependency_group='group'+str(i),cohort_id=cohort,shared_dataset_ids=[],shared_donor_ids=None,locators=[],statement='engineering statement',human_review_status='reviewed',result_status='reported')
        sources.append(dict(source_id='e'+str(i),sha256=str(i)*64,metadata=dict(typed_evidence=e,original_sha256=str(i)*64,locator_verification={'locator_verified':True})))
    data=build_matrix([c],sources,[])
    assert len(data['dependency_groups'])==expected
    assert data['candidates'][0]['support_count']==expected


def test_comparison_proof_is_scoped_to_c_requests_and_preserves_old_source_identity(monkeypatch):
    from types import SimpleNamespace
    import app.domain.bio_insights.sources as source_module
    from app.domain.bio_insights.service import frozen_sources, source_digest, portable
    from app.adapters.bio_insights_engine.transport import project_transport_payload
    reader=object.__new__(source_module.InsightSourceReader);reader.assets=object()
    monkeypatch.setattr(source_module,'require_phase',lambda *args:None)
    source=dict(source_kind='bio_insight_result_version',source_id='result',role='result',sha256='b'*64,project_id='p',locator={},metadata={'plan_config':{'kind':'comparison'}},members={})
    calls=[]
    def resolve(*args,**kwargs):
        calls.append(kwargs);value=copy.deepcopy(source)
        if kwargs.get('comparison_proof'):value['metadata']['comparison_inputs']=[]
        return value
    monkeypatch.setattr(reader,'_resolve_in_phase',resolve)
    selections=[SimpleNamespace(source_id='result',source_kind='bio_insight_result_version')]
    def read(config):return reader._resolve_many_in_phase(None,'p',selections,config,phase=object())
    old=read(SimpleNamespace(kind='figure'))
    empty_c=read(SimpleNamespace(kind='candidate',schema_version=2,independent_support_requests=[]))
    proved=read(SimpleNamespace(kind='candidate',schema_version=2,independent_support_requests=[SimpleNamespace(result_source_id='result')]))
    assert all('comparison_proof' not in c for c in calls[:2]) and calls[2]['comparison_proof'] is True
    assert portable(old)==portable(empty_c)==portable([source])
    assert frozen_sources(proved)==frozen_sources(old) and source_digest(proved)==source_digest(old)
    assert 'comparison_inputs' in project_transport_payload({'sources':proved})['sources'][0]['metadata']


def test_transport_keeps_complete_bound_positive_gate(bound_inputs):
    from app.adapters.bio_insights_engine.transport import project_transport_payload
    c,e,request,sources=bound_inputs
    projected=project_transport_payload({'sources':sources})['sources']
    assert 'feature_ids' not in projected[1]['metadata']
    assert independent_support(c,e,request,projected)['supported'] is True
