"""Versioned draft outlines derived from publisher author guidelines."""
from copy import deepcopy
import re

MAX_SCI_SECTIONS = 300
CUSTOM_SCI_SECTION = re.compile(r'sci-section-[a-f0-9]{32}')

_HEADINGS = {
    'title': ('Title', '标题'),
    'abstract': ('Abstract', '摘要'),
    'introduction': ('Introduction', '引言'),
    'materials_and_methods': ('Materials and Methods', '材料与方法'),
    'results': ('Results', '结果'),
    'discussion': ('Discussion', '讨论'),
    'literature_scope': ('Literature sources and inclusion scope', '文献来源与纳入说明'),
    'themes': ('Thematic sections', '主题小节'),
    'conclusion': ('Conclusion', '结论'),
    'references': ('References', '参考文献'),
}
_METHODS_FIRST = ('title', 'abstract', 'introduction', 'materials_and_methods', 'results', 'discussion', 'references')
_METHODS_LAST = ('title', 'abstract', 'introduction', 'results', 'discussion', 'materials_and_methods', 'references')
_REVIEW = ('title', 'abstract', 'introduction', 'literature_scope', 'themes', 'discussion', 'conclusion', 'references')
_FRONTIERS = 'https://www.frontiersin.org/journals/genetics/for-authors/article-types'


def _template(identity, name, article_type, order, source_url=None, **headings):
    sections = []
    for sid in order:
        english, chinese = headings.get(sid, _HEADINGS[sid])
        sections.append(dict(id=sid, en=english, zh=chinese))
    return dict(id=identity, name=name, article_type=article_type, source_url=source_url, sections=sections)


_CATALOG = (
    _template('frontiers-genetics-research-v1', 'Frontiers in Genetics · Original Research', 'research',
              _METHODS_FIRST, _FRONTIERS + '#original-research'),
    _template('scientific-reports-article-v1', 'Scientific Reports · Article', 'research', _METHODS_LAST,
              'https://www.nature.com/srep/author-instructions/submission-guidelines', materials_and_methods=('Methods', '方法')),
    _template('plos-one-research-v1', 'PLOS One · Research Article', 'research', _METHODS_FIRST,
              'https://journals.plos.org/plosone/s/submission-guidelines#loc-manuscript-organization'),
    _template('standard-sci-research-v1', '通用研究型论文', 'research', _METHODS_LAST),
    _template('frontiers-genetics-review-v1', 'Frontiers in Genetics · Review', 'narrative_review', _REVIEW,
              _FRONTIERS + '#review'),
    _template('standard-sci-review-v1', '通用综述', 'narrative_review', _REVIEW,
              introduction=('Scope and background', '范围与背景'), themes=('Thematic synthesis', '主题综合'),
              discussion=('Synthesis and limitations', '综合讨论与局限')),
)


def templates_for(article_type):
    return [deepcopy(template) for template in _CATALOG if template['article_type'] == article_type]


def selected_template(article_type, identity):
    for template in _CATALOG:
        if template['article_type'] == article_type and template['id'] == identity:
            return deepcopy(template)
    return None


def configured_template(article_type, identity, sections=None):
    template = selected_template(article_type, identity)
    if template is not None and sections is not None:
        template['sections'] = deepcopy(sections)
    return template
