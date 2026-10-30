"""Resolve school bindings separately from research sources and historical content."""
from copy import deepcopy
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.literature.service import digest
from app.domain.school_templates.service import SchoolTemplateService
from .contracts import SCHOOL_PURPOSES


def readiness(service,db,project):
    schools=SchoolTemplateService(service.assets)
    profile=schools.profile_view(db,project)
    result=dict(ready=False,blocking_reasons=[],profile=profile,confirmation_id=profile['bound_confirmation_id'],chapters=[],purposes=list(SCHOOL_PURPOSES),template_source_file_ids=[])
    if not profile['bound_confirmation_id']:
        result['blocking_reasons'].append('school_template_not_bound')
        return result
    saved=db.execute('SELECT * FROM school_template_confirmations WHERE id=%s AND project_id=%s AND user_id=%s',(profile['bound_confirmation_id'],project,service.store.user_id)).fetchone()
    if not saved:
        result['blocking_reasons'].append('school_confirmation_unavailable')
        return result
    row=schools.row(db,project,saved['template_version_id'])
    sources,task=schools.validate(db,row);confirmation=schools.confirmation(db,row)
    result['chapters']=confirmation['chapters']
    result['template_source_file_ids']=[s['file_id'] for s in sources if s['role'] in ('template','supplement')]
    if task['status']!='succeeded':result['blocking_reasons'].append('school_template_not_ready')
    if schools.current_changes(db,row,sources):result['blocking_reasons'].append('school_template_source_changed')
    result['ready']=not result['blocking_reasons']
    return result


def freeze_context(service,project,request):
    with service.store.connection() as db:
        project_row=service.require_project(db,project)
        if project_row['project_type']!='thesis' or request.thesis is None:
            raise StorageError('task_input_invalid','毕业论文必须选择固定学校确认版本及章节用途。',422)
        current=readiness(service,db,project);selected=request.thesis
        if not current['ready'] or current['confirmation_id']!=selected.confirmation_id or current['profile']['revision']!=selected.profile_revision:
            raise StorageError('task_source_conflict','学校配置未就绪或已变化，请重新确认。',409)
        if any(len(c['id'])>200 for c in current['chapters']):raise StorageError('task_input_invalid','学校章节标识最长200字符，请建立新的确认版本。',422)
        if [m.chapter_id for m in selected.chapter_mappings]!=[c['id'] for c in current['chapters']]:
            raise StorageError('task_input_invalid','章节用途必须按固定确认版完整对应。',422)
        if sum(m.purpose=='references' for m in selected.chapter_mappings)>1:raise StorageError('task_input_invalid','共用引用清单只能映射一个参考文献章节。',422)
        groups={g.id for g in request.results_groups};used=[];chapters=[]
        for chapter,mapping in zip(current['chapters'],selected.chapter_mappings):
            if (mapping.result_group_ids and mapping.purpose!='results') or not set(mapping.result_group_ids)<=groups:
                raise StorageError('task_input_invalid','结果组只能分配到结果用途章节。',422)
            used.extend(mapping.result_group_ids)
            chapters.append(dict(**chapter,purpose=mapping.purpose,output_language=request.output_language if mapping.output_language=='project' else mapping.output_language,result_group_ids=mapping.result_group_ids))
        if len(used)!=len(set(used)):raise StorageError('task_input_invalid','结果组不可重复分配。',422)
        if any(s.file_id in current['template_source_file_ids'] for s in request.sources):
            raise StorageError('task_input_invalid','学校模板和补充规范不能作为研究事实来源。',422)
        saved=db.execute('SELECT * FROM school_template_confirmations WHERE id=%s AND project_id=%s AND user_id=%s',(selected.confirmation_id,project,service.store.user_id)).fetchone()
        schools=SchoolTemplateService(service.assets);row=schools.row(db,project,saved['template_version_id'])
        sources,_=schools.require_current(db,row);confirmation=schools.confirmation(db,row)
        from app.domain.school_templates.front_matter import validate_content_purposes
        try:validate_content_purposes(confirmation.get('front_matter'),chapters)
        except ValueError as exc:raise StorageError('task_input_invalid','前置内容要求须对应声明人工章节或致谢用途。',422) from exc
        return deepcopy(dict(schema_version=1,profile=current['profile'],template_version_id=row['id'],confirmation_id=saved['id'],confirmation_sha256=saved['snapshot_sha256'],confirmation=confirmation,source_files=sources,chapters=chapters))


def validate_frozen(service,db,row):
    context=row['snapshot_json'].get('thesis_context')
    if not context:
        if row.get('school_confirmation_id') is not None:raise source_conflict()
        return
    if row.get('school_confirmation_id')!=context['confirmation_id']:raise source_conflict()
    schools=SchoolTemplateService(service.assets)
    template=schools.row(db,row['project_id'],context['template_version_id'])
    sources,_=schools.validate(db,template);confirmation=schools.confirmation(db,template)
    if (confirmation!=context['confirmation'] or digest(confirmation)!=context['confirmation_sha256'] or sources!=context['source_files']):raise source_conflict()
    selected=row['request_json'].get('thesis')
    if not selected or selected['confirmation_id']!=context['confirmation_id'] or selected['profile_revision']!=context['profile']['revision']:raise source_conflict()
    expected=[dict(**chapter,purpose=mapping['purpose'],output_language=row['snapshot_json']['output_language'] if mapping['output_language']=='project' else mapping['output_language'],result_group_ids=mapping['result_group_ids']) for chapter,mapping in zip(confirmation['chapters'],selected['chapter_mappings'])]
    if (len(expected)!=len(confirmation['chapters']) or [m['chapter_id'] for m in selected['chapter_mappings']]!=[c['id'] for c in confirmation['chapters']] or context['chapters']!=expected):raise source_conflict()
    from .school import validate_chapters
    try:validate_chapters(context,{g['id'] for g in row['snapshot_json']['results_groups']})
    except (KeyError,TypeError,ValueError) as exc:raise source_conflict() from exc


def current_changes(service,project,snapshot):
    context=snapshot.get('thesis_context')
    if not context:return []
    with service.store.connection() as db:
        state=readiness(service,db,project)
    reasons=[]
    if state['profile']!=context['profile']:reasons.append('school_profile_changed')
    if state['confirmation_id']!=context['confirmation_id']:reasons.append('school_confirmation_changed')
    reasons.extend(state['blocking_reasons'])
    return [dict(kind='school_configuration',id=context['confirmation_id'],reasons=reasons)] if reasons else []
