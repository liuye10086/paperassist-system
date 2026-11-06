"""Explicit wire projection; full frozen snapshots remain the source of truth."""
from copy import deepcopy


def project_transport_payload(payload):
    """Drop redundant wire metadata; declared leaves remain authoritative.

    Observations (including confirmed mapping overlays), configuration, identity,
    all source bindings and every declared member/path/hash are retained. Raw
    arrays and their axis members remain authoritative; no feature sampling,
    axis construction or default shape is performed here. Single-cell assignment
    metadata is restored from its verified declared leaf after isolation.
    Applying twice is safe.
    """
    if not isinstance(payload,dict) or not isinstance(payload.get('sources'),list):
        raise ValueError('transport_payload_sources_invalid')
    projected=deepcopy(payload)
    single_cell=(payload.get('kind')=='bio_comparison' and (payload.get('config',{}).get('schema_version')==5 or payload.get('config',{}).get('single_cell_selection') is not None)) or (payload.get('kind')=='bio_integration' and payload.get('config',{}).get('schema_version')==2)
    for source in projected['sources']:
        if not isinstance(source,dict):raise ValueError('transport_source_invalid')
        if single_cell and source.get('source_kind')=='bio_annotation_version':
            # Assignments and their hashed member define the fixed cell axis.
            # Duplicated manual cell/cluster lists are retained in the frozen DB
            # snapshot but never consumed by this numerical operation.
            metadata=source.get('metadata',{})
            metadata.pop('assignments',None)
            metadata['labels']=[{k:v for k,v in row.items() if k not in ('cell_ids','cluster_ids')} for row in metadata.get('labels',[])]
        if source.get('source_kind')!='bio_processed_dataset_version':continue
        metadata=source.get('metadata')
        if not isinstance(metadata,dict):raise ValueError('processed_metadata_invalid')
        for key in ('feature_ids','retained_feature_ids','manifest','shape'):metadata.pop(key,None)
        if source.get('raw',{}).get('manifest',{}).get('schema_version')==3:
            # Preserve scale/layers/raw semantics; axes are reconstructed from verified leaves.
            continue
        if 'raw' in source:
            raw=source['raw']
            if (not isinstance(raw,dict) or not isinstance(raw.get('manifest'),dict)
                    or not isinstance(raw['manifest'].get('input_shape'),dict)):
                raise ValueError('processed_raw_input_shape_required')
            raw['manifest']={'input_shape':raw['manifest']['input_shape']}
    return projected


def hydrate_single_cell_annotations(payload):
    """Called by the numerical pipeline only after the Worker's isolation step.

    The full snapshot remains in storage. The wire carries the exact declared
    assignment member/hash once; its document replaces redundant metadata.
    A separate copy keeps manifest/recipe source bindings small and reproducible.
    """
    single_cell=(payload.get('kind')=='bio_comparison' and (payload.get('config',{}).get('schema_version')==5 or payload.get('config',{}).get('single_cell_selection') is not None)) or (payload.get('kind')=='bio_integration' and payload.get('config',{}).get('schema_version')==2)
    if not single_cell:return payload
    from .inputs import document
    hydrated=deepcopy(payload)
    for source in hydrated['sources']:
        if source.get('source_kind')!='bio_annotation_version':continue
        assignments=document(source['members']['assignments'])
        if not isinstance(assignments,dict) or not isinstance(assignments.get('rows'),list):raise ValueError('annotation_assignments_invalid')
        source['metadata']['assignments']=assignments
    return hydrated
