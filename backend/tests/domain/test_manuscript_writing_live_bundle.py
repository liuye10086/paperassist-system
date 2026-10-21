import json
import pytest
from app.core.exceptions import StorageError
from app.domain.manuscript_writing.bundle import build_bundle
from app.domain.manuscript_writing.live_contracts import PreviewRequest

@pytest.fixture(autouse=True)
def postgres_schema():
    # These tests exercise pure projection only; no database schema is needed.
    yield None

def material():
    base=dict(title='Synthetic study',output_language='en',methods=[],results_groups=[],references=[],sources=[dict(id='private-source',kind='analysis_run',role='computed_results',content=dict(statistics=dict(n=12,coefficient=0.123456789),groups=[dict(label='Treatment A',unit='mg',mean=2.3)],private_path='C:/secret/data.csv',api_key='do-not-send'))])
    request=PreviewRequest(schema_version=2,base_revision=1,mode='full_draft',output_language='en',selected_source_ids=['private-source'],selected_evidence_ids=[]).model_dump(mode='json')
    return base,request

def test_numeric_paths_and_group_units_are_preserved_without_private_content():
    base,request=material();bundle=build_bundle(base,request)
    payload=json.loads(json.loads(bundle['wire_json'])['input']);source=payload['sources'][0]
    assert dict(fact_path='/statistics/coefficient',value='0.123456789') in source['facts']
    assert source['labels']==[dict(path='/groups/0/label',value='Treatment A'),dict(path='/groups/0/unit',value='mg')]
    assert 'private-source' not in bundle['wire_json'] and 'do-not-send' not in bundle['wire_json']

@pytest.mark.parametrize('text',['C:/Users/private/secret.csv',r'C:\private\data.csv','Bearer abcdef123456','api_key=secretvalue'])
def test_private_path_and_credential_text_is_blocked(text):
    base,request=material();request['instructions']=text
    with pytest.raises(StorageError): build_bundle(base,request)

def test_no_silent_truncation_for_complete_wire_limit():
    base,request=material();base['methods']=[dict(id='method:1',text='中'*40000,origin='user_provided',source_ids=[])]
    with pytest.raises(StorageError,match='超过输入上限'): build_bundle(base,request)

def test_json_schema_is_recursively_closed_and_all_fields_required():
    base,request=material();wire=json.loads(build_bundle(base,request)['wire_json'])
    def check(value):
        if isinstance(value,dict):
            if value.get('type')=='object':
                assert value['additionalProperties'] is False
                assert set(value['required'])==set(value['properties'])
            for child in value.values(): check(child)
        elif isinstance(value,list):
            for child in value: check(child)
    check(wire['text']['format']['schema'])

def test_figure_and_table_identity_text_only_selected_material():
    base,request=material();base['results_groups']=[dict(paragraphs=[],tables=[dict(id='table-private',number=1,title='Table title',source_ids=['private-source'],columns=['Variable','Value'],rows=[['Mean',2.3]])],figures=[])]
    payload=json.loads(json.loads(build_bundle(base,request)['wire_json'])['input'])
    assert payload['illustrations'][0]['number']==1
    assert payload['illustrations'][0]['kind']=='table'
    assert 'table-private' not in json.dumps(payload)


@pytest.mark.parametrize('path',[
    '/run/secrets/model-api-key','/data/private/patients.csv','/arbitrary-root/file',
    '../private/patients.csv','./private/patients.csv',r'..\private\patients.csv',
    r'.\private\patients.csv',r'\private\patients.csv',r'\\server\share\patients.csv',
    'C:/private/patients.csv',r'C:\private\patients.csv','C:private.csv','~/private/patients.csv',
])
@pytest.mark.parametrize('wrapper',['{}','See ({}) for details.','Read "{}".','请读取{}','资料位于{}'])
def test_local_paths_are_blocked_independently_of_root_or_punctuation(path,wrapper):
    base,request=material();request['instructions']=wrapper.format(path)
    with pytest.raises(StorageError) as exc: build_bundle(base,request)
    assert exc.value.code=='manuscript_writing_material_blocked'


@pytest.mark.parametrize('text',[
    'DOI: 10.1038/s41586-020-2649-2',
    'See (https://doi.org/10.1038/s41586-020-2649-2).',
    'https://pubmed.ncbi.nlm.nih.gov/12345678/',
    'https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/',
    'The ratio was 3/4 and the concentration unit was mg/mL.',
    '比例为3/4，浓度单位为mg/mL，文献DOI为10.1038/s41586-020-2649-2。',
    '文献见https://doi.org/10.1038/s41586-020-2649-2。',
    '文献见https://pubmed.ncbi.nlm.nih.gov/12345678/。',
])
def test_public_bibliographic_identifiers_and_scientific_slashes_remain_exact(text):
    base,request=material();request['instructions']=text
    payload=json.loads(json.loads(build_bundle(base,request)['wire_json'])['input'])
    assert payload['instructions']==text


@pytest.mark.parametrize('url',[
    'https://doi.org.evil.example/10.1038/s41586-020-2649-2',
    'https://user:pass@doi.org/10.1038/s41586-020-2649-2',
    'https://doi.org/10.1038/s41586-020-2649-2?token=private',
    'https://pubmed.ncbi.nlm.nih.gov/12345678/#private',
    'https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/pdf/paper.pdf',
    'https://example.org/paper','file:///data/private.csv','http://127.0.0.1/private',
    'https://doi.org:443/10.1038/s41586-020-2649-2',
    'https://doi.org/10.1038/../../private.csv',
    'DOI 10.1038/example(/data/private.csv)',
    'https://doi.org/10.1038/example(/data/private.csv)',
])
def test_noncanonical_private_or_download_urls_are_not_public_text_exemptions(url):
    base,request=material();request['instructions']=url
    with pytest.raises(StorageError): build_bundle(base,request)


def test_arbitrary_source_dictionary_key_cannot_masquerade_as_generated_fact_path():
    base,request=material();base['sources'][0]['content']['statistics']['/data/private.csv']=7
    with pytest.raises(StorageError): build_bundle(base,request)


def test_user_method_text_is_subject_to_the_same_path_gate():
    base,request=material()
    base['methods']=[dict(id='method:1',text='See "/run/secrets/model-api-key".',origin='user_provided',source_ids=[])]
    with pytest.raises(StorageError): build_bundle(base,request)


@pytest.mark.parametrize('journal_title,abbreviation,expected',[
    ('Nature','Nature Abbr','Nature'),('','Nature Abbr','Nature Abbr'),
])
def test_selected_evidence_projects_real_metadata_journal_contract(journal_title,abbreviation,expected):
    from app.domain.literature_citations.contracts import Metadata,Author
    base,request=material()
    metadata=Metadata(title='Public title',authors=[Author(family='Researcher',given='A')],
        year='2020',doi='10.1038/s41586-020-2649-2',journal_title=journal_title,
        journal_abbreviation=abbreviation,volume='PRIVATE_UNUSED_VOLUME').model_dump(mode='json')
    base['citation_snapshot']=dict(paragraphs=[dict(id='paragraph:1',fragments=[dict(bindings=[dict(metadata=metadata,
        evidence=[dict(id='selected-evidence',quote='A public observation.',reading_scope='abstract_only')])])])])
    request['selected_evidence_ids']=['selected-evidence']
    bundle=build_bundle(base,request);payload=json.loads(json.loads(bundle['wire_json'])['input'])
    bibliography=payload['evidence'][0]['bibliography']
    assert bibliography==dict(title='Public title',authors=metadata['authors'],year='2020',
        doi='10.1038/s41586-020-2649-2',journal=expected)
    assert 'PRIVATE_UNUSED_VOLUME' not in bundle['wire_json']
