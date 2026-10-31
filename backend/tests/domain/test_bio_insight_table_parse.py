import pytest
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def postgres_schema():yield None


def test_table_parse_snapshot_is_strict_at_every_boundary():
    from app.domain.bio_insights.table_parse import TableParseSnapshot,LIMITS
    payload=dict(project={'id':'p'},file=dict(id='f',filename='input.csv',sha256='a'*64,size_bytes=2,file_type='bio_component',storage_backend='local',object_key='files/f.bio_component'),
                 parse_id='parse',settings={**LIMITS,'delimiter':',','encoding':'utf-8-sig','header_row':1})
    TableParseSnapshot.model_validate(payload)
    for patch in ({'file':{**payload['file'],'script':'run me'}},{'settings':{**payload['settings'],'max_rows':1000000}},
                  {'file':{**payload['file'],'size_bytes':'2'}}):
        with pytest.raises(ValidationError):TableParseSnapshot.model_validate({**payload,**patch})


@pytest.mark.parametrize('compressed,size,expanded',[(False,250*1024**2,512*1024**2),(True,10,1024**3)])
def test_resource_preview_enforces_aggregate_input_and_expansion_budgets(compressed,size,expanded):
    from types import SimpleNamespace
    from app.domain.bio_insights.contracts import ResourceImportRequest
    from app.domain.bio_insights.resources import BioResourceService
    from app.core.exceptions import StorageError
    suffix='gmt.gz' if compressed else 'gmt'
    def original(db,project,file_id,parse_id,progress):
        return ({'id':file_id,'filename':'resource.'+suffix,'size_bytes':size,'sha256':'a'*64},{'filename':'resource.'+suffix},{'original_file':{}})
    service=object.__new__(BioResourceService);service.reader=lambda:SimpleNamespace(original=original)
    request=ResourceImportRequest(kind='gene_sets',title='budget test',species_taxon_id=9606,namespace='Ensembl',release='v1',
        source={'institution':'lab','name':'sets','description':'synthetic metadata for admission boundary'},
        usage={'basis':'test fixture','redistribution_allowed':False,'scope':'project'},
        files=[{'file_id':str(i),'sha256':'a'*64,'role':'gmt','format':suffix,'max_uncompressed_bytes':expanded} for i in range(3)])
    with pytest.raises(StorageError) as raised:service._files(None,'project',request)
    assert raised.value.code=='bio_insight_limit_exceeded'
