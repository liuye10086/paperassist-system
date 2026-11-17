"""Bind optional presentation to the existing immutable export task."""
from copy import deepcopy
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.literature.service import digest
from app.domain.school_templates import bsu_gs501
from .contracts import ExportRequest
from .presentation import PresentationService

SCHOOL_IDENTITY_MASK = 'protected-fields-v1'


def resolve(service, db, version, request):
    if not request.presentation_version_id:return None
    row, base, peer, preview = PresentationService(service).fixed(
        db, version['project_id'], version['manuscript_id'], request.presentation_version_id, base_version=version)
    if base['id'] != version['id']:raise StorageError('task_input_invalid','输出配置不属于当前稿件版本。',422)
    view = request.language_view or base['snapshot_json']['output_language']
    language = 'zh-CN' if view == 'zh-CN-en' else view
    selected = next((v for v in (base, peer) if v and v['snapshot_json']['output_language'] == language), None)
    if selected is None or view == 'zh-CN-en' and peer is None:
        raise StorageError('presentation_language_unavailable','输出配置缺少所选语言的固定稿件。',422)
    binding = dict(presentation_version_id=row['id'], config_sha256=digest(preview['config']),
                   presentation_sha256=row['snapshot_sha256'], base_version_id=base['id'], base_sha256=base['snapshot_sha256'],
                   peer_version_id=peer['id'] if peer else None, peer_sha256=peer['snapshot_sha256'] if peer else None,
                   language_view=view, review_mode=request.review_mode)
    review=preview['config'].get('language_review')
    if review and (review['language_view']!=view or review['review_mode']!=request.review_mode):
        raise StorageError('task_input_invalid','所选视图与固定语言确认不符，请使用对应配置。',422)
    return dict(row=row, base=base, peer=peer, selected=selected, preview=preview, binding=binding)


def school_request(context, request):
    if context is None:return request
    school = context['preview']['config'].get('school')
    if not school:return request
    options = school['options']
    if request.school is not None and request.school.model_dump(mode='json') != options:
        raise StorageError('task_input_invalid','学校选项已固定在输出配置中；修改后请保存新配置版本。',422)
    return ExportRequest(school=options)


def reviewed_school_submission_forms(db, context):
    """Use the form variant already represented by an exact language approval."""
    if context is None or not bsu_gs501.selected(context['selected']['snapshot_json']):
        return None
    review = context['preview']['config'].get('language_review')
    if not review:
        return None
    version = context['base']
    row = db.execute('SELECT metadata_json FROM manuscript_exports WHERE id=%s AND version_id=%s',
                     (review['source_export_id'], version['id'])).fetchone()
    if not row or not row['metadata_json']:
        raise source_conflict()
    metadata = row['metadata_json']
    school = metadata.get('presentation', {}).get('school') or metadata.get('school') or {}
    return 'submission_forms_source_sha256' in school.get('plan', {})


def customer_school_mask(service, db, context):
    snapshot=context['selected']['snapshot_json']
    if (context['binding']['review_mode']!='blind' or not snapshot.get('thesis_context')
            or not (service.assets.customer or bsu_gs501.selected(snapshot))):
        return None
    _require_masked_language_source(db, context)
    return SCHOOL_IDENTITY_MASK


def _require_masked_language_source(db, context):
    review=context['preview']['config'].get('language_review')
    if not review:return
    base=context['base']
    source=db.execute('''SELECT t.input_snapshot->'presentation'->>'school_identity_mask' AS mask
        FROM manuscript_exports e JOIN tasks t ON t.id=e.task_id
        WHERE e.id=%s AND e.version_id=%s AND t.project_id=%s AND t.user_id=%s''',
        (review['source_export_id'],base['id'],base['project_id'],base['user_id'])).fetchone()
    if not source or source['mask']!=SCHOOL_IDENTITY_MASK:
        raise StorageError('task_input_invalid','请先生成遮蔽固定身份字段的盲审 Word，再用于语言确认。',422)


def seal(service, db, context):
    if not context['preview']['can_export']:
        raise StorageError('presentation_consistency_conflict','输出配置存在一致性冲突，请先核对。',422)
    selected = context['selected']; plan = None
    if bsu_gs501.selected(selected['snapshot_json']) and excluded_chapters(context):
        raise StorageError('school_export_input_invalid','GS501 论文须保留已确认的全部章节。',422)
    if selected['id'] != context['base']['id'] and selected['snapshot_json'].get('thesis_context'):
        options = service.school_options(selected, school_request(context, ExportRequest()))
        plan = service.compile_school_intent(db, selected, options,
            submission_forms=reviewed_school_submission_forms(db, context))['plan']
        if not plan['report']['can_export']:
            raise StorageError('task_input_invalid','所选语言的学校排版配置存在错误。',422)
    sealed=dict(binding=context['binding'], render_school_plan=plan)
    mask=customer_school_mask(service,db,context)
    if mask is not None:sealed['school_identity_mask']=mask
    return sealed


def verify(service, db, version, task, *, current=False, progress=None):
    sealed = task['input_snapshot'].get('presentation')
    if sealed is None:return None
    binding = sealed['binding']
    request = ExportRequest(presentation_version_id=binding['presentation_version_id'],
                            language_view=binding['language_view'], review_mode=binding['review_mode'])
    context = resolve(service, db, version, request)
    if context['binding'] != binding or not context['preview']['can_export']:raise source_conflict()
    selected = context['selected']; plan = sealed.get('render_school_plan')
    needs_plan = selected['id'] != version['id'] and bool(selected['snapshot_json'].get('thesis_context'))
    if (plan is not None) != needs_plan:raise source_conflict()
    if plan is not None:
        from .school_export import validate_school_export
        validate_school_export(plan, selected['snapshot_json'], service.school_analysis(db, selected, current=current))
    if 'school_identity_mask' in sealed:
        if (sealed['school_identity_mask']!=SCHOOL_IDENTITY_MASK or binding['review_mode']!='blind'
                or not selected['snapshot_json'].get('thesis_context')):raise source_conflict()
        _require_masked_language_source(db, context)
    if context['peer'] is not None:
        producer = service.store.require_task(db, context['peer']['task_id'])
        if producer['status'] != 'succeeded':raise source_conflict()
        if current:service.verify_task(db, producer, current=True, progress=progress)
    return context


def excluded_chapters(context):
    config = context['preview']['config']; school = config.get('school') or {}
    chapters = context['selected']['snapshot_json'].get('sections', [])
    excluded = set(school.get('exclude_chapter_ids', []))
    included = school.get('include_chapter_ids', [])
    if included:
        excluded.update(s['id'] for s in chapters if s['id'] not in included and s.get('purpose') != 'abstract')
    if context['binding']['review_mode'] == 'blind':excluded.update(config['blind']['hidden_chapter_ids'])
    return excluded


def preview_view(context):
    from app.adapters.manuscript_presentation_docx import paragraphs
    selected = context['selected']['snapshot_json']; config = context['preview']['config']
    hidden = excluded_chapters(context)
    items = [(p, s.get('output_language', selected['output_language'])) for s in selected.get('sections', []) if s['id'] not in hidden
             for p in s['paragraphs']] if selected.get('sections') else [(p, selected['output_language']) for p in paragraphs(selected)]
    if context['binding']['language_view'] == 'zh-CN-en':
        english = next(v['snapshot_json'] for v in (context['base'],context['peer']) if v['snapshot_json']['output_language']=='en')
        lookup = {p['id']:p for p in paragraphs(english)}
        visible={p['id'] for p,_ in items}
        suppressed={p['id'] for s in english.get('sections',[]) if s['id'] in hidden for p in s['paragraphs']}
        after={};used=set(suppressed)
        for group in config['paragraph_groups']:
            anchors=[identity for identity in group['zh_ids'] if identity in visible]
            if group['zh_ids'] and not anchors:
                used.update(group['en_ids']);continue
            if anchors:after[anchors[-1]]=group['en_ids']
        assembled = []
        for p, lang in items:
            assembled.append((p, lang))
            for identity in after.get(p['id'],[]):
                if identity in suppressed:continue
                assembled.append((lookup[identity],'en'));used.add(identity)
        assembled.extend((p,'en') for key,p in lookup.items() if key not in used)
        items=assembled
    allowed={e['term'] for e in config['blind']['exceptions']}
    terms=sorted((t for t in config['blind']['identity_terms'] if t not in allowed), key=len, reverse=True)
    replacement='XXX' if bsu_gs501.selected(selected) else '[已隐去]'
    projected=[]
    for p, language in items:
        text=p['text']
        if context['binding']['review_mode']=='blind':
            for term in terms:text=text.replace(term,replacement)
        projected.append(dict(id=p['id'],text=text,target_language=language))
    return dict(binding=context['binding'],checks=context['preview']['checks'],quality=context['preview']['quality'],
                preview_paragraphs=projected,blind_rules=deepcopy(config['blind']),
                notice='固定文本预览；实际 DOCX 身份及图像检查以导出回执为准。')


def public_view(context, metadata=None):
    saved=(metadata or {}).get('presentation')
    if saved is not None and saved.get('binding')!=context['binding']:raise source_conflict()
    return saved or dict(binding=context['binding'],checks=context['preview']['checks'],quality=context['preview']['quality'],
                         blind=None,language_inventory=[])


def confirmed_metadata(context, prior):
    """Overlay exact-output confirmation without rewriting source observations."""
    result=deepcopy(prior);preview=context['preview'];review=preview['config']['language_review']
    original_checks=deepcopy(prior.get('checks',[]))
    actual={c['code']:c for c in original_checks if c.get('count_projection',{}).get('scope')=='actual_docx_main_document'}
    result['checks']=[deepcopy(actual[c['code']]) if c['code'] in actual and c.get('requirement')==actual[c['code']].get('requirement') else deepcopy(c) for c in preview['checks']]
    result['binding']=deepcopy(context['binding'])
    proof=preview['language_review']
    result['language_review']=dict(deepcopy(review),**deepcopy(proof),source_checks=original_checks)
    result['quality']=dict(preview['quality'],language_review='confirmed_for_exact_output')
    decisions={d['location']:d for d in review['decisions']}
    for item in result.get('language_inventory',[]):
        decision=decisions[item['location']]
        item['confirmation']=dict(status='confirmed_for_exact_output',source_export_id=review['source_export_id'],source_sha256=review['source_sha256'],
            content_sha256=decision['content_sha256'],decision=decision['decision'],reason=decision['reason'],exceptions=deepcopy(decision['exceptions']))
    return result


def verify_gs501_reviewed_output(context, plan, content):
    """A previously reviewed document can still contain newly identified terms."""
    if context['binding']['review_mode'] != 'blind' or not bsu_gs501.selected(context['selected']['snapshot_json']):
        return
    from app.adapters.manuscript_presentation_docx import inspect_docx

    config = context['preview']['config']
    rules = bsu_gs501.blind_terms(plan, config['blind'], authors=config['authors'])
    if inspect_docx(content, rules)['known_identity_check'] != 'passed':
        raise StorageError('gs501_reviewed_output_stale', '已确认的盲评稿仍含已知身份信息，请重新生成盲评 Word 并确认输出语言。', 422)


def actual_checks(context, inventory):
    """Finish only whole-document observations that require the actual new output."""
    import re
    from app.domain.journals.format_rules import count_text
    checks=deepcopy(context['preview']['checks'])
    school=context['preview']['config'].get('school') or {}
    for index,limit in enumerate(school.get('length_requirements',[])):
        if limit['scope']!='whole':continue
        text='\n'.join(i['text'] for i in inventory if i['location'].startswith('word/document.xml:') and i['target_language']==limit['language'])
        observed=count_text(text,limit['language'])
        actual=(len(re.sub(r'\s','',text)) if limit['unit']=='characters' else observed['hanzi']+observed['latin_words'] if limit['language']=='zh-CN' else observed['whitespace_words'])
        passed=actual>=limit['value'] if limit['kind']=='minimum' else actual<=limit['value']
        code='school:length:'+str(index)
        replacement=dict(code=code,status='passed' if passed else 'conflict',actual=actual,requirement=limit,
            count_projection=dict(scope='actual_docx_main_document',language=limit['language'],
                count_method='non_whitespace_characters' if limit['unit']=='characters' else 'zh_hanzi_latin' if limit['language']=='zh-CN' else 'en_whitespace',
                includes=['cover','headings','abstract','body','manual_material','references','authors','statements','tables_captions','toc_cache'],
                excludes=['headers_footers','document_properties','image_text']),
            message='按实际DOCX主文档文字及逐位置预期语言计数；包括前置页和声明，排页眉页脚、属性和图内文字；不是Word软件字数或真实合规验收。')
        checks=[replacement if c['code']==code else c for c in checks]
    return checks
