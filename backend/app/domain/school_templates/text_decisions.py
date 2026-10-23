"""Only the two explicit written rules supported by the school renderer."""
from app.domain.literature.service import digest


def evidence(analysis):
    result={}
    for identity,label in [('latin_font','英文及数字字体'),('heading1_line_spacing','一级标题行距')]:
        notes=(analysis or {}).get('notes',[])
        if identity=='latin_font':note=next((n for n in notes if '英文一律' in n['text'] and 'Times New Roman' in n['text']),None)
        else:note=next((n for n in notes if '一级标题' in n['text'] and '1.5倍' in n['text']),None)
        rules=[r for r in (analysis or {}).get('rules',[]) if (r['id'].endswith('font_latin') if identity=='latin_font' else r['id'] in ('heading1.line_spacing','heading1.line_rule'))]
        attributes={r['id']:r['value'] for r in rules}
        value='Times New Roman' if identity=='latin_font' else '1.5'
        result[identity]=dict(id=identity,label=label,source_text=note['text'] if note else None,text_value=value if note else None,attribute_value=attributes,
            source_sha256=digest(dict(note=note,attributes=attributes,attribute_sources={r['id']:r['source'] for r in rules})),choices=['text','attributes'] if note else ['attributes'])
    return result


def options(analysis,previous_analysis=None,previous_confirmation=None,legacy=False):
    current=evidence(analysis);previous=evidence(previous_analysis)
    selected={x['id']:x['choice'] for x in (previous_confirmation or {}).get('text_decisions',[])}
    result=[]
    for identity,item in current.items():
        old=previous[identity]
        if not item['source_text'] and not old['source_text']:continue
        same=previous_analysis is not None and item['source_sha256']==old['source_sha256']
        choice=selected.get(identity) or ('text' if legacy and old['source_text'] else None)
        result.append(item|dict(suggested_choice=choice if same else None,changed=previous_analysis is not None and not same))
    return result
