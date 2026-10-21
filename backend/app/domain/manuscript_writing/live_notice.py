"""Presentation metadata for new compositions, independent of study-data provenance."""
COMPOSITION_VERSION = 2
SECTION_NAMES = {
    'title': ('Title', '标题'), 'abstract': ('Abstract', '摘要'),
    'introduction': ('Introduction', '引言'), 'results': ('Results', '结果'),
    'discussion': ('Discussion', '讨论'), 'materials_and_methods': ('Materials and methods', '材料与方法'),
}


def update_notice(candidate, request, *, reviewed=False):
    en = candidate['output_language'] == 'en'
    provenance = candidate['writing_provenance']['provider_provenance']
    if provenance not in ('synthetic_fixture', 'openai_live'):
        raise ValueError('Unknown writing provider provenance')
    if request['mode'] == 'full_draft':
        scope = ('Full manuscript candidate: title, abstract, introduction, results, discussion, materials and methods; references managed by the server.' if en else
                 '完整稿候选：标题、摘要、引言、结果、讨论、材料与方法；参考文献由服务器管理。')
    else:
        section = SECTION_NAMES[request['target_section']][0 if en else 1]
        scope = (f'Single-section rewrite candidate: {section}; other sections preserved.' if en else
                 f'单章重写候选：{section}；其他章节保留。')
    if provenance == 'synthetic_fixture':
        provider = 'Writing source: synthetic provider fixture; no real model call.' if en else '写作来源：合成模型调用替身；未发生真实模型调用。'
    else:
        provider = 'Writing source: OpenAI live response.' if en else '写作来源：OpenAI真实调用回执。'
    science = (('Explicit human scientific review recorded for the changed text; study validity is not certified.' if reviewed else 'Scientific review pending.') if en else
               ('已记录对新文本的人工科学审核；这不构成研究有效性认证。' if reviewed else '科学审核待完成。'))
    origin = 'Study-data origin remains defined by the saved source records.' if en else '研究数据来源仍以保存的事实记录为准。'
    candidate['notice'] = (' ' if en else '').join((scope, provider, science, origin))
    scope_issue = dict(id='scope', kind='limitation', field='scope', message=candidate['notice'], values=[])
    issues = candidate.get('issues', [])
    candidate['issues'] = [scope_issue if item.get('id') == 'scope' else item for item in issues]
    if not any(item.get('id') == 'scope' for item in issues):
        candidate['issues'].append(scope_issue)
