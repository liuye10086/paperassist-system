"""Finite human-readable summaries; exact records remain in saved snapshots."""
from .grounded import evidence_summary

def citation_text(bindings, language):
    en=language=='en'
    if not bindings:return 'No citation bound.' if en else '尚未绑定引用。'
    values=[]
    for binding in bindings:
        metadata=binding.get('metadata') or {};authors=[]
        for author in metadata.get('authors',[])[:3]:
            name=author.get('collective') or ' '.join(filter(None,(author.get('family'),author.get('given') or author.get('initials'))))
            if name:authors.append(name)
        status=(binding.get('review') or {}).get('status') or ('not recorded' if en else '未记录')
        fields=[', '.join(authors),metadata.get('title'),metadata.get('year') or metadata.get('date')]
        label='; '.join(str(value) for value in fields if value)
        if not label:label='Saved reference metadata unavailable' if en else '已保存引用缺少可显示的题录信息'
        values.append(label+('; support: ' if en else '；支持状态：')+status)
    return '\n'.join(values)

def change_text(change, side, language):
    value=change[side];en=language=='en'
    if change['kind']=='remove_figure':
        if side=='after':return 'Removed from this manuscript; the original figure remains in its fixed parent version.' if en else '本稿已移出该图；原图和固定父稿继续保留。'
        return ' / '.join(str(v) for v in (value.get('title'),value.get('caption')) if v)
    if change['kind']=='bind_citation':return citation_text(value,language)
    if change['kind']=='reorder_paragraphs':
        order={identity:str(n) for n,identity in enumerate(change['before'],1)}
        if any(identity not in order for identity in value):
            return 'Saved paragraph order requires verification.' if en else '已保存的段落顺序仍需核对。'
        return ('Original paragraph order: ' if en else '按修改前段落编号排序：')+' → '.join(order[identity] for identity in value)
    if isinstance(value,str):return value
    return 'Saved structured change; inspect the fixed source record.' if en else '已保存结构化修改，详情可核对固定来源记录。'

def evidence_text(entry):
    summary=evidence_summary(dict(entry,kind=entry.get('kind','document_version')))
    if len(summary)>850:summary=summary[:850]+'… [excerpt; 完整内容见已保存来源]'
    return summary
