"""Only explicit human choices can adopt validated school advice."""
from copy import deepcopy
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from .suggestion_service import SuggestionService
from .suggestion_validation import ROLES

def apply(service,db,project,template,request,rules):
    advice=SuggestionService(service.assets);row=advice.suggestion_row(db,project,request.suggestion_id)
    task=service.store.require_task(db,row['task_id'])
    if row['template_version_id']!=template['id'] or task['status']!='succeeded' or row['artifact_sha256']!=request.suggestion_artifact_sha256:raise source_conflict()
    candidates={c['id']:c for c in row['result_json']['candidates']};decisions={d.candidate_id:d for d in request.suggestion_decisions}
    if len(decisions)!=len(request.suggestion_decisions) or set(decisions)!=set(candidates) or any(not d.reason.strip() for d in decisions.values()):raise StorageError('task_input_invalid','每项规范建议均须明确接受、拒绝或保留待核对并填写理由。',422)
    accepted={};deferred=[]
    for identity,decision in decisions.items():
        candidate=candidates[identity]
        if decision.action=='accept':
            if candidate['status'] not in ('proposed','conflict'):raise StorageError('task_input_invalid','未知或不支持的规范不能作为可执行规则接受。',422)
            target=candidate['target_id'];value=candidate['normalized_value']
            if target in accepted and accepted[target]['normalized_value']!=value:raise StorageError('task_input_invalid','同一规则不能同时接受互相冲突的值。',422)
            accepted[target]=candidate
        if decision.action=='defer':deferred.append(dict(id='suggestion:'+identity,message='模型建议仍待人工核对。',source=deepcopy(candidate['source'])))
    # Existing explicit text-source choices are applied by the renderer after
    # ordinary rules. A new acceptance must never be silently overwritten there.
    options={option['id']:option for option in service.text_options(db,template)}
    for choice in request.text_decisions:
        option=options[choice.id]
        for target,candidate in accepted.items():
            relevant=(choice.id=='latin_font' and target.endswith('.font_latin') or
                choice.id=='heading1_line_spacing' and target in ('heading1.line_spacing','heading1.line_rule'))
            if not relevant:continue
            if choice.choice=='attributes':expected=option['attribute_value'].get(target)
            elif choice.id=='latin_font':expected='Times New Roman'
            else:expected='360' if target.endswith('.line_spacing') else 'auto'
            if expected is not None and str(candidate['normalized_value'])!=str(expected):
                raise StorageError('task_input_invalid','建议值与本次明确选择的文字规范来源冲突，请统一来源决定。',422)
    for target,candidate in accepted.items():
        old=next((r for r in rules if r['id']==target),None)
        category=target.split('.',1)[0];category=category if category in ROLES else 'page'
        record=dict(id=target,category=category,label=old['label'] if old and 'label' in old else target,value=deepcopy(candidate['normalized_value']),
            source=deepcopy(candidate['source']),origin='human_confirmed_suggestion')
        if old is None:rules.append(record)
        else:old.update(record)
    return dict(suggestion_id=row['id'],artifact_sha256=row['artifact_sha256'],decisions=[d.model_dump(mode='json') for d in request.suggestion_decisions],
        quote_existence_is_not_semantic_verification=True),deferred
