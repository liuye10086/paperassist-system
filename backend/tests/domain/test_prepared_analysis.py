"""Prepared analysis provenance and original-coordinate statistics contracts."""
from types import SimpleNamespace
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def raw_source():
    return dict(kind='dataset_version', schema_version=1, dataset_id='raw', structure_id='structure',
        dataset_version=3, file_id='file', source_sha256='a'*64, dataset_sha256='b'*64,
        dataset_size_bytes=100, dataset_schema_version=1, sheet_index=2, sheet_name='研究数据',
        parser_version='openpyxl-3.1.5-structure-v1')


def test_raw_source_builder_preserves_accepted_contract():
    from app.domain.analysis_sources import raw_dataset_source
    row = dict(id='raw', structure_id='structure', version=3, source_sha256='a'*64,
               sha256='b'*64, size_bytes=100, parser_version='openpyxl-3.1.5-structure-v1')
    assert raw_dataset_source(row, SimpleNamespace(index=2, name='研究数据'), 'file') == raw_source()


def test_prepared_source_survives_shared_result_serialization():
    from app.domain.analysis_sources import OptionalAnalysisSource, prepared_dataset_source, source_dict, statistics_engine, DATASET_ENGINE
    prepared = prepared_dataset_source(dict(id='prepared', version=2, parent_dataset_id='raw',
        sha256='c'*64, size_bytes=200), raw_source())
    assert prepared == {**raw_source(), 'kind':'prepared_dataset_version', 'dataset_id':'prepared',
        'dataset_version':2, 'dataset_sha256':'c'*64, 'dataset_size_bytes':200,
        'parent_dataset_id':'raw', 'parent_dataset_version':3, 'transform_version':'excel_prepare_v1'}
    assert OptionalAnalysisSource(source=prepared).model_dump() == {'source':prepared}
    assert source_dict(prepared) == prepared
    assert statistics_engine({'source':prepared}) == DATASET_ENGINE


def test_prepared_builder_rejects_wrong_parent_at_source_boundary():
    from app.core.exceptions import StorageError
    from app.domain.analysis_sources import prepared_dataset_source
    with pytest.raises(StorageError) as error:
        prepared_dataset_source(dict(id='prepared', version=1,parent_dataset_id='other',sha256='c'*64,size_bytes=200),raw_source())
    assert error.value.code == 'source_conflict'


def test_legacy_and_raw_source_output_stay_exact():
    from app.domain.analysis_sources import OptionalAnalysisSource
    assert OptionalAnalysisSource().model_dump() == {}
    assert OptionalAnalysisSource(source=raw_source()).model_dump() == {'source':raw_source()}


def test_prepared_scan_uses_original_columns_names_units_and_selected_blank_rows():
    from app.domain.dataset_preparation.contracts import PreparedSheet
    from app.domain.dataset_analysis import scan_dataset
    from app.domain.analysis import AnalysisSelection
    sheet = PreparedSheet(index=2, name='研究数据', data_range='C5:D9', merged_ranges=[],
        fields=[dict(column=3,name='处理组',unit=dict(status='confirmed',value='')),
                dict(column=4,name='体重',unit=dict(status='confirmed',value='mg'))],
        cells=[dict(row=r,column=c,coordinate=f'{letter}{r}',kind=k,value=v) for r,c,letter,k,v in
            [(5,3,'C','text','A'),(5,4,'D','number','1'),(7,3,'C','text','A'),(7,4,'D','number','3')]])
    selection = AnalysisSelection(task_type='descriptive_boxplot',sheet_name=sheet.name,
        numeric_column='D',group_column='C',unit='mg',missing_policy='exclude_selected_missing')
    profile, scan = scan_dataset(sheet, selection, collect_values=True)
    assert profile.row_count == 5
    assert [(c.id,c.name,c.missing_count) for c in profile.columns] == [('C','处理组',3),('D','体重',3)]
    assert profile.model_dump()['columns'][1]['unit'] == {'status':'confirmed','value':'mg'}
    assert scan.check(profile).ready and scan.check(profile).excluded_count == 3
    assert scan.values == [1.0,3.0]
    assert [(g.label,g.count) for g in scan.check(profile).groups] == [('A',2)]


def test_raw_profile_still_omits_unit_metadata():
    from app.domain.analysis import SheetScan
    profile=SheetScan('Data',None).profile(SimpleNamespace(name='Data',row_count=0,columns=['Value'],warnings=[]))
    assert 'unit' not in profile.model_dump()['columns'][0]


def test_prepared_disclosure_requires_own_confirmation_version_and_source():
    from app.domain.analysis_sources import prepared_dataset_source
    from app.domain.external_processing import disclosure,freeze_confirmation,source_digest
    from app.core.exceptions import StorageError
    snapshot=dict(file={'filename':'研究.xlsx'},result={'numeric_name':'体重','group_name':None,
        'selection':{'unit':'mg'},'groups':[],'check':{'valid_count':2,'excluded_count':3}})
    legacy=disclosure(snapshot,'boxplot','user')
    assert legacy['version']==1 and 'source' not in legacy
    snapshot['source']=raw_source()
    raw=disclosure(snapshot,'boxplot','user')
    assert raw['version']==2 and raw['source']=={'filename':'研究.xlsx','sheet_name':'研究数据','dataset_version':3}
    snapshot['source']=prepared_dataset_source(dict(id='prepared',version=2,parent_dataset_id='raw',sha256='c'*64,size_bytes=200),raw_source())
    result=disclosure(snapshot,'boxplot','user')
    assert result['version']==3 and result['source']=={'filename':'研究.xlsx','sheet_name':'研究数据','dataset_version':2,
        'parent_dataset_version':3,'dataset_kind':'prepared'}
    assert result['source_digest'] != raw['source_digest']
    confirmation=dict(version=3,confirmed=True,source_digest=source_digest(snapshot,'boxplot','user'),labels={'numeric_name':'体重','unit':'mg'})
    assert freeze_confirmation(snapshot,'boxplot','user',confirmation)['version']==3
    with pytest.raises(StorageError):
        freeze_confirmation(snapshot,'boxplot','user',{**confirmation,'version':2})
