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


def disclosure_version(snapshot):
    from app.domain.artifact_contracts import modern_artifact, comparison_artifact
    from app.domain.artifact_contracts import modeling_artifact
    if modeling_artifact(snapshot.get('result',snapshot)): return 6
    if comparison_artifact(snapshot.get('result', snapshot)):
        return 5
    if modern_artifact(snapshot.get('result', snapshot)):
        return 4
    if snapshot.get('source', {}).get('kind') == 'prepared_dataset_version':
        return 3
    return 2 if 'source' in snapshot else 1


def disclosed_source(snapshot):
    source = snapshot['source']
    result = dict(filename=snapshot['file']['filename'], sheet_name=source['sheet_name'],
                  dataset_version=source['dataset_version'])
    if source['kind'] == 'prepared_dataset_version':
        result.update(parent_dataset_version=source['parent_dataset_version'], dataset_kind='prepared')
    return result


def source_digest(snapshot, task_type, user_id):
    material = {'version': disclosure_version(snapshot), 'task_type': task_type, 'user_id': user_id,
                **{key: snapshot.get(key) for key in ('file', 'result', 'figure', 'versions', 'output_language')}}
    if 'source' in snapshot:
        material['source'] = snapshot['source']
    return digest(material)


def default_labels(snapshot, task_type):
    result = snapshot['result']
    from app.domain.artifact_contracts import modern_artifact
    if result.get('result_type') in ('correlation', 'group_comparison','regression','roc','survival'):
        labels = {}
        for variable in result['variables']:
            if variable['column']==result['selection'].get('id_column'): continue
            labels['field:' + variable['column']] = variable['name']
            labels['unit:' + variable['column']] = variable['unit'] or ''
        if result.get('result_type') == 'group_comparison':
            labels.update({f'group:{index}':group['label'] for index,group in enumerate(result['groups'])})
        if result.get('result_type') == 'regression':
            field_names={v['column']:v['name'] for v in result['variables']}
            labels.update({f'effect:{i}':field_names[c['column']]+(
                ': '+c['level']['value']+' / reference '+c['reference']['value'] if c['level'] is not None else '')
                for i,c in enumerate(result['statistics']['coefficients']) if c['column'] is not None})
        if result.get('result_type') == 'survival':
            labels.update({f'group:{index}':group['label'] for index,group in enumerate(result['statistics']['groups'])})
        if task_type == 'explanation':
            figure = snapshot['figure']
            inherited = figure.get('external_processing')
            if inherited:
                labels.update({key:value for key,value in inherited['labels'].items() if key in labels})
            labels.update(figure_title=figure['title'], research_summary='')
        return labels
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
        if modern_artifact(result):
            labels['research_summary'] = ''
    return labels


def disclosure(snapshot, task_type, user_id, *, has_saved_result=False):
    result = snapshot['result']
    from app.domain.artifact_contracts import modern_artifact, figure_kind, artifact_language
    summary = {'valid_count': result['check']['valid_count'], 'excluded_count': result['check']['excluded_count'],
               'group_count': len(result.get('groups', []))}
    if modern_artifact(result):
        summary.update(figure_kind=figure_kind(result), output_language=artifact_language(result),
            method=result.get('statistics', {}).get('method', 'descriptive'),
            mode=result.get('selection', {}).get('mode'), variable_count=len(result.get('variables', [])),
            variables=result.get('variables', []))
        if result.get('result_type') == 'group_comparison':
            summary.update(design=result['selection']['design'], posthoc=result['selection']['posthoc'],
                paired_direction='before_minus_after' if result['selection']['design']=='paired' else None,
                observation_basis='complete_pairs' if result['selection']['design']=='paired' else 'independent_rows')
    if result.get('result_type') in ('regression','roc','survival'):
        summary['variables']=[v for v in result['variables'] if v['column']!=result['selection'].get('id_column')]
        summary['variable_count']=len(summary['variables'])
    if result.get('result_type')=='survival': summary['group_count']=len(result['statistics']['groups'])
    if result.get('result_type') in ('regression','roc','survival'):
        summary.update(verification_scope='local_effect_projection' if result['result_type']=='regression' else 'independent_curve_calculation',
            outbound_data='local_effects_and_intervals' if result['result_type']=='regression' else 'necessary_anonymous_observations')
    return {'version': disclosure_version(snapshot), 'provider': 'openai', 'task_type': task_type,
            **({'source': disclosed_source(snapshot)} if 'source' in snapshot else {}),
            'source_digest': source_digest(snapshot, task_type, user_id),
            'has_saved_result': has_saved_result,
            'summary': summary,
            'labels': [{'key': key, 'value': value} for key, value in default_labels(snapshot, task_type).items()]}


def normalize_confirmation(confirmation):
    if (not isinstance(confirmation, dict) or set(confirmation) != {'version', 'confirmed', 'source_digest', 'labels'}
            or type(confirmation['version']) is not int or confirmation['version'] not in (1, 2, 3, 4, 5, 6)
            or confirmation['confirmed'] is not True or not isinstance(confirmation['source_digest'], str)
            or not isinstance(confirmation['labels'], dict)):
        raise invalid()
    labels = {}
    for key, value in confirmation['labels'].items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise invalid()
        modern = confirmation['version'] in (4, 5, 6)
        is_summary = modern and key == 'research_summary'
        is_unit = key == 'unit' or modern and key.startswith('unit:')
        limit = 4000 if is_summary else 80 if modern and is_unit else 160
        if (not isinstance(key, str) or not isinstance(value, str) or len(value) > limit
                or any(unicodedata.category(char) in ('Cc', 'Cf', 'Cs') and not (is_summary and char in '\n\t') for char in value)):
            raise invalid()
        value = value.strip()
        if not value and not (is_unit or is_summary):
            raise invalid()
        labels[key] = value
    return {**confirmation, 'labels': labels}


def freeze_confirmation(snapshot, task_type, user_id, confirmation):
    normalized = normalize_confirmation(confirmation)
    if (normalized['version'] != disclosure_version(snapshot)
            or normalized['source_digest'] != source_digest(snapshot, task_type, user_id)):
        raise StorageError('task_source_conflict', '发送前检查的资料已变化，请重新读取并确认。', 409)
    labels = validate_labels(snapshot, task_type, normalized['labels'])
    return {'version': normalized['version'], 'provider': 'openai', 'task_type': task_type, 'labels': labels,
            'source_digest': normalized['source_digest'], 'confirmed_by': user_id,
            'confirmed_at': datetime.now(timezone.utc).isoformat(), 'confirmation_digest': digest(normalized)}


def validate_labels(snapshot, task_type, labels):
    if set(labels) != set(default_labels(snapshot, task_type)):
        raise invalid()
    if snapshot['result'].get('result_type') in ('correlation', 'group_comparison','regression','roc','survival'):
        fields = [labels['field:'+variable['column']] for variable in snapshot['result']['variables'] if variable['column']!=snapshot['result']['selection'].get('id_column')]
        if len(fields) != len(set(fields)):
            raise invalid()
        if snapshot['result'].get('result_type') in ('correlation','regression','roc'): return labels
        if snapshot['result'].get('result_type')=='survival':
            groups=[labels[f'group:{i}'] for i in range(len(snapshot['result']['statistics']['groups']))]
            if len(groups)!=len(set(groups)): raise invalid()
            return labels
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
