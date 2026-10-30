"""H5 import is versioned without changing existing v1 request/wait hashes."""
import importlib
import pytest
from app.core.exceptions import StorageError
from app.domain.bioinformatics.contracts import BioImportRequest, canonical, digest, input_version, validate_snapshot
from app.domain.bioinformatics.settings import BioLimits


def legacy_snapshot():
    return dict(schema_version=1, kind='bio_import', workflow_version='bio_import_v1', project_id='p',
                import_id='i', dataset_id='d', name='counts', assay='visium', parser_version='geo_visium_import_v1',
                expected_dataset_revision=1, output_language='en', files=[{'id': 'f'}], settings=BioLimits().model_dump())


def task(snapshot):
    return {'task_type': 'bio_import', 'workflow_version': snapshot['workflow_version'],
            'project_id': 'p', 'input_snapshot': snapshot, 'input_digest': digest(snapshot)}


def test_v1_request_and_public_input_remain_byte_equivalent():
    request = BioImportRequest(file_ids=['f'], assay='visium', name='counts', expected_dataset_revision=0)
    assert request.model_dump() == {'file_ids':['f'],'assay':'visium','name':'counts','dataset_id':None,
                                   'expected_dataset_revision':0,'roles':{}}
    value = legacy_snapshot()
    assert validate_snapshot(task(value)) == value
    assert input_version(task(value)) == {'kind':'bio_import','import_id':'i','dataset_id':'d',
        'workflow_version':'bio_import_v1','source_file_ids':['f'],'parser_version':'geo_visium_import_v1','output_language':'en'}


def test_v2_request_requires_explicit_representation_and_keeps_confirmation_choice():
    module = importlib.import_module('app.domain.bioinformatics.contracts')
    value = module.BioImportRequestV2(file_ids=['f'], assay='visium', name='counts',
             expected_dataset_revision=0, matrix_representation='10x_h5', compare_alternate=True)
    assert value.matrix_representation == '10x_h5'
    assert value.compare_alternate is True
    assert canonical(value.model_dump()) != canonical(BioImportRequest(file_ids=['f'],assay='visium',name='counts',expected_dataset_revision=0).model_dump())


def test_v2_snapshot_freezes_science_environment_and_remains_a_bio_import():
    from app.domain.bioinformatics.analysis_settings import BioAnalysisLimits
    value = legacy_snapshot()
    value.update(workflow_version='bio_import_v2', parser_version='geo_visium_import_v2',
                 matrix_representation='10x_h5', compare_alternate=True,
                 analysis_limits=BioAnalysisLimits().model_dump(), engine_version='visium_explore_v1.0.0',
                 environment_digest='a'*64, code_digest='b'*64)
    assert validate_snapshot(task(value)) == value
    view = input_version(task(value))
    assert view['workflow_version'] == 'bio_import_v2'
    assert view['matrix_representation'] == '10x_h5'
    assert view['environment_digest'] == 'a'*64


def test_unknown_import_workflow_is_closed():
    value = legacy_snapshot()
    value['workflow_version'] = 'bio_import_v999'
    with pytest.raises(StorageError):
        validate_snapshot(task(value))
