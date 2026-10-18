"""Independent expectations for approved quality operations and immutable provenance."""
import copy
import importlib.util
import pytest
from app.domain.dataset_preparation.contracts import PreparedCell, PreparedSheet
from app.domain.analysis_sources import prepared_dataset_source

@pytest.fixture(autouse=True)
def postgres_schema():
    yield None

def quality():
    assert importlib.util.find_spec('app.domain.dataset_preparation.quality_transform'), 'Quality v2 transform is missing'
    from app.domain.dataset_preparation.quality_transform import prepare_quality
    from app.domain.dataset_preparation.quality_contracts import QualityRecipe
    return prepare_quality, QualityRecipe

def base(rows=None):
    from types import SimpleNamespace
    values=rows or [[10,1,'A'],[20,2,'A'],[20,2,'A'],[' NA ',3,'A'],[40,None,'B'],[1000,10,'B'],[50,5,'B'],[1000,10,'B'],[60,6,'B'],[70,7,'B']]
    fields=[dict(column=c,name=n,unit=dict(status='unconfirmed',value=None)) for c,n in enumerate(['X','Y','Group'],1)]
    cells=[]
    for r,vs in enumerate(values,2):
        for c,v in enumerate(vs,1):
            kind='blank' if v is None else 'boolean' if isinstance(v,bool) else 'number' if isinstance(v,(int,float)) else 'text'
            cells.append(PreparedCell(row=r,column=c,coordinate=f'{chr(64+c)}{r}',kind=kind,value=str(v) if kind=='number' else v))
    sheet=PreparedSheet(index=0,name='Sheet',data_range=f'A2:C{len(values)+1}',fields=fields,cells=cells,merged_ranges=[])
    root=dict(kind='dataset_version',schema_version=1,dataset_id='raw',structure_id='structure',dataset_version=1,file_id='file',source_sha256='a'*64,dataset_sha256='b'*64,dataset_size_bytes=10,dataset_schema_version=1,sheet_index=0,sheet_name='Sheet',parser_version='openpyxl-3.1.5-structure-v1')
    from app.domain.analysis_sources import DatasetAnalysisSource
    obj=SimpleNamespace(sheet=sheet,parent_source=DatasetAnalysisSource.model_validate(root))
    source=prepared_dataset_source(dict(id='base',parent_dataset_id='raw',version=1,sha256='c'*64,size_bytes=10),root)
    return obj,source

def test_independent_main_fixture_and_full_manifest():
    run,Recipe=quality(); obj,source=base()
    recipe=Recipe(fields=[dict(column=1,trim_text=True,missing_markers=['NA']),dict(column=2),dict(column=3)],manual_exclusions=[dict(row=9,reason='合成重复'),dict(row=11,reason='合成排除')],duplicate_policy='exact')
    before=copy.deepcopy(obj.sheet.model_dump())
    sheet,summary,manifest=run(obj,source,recipe)
    assert sheet.active_source_rows==[2,3,5,6,7,8,10]
    assert sheet.row_count==7 and obj.sheet.model_dump()==before
    assert (summary.root_record_count,summary.manual_excluded_row_count,summary.duplicate_excluded_row_count)==(10,2,1)
    assert (summary.changed_cell_count,summary.trimmed_cell_count,summary.missing_marker_cell_count)==(1,1,1)
    assert len(manifest.entries)==4
    change=next(e for e in manifest.entries if e.operation=='cell_change')
    assert change.coordinate=='A5' and change.operations==['trim_text','missing_marker']
    assert any(c.row==7 and c.value=='1000' for c in sheet.cells)
    assert summary.after_quality.missing_cell_count==2

def test_types_missing_blank_rows_and_first_remaining_duplicate():
    run,Recipe=quality(); obj,source=base([[1,None,'A'],[1.0,'  ','A'],['1',None,'A'],[True,None,'A'],[None,None,None],[None,' ',None]])
    recipe=Recipe(fields=[dict(column=c) for c in (1,2,3)],manual_exclusions=[dict(row=2,reason='first')],duplicate_policy='exact')
    sheet,summary,_=run(obj,source,recipe)
    assert sheet.active_source_rows==[3,4,5,6,7] and summary.duplicate_excluded_row_count==0
    sheet,summary,_=run(obj,source,Recipe(fields=[dict(column=c) for c in (1,2,3)],duplicate_policy='exact'))
    assert sheet.active_source_rows==[2,4,5,6,7] and summary.duplicate_excluded_row_count==1

def test_full_45_changes_and_empty_preview_are_retained():
    run,Recipe=quality(); obj,source=base([[' A ',None,None] for _ in range(45)])
    _,summary,manifest=run(obj,source,Recipe(fields=[dict(column=1,trim_text=True),dict(column=2),dict(column=3)]))
    assert len(manifest.entries)==45 and summary.impact_count==45
    sheet,summary,_=run(obj,source,Recipe(fields=[dict(column=c) for c in (1,2,3)],manual_exclusions=[dict(row=r,reason='explicit') for r in range(2,47)]))
    assert sheet.active_source_rows==[] and summary.retained_record_count==0

def test_v2_source_strict_versions_and_v1_unchanged():
    quality(); obj,source=base()
    row=dict(id='next',parent_dataset_id='raw',version=2,sha256='d'*64,size_bytes=10)
    root=obj.parent_source.model_dump()
    old=prepared_dataset_source(row,root)
    new=prepared_dataset_source(row,root,schema_version=2)
    assert old['schema_version']==1 and new['schema_version']==new['dataset_schema_version']==2
    from app.domain.analysis_sources import source_dict
    assert source_dict(new)==new
    for changes in ({'schema_version':True},{'dataset_schema_version':1},{'transform_version':'excel_prepare_v1'}):
        with pytest.raises(Exception): source_dict({**new,**changes})

def test_inherited_exclusion_is_not_restored_and_changes_on_duplicates_separate():
    run,Recipe=quality(); obj,source=base([[' A ',1,'A'],[' A ',1,'A'],['B',2,'B']])
    sheet,summary,manifest=run(obj,source,Recipe(fields=[dict(column=1,trim_text=True),dict(column=2),dict(column=3)],duplicate_policy='exact'))
    assert sheet.active_source_rows==[2,4]
    assert summary.changed_cell_count==2 and summary.retained_changed_cell_count==summary.excluded_changed_cell_count==1
    obj.sheet=sheet
    later,summary,_=run(obj,source,Recipe(fields=[dict(column=c) for c in (1,2,3)]))
    assert later.active_source_rows==[2,4] and summary.inherited_excluded_row_count==1 and summary.changed_cell_count==0
    assert later.cells[0].value=='A'

def test_nonblank_reasons_and_fixed_policies_required():
    _,Recipe=quality()
    for change in ({'manual_exclusions':[dict(row=2,reason='   ')]},{'missing_policy':'mean'},{'outlier_policy':'remove_iqr'},{'duplicate_policy':'subject_id'}):
        with pytest.raises(ValueError): Recipe(fields=[dict(column=1)],**change)

def test_manifest_local_immutability_limits_integrity_and_paths(tmp_path):
    import json
    from uuid import uuid4
    from app.adapters.quality_manifest_objects import QualityManifestObjects
    from app.adapters.prepared_dataset_objects import PreparedDatasetObjects
    from app.domain.dataset_preparation.quality_transform import build_quality_object
    from app.core.exceptions import StorageError
    run,Recipe=quality(); obj,source=base()
    recipe=Recipe(fields=[dict(column=c) for c in (1,2,3)])
    sheet,summary,manifest=run(obj,source,recipe)
    manifests=QualityManifestObjects(tmp_path); objects=PreparedDatasetObjects(tmp_path); identity=str(uuid4())
    body=manifest.model_dump_json().encode()
    maximum=body+b' '*(16*1024*1024-len(body))
    ref=manifests.save(identity,maximum)
    assert manifests.read(ref)[0]==maximum
    assert manifests.save(identity,maximum)==ref
    with pytest.raises(StorageError): manifests.save(str(uuid4()),maximum+b' ')
    with pytest.raises(StorageError): manifests.read({**ref,'sha256':'0'*64})
    with pytest.raises(StorageError): manifests.read({**ref,'entry_count':1})
    for key in ('../escape','quality-manifests/../x','files/a','quality-manifests/x:y'):
        with pytest.raises(StorageError): manifests.path(key)
    ref['entry_count']=0
    prepared=build_quality_object(obj,source,recipe,sheet,summary,ref)
    content=prepared.model_dump_json().encode(); bounded=content+b' '*(4*1024*1024-len(content))
    obj_ref=objects.save(identity,bounded)
    assert objects.read(obj_ref)[1]==prepared
    with pytest.raises(StorageError): objects.save(str(uuid4()),bounded+b' ')
    manifests.path(ref['object_key']).write_bytes(b'corrupted')
    with pytest.raises(StorageError): manifests.save(identity,maximum)
    assert manifests.path(ref['object_key']).read_bytes()==b'corrupted'

def test_schema_literals_reject_bool_and_float():
    from app.domain.dataset_preparation.quality_contracts import QualityManifest
    run,Recipe=quality(); obj,source=base()
    _,_,manifest=run(obj,source,Recipe(fields=[dict(column=c) for c in (1,2,3)]))
    for value in (True,1.0):
        with pytest.raises(ValueError): QualityManifest.model_validate({**manifest.model_dump(),'schema_version':value})

def test_offset_rectangle_keeps_real_coordinates():
    from openpyxl.utils.cell import get_column_letter
    run,Recipe=quality(); obj,source=base()
    payload=obj.sheet.model_dump(); payload['data_range']='C5:E14'
    for field in payload['fields']: field['column']+=2
    for cell in payload['cells']:
        cell['row']+=3; cell['column']+=2; cell['coordinate']=f"{get_column_letter(cell['column'])}{cell['row']}"
    obj.sheet=PreparedSheet.model_validate(payload)
    sheet,summary,manifest=run(obj,source,Recipe(fields=[dict(column=3,trim_text=True,missing_markers=['NA']),dict(column=4),dict(column=5)],
        manual_exclusions=[dict(row=12,reason='explicit'),dict(row=14,reason='explicit')],duplicate_policy='exact'))
    assert sheet.active_source_rows==[5,6,8,9,10,11,13]
    assert next(e.coordinate for e in manifest.entries if e.operation=='cell_change')=='C8'
    assert summary.retained_record_count==7
