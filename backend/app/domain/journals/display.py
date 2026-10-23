"""Finite display projection; canonical scientific content never changes."""
from copy import deepcopy
from app.domain.manuscript_writing.contracts import SECTION_IDS

DISPLAY_VERSION='journal_display_v1'
STYLE_KEYS=tuple(scope+'_'+field for scope in ('heading','body') for field in ('font_size_pt','line_spacing','space_before_pt','space_after_pt'))
STYLE_DEFAULTS=dict(heading_font_size_pt=14,body_font_size_pt=11,heading_line_spacing=1.15,body_line_spacing=1.15,heading_space_before_pt=12,heading_space_after_pt=6,body_space_before_pt=0,body_space_after_pt=6)

def synthetic_input(snapshot):
    return bool(snapshot.get('synthetic') is True or snapshot.get('writing_provenance',{}).get('provider_provenance')=='synthetic_fixture' or snapshot.get('journal_adaptation_provenance',{}).get('synthetic') is True or any(s.get('content',{}).get('engine',{}).get('id')=='synthetic_fixture' for s in snapshot.get('sources',[])))

def defaults(snapshot):
    from app.adapters.manuscript_docx import SECTION_LABELS
    return dict(version=DISPLAY_VERSION,names={k:en if snapshot['output_language']=='en' else zh for k,en,zh in SECTION_LABELS},order=list(SECTION_IDS),styles={})

def context(snapshot):
    value=deepcopy(snapshot.get('journal_display_context') or defaults(snapshot))
    if value.get('version')!=DISPLAY_VERSION or set(value['names'])!=set(SECTION_IDS) or sorted(value['order'])!=sorted(SECTION_IDS) or value['order'][0]!='title':raise ValueError('Invalid journal display mapping')
    if len(set(value['names'].values()))!=len(SECTION_IDS):raise ValueError('Display headings must be one-to-one')
    if set(value['styles'])-set(STYLE_KEYS):raise ValueError('Unsupported journal style')
    for key,number in value['styles'].items():validate_style(key,number)
    return value

def validate_style(key,value):
    low,high=(8,36) if key.endswith('font_size_pt') else (1,3) if key.endswith('line_spacing') else (0,72)
    if type(value) not in (int,float) or not low<=value<=high:raise ValueError('Finite display value outside supported range')

def display_sections(snapshot):
    value=context(snapshot);sections={s['id']:s for s in snapshot['sections']}
    return [dict(sections[k],display_name=value['names'][k]) for k in value['order']]

def plan(snapshot,target,warnings):
    before=context(snapshot);after=deepcopy(before);actions=[];unexecuted=[]
    rules=sorted(target['selected_requirements'],key=lambda r:r['key']=='section_order')
    complete=[s['id'] for s in snapshot.get('sections',[])]==list(SECTION_IDS)
    for rule in rules:
        key=rule['key'];reason=None;old=None;new=rule['value']
        if not complete:reason='需要已发布的完整七部分公共稿件。'
        elif any(w.get('blocks_rules',True) and w.get('source_id') in (None,rule['source_id']) for w in warnings):reason='来源或许可不可用，不能执行。'
        elif rule['status']!='known':reason='未知或不支持要求。'
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
    sections=[dict(section_id=k,before=dict(display_name=before['names'][k],position=before['order'].index(k),styles={} if k=='title' else before['styles']),after=dict(display_name=after['names'][k],position=after['order'].index(k),styles={} if k=='title' else after['styles'])) for k in SECTION_IDS]
    for s in sections:s['changed']=s['before']!=s['after']
    return dict(sections=sections,actions=actions,unexecuted=unexecuted,display_context=after)

def apply(snapshot,actions):
    result=deepcopy(snapshot);value=context(snapshot)
    for a in actions:
        if a['key']=='section_display_names':value['names']=deepcopy(a['after'])
        elif a['key']=='section_order':value['order']=deepcopy(a['after'])
        else:value['styles'][a['key']]=a['after']
    result['journal_display_context']=value
    context(result)
    return result
