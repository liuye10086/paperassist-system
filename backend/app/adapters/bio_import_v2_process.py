"""Known H5/MTX import uses the attested isolated scientific interpreter."""
from app.adapters.bio_analysis_process import execute_bio_analysis
from app.core.exceptions import StorageError
from app.domain.bioinformatics.analysis_settings import runtime_identity


def parse_bio_v2(input_manifest, output_directory, settings):
    runtime = runtime_identity()
    if (not runtime['available'] or input_manifest.get('parser_version') != 'geo_visium_import_v2'
            or any(input_manifest.get(key) != runtime.get(key)
                   for key in ('engine_version', 'environment_digest', 'code_digest'))):
        raise StorageError('bio_environment_unavailable', '固定生信导入环境已变化，请重新核对。', 409)
    payload = {key: input_manifest[key] for key in ('files', 'matrix_representation', 'compare_alternate')}
    payload.update(settings=settings, analysis_limits=input_manifest['analysis_limits'],
                   identity={key: input_manifest[key] for key in ('engine_version', 'environment_digest', 'code_digest')})
    return execute_bio_analysis(payload, output_directory, mode='import_v2')
