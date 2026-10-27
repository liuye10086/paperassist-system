"""Installed C fallback validation, with no reads of the current configuration."""
from app.core.exceptions import StorageError

TASKS={'journal_recommendation','journal_format_check','journal_adaptation','school_template_parse',
       'review_round_plan','review_revision','review_document_export'}


def require(condition):
    if not condition:raise ValueError('Incomplete installed legacy contract')


def affected(task, paths):
    name=task['task_type'];snapshot=task['input_snapshot'] or {}
    # Safe administrative update records do not participate in scientific execution.
    metadata=('journals.source_label','journals.update_plan','journals.update_result','journals.update_note','journals.update_mode')
    paths=[p for p in paths if not any(p==field or p.startswith(field+'.') for field in metadata)]
    if not paths:return False
    try:
        if name=='journal_recommendation':
            from app.domain.journals.service import input_version
            from app.domain.journals.contracts import RecommendationRequest
            input_version(task);RecommendationRequest.model_validate(snapshot['research'])
            require(isinstance(snapshot['profiles'],list) and isinstance(snapshot['materials'],list))
            require(all(isinstance(p,dict) and all(k in p for k in ('id','fields','source_status','source_type')) for p in snapshot['profiles']))
        elif name=='journal_format_check':
            from app.domain.journals.format_service import input_version
            input_version(task)
            require(isinstance(snapshot['target']['selected_requirements'],list) and isinstance(snapshot['target']['conflicts'],list))
            require(isinstance(snapshot['manuscript']['snapshot'],dict) and snapshot['manuscript']['sha256'])
            require(snapshot['public_check_version'] in (2,3))
        elif name=='journal_adaptation':
            from app.domain.journals.adaptation_service import input_version
            input_version(task)
            require(isinstance(snapshot['preview']['actions'],list) and isinstance(snapshot['selected_action_ids'],list))
            require(snapshot['base_sha256'] and snapshot['requirements_version'])
        elif name=='school_template_parse':
            from app.domain.school_templates.service import input_version
            input_version(task)
            require(isinstance(snapshot['sources_sha256'],str) and len(snapshot['sources_sha256'])==64)
        elif name=='review_round_plan':
            from app.domain.review_rounds.service import input_version
            input_version(task)
            require(isinstance(snapshot['materials'],list) and isinstance(snapshot['sources'],list))
            require(all(isinstance(s['segments'],list) and all(isinstance(p['text'],str) for p in s['segments']) for s in snapshot['sources']))
        elif name=='review_revision':
            from app.domain.review_rounds.revisions import input_version
            input_version(task)
            require(isinstance(snapshot['plan_state']['items'],list) and isinstance(snapshot['operations'],list))
            require(isinstance(snapshot['preview'],dict) and snapshot['output_language'] in ('zh-CN','en'))
        elif name=='review_document_export':
            from app.domain.review_rounds.document_exports import input_version
            input_version(task)
            require(snapshot['document']['language'] in ('zh-CN','en'))
            require(all(isinstance(item['text'],str) for item in snapshot['document']['items']))
            require(snapshot.get('renderer_version','review_docx_v1') in ('review_docx_v1','review_docx_v2','review_docx_v3'))
        else:return True
    except (ValueError,TypeError,KeyError,AssertionError,StorageError):
        return True
    # All supported legacy implementations retain installed rules/defaults. No
    # historical binding is invented, including after failed-task recovery.
    return False
