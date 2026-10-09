"""Versioned disclosure and server-owned confirmation of external materials."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import unicodedata

from app.core.exceptions import StorageError


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                             separators=(',', ':')).encode('utf-8')).hexdigest()


def invalid():
    return StorageError('task_input_invalid', '请核对发送前检查并确认本次使用的完整名称。', 422)


def source_digest(snapshot, task_type, user_id):
    return digest({'version': 1, 'task_type': task_type, 'user_id': user_id,
                   **{key: snapshot.get(key) for key in ('file', 'result', 'figure', 'versions', 'output_language')}})


def default_labels(snapshot, task_type):
    result = snapshot['result']
    labels = {'numeric_name': result['numeric_name'], 'unit': result['selection']['unit'] or ''}
    if result['group_name'] is not None:
        labels['group_name'] = result['group_name']
        labels.update({f'group:{index}': group['label'] for index, group in enumerate(result['groups'])})
    if task_type == 'explanation':
        figure = snapshot['figure']
        inherited = figure.get('external_processing')
        if inherited:
            labels.update({key: value for key, value in inherited['labels'].items() if key in labels})
        labels['figure_title'] = figure['title']
    return labels


def disclosure(snapshot, task_type, user_id, *, has_saved_result=False):
    result = snapshot['result']
    return {'version': 1, 'provider': 'openai', 'task_type': task_type,
            'source_digest': source_digest(snapshot, task_type, user_id),
            'has_saved_result': has_saved_result,
            'summary': {'valid_count': result['check']['valid_count'],
                        'excluded_count': result['check']['excluded_count'], 'group_count': len(result['groups'])},
            'labels': [{'key': key, 'value': value} for key, value in default_labels(snapshot, task_type).items()]}


def normalize_confirmation(confirmation):
    if (not isinstance(confirmation, dict) or set(confirmation) != {'version', 'confirmed', 'source_digest', 'labels'}
            or type(confirmation['version']) is not int or confirmation['version'] != 1
            or confirmation['confirmed'] is not True or not isinstance(confirmation['source_digest'], str)
            or not isinstance(confirmation['labels'], dict)):
        raise invalid()
    labels = {}
    for key, value in confirmation['labels'].items():
        if (not isinstance(key, str) or not isinstance(value, str) or len(value) > 160
                or any(unicodedata.category(char) in ('Cc', 'Cf', 'Cs') for char in value)):
            raise invalid()
        value = value.strip()
        if not value and key != 'unit':
            raise invalid()
        labels[key] = value
    return {**confirmation, 'labels': labels}


def freeze_confirmation(snapshot, task_type, user_id, confirmation):
    normalized = normalize_confirmation(confirmation)
    if normalized['source_digest'] != source_digest(snapshot, task_type, user_id):
        raise StorageError('task_source_conflict', '发送前检查的资料已变化，请重新读取并确认。', 409)
    labels = validate_labels(snapshot, task_type, normalized['labels'])
    return {'version': 1, 'provider': 'openai', 'task_type': task_type, 'labels': labels,
            'source_digest': normalized['source_digest'], 'confirmed_by': user_id,
            'confirmed_at': datetime.now(timezone.utc).isoformat(), 'confirmation_digest': digest(normalized)}


def validate_labels(snapshot, task_type, labels):
    if set(labels) != set(default_labels(snapshot, task_type)):
        raise invalid()
    groups = [labels[f'group:{index}'] for index in range(len(snapshot['result']['groups']))]
    if len(groups) != len(set(groups)):
        raise invalid()
    return labels


def request_digest(request):
    value = request.model_dump()
    if value.get('external_processing') is None:
        value.pop('external_processing', None)
    else:
        value['external_processing'] = normalize_confirmation(value['external_processing'])
    return digest(value)


def validate_frozen(snapshot, task_type, user_id, external):
    try:
        rebuilt = freeze_confirmation(snapshot, task_type, user_id,
            {'version': external['version'], 'confirmed': True, 'source_digest': external['source_digest'],
             'labels': external['labels']})
        if (external['provider'] != 'openai' or external['task_type'] != task_type
                or external['confirmed_by'] != user_id
                or external['confirmation_digest'] != rebuilt['confirmation_digest']
                or datetime.fromisoformat(external['confirmed_at']).utcoffset() is None):
            raise ValueError('Invalid frozen confirmation')
    except (KeyError, TypeError, ValueError, StorageError) as exc:
        raise StorageError('task_source_conflict', '已确认的资料与任务来源不一致。', 409) from exc


def get_disclosure(project_id, file_id, run_id, store, task_type):
    from app.adapters.task_store import TaskStore
    from app.domain.tasks.contracts import TaskCreateRequest
    if task_type == 'boxplot':
        from app.domain.plot_tasks import context
        result, state = context(project_id, file_id, run_id, store)
        figure = None
        saved = bool(state['figure'])
    else:
        from app.domain.explanations import context
        result, figure, state = context(store, project_id, file_id, run_id)
        if figure is None:
            raise StorageError('task_source_conflict', '请先生成当前统计结果的图表。', 409)
        saved = bool(state['explanation'])
    scoped = TaskStore(store.owner_id)
    request = TaskCreateRequest(task_type=task_type, file_id=file_id, analysis_run_id=run_id,
                               expected_revision=result['setup_revision'], figure_id=figure['id'] if figure else None)
    with scoped.connection() as db:
        snapshot = scoped.source_snapshot(db, scoped.require_project(db, project_id), request)
        return disclosure(snapshot, task_type, store.owner_id, has_saved_result=saved)
