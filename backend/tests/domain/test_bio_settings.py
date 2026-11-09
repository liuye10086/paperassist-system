from app.domain.bioinformatics.settings import BioLimits


def test_single_cell_upload_limit_allows_128_mib_inputs():
    assert BioLimits().max_upload_bytes == 128 * 1024 * 1024
    assert BioLimits(max_upload_bytes=128 * 1024 * 1024).max_upload_bytes == 128 * 1024 * 1024
