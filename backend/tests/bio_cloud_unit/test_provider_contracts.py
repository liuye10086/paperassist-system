import pytest
from pydantic import ValidationError


def _profile(**updates):
    from app.domain.bio_cloud.contracts import WorkflowProfile

    value = dict(
        id='p',
        name='p',
        workflow_id='123',
        species='human',
        chemistries=['v3'],
        reference_id='ref',
        parameters={'input': '{samplesheet_uri}'},
        outputs={
            'matrix': 'matrix.mtx.gz',
            'features': 'features.tsv.gz',
            'barcodes': 'barcodes.tsv.gz',
            'qc': 'qc.json',
            'log': 'run.log',
        },
    )
    value.update(updates)
    return WorkflowProfile.model_validate(value)


def test_cloud_settings_exposes_supported_provider_name():
    from app.domain.bio_cloud.settings import CloudSettings

    settings = CloudSettings(provider='aws_healthomics')
    assert settings.provider == 'aws_healthomics'


def test_cloud_settings_rejects_unimplemented_provider():
    from app.domain.bio_cloud.settings import CloudSettings

    with pytest.raises(ValidationError):
        CloudSettings(provider='aliyun_easygene')


def test_profile_rejects_duplicate_output_paths():
    outputs = {
        'matrix': 'matrix.mtx.gz',
        'features': 'matrix.mtx.gz',
        'barcodes': 'barcodes.tsv.gz',
        'qc': 'qc.json',
        'log': 'run.log',
    }
    with pytest.raises(ValidationError):
        _profile(outputs=outputs)


def test_reconcile_request_accepts_opaque_provider_run_id():
    from app.domain.bio_cloud.requests import ReconcileRequest

    request = ReconcileRequest(provider_run_id='job-2026_11:abc/7')
    assert request.provider_run_id == 'job-2026_11:abc/7'


def test_provider_run_id_contract_rejects_control_and_empty_values():
    from app.domain.bio_cloud.provider import ProviderError, provider_run_id

    with pytest.raises(ProviderError):
        provider_run_id('')
    with pytest.raises(ProviderError):
        provider_run_id('job\nsecret')


def test_output_record_requires_positive_size_and_etag():
    from app.domain.bio_cloud.provider import ProviderError, output_record

    assert output_record({'key': 'p/matrix.mtx.gz', 'size_bytes': 3, 'etag': 'etag'}) == {
        'key': 'p/matrix.mtx.gz', 'size_bytes': 3, 'etag': 'etag'
    }
    with pytest.raises(ProviderError):
        output_record({'key': 'p/matrix.mtx.gz', 'size_bytes': 3, 'etag': None})
