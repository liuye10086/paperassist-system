"""Carry layout choices into a new body without carrying a review receipt."""
from copy import deepcopy


def retain_school_layout(snapshot):
    writing = snapshot.pop('writing_provenance', None) or {}
    if snapshot.get('thesis_context') and writing.get('school_content_version') == 'school-live-v1':
        layout = {'language_mapping_version': 1}
        if writing.get('school_export_options') is not None:
            layout['options'] = deepcopy(writing['school_export_options'])
        if writing.get('school_pagination_version') == 2:
            layout['pagination_version'] = 2
        snapshot['review_school_layout'] = layout
