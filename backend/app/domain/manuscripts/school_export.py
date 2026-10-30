"""Seal a bounded school rendering plan without rewriting manuscript evidence."""
from copy import deepcopy
import re

from app.core.exceptions import StorageError
from app.domain.literature.service import digest
from .school import CHAPTER_FIELDS, validate_chapters

RULES_VERSION='school-export-v1'
FRONT_RULES_VERSION='school-export-v2'
REAL_TEMPLATE_SHA256='9de691486c50471b124fd4378d09b9b5f45d81404ad8108e91f3116520b974fa'
MANUAL_LABELS={'author':'作者','student_id':'学号','department':'院系','major':'专业','class_name':'班级','supervisor':'指导教师','submission_date':'提交日期'}


def invalid(message):
    return StorageError('school_export_input_invalid',message,422)


def _position(source):
    match=re.search(r'/w:body/w:p\[(\d+)\]',source.get('path',''))
    return int(match[1]) if match else None


def _section(chapter,analysis):
    original=next((c for c in analysis.get('chapters',[]) if c['id']==chapter['id']),None)
    position=_position(original.get('source',{})) if original else None
    sections=analysis.get('sections',[])
    if not sections:raise invalid('固定学校分析缺少页面分节来源。')
    if position is not None:
        for section in sections:
            end=_position(section.get('source',{}))
            if end is None or position<=end:return deepcopy(section),True
    return deepcopy(sections[0]),False


def _explicit_style_spacing(analysis,styles,style_sources):
    """Preserve only located raw paragraph attributes for four fixed style roles."""
    raw=analysis.get('raw_styles',[]);by_id={s['id']:s for s in raw}
    for category,names in [('heading1',('heading1','标题1')),('heading2',('heading2','标题2')),('heading3',('heading3','标题3')),('title_zh',('title',))]:
        matches=[s for s in raw if re.sub(r'\s+','',s['name']).lower() in names]
        if len(matches)!=1:continue
        for key,prop in [('space_before_lines','pPr.spacing.beforeLines'),('space_after_lines','pPr.spacing.afterLines')]:
            node=matches[0];seen=set()
            while node and node['id'] not in seen:
                seen.add(node['id']);value=node.get('properties',{}).get(prop)
                if value is not None:
                    if re.fullmatch(r'\d{1,5}',str(value)):
                        styles.setdefault(category,{})[key]=str(value)
                        style_sources.setdefault(category,{})[key]=dict(part='word/styles.xml',path=f'/w:styles/w:style[@w:styleId="{node["id"]}"]',text=prop)
                    break
                node=by_id.get(node.get('based_on'))


def compile_school_export(snapshot,analysis,options):
    context=snapshot.get('thesis_context')
    if not context or digest(analysis)!=context['confirmation'].get('analysis_sha256'):
        raise StorageError('task_source_conflict','学校导出必须读取稿件固定确认的原分析版本。',409)
    if digest(context['confirmation'])!=context['confirmation_sha256']:
        raise StorageError('task_source_conflict','学校确认快照已变化。',409)
    from app.domain.school_templates.front_matter import validate_content_purposes
    front=context['confirmation'].get('front_matter')
    try:validate_content_purposes(front,context['chapters'])
    except ValueError as exc:raise invalid('前置内容要求须对应声明人工章节或致谢用途。') from exc
    validate_chapters(context,{g['id'] for g in snapshot['results_groups']})
    if [{k:s.get(k) for k in CHAPTER_FIELDS} for s in snapshot['sections']]!=[{k:c[k] for k in CHAPTER_FIELDS} for c in context['chapters']]:
        raise invalid('稿件章节与固定学校确认不一致。')
    chapters=deepcopy(context['chapters']);by_id={c['id']:c for c in chapters}
    front_sources={}
    if front is not None:
        from app.domain.school_templates.front_matter import validate_front_matter,resolved_sources
        front=validate_front_matter(front,analysis,chapters)
        front_sources=resolved_sources(front,analysis)
        if set(options.get('field_values',{}))-{f['id'] for f in front['fields']}:raise invalid('动态值必须对应固定学校确认字段。')
    elif options.get('field_values'):raise invalid('旧学校确认不接受动态前置字段。')
    for key,role in [('manual_chapters','manual'),('keywords','abstract')]:
        seen=set()
        for item in options.get(key,[]):
            identity=item['chapter_id']
            if identity in seen or identity not in by_id or by_id[identity]['purpose']!=role:
                raise invalid('人工内容或关键词必须对应固定学校章节，且不能重复。')
            seen.add(identity)
    styles={};style_sources={}
    for rule in context['confirmation']['rules']:
        if rule['category'] in ('page','text_requirement'):continue
        name=rule['category'];key=rule['id'].split('.',1)[-1]
        styles.setdefault(name,{})[key]=deepcopy(rule['value'])
        style_sources.setdefault(name,{})[key]=deepcopy(rule['source'])
    issues=[]
    def issue(identity,kind,message,*,location='',severity='human_review',sources=None):
        issues.append(dict(id=identity,kind=kind,severity=severity,location=location,message=message,source_evidence=deepcopy(sources or [])))
    decisions=[];notes=deepcopy(analysis.get('notes',[]));supported=any(s.get('role')=='template' and s.get('sha256')==REAL_TEMPLATE_SHA256 for s in context['source_files'])
    # These two source conflicts were explicitly decided by the user for this
    # actual retained template. They never mutate the old confirmation JSON.
    if supported and front is None:
        latin=next((n for n in notes if '英文一律' in n['text'] and 'Times New Roman' in n['text']),None)
        line=next((n for n in notes if '一级标题' in n['text'] and '1.5倍' in n['text']),None)
        if latin and not context['confirmation'].get('text_decisions'):
            for style in styles.values():style['font_latin']='Times New Roman'
            decisions.append(dict(id='user-text-latin',message='用户已确认采用模板文字说明：英文及数字采用Times New Roman；原确认属性保留。',source_evidence=[latin['source']]))
        if line and not context['confirmation'].get('text_decisions'):
            styles.setdefault('heading1',{}).update(line_spacing='360',line_rule='auto')
            decisions.append(dict(id='user-text-heading-spacing',message='用户已确认采用模板文字说明：一级标题1.5倍行距；原确认属性保留。',source_evidence=[line['source']]))
        # The paragraph spacings below agree with the original paragraph/style
        # attributes. They supplement fields omitted by the first-batch parser.
        for category,label,lines in [('heading1','一级标题',200),('heading2','二级标题',100),('heading3','三级标题',100)]:
            note=next((n for n in notes if label in n['text'] and f'段前{lines//100}行' in n['text'] and f'段后{lines//100}行' in n['text']),None)
            if note:
                for key in ('space_before_lines','space_after_lines'):
                    styles.setdefault(category,{})[key]=str(lines)
                    style_sources.setdefault(category,{})[key]=deepcopy(note['source'])
        title=next((s for s in analysis.get('raw_styles',[]) if s['name']=='Title'),None)
        if title:
            for category in ('title_zh',):
                for key,prop in [('space_before_lines','pPr.spacing.beforeLines'),('space_after_lines','pPr.spacing.afterLines')]:
                    if prop in title['properties']:
                        styles.setdefault(category,{})[key]=title['properties'][prop]
                        style_sources.setdefault(category,{})[key]=dict(part='word/styles.xml',path=f'/w:styles/w:style[@w:styleId="{title["id"]}"]',text=prop)
    else:
        issue('school:template-support','unsupported','此模板尚无本批真实成品还原证据；导出只应用可确定规则，须人工核对。')
        _explicit_style_spacing(analysis,styles,style_sources)
    explicit=context['confirmation'].get('text_decisions',[])
    if explicit:
        decisions=[d for d in decisions if d['id'] not in ('user-text-latin','user-text-heading-spacing')]
        for decision in explicit:
            if decision['choice']!='text':continue
            if decision['id']=='latin_font':
                for style in styles.values():style['font_latin']='Times New Roman'
            elif decision['id']=='heading1_line_spacing':styles.setdefault('heading1',{}).update(line_spacing='360',line_rule='auto')
            decisions.append(dict(id='confirmed-text-'+decision['id'],message='本次学校确认明确采用文字说明。',source_evidence=[decision['evidence']]))
    sections=[]
    for chapter in chapters:
        section,located=_section(chapter,analysis)
        # Resolved per-section page values override the original raw attributes.
        for rule in context['confirmation']['rules']:
            prefix=section['id']+'.'
            if rule['category']=='page' and rule['id'].startswith(prefix):section['page'][rule['id'][len(prefix):]]=rule['value']
        section['chapter_id']=chapter['id'];sections.append(section)
        if not located:issue('school:section:'+chapter['id'],'format','新增章节没有原模板位置，使用首节页面规则；请核对分节。',location=chapter['id'])
    first=deepcopy(next(s for s in analysis['sections'] if s['id']==front['cover_section_id']) if front is not None else analysis['sections'][0]);first['chapter_id']='__cover__'
    if front is not None:
        for rule in context['confirmation']['rules']:
            prefix=first['id']+'.'
            if rule['category']=='page' and rule['id'].startswith(prefix):first['page'][rule['id'][len(prefix):]]=rule['value']
    toc_original=next((c for c in analysis.get('chapters',[]) if re.sub(r'\s+','',''+c['title']) in ('目录','Contents')),None)
    toc_section=_section(toc_original,analysis)[0] if toc_original else deepcopy(sections[0])
    toc_section['chapter_id']='__toc__'
    # Template section format is immutable; defaults below are explicit OOXML
    # defaults, not inferred changes to the old school profile.
    label_map=dict(figures={},tables={});chapter_number=0;chapter_counts={}
    for chapter in chapters:
        if chapter['purpose'] in ('manual','abstract','references','acknowledgements'):continue
        if chapter['level']==1:chapter_number+=1
        match=re.match(r'^\s*(\d+)(?:[.、．\s]|$)',chapter['title'])
        number=match[1] if match else str(max(1,chapter_number))
        counts=chapter_counts.setdefault(number,dict(figures=0,tables=0))
        for group in snapshot['results_groups']:
            if group['id'] not in chapter['result_group_ids']:continue
            for kind in counts:
                for item in group[kind]:
                    counts[kind]+=1
                    label_map[kind][str(item['number'])]=number+'.'+str(counts[kind])
    manual=options.get('manual_fields',{})
    for key,label in (MANUAL_LABELS.items() if front is None else []):
        if not (manual.get(key) or context['profile'].get(key)):
            issue('school:manual:'+key,'manual',label+'未提供，工程稿保留待填写。',location=key)
    manual_text={i['chapter_id']:i['text'] for i in options.get('manual_chapters',[])}
    keyword_options={i['chapter_id']:i['values'] for i in options.get('keywords',[])}
    for chapter in chapters:
        if front is None and chapter['purpose']=='manual' and not manual_text.get(chapter['id']):
            issue('school:manual-chapter:'+chapter['id'],'manual','声明、身份及签名须由用户提供；此章保留待补充。',location=chapter['id'])
        if chapter['purpose']=='abstract':
            values=keyword_options.get(chapter['id'],snapshot.get('keywords',[]) if chapter['output_language']==snapshot['output_language'] else [])
            if front is None and not 3<=len(values)<=5:issue('school:keywords:'+chapter['id'],'content','请核对本章关键词，当前真实模板要求3至5个。',location=chapter['id'])
            if chapter['output_language']=='en' and snapshot['output_language']!='en' and not options.get('english_title'):
                issue('school:english-title','manual','英文题名未提供，不自动翻译或编造。',location=chapter['id'])
    for item in context['confirmation'].get('missing',[]):
        if front is not None and item['id']=='cover_rules':continue
        issue('school:missing:'+item['id'],'manual',item['message'])
    for item in context['confirmation'].get('unsupported',[]):
        if item['id'] not in ('footnote_citations','text_rules_manual'):
            issue('school:unsupported:'+item['id'],'unsupported',item['message'])
    if notes:issue('school:written-requirements','format','固定文字规范及适用边界已列出；正文语义、图片内字和未结构化要求仍须人工核对。')
    if front is None and len(snapshot['references'])<15 and any('参考文献15篇' in n['text'] for n in notes):
        issue('school:reference-count','content','模板要求15篇以上参考文献（含外文要求）；当前已核实书目不足，不能为达标编造。')
    for item in snapshot.get('school_content_report',{}).get('issues',[]):
        if item.get('severity')=='error':issue('school:content:'+item['id'],'content',item['message'],severity='error',location=item.get('location',''),sources=item.get('source_evidence',[]))
    eligible=any(c['purpose'] not in ('manual','abstract') for c in chapters)
    if options.get('include_toc',True) and not eligible:issue('school:toc-empty','format','目录没有可用的学校标题。',severity='error')
    if front is not None:
        values=options.get('field_values',{})
        for field in front['fields']:
            evidence=[front_sources[field['source_id']]['source']]
            if field['required'] and not values.get(field['id'],'').strip():
                issue('school:field:'+field['id'],'manual',field['label']+'未提供，保留待填写。',location=field['chapter_id'] or field['id'],sources=evidence)
            if field['kind']=='signature' and values.get(field['id'],'').strip():
                issue('school:signature-review:'+field['id'],'manual',field['label']+'仅为用户提供的文字，签名真实性仍须本人核对。',location=field['chapter_id'] or field['id'],sources=evidence)
        for requirement in front['content_requirements']:
            chapter=by_id[requirement['chapter_id']]
            expected='manual' if requirement['kind']=='declaration' else 'acknowledgements'
            section=next(s for s in snapshot['sections'] if s['id']==chapter['id'])
            supplied=manual_text.get(chapter['id'],'').strip() if expected=='manual' else ''
            supplied=supplied or any(p.get('text','').strip() and not p.get('id','').endswith(':pending') for p in section['paragraphs'])
            if requirement['required'] and not supplied:
                issue('school:required-content:'+requirement['id'],'content',chapter['title']+'正文待用户提供。',location=chapter['id'],sources=[front_sources[requirement['source_id']]['source']])
        issue('school:front-layout','unsupported','前置规则仅支持普通段落及有限来源样式；复杂表格、浮动布局和真实学校逐页合规仍须人工核对。')
    version=FRONT_RULES_VERSION if front is not None else RULES_VERSION
    result=dict(schema_version=2 if front is not None else 1,rules_version=version,snapshot_sha256=digest(snapshot),confirmation_id=context['confirmation_id'],confirmation_sha256=context['confirmation_sha256'],analysis_sha256=digest(analysis),options=deepcopy(options),styles=styles,style_sources=style_sources,
        sections=[first,toc_section,*sections],chapters=chapters,toc=dict(enabled=options.get('include_toc',True),depth=options.get('toc_depth',3)),label_map=label_map,rule_decisions=decisions,requirements=notes,
        citation_footnotes=any('脚注' in n['text'] and '正文引用' in n['text'] for n in notes),
        report=dict(rules_version=version,issues=issues,can_export=not any(i['severity']=='error' for i in issues),scientifically_verified=False))
    if front is not None:
        from app.domain.school_templates.front_matter import resolved_sections
        result.update(front_matter=deepcopy(front),front_matter_sources=front_sources,front_matter_sections=resolved_sections(analysis,context['confirmation']['rules']))
    provenance=snapshot.get('writing_provenance',{})
    if provenance.get('school_content_version')=='school-live-v1':
        result['language_mapping_version']=1
        if provenance.get('school_pagination_version')==2:result['pagination_version']=2
    return result


def validate_school_export(plan,snapshot,analysis=None):
    context=snapshot.get('thesis_context') or {}
    front=context.get('confirmation',{}).get('front_matter')
    provenance=snapshot.get('writing_provenance',{})
    pagination=2 if provenance.get('school_content_version')=='school-live-v1' and provenance.get('school_pagination_version')==2 else None
    if plan.get('pagination_version')!=pagination:raise invalid('学校分页版本与冻结产物不一致。')
    if snapshot.get('writing_provenance',{}).get('school_content_version')=='school-live-v1' and snapshot['writing_provenance'].get('language_review_id'):
        from app.domain.manuscript_writing.school_language import validate_options_binding
        validate_options_binding(snapshot,plan['options'],plan)
    if (plan.get('schema_version')!=(2 if front is not None else 1) or plan.get('rules_version')!=(FRONT_RULES_VERSION if front is not None else RULES_VERSION) or plan.get('snapshot_sha256')!=digest(snapshot)
        or plan.get('confirmation_id')!=context.get('confirmation_id') or plan.get('confirmation_sha256')!=context.get('confirmation_sha256')
        or plan.get('analysis_sha256')!=context.get('confirmation',{}).get('analysis_sha256')
        or plan.get('chapters')!=context.get('chapters')):
        raise StorageError('task_source_conflict','学校导出意图与原稿固定版本不一致。',409)
    if front is not None:
        from app.domain.school_templates.front_matter import FrontMatter,validate_front_matter,resolved_sources,resolved_sections
        FrontMatter.model_validate(front)
        if plan.get('front_matter')!=front or not isinstance(plan.get('front_matter_sources'),dict):raise invalid('前置规则与固定确认不一致。')
        if analysis is not None:
            validate_front_matter(front,analysis,context['chapters'])
            if plan['front_matter_sources']!=resolved_sources(front,analysis):raise invalid('前置规则来源不一致。')
            if plan.get('front_matter_sections')!=resolved_sections(analysis,context['confirmation']['rules']):raise invalid('前置页面来源不一致。')
