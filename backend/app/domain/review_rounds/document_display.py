"""Finite human-readable summaries; exact records remain in saved snapshots."""
from .grounded import evidence_summary


ITEM_STATUSES = {
    'pending': ('Pending', '待处理'),
    'waiting_confirmation': ('Awaiting confirmation', '待确认'),
    'waiting_material': ('Awaiting additional material', '待补材料'),
    'not_adopted': ('Not adopted', '未采纳'),
    'executing': ('In progress', '处理中'),
    'completed': ('Addressed', '已修改'),
}
SOURCE_ROLES = {
    'editor': ('Editor', '编辑'), 'reviewer': ('Reviewer', '审稿人'),
    'advisor': ('Advisor', '导师'), 'evaluator': ('Evaluator', '评阅人'),
    'defense': ('Defense committee', '答辩委员'),
}
CITATION_STATUSES = {
    'supported': ('Supported', '支持'), 'partial': ('Partially supported', '部分支持'),
    'unsupported': ('Unsupported', '不支持'), 'needs_review': ('Requires review', '待核验'),
}
SYSTEM_WAITING_REASONS_EN = {
    ('waiting_material', '待补充或核验材料、分析、实验、文献；取得实际结果并通过公共检查后才能完成修改。'):
        ('Further evidence is needed before this point can be addressed. '
         'The requested materials, analyses, experiments or references still need to be supplied or verified.'),
    ('waiting_confirmation', '待用户明确处理歧义、冲突或结论变化。'):
        'A decision is needed to resolve the ambiguity, conflict or proposed change to the conclusions.',
    ('pending', '返修计划已保存，尚未实际修改稿件。'):
        'The revision is planned and still awaits changes to the manuscript.',
    ('pending', '本次未选择具体修改。'):
        'A revision has yet to be selected for this point.',
}
EVIDENCE_FIELDS = {
    'numeric_name': ('Measured variable', '测量变量'), 'group_name': ('Grouping', '分组'),
    'unit': ('Unit', '单位'), 'n': ('Sample size', '样本量'), 'mean': ('Mean', '均值'),
    'std': ('Standard deviation', '标准差'), 'median': ('Median', '中位数'),
    'min': ('Minimum', '最小值'), 'max': ('Maximum', '最大值'), 'p_value': ('P value', 'P 值'),
}


def localized(labels, language):
    return labels[0 if language == 'en' else 1]


def citation_text(bindings, language, *, customer_view=False):
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
        if customer_view:
            label = (' / ' if en else '，').join(str(value) for value in fields if value)
            display = localized(CITATION_STATUSES.get(status, ('Status unavailable', '支持状态待核对')), language)
            values.append((label + ' — ' if label else '') + display)
            continue
        label='; '.join(str(value) for value in fields if value)
        if not label:label='Saved reference metadata unavailable' if en else '已保存引用缺少可显示的题录信息'
        values.append(label+('; support: ' if en else '；支持状态：')+status)
    return '\n'.join(values)

def change_text(change, side, language, *, customer_view=False):
    value=change[side];en=language=='en'
    if change['kind']=='remove_figure':
        if side=='after':
            if customer_view:return 'The figure was removed from the revised manuscript.' if en else '该图已从修订稿移除。'
            return 'Removed from this manuscript; the original figure remains in its fixed parent version.' if en else '本稿已移出该图；原图和固定父稿继续保留。'
        return ' / '.join(str(v) for v in (value.get('title'),value.get('caption')) if v)
    if change['kind']=='bind_citation':return citation_text(value,language,customer_view=customer_view)
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


def reply_text(actual, status, reason, language, *, customer_view=False):
    en = language == 'en'
    def changes():
        return '\n'.join(change_text(change, 'after', language, customer_view=customer_view) for change in actual)
    if status == 'completed':
        return ('The manuscript was revised as follows: ' if en else '稿件已作以下实际修改：') + changes()
    if status == 'not_adopted':
        return ('Not adopted. Reason: ' if en else '未采纳。原因：') + reason
    if actual:
        return (('Partial changes were made: ' if en else '已作部分实际修改：') + changes() +
                ('\nNot fully completed. Reason: ' if en else '\n本项尚未全部完成。原因：') + reason)
    return ('Not completed. Reason: ' if en else '未完成，仍待补充。原因：') + reason


def section_label(section_id, language, article_type=None):
    from app.domain.manuscript_writing.article_contract import COMMON, labels

    captions = {key: (en, zh) for key, en, zh in labels(article_type)} if article_type else COMMON
    return localized(captions.get(section_id, ('', '')), language)


def customer_location(location, language):
    en = language == 'en'
    kind, section = location.get('kind'), location.get('section_id')
    title = location.get('section_title')
    caption = title if title and title != section else section_label(section, language)
    labels = {
        'paragraph': ('paragraph', '段落'), 'figure': ('Figure', '图'),
        'table': ('Table', '表'), 'section': ('section', '章节'),
    }
    word = localized(labels.get(kind, ('location', '位置')), language)
    number = location.get(f'{kind}_number')
    if kind == 'paragraph' and number is not None and not en:
        word = f'第 {number} 段'
    elif number is not None:
        word = f'{word} {number}'
    if kind == 'section' and caption:
        return caption
    return (', ' if en else '，').join(value for value in (caption, word) if value)


def customer_evidence_text(entry, language):
    en = language == 'en'
    if entry.get('kind') == 'analysis_run':
        content = entry['content']
        def facts(values, fields):
            return (', ' if en else '，').join(
                f'{localized(EVIDENCE_FIELDS[key], language)} {values[key]}'
                for key in fields if values.get(key) not in (None, ''))
        metrics = ('n', 'mean', 'std', 'median', 'min', 'max', 'p_value')
        parts = [facts(content, ('numeric_name', 'group_name', 'unit'))]
        parts.extend(facts(content[name], metrics) for name in ('overall', 'statistics')
                     if isinstance(content.get(name), dict))
        for group in content.get('groups', [])[:8]:
            if isinstance(group.get('statistics'), dict):
                counts = facts(group['statistics'], ('n', 'mean', 'std', 'median'))
                if counts:
                    label = str(group.get('label') or ('Group' if en else '分组'))
                    parts.append(label + ' — ' + counts)
        if not content.get('unit'):
            parts.append('Unit pending confirmation.' if en else '单位待核对。')
        summary = (' / ' if en else '。').join(value for value in parts if value)
    else:
        summary = evidence_summary(dict(entry, kind=entry.get('kind', 'document_version')))
        if summary == '固定资料未提供可用于本项的明确文本/统计字段；需人工核对原材料。':
            summary = 'Consult the original material.' if en else '请核对原资料。'
    if len(summary) > 850:
        return summary[:850] + ('… (excerpt)' if en else '…（节选）')
    return summary
