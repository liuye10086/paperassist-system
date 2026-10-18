"""Independent population expectations, without database access."""
import pytest
from tests.domain.test_batch07_quality_transform import base

@pytest.fixture(autouse=True)
def postgres_schema():
    yield None

def recipe(**changes):
    return dict(conditions=[dict(column=1,kind='number',operator='between',lower='18',upper='65'),dict(column=2,kind='text',operator='eq',value='A')],reason='成人A组',unit_acknowledged=True,**changes)

def test_independent_population_and_three_valued_receipt():
    from app.domain.dataset_preparation.filter_transform import prepare_filter
    obj,source=base([[17,'A',10],[18,'A',20],[30,'B',30],[65,'A',40],[None,'A',50],[40,'A',60],[45,'B',70]])
    sheet,summary,manifest=prepare_filter(obj,source,recipe())
    assert sheet.active_source_rows==[3,5,7]
    assert (summary.retained_record_count,summary.mismatch_excluded_row_count,summary.unknown_excluded_row_count)==(3,3,1)
    values=[int(c.value) for c in sheet.cells if c.column==3]
    assert len(values)==3 and sum(values)/len(values)==40
    assert len(manifest.entries)==7
    assert manifest.entries[4].unknown_conditions==[0]
    assert manifest.entries[4].evaluations[0].coordinate=='A6'

def test_missing_ne_false_precedence_type_sensitive_and_no_trim():
    from app.domain.dataset_preparation.filter_transform import prepare_filter
    from app.core.exceptions import StorageError
    obj,source=base([[None,'B',1],[None,'A',2],[18,' A',3],[20,'A',4]])
    r=recipe();r['conditions'][0]=dict(column=1,kind='number',operator='ne',value='18')
    sheet,summary,manifest=prepare_filter(obj,source,r)
    assert sheet.active_source_rows==[5]
    assert [e.classification for e in manifest.entries]==['mismatch','unknown','mismatch','retained']
    assert manifest.entries[0].failed_conditions==[1] and manifest.entries[0].unknown_conditions==[0]
    obj,source=base([['18','A',1]])
    with pytest.raises(StorageError):prepare_filter(obj,source,r)

def test_invalid_limits_and_unknown_units():
    from app.domain.dataset_preparation.filter_transform import prepare_filter
    from app.domain.dataset_preparation.filter_contracts import FilterRecipe
    from app.core.exceptions import StorageError
    obj,source=base([[20,'A',1]])
    for conditions in ([],[dict(column=1,kind='number',operator='eq',value='20')]*11,[dict(column=1,kind='number',operator='eq',value='NaN')],[dict(column=1,kind='text',operator='in',values=['x']*21)]):
        with pytest.raises(ValueError):FilterRecipe.model_validate({**recipe(),'conditions':conditions})
    with pytest.raises(StorageError):prepare_filter(obj,source,{**recipe(),'unit_acknowledged':False})

def test_explicit_missing_zero_preview_and_inherited_rows():
    from app.domain.dataset_preparation.filter_transform import prepare_filter
    from app.domain.dataset_preparation.quality_contracts import PreparedSheetV2
    obj,source=base([[None,'A',1],[20,'A',2],[0,'NA',3]])
    r={**recipe(),'conditions':[dict(column=1,kind='missing',operator='is_missing')]}
    sheet,_,_=prepare_filter(obj,source,r)
    assert sheet.active_source_rows==[2]
    obj.sheet=PreparedSheetV2(**{**sheet.model_dump()})
    sheet,summary,_=prepare_filter(obj,source,{**r,'conditions':[dict(column=1,kind='missing',operator='is_not_missing')]})
    assert sheet.active_source_rows==[] and summary.inherited_excluded_row_count==2

def test_boolean_sets_text_exactness_missing_markers_and_overlap():
    from app.domain.dataset_preparation.filter_transform import prepare_filter
    obj,source=base([[0,'NA',True],[0,'na',False],[0,' NA ',True],[None,'  ',False]])
    r={**recipe(),'conditions':[dict(column=2,kind='text',operator='in',values=['NA','na']),dict(column=3,kind='boolean',operator='eq',value=True)]}
    sheet,summary,manifest=prepare_filter(obj,source,r)
    assert sheet.active_source_rows==[2]
    assert summary.mismatch_excluded_row_count==3 and summary.unknown_excluded_row_count==0
    assert manifest.entries[-1].failed_conditions==[1] and manifest.entries[-1].unknown_conditions==[0]
    assert [(c.true_count,c.false_count,c.unknown_count) for c in summary.condition_counts]==[(2,1,1),(2,2,0)]
    r['conditions']=[dict(column=1,kind='number',operator='eq',value='0')]
    assert prepare_filter(obj,source,r)[0].active_source_rows==[2,3,4]

@pytest.mark.parametrize('kind,value',[('formula','=1'),('error','#DIV/0!'),('date','2026-10-16'),('boolean',True)])
def test_incompatible_nonmissing_blocks_even_when_other_condition_false(kind,value):
    from app.domain.dataset_preparation.filter_transform import prepare_filter
    from app.domain.dataset_preparation.contracts import PreparedCell
    from app.core.exceptions import StorageError
    obj,source=base([[20,'B',1]])
    obj.sheet.cells[0]=PreparedCell(row=2,column=1,coordinate='A2',kind=kind,value=value)
    with pytest.raises(StorageError):prepare_filter(obj,source,recipe())

def test_v3_source_literals_and_immutable_object_bounds(tmp_path):
    from uuid import uuid4
    from app.domain.analysis_sources import prepared_dataset_source,source_dict
    from app.domain.dataset_preparation.filter_transform import prepare_filter
    from app.domain.dataset_preparation.derivation_contracts import PreparedDatasetObjectV3
    from app.domain.dataset_preparation.derivation_service import DerivationManifestObjects
    from app.adapters.prepared_dataset_objects import PreparedDatasetObjects
    from app.core.exceptions import StorageError
    obj,source=base([[20,'A',1]])
    new=prepared_dataset_source(dict(id='next',parent_dataset_id='raw',version=2,sha256='d'*64,size_bytes=10),obj.parent_source.model_dump(),schema_version=3)
    assert source_dict(new)==new
    for changes in ({'schema_version':True},{'dataset_schema_version':2},{'transform_version':'excel_prepare_v2'}):
        with pytest.raises(StorageError):source_dict({**new,**changes})
    sheet,summary,manifest=prepare_filter(obj,source,recipe());identity=str(uuid4())
    receipts=DerivationManifestObjects(tmp_path);objects=PreparedDatasetObjects(tmp_path)
    content=manifest.model_dump_json().encode();bounded=content+b' '*(16*1024*1024-len(content))
    reference=receipts.save(identity,bounded);reference['entry_count']=1
    assert receipts.read(reference)[1]==manifest
    with pytest.raises(StorageError):receipts.save(str(uuid4()),bounded+b' ')
    prepared=PreparedDatasetObjectV3(parent_source=obj.parent_source,base_source=source,operation='population_filter',recipe=recipe(),sheet=sheet,summary=summary,manifest=reference)
    content=prepared.model_dump_json().encode();bounded=content+b' '*(4*1024*1024-len(content))
    saved=objects.save(identity,bounded)
    assert objects.read(saved)[1]==prepared
    with pytest.raises(StorageError):objects.save(str(uuid4()),bounded+b' ')
    with pytest.raises(StorageError):receipts.read({**reference,'entry_count':0})
