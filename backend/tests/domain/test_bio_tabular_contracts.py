import importlib.util
import pytest


def request_body(assay='bulk_rna_counts', scale='raw_counts'):
    return dict(workflow_version='bio_import_v3', file_ids=['m','s'], assay=assay,
        name='quantitative', expected_dataset_revision=0,
        tables=[dict(file_id='m',role='quantitative_matrix',format='csv'),
                dict(file_id='s',role='sample_metadata',format='csv')],
        feature_id_column='feature_id', sample_columns=['s1','s2','s3'],
        scale=dict(kind=scale,unit='counts' if scale=='raw_counts' else 'relative',upstream_method='provided'))


def test_new_contract_exists_without_changing_spatial_request():
    assert importlib.util.find_spec('app.domain.bioinformatics.tabular_contracts') is not None
    from app.domain.bioinformatics.tabular_contracts import BioImportRequestV3
    from app.domain.bioinformatics.contracts import BioImportRequest
    assert BioImportRequestV3(**request_body()).assay == 'bulk_rna_counts'
    assert BioImportRequest(file_ids=['m'],assay='visium',name='old',expected_dataset_revision=0).model_dump()['roles']=={}


def test_counts_cannot_claim_tpm_and_xlsx_needs_sheet():
    from app.domain.bioinformatics.tabular_contracts import BioImportRequestV3
    with pytest.raises(ValueError):BioImportRequestV3(**request_body(scale='tpm'))
    body=request_body();body['tables'][0]['format']='xlsx'
    with pytest.raises(ValueError):BioImportRequestV3(**body)


def test_log_input_cannot_be_logged_again():
    from app.domain.bioinformatics.tabular_contracts import TabularRecipeParameters, validate_recipe
    params=TabularRecipeParameters(transform='log2')
    with pytest.raises(ValueError):validate_recipe(params,dict(assay='normalized_expression',scale=dict(kind='log2')))


def test_upload_accepts_xlsx_original():
    from app.domain.file_batches import BioUploadService
    assert '.xlsx' in BioUploadService.extensions
    assert '.html' in BioUploadService.extensions and '.pdf' in BioUploadService.extensions


def test_bulk_contract_records_explicit_input_origin_and_quality_report():
    from app.domain.bioinformatics.tabular_contracts import BioImportRequestV3
    body=request_body()
    body['file_ids']=['m','s','qc']
    body['quality_reports']=[dict(file_id='qc',source='user_provided',report_type='multiqc')]
    body['scale']['input_origin']='bulk_rna'
    value=BioImportRequestV3(**body)
    assert value.roles['qc']=='upstream_quality_report'
    assert value.scale.input_origin=='bulk_rna'


def test_bulk_contract_rejects_single_cell_origin_and_invalid_mapping():
    from app.domain.bioinformatics.tabular_contracts import BioImportRequestV3
    body=request_body()
    body['scale']['input_origin']='single_cell_expression'
    with pytest.raises(ValueError,match='bulk_input_origin_invalid'):
        BioImportRequestV3(**body)
    body=request_body();body['sample_metadata_mapping']={'sample_id':'sample','condition':'sample','biological_unit_id':'biological_unit_id'}
    with pytest.raises(ValueError,match='sample_metadata_mapping_invalid'):
        BioImportRequestV3(**body)
