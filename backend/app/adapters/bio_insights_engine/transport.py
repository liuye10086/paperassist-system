"""Explicit wire projection; full frozen snapshots remain the source of truth."""
from copy import deepcopy


def project_transport_payload(payload):
    """Drop only redundant processed metadata that no numeric operation reads.

    Observations (including confirmed mapping overlays), configuration, identity,
    all source bindings and every declared member/path/hash are retained. Raw
    arrays and their axis members remain authoritative; no feature sampling,
    axis construction or default shape is performed here. Applying twice is safe.
    """
    if not isinstance(payload,dict) or not isinstance(payload.get('sources'),list):
        raise ValueError('transport_payload_sources_invalid')
    projected=deepcopy(payload)
    for source in projected['sources']:
        if not isinstance(source,dict):raise ValueError('transport_source_invalid')
        if source.get('source_kind')!='bio_processed_dataset_version':continue
        metadata=source.get('metadata')
        if not isinstance(metadata,dict):raise ValueError('processed_metadata_invalid')
        for key in ('feature_ids','manifest','shape'):metadata.pop(key,None)
        if 'raw' in source:
            raw=source['raw']
            if (not isinstance(raw,dict) or not isinstance(raw.get('manifest'),dict)
                    or not isinstance(raw['manifest'].get('input_shape'),dict)):
                raise ValueError('processed_raw_input_shape_required')
            raw['manifest']={'input_shape':raw['manifest']['input_shape']}
    return projected
