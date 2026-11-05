"""Compare verified sources using the two known historical v1 projections.

This is not source verification. Callers must first check ownership, fixed hashes,
bytes and the complete ancestry. Only additive fields absent from an old frozen
projection may be omitted; every original field still compares exactly.
"""
from copy import deepcopy


def frozen_source_projection(current, frozen):
    value = deepcopy(current)
    if (value.get('schema_version') != 1 or frozen.get('schema_version') != 1
            or value.get('source_kind') != frozen.get('source_kind')):
        return value
    content, old = value.get('content', {}), frozen.get('content', {})
    if value['source_kind'] == 'bio_processed_dataset_version' and 'layers' not in old:
        # layers is projected from the same byte-verified, SHA-pinned manifest.
        content.pop('layers', None)
    if value['source_kind'] == 'bio_figure_version':
        task = content.get('figure', {}).get('task', {})
        old_task = old.get('figure', {}).get('task', {})
        for key in ('result_bio_resource_version_id', 'result_bio_insight_result_version_id'):
            if key not in old_task and task.get(key) is None:
                task.pop(key, None)
    return value


def matches_frozen_source(current, frozen):
    return frozen_source_projection(current, frozen) == frozen
