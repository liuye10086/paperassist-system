"""Exact registered customer operations used by the paper workspaces."""

PROJECT = '/api/v1/projects/{project_id}'
MANUSCRIPT = '/manuscripts/{manuscript_id}'
WRITING = MANUSCRIPT + '/writing-requests'

_PAPER_ROUTES = {
    '/paper-materials': {'GET': ('', '/worksheets/{file_id}'), 'PUT': ('/{note_id}',)},
    '/manuscripts': {
        'GET': ('/config', '/candidates'),
        'POST': ('', '/preview', '/selected-references'),
    },
    MANUSCRIPT: {
        'GET': ('/versions/{revision}/writing-materials',),
        'POST': ('/versions',),
    },
    MANUSCRIPT + '/writing-previews': {
        'GET': ('', '/{bundle_id}'),
        'POST': ('',),
    },
    WRITING: {'GET': ('', '/{request_id}', '/{request_id}/draft-reader', '/{request_id}/draft-reader/word',
                      '/{request_id}/draft-reader/figures/{number}'),
              'POST': ('', '/{request_id}/draft-feedback')},
    '/writing-authorizations': {
        'GET': ('', '/{authorization_id}'),
        'POST': ('', '/{authorization_id}/close'),
    },
    '/files/{file_id}/document-versions': {
        'GET': ('', '/{parse_id}', '/{parse_id}/blocks', '/{parse_id}/download', '/{parse_id}/images/{image_id}'),
        'POST': ('',),
    },
    '': {
        'GET': ('/sci-current-draft', '/draft-history', '/external-evidence/{version_id}', '/files/{file_id}/external-evidence-source',
                '/files/{file_id}/image-preview'),
    },
    '/layout-exports/{export_id}': {'GET': ('', '/download')},
    '/literature': {
        'GET': ('/config', '/searches', '/searches/{search_id}', '/references', '/references/{reference_id}', '/receipts/{receipt_id}/source'),
        'POST': ('/searches',),
        'PATCH': ('/references/{reference_id}',),
    },
}

_THESIS_ROUTES = {
    '/reviews': {
        'GET': (
            '/inputs', '/rounds', '/rounds/{identity}', '/rounds/{identity}/science',
            '/rounds/{identity}/revision-context', '/rounds/{identity}/revisions', '/revisions/{identity}',
            '/revisions/{revision_id}/documents', '/documents/{document_id}', '/documents/{document_id}/exports',
            '/document-exports/{export_id}', '/document-exports/{export_id}/download',
            '/rounds/{identity}/continuation-context', '/returns/{identity}', '/progress',
        ),
        'POST': (
            '/sources/preview', '/rounds', '/rounds/{identity}/plans', '/rounds/{identity}/decisions',
            '/rounds/{identity}/revisions/preview', '/rounds/{identity}/revisions', '/rounds/{identity}/revisions/adopt',
            '/revisions/{revision_id}/documents', '/documents/{document_id}/versions',
            '/documents/{document_id}/confirm', '/documents/{document_id}/exports',
            '/rounds/{identity}/returns', '/returns/{identity}/preview', '/returns/{identity}/adopt', '/progress',
        ),
    },
    '/literature/checks': {
        'GET': ('/config', '/candidates', '/references/{project_reference_id}', '/references/{project_reference_id}/history'),
        'POST': ('/references/{project_reference_id}/receipts',),
    },
    '/literature/evidence': {
        'GET': (
            '/config', '/material-options', '/materials', '/materials/{material_id}/source',
            '/claims', '/claims/{claim_id}', '/claims/{claim_id}/evidence', '/claims/{claim_id}/reviews',
        ),
        'POST': ('/materials', '/claims', '/claims/{claim_id}/versions', '/claims/{claim_id}/evidence', '/claims/{claim_id}/reviews'),
    },
    '/literature/citations': {
        'GET': (
            '/config', '/candidates', '/todos', '/drafts', '/drafts/{draft_id}', '/drafts/{draft_id}/versions/{revision}/output',
            '/drafts/{draft_id}/versions/{revision}/source', '/references/{project_reference_id}/metadata',
            '/metadata/{metadata_version_id}/source', '/materials/{material_id}/confirmations',
        ),
        'POST': ('/drafts', '/drafts/{draft_id}/versions', '/references/{project_reference_id}/metadata', '/materials/{material_id}/confirmations'),
    },
    '/manuscript-figure-language-versions': {
        'GET': ('', '/{version_id}', '/{version_id}/download'),
        'POST': ('',),
    },
    WRITING: {
        'GET': (
            '/{request_id}/review-context', '/{request_id}/reviews/{review_id}',
            '/{request_id}/reviews/{review_id}/language-context', '/{request_id}/reviews/{review_id}/language-reviews',
            '/{request_id}/language-reviews/{language_id}',
        ),
        'POST': (
            '/{request_id}/publish', '/{request_id}/reviews',
            '/{request_id}/reviews/{review_id}/language-context', '/{request_id}/language-reviews',
            '/{request_id}/draft-reader/word',
        ),
    },
    '/thesis-requirements': {'GET': ('',), 'PUT': ('',)},
    '/thesis-profile': {'GET': ('',), 'PUT': ('',)},
    '/thesis-template-binding': {'POST': ('', '/preview')},
    '/school-templates': {
        'GET': ('',),
        'POST': ('', '/{identity}/retry', '/{identity}/confirm'),
    },
    MANUSCRIPT: {
        'GET': ('/school-changes', '/school-changes/{change_id}', '/presentations', '/presentations/{presentation_id}'),
        'POST': (
            '/versions/{revision}/exports', '/versions/{revision}/exports/preview',
            '/versions/{revision}/school-changes', '/school-changes/{change_id}/preview',
            '/school-changes/{change_id}/adopt', '/presentations', '/presentations/preview',
        ),
    },
}


def operations(routes):
    return frozenset(
        (method, PROJECT + prefix + suffix)
        for prefix, methods in routes.items()
        for method, paths in methods.items()
        for suffix in paths
    )


PAPER_PROJECT_OPERATIONS = operations(_PAPER_ROUTES)
THESIS_PROJECT_OPERATIONS = operations(_THESIS_ROUTES)

REVIEW_TASK_TYPES = ('review_round_plan', 'review_revision', 'review_document_export')
PAPER_TASK_TYPES = ('manuscript_draft', 'manuscript_docx', 'manuscript_writing', 'literature_search') + REVIEW_TASK_TYPES
PAPER_READ_ONLY_TASK_TYPES = ('layout_docx',)
SCI_TASK_TYPES = ('journal_recommendation', 'journal_format_check', 'journal_adaptation')
THESIS_TASK_TYPES = ('school_template_parse',)
PAPER_RECOVERY_TASK_TYPES = ('manuscript_writing', 'manuscript_docx', 'manuscript_draft', 'literature_search') + REVIEW_TASK_TYPES
