"""Finite display projection; canonical scientific content never changes."""
from copy import deepcopy
from app.domain.manuscript_writing.contracts import SECTION_IDS
from . import frontiers_review as frontiers

DISPLAY_VERSION='journal_display_v1'
STYLE_KEYS=tuple(scope+'_'+field for scope in ('heading','body') for field in ('font_size_pt','line_spacing','space_before_pt','space_after_pt'))
STYLE_DEFAULTS=dict(heading_font_size_pt=14,body_font_size_pt=11,heading_line_spacing=1.15,body_line_spacing=1.15,heading_space_before_pt=12,heading_space_after_pt=6,body_space_before_pt=0,body_space_after_pt=6)

def synthetic_input(snapshot):
    return bool(snapshot.get('synthetic') is True or snapshot.get('writing_provenance',{}).get('provider_provenance')=='synthetic_fixture' or snapshot.get('journal_adaptation_provenance',{}).get('synthetic') is True or any(s.get('content',{}).get('engine',{}).get('id')=='synthetic_fixture' for s in snapshot.get('sources',[])))

def is_narrative_review(snapshot):
    return snapshot.get('article_type') == 'narrative_review' and not snapshot.get('thesis_context')

def completed_narrative_review(snapshot):
    if not is_narrative_review(snapshot):
        return False
    from app.domain.manuscript_writing.article_contract import STRUCTURES

    review = snapshot.get('writing_provenance', {})
    return (tuple(section['id'] for section in snapshot.get('sections', [])) == STRUCTURES['narrative_review']
            and review.get('schema_version') == 2
            and review.get('verification_status') == 'scientific_and_language_reviewed')

def defaults(snapshot):
    from app.adapters.manuscript_docx import SECTION_LABELS

    labels = SECTION_LABELS
    if is_narrative_review(snapshot):
        from app.domain.manuscript_writing.article_contract import labels as article_labels

        labels = article_labels('narrative_review')
    names = {key: en if snapshot['output_language'] == 'en' else zh for key, en, zh in labels}
    return dict(version=DISPLAY_VERSION, names=names, order=list(names), styles={})

def context(snapshot):
    base = defaults(snapshot)
    saved = snapshot.get('journal_display_context')
    value = deepcopy(saved or base)
    if value.get('version') != DISPLAY_VERSION or set(value['names']) != set(base['names']) or sorted(value['order']) != sorted(base['order']) or value['order'][0] != 'title':
        raise ValueError('Invalid journal display mapping')
    if len(set(value['names'].values())) != len(base['order']):
        raise ValueError('Display headings must be one-to-one')
    profile = value.get('frontiers_review')
    if profile is not None:
        if (not completed_narrative_review(snapshot) or snapshot['output_language'] != 'en'
                or not isinstance(profile, dict) or not profile
                or set(profile)-{'headings', 'single_spacing', 'page_line_numbers', 'reference_texts', 'submission_layout'}
                or any(v is not True for k, v in profile.items() if k != 'reference_texts')
                or ('reference_texts' in profile and profile['reference_texts'] != frontiers.reference_texts(snapshot))):
            raise ValueError('Invalid Frontiers Review display configuration')
    if saved and is_narrative_review(snapshot):
        names = base['names'] | (frontiers.HEADING_NAMES if (profile or {}).get('headings') else {})
        if not completed_narrative_review(snapshot) or value['names'] != names or value['order'] != base['order']:
            raise ValueError('Narrative review display requires reviewed sections in canonical order')
    if set(value['styles'])-set(STYLE_KEYS):raise ValueError('Unsupported journal style')
    for key,number in value['styles'].items():validate_style(key,number)
    return value

def validate_style(key,value):
    low,high=(8,36) if key.endswith('font_size_pt') else (1,3) if key.endswith('line_spacing') else (0,72)
    if type(value) not in (int,float) or not low<=value<=high:raise ValueError('Finite display value outside supported range')

def display_sections(snapshot):
    value=context(snapshot);sections={s['id']:s for s in snapshot['sections']}
    return [dict(sections[k], display_name=value['names'][k], heading_level=_heading_level(value, k)) for k in value['order']]


def _heading_level(value, key):
    return frontiers.HEADING_LEVELS.get(key, 1) if value.get('frontiers_review', {}).get('headings') else 1


def _frontiers_action(snapshot, value, key, new):
    texts = frontiers.reference_texts(snapshot) if key == 'reference_style' else None
    profile = value.setdefault('frontiers_review', {})
    if key == 'required_sections':
        value['names'].update({k: heading['display_name'] for k, heading in new.items()})
        profile['headings'] = True
    elif key in frontiers.DISPLAY_FLAGS:
        profile[frontiers.DISPLAY_FLAGS[key]] = True
    elif key == frontiers.SUBMISSION_LAYOUT:
        profile['submission_layout'] = True
    else:
        profile['reference_texts'] = texts

def plan(snapshot,target,warnings):
    before=context(snapshot);after=deepcopy(before);actions=[];unexecuted=[]
    rules=sorted(target['selected_requirements'],key=lambda r:r['key']=='section_order')
    complete_research = [s['id'] for s in snapshot.get('sections', [])] == list(SECTION_IDS)
    narrative = is_narrative_review(snapshot)
    complete_review = completed_narrative_review(snapshot)
    for rule in rules:
        key=rule['key'];reason=None;old=None;new=rule['value']
        if not (complete_research or complete_review):
            reason = '综述须先完成科学与语言审核并发布。' if narrative else '需要已发布的完整七部分公共稿件。'
        elif any(w.get('blocks_rules',True) and w.get('source_id') in (None,rule['source_id']) for w in warnings):reason='来源或许可不可用，不能执行。'
        elif rule['status']!='known':reason='未知或不支持要求。'
        elif complete_review and snapshot['output_language']=='en' and frontiers.confirmed_rule(target, rule):
            profile = after.get('frontiers_review', {})
            evidence = [rule]
            if key == 'required_sections':
                keys = (*frontiers.HEADING_NAMES, *frontiers.HEADING_LEVELS)
                old = {k: dict(display_name=after['names'][k], level=_heading_level(after, k)) for k in keys}
                new = {k: dict(display_name=frontiers.HEADING_NAMES.get(k, after['names'][k]),
                               level=frontiers.HEADING_LEVELS.get(k, 1)) for k in keys}
            elif key == 'section_order':
                if [after['names'][k] for k in after['order'] if after['names'][k] in new] == new:
                    continue  # Heading mapping meets the order without moving text.
                reason = '所选综述章节显示尚不匹配；需核对必需章节。'
            elif key == 'document_single_spacing':
                old = bool(profile.get('single_spacing'))
            elif key == 'document_page_line_numbers':
                old = dict(page=True, line=bool(profile.get('page_line_numbers')))
                new = dict(page=True, line=True)
            elif key == 'reference_style':
                old = frontiers.REFERENCE_STYLE if 'reference_texts' in profile else 'NLM'
            elif key == frontiers.SUBMISSION_LAYOUT:
                old = bool(profile.get('submission_layout'))
                evidence = frontiers.submission_evidence(target, ('word_limit', *frontiers.LAYOUT_RULES), warnings)
                if not evidence:
                    reason = '先确认 Review 篇幅和图表排版的官方条款。'
                else:
                    content = frontiers.submission_content(snapshot)
                    if (not all(frontiers.sequential_numbering(content[k]) for k in ('figures', 'tables'))
                            or not all(frontiers.editable_table(table) for table in content['tables'])):
                        reason = '图表编号或表格结构待核对，无法采用投稿排版。'
            else:
                continue  # A confirmed requirement is used by the read-only submission check.
            if not reason and old != new:
                try:
                    _frontiers_action(snapshot, after, key, new)
                except (ValueError, KeyError, TypeError):
                    reason = '参考文献缺少完整固定元数据，须人工处理。'
                else:
                    actions.append(dict(id=rule['id'], key=key, before=old, after=new, evidence=evidence,
                                        reason='采用已确认的 Frontiers 综述规则；保留审后正文与引用编号。'))
                    continue
            elif not reason:
                continue
        elif narrative and key in ('section_display_names', 'section_order'):
            reason = '综述使用固定的章节名称与顺序。'
        elif key=='section_display_names':
            old=after['names'];new={i['section_id']:i['display_name'] for i in new}
        elif key=='section_order':
            names={v:k for k,v in after['names'].items()};old=after['order']
            if len(new)!=len(SECTION_IDS) or set(new)!=set(names):reason='顺序列表必须明确映射全部七个语义部分。'
            else:
                new=[names[n] for n in new]
                if new[0]!='title':reason='标题必须保持首位。'
        elif key in STYLE_KEYS:
            old=after['styles'].get(key,STYLE_DEFAULTS[key])
        else:reason='本批仅执行显示名称、顺序及有限格式；此项保留人工处理。'
        if reason:
            unexecuted.append(dict(key=key,evidence=[rule],reason=reason));continue
        if old==new:continue
        action=dict(id=rule['id'],key=key,before=deepcopy(old),after=deepcopy(new),evidence=[rule],reason='采用明确原句和固定指南版本；仅改变显示。')
        if key=='section_order':
            candidate=deepcopy(snapshot);candidate['journal_display_context']=deepcopy(after)|dict(order=new)
            from app.domain.manuscript_review.checks import check_snapshot
            if any(i['category']=='reference' and i['severity']=='error' for i in check_snapshot(candidate)):
                unexecuted.append(dict(key=key,evidence=[rule],reason='重排无法保持NLM首次引用顺序，须人工处理。'));continue
        actions.append(action)
        if key=='section_display_names':after['names']=new
        elif key=='section_order':after['order']=new
        else:after['styles'][key]=new
    unexecuted += [dict(key=c['key'],evidence=c['requirements'],reason=c['reason']) for c in target['conflicts']]
    def section_display(value, key):
        profile = value.get('frontiers_review', {})
        scoped = 'frontiers_review' in before or 'frontiers_review' in after
        styles = value['styles'] if key != 'title' else {}
        if profile.get('single_spacing'):
            styles = styles | dict(document_single_spacing=True)
        return dict(display_name=value['names'][key], position=value['order'].index(key), styles=styles,
                    **({'level': _heading_level(value, key)} if scoped else {}))
    sections=[dict(section_id=k,before=section_display(before,k),after=section_display(after,k)) for k in before['names']]
    for s in sections:s['changed']=s['before']!=s['after']
    return dict(sections=sections,actions=actions,unexecuted=unexecuted,display_context=after)

def apply(snapshot,actions):
    result=deepcopy(snapshot);value=context(snapshot)
    for a in actions:
        if a['key']=='section_display_names':value['names']=deepcopy(a['after'])
        elif a['key']=='section_order':value['order']=deepcopy(a['after'])
        elif a['key'] in ('required_sections', 'reference_style', frontiers.SUBMISSION_LAYOUT, *frontiers.DISPLAY_FLAGS):
            _frontiers_action(snapshot,value,a['key'],a['after'])
        else:value['styles'][a['key']]=a['after']
    result['journal_display_context']=value
    context(result)
    return result
