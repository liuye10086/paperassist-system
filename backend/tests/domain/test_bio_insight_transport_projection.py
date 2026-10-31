"""Projection is explicit metadata reduction, never a data/identity transformation."""
import copy
import importlib
import json
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():yield None


def payload():
    member={'path':'/attempt/frozen.npy','sha256':'a'*64,'size_bytes':32,'format':'npy','role':'matrix_data'}
    observation={'processed_version_id':'p1','barcode':'same-barcode','donor':'D1','condition':'B','batch':'batch1',
                 'section':None,'retained':True,'library_counts':12}
    return {'schema_version':1,'kind':'bio_comparison','config':{'mode':'donor_paired','numerator':'B','denominator':'A'},
        'identity':{'source_digest':'b'*64,'task_id':'task1'},'sources':[
        {'source_kind':'bio_processed_dataset_version','source_id':'p1','role':'processed','sha256':'c'*64,
         'project_id':'project1','locator':{'kind':'object'},'metadata':{'feature_ids':['redundant'],
            'manifest':{'redundant_identity':'not_an_engine_input'},'shape':{'features':58735},
            'observations':[observation],'canonical_dataset_id':'canonical1','species_taxon_id':9606,
            'namespace':'Ensembl','reference_version':'GRCh38_release95','custom_metadata':{'keep':True}},
         'members':{'matrix_data':member},'raw':{'manifest':{'input_shape':{'observations':6,'features':3},
            'redundant_provenance':{'never_read_by_numeric_inputs':True}},'members':{'matrix_data':copy.deepcopy(member)}}},
        {'source_kind':'bio_insight_result_version','source_id':'result1','metadata':{'feature_ids':['must_stay'],
            'manifest':{'must':'stay'},'shape':{'must':'stay'}},'members':{}}]}


def test_projection_is_deep_pure_idempotent_and_keeps_all_numeric_inputs():
    project=importlib.import_module('app.adapters.bio_insights_engine.transport').project_transport_payload
    full=payload();before=copy.deepcopy(full);small=project(full)
    assert full==before and small is not full
    processed=small['sources'][0];original=full['sources'][0]
    assert set(original['metadata'])-set(processed['metadata'])=={'feature_ids','manifest','shape'}
    assert processed['raw']['manifest']=={'input_shape':original['raw']['manifest']['input_shape']}
    assert processed['metadata']['observations']==original['metadata']['observations']
    assert small['config']==full['config'] and small['identity']==full['identity']
    assert processed['members']==original['members'] and processed['raw']['members']==original['raw']['members']
    assert small['sources'][1]==full['sources'][1]
    assert project(small)==small
    processed['metadata']['observations'][0]['donor']='changed copy'
    processed['members']['matrix_data']['sha256']='changed copy'
    assert full==before


def test_redundant_axes_can_fit_pipe_without_increasing_its_limit():
    project=importlib.import_module('app.adapters.bio_insights_engine.transport').project_transport_payload
    full=payload();full['sources'][0]['metadata']['feature_ids']=[f'ENSG{i:011d}.17' for i in range(100000)]
    original=json.dumps(full,separators=(',',':')).encode()
    small=json.dumps(project(full),separators=(',',':')).encode()
    assert len(original)>2*1024**2 and len(small)<2*1024**2


def test_projection_never_guesses_a_missing_raw_input_shape():
    project=importlib.import_module('app.adapters.bio_insights_engine.transport').project_transport_payload
    full=payload();del full['sources'][0]['raw']['manifest']['input_shape']
    with pytest.raises(ValueError,match='input_shape'):project(full)
