"""Offline annotation contracts; no database, model or biological validation."""
import json
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def source():
    return dict(kind='bio_dataset_version',schema_version=1,project_id='p',dataset_id='d',dataset_version_id='raw',version=1,
                source_file_ids=['f'],manifest_sha256='a'*64,parser_version='single_cell_import_v1')


def request(**kwargs):
    from app.domain.bioinformatics.analysis_contracts import BioAnnotationRequest
    return BioAnnotationRequest(name='Labels',raw_source=source(),processed_dataset_version_id='processed',expected_revision=0,**kwargs)


def test_cell_labels_keep_uncertain_and_reference_manual_evidence():
    value=request(labels=[dict(id='T',name='T candidate',status='uncertain',cell_ids=['c1'])],
                  evidence=[dict(label_id='T',kind='manual',note='Reviewed markers'),dict(label_id='T',kind='reference',note='Reference DOI/version')])
    assert value.labels[0].cell_ids==['c1']
    from app.adapters.bio_annotation_store import assign_regions
    rows=assign_regions([dict(barcode='c1'),dict(barcode='c2')],[],'ambiguity',[l.model_dump() for l in value.labels])
    assert rows[0]['label_id']=='T' and rows[0]['status']=='uncertain'
    assert rows[1]['status']=='unknown'


def annotation_store():
    from app.adapters.bio_annotation_store import BioAnnotationStore
    store=object.__new__(BioAnnotationStore)
    store.axes=lambda *args:({},dict(assay='single_cell'),[],['c1','c2','filtered'],{})
    store.processed_record=lambda *args: (dict(raw_dataset_version_id='raw'),{},[dict(key='observations')])
    store.objects=SimpleNamespace(read=lambda _:b'barcode\tkept\tcluster\nc1\tTrue\t0\nc2\tTrue\t1\nfiltered\tFalse\t\n')
    return store


def test_single_cell_annotations_use_retained_cells_without_positions():
    store=annotation_store()
    rows,checks=store.validate(None,'p',request(labels=[dict(id='T',name='T',cluster_ids=['0'])]))
    assert [r['barcode'] for r in rows]==['c1','c2']
    assert rows[0]['label_id']=='T' and rows[1]['status']=='unknown'
    assert checks['coordinate_space']=='cell' and checks['biological_validation'] is False


@pytest.mark.parametrize('cell',['missing','filtered'])
def test_single_cell_annotation_rejects_unretained_or_unknown_cells(cell):
    from app.core.exceptions import StorageError
    with pytest.raises(StorageError) as exc:
        annotation_store().validate(None,'p',request(labels=[dict(id='T',name='T',cell_ids=[cell])]))
    assert exc.value.code=='bio_annotation_invalid'


def test_single_cell_annotations_require_processed_and_reject_spatial_regions():
    from app.core.exceptions import StorageError
    value=request()
    value.processed_dataset_version_id=None
    with pytest.raises(StorageError):annotation_store().validate(None,'p',value)
    value=request(labels=[dict(id='T',name='T')],regions=[dict(id='r',label_id='T',points=[[0.,0.],[1.,0.],[0.,1.]])])
    with pytest.raises(StorageError):annotation_store().validate(None,'p',value)


def test_cell_and_cluster_selectors_must_be_unique():
    from pydantic import ValidationError
    for field in ['cell_ids','cluster_ids']:
        with pytest.raises(ValidationError):request(labels=[dict(id='T',name='T',**{field:['c1','c1']})])


def test_unknown_label_is_explicit_and_conflicting_cell_labels_are_ambiguous():
    from app.adapters.bio_annotation_store import assign_regions
    point=[dict(barcode='c1',cluster='0')]
    assert assign_regions(point,[],'ambiguity',[dict(id='a',cell_ids=['c1'],status='unknown')])[0]['status']=='unknown'
    assert assign_regions(point,[],'ambiguity',[dict(id='a',cell_ids=['c1']),dict(id='b',cluster_ids=['0'])])[0]['status']=='ambiguous'


def test_legacy_spatial_request_replay_accepts_only_new_empty_cell_default():
    from app.adapters.bio_annotation_store import annotation_request_digests
    from app.domain.bioinformatics.contracts import digest
    value=request(labels=[dict(id='T',name='T',cluster_ids=['0'])])
    historical=value.model_dump(mode='json')
    for label in historical['labels']:label.pop('cell_ids')
    assert digest(historical) in annotation_request_digests(value)
    selected=request(labels=[dict(id='T',name='T',cell_ids=['c1'])])
    assert len(annotation_request_digests(selected))==1
