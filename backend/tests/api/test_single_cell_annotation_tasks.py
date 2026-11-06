"""Offline task contracts and candidate publication projection."""
from datetime import datetime,timezone
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def parent():
    raw=dict(kind='bio_dataset_version',schema_version=1,project_id='p',dataset_id='d',dataset_version_id='raw',version=1,
        source_file_ids=['f'],manifest_sha256='a'*64,parser_version='single_cell_import_v1')
    return dict(kind='bio_processed_dataset_version',schema_version=1,project_id='p',processed_dataset_version_id='processed',
        analysis_run_id='run',raw_source=raw,recipe_version_id='recipe',manifest_sha256='b'*64,
        engine_version='visium_explore_v1.0.0',environment_digest='c'*64)


def snapshot():
    from app.domain.bioinformatics.annotation_contracts import BioAnnotationRunRequest
    from app.domain.bioinformatics.single_cell_resources import SingleCellRAnalysisLimits
    request=BioAnnotationRunRequest(name='SingleR candidates',parent_processed_source=parent(),reference_id='monaco_immune_2024-02-26')
    return dict(schema_version=1,kind='bio_annotation',workflow_version='bio_annotation_v1',project_id='p',run_id='run',name=request.name,
        parent_processed_source=parent(),reference=dict(reference_id=request.reference_id),seed=0,request_digest='e'*64,
        engine_version='visium_explore_v1.0.0',environment_digest='c'*64,code_digest='d'*64,output_language='en',limits=SingleCellRAnalysisLimits().model_dump())


def test_annotation_task_is_independent_of_base_processed_and_manual_versions():
    from app.domain.bioinformatics.annotation_contracts import validate_snapshot
    from app.adapters.task_store import TaskStore
    from app.domain.bioinformatics.contracts import digest
    value=snapshot();moment=datetime.now(timezone.utc)
    task=dict(input_snapshot=value,input_digest=digest(value),task_type='bio_annotation',workflow_version='bio_annotation_v1',project_id='p',
        id='t',status='queued',phase='compute',revision=1,current_attempt=0,reason_code=None,created_at=moment,updated_at=moment)
    assert validate_snapshot(task)['parent_processed_source']==parent()
    view=TaskStore.public_task(task)
    assert view['input_version']['kind']=='bio_annotation'
    assert view['result_bio_processed_dataset_version_id'] is None


def test_candidates_project_to_stable_proposed_labels_without_confirmation():
    from app.domain.bioinformatics.annotation_service import candidate_annotations
    rows=[dict(barcode='a',candidate_label='T cells',pruned_label='T cells',delta_next='0.5',delta_median='0.8'),
          dict(barcode='b',candidate_label='B cells',pruned_label='unknown',delta_next='0.01',delta_median='0.02')]
    labels,assignments=candidate_annotations(rows)
    assert labels[0]['status']=='proposed'
    assert {r['status'] for r in assignments}=={'proposed','uncertain'}
    assert all(r['candidate_label'] for r in assignments)
    assert assignments[1]['pruned_label']=='unknown'
    assert all(l['status']!='confirmed' for l in labels)


def test_annotation_input_rejects_foreign_project_and_modified_digest():
    from app.domain.bioinformatics.annotation_contracts import validate_snapshot
    from app.domain.bioinformatics.contracts import digest
    from app.core.exceptions import StorageError
    value=snapshot();task=dict(input_snapshot=value,input_digest=digest(value),task_type='bio_annotation',workflow_version='bio_annotation_v1',project_id='foreign')
    with pytest.raises(StorageError):validate_snapshot(task)


@pytest.mark.parametrize('samples',[[],[dict(species_taxon_id=9606),dict(species_taxon_id=None)],[dict(species_taxon_id=10090)]])
def test_annotation_parent_does_not_infer_unknown_species_from_another_library(samples):
    from app.domain.bioinformatics.annotation_service import BioAnnotationService
    from app.core.exceptions import StorageError
    service=object.__new__(BioAnnotationService)
    service.processed_record=lambda *args: ({},dict(assay='single_cell'),[])
    service.processed_source=lambda *args:parent()
    service.raw=lambda *args:({},dict(samples=samples),[])
    with pytest.raises(StorageError) as exc:service._parent(None,'p',parent())
    assert exc.value.code=='bio_annotation_invalid'
