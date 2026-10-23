"""Adapt confirmed school chapters to the common frozen manuscript, never its facts."""
from copy import deepcopy

PURPOSES = ('abstract', 'introduction', 'materials_and_methods', 'results', 'discussion',
            'conclusion', 'references', 'acknowledgements', 'manual', 'other')
CHAPTER_FIELDS = ('id', 'title', 'level', 'purpose', 'output_language', 'result_group_ids')
RULES_VERSION = 'school-content-v1'


def purpose(section):
    return section.get('purpose', section['id'])


def pending(chapter):
    text = ('Missing chapter content; researcher material and review required.'
            if chapter['output_language'] == 'en' else '本章正文待补充；须提供研究资料并由研究人员核对。')
    if chapter['purpose'] == 'manual':
        text = ('Manual content pending; identity, declaration, signature or contents fields are not generated.'
                if chapter['output_language'] == 'en' else '人工内容待补充；身份、声明、签名和目录域不由系统编造。')
    return dict(id='school:' + chapter['id'] + ':pending', text=text, origin='user_provided',
                source_ids=[], citations=[], numeric_bindings=[])


def validate_chapters(context, groups):
    chapters = context['chapters']
    if not chapters or len(chapters) > 300 or len({c['id'] for c in chapters}) != len(chapters):
        raise ValueError('School chapters must have unique fixed identities')
    confirmed = context['confirmation']['chapters']
    if [{k:c[k] for k in ('id','title','level')} for c in chapters] != [{k:c[k] for k in ('id','title','level')} for c in confirmed]:
        raise ValueError('School chapter order, title and level must match confirmation')
    assigned = set()
    for chapter in chapters:
        if (set(chapter) != set(CHAPTER_FIELDS) or chapter['purpose'] not in PURPOSES
                or chapter['output_language'] not in ('zh-CN', 'en')
                or type(chapter['level']) is not int or not 1 <= chapter['level'] <= 9):
            raise ValueError('Invalid school chapter mapping')
        ids = chapter['result_group_ids']
        if (not isinstance(ids, list) or len(ids) != len(set(ids)) or not set(ids) <= groups
                or assigned.intersection(ids) or ids and chapter['purpose'] != 'results'):
            raise ValueError('Result groups must belong to exactly one results chapter')
        assigned.update(ids)
    if sum(c['purpose'] == 'references' for c in chapters) > 1:
        raise ValueError('A common reference list requires one explicit references chapter')
    return chapters


def seed_school_snapshot(snapshot, context):
    from app.domain.manuscript_writing.context import literature_paragraphs
    result = deepcopy(snapshot)
    chapters = validate_chapters(context, {g['id'] for g in snapshot['results_groups']})
    result['thesis_context'] = deepcopy(context)
    sections = []
    used_methods = False
    used_literature = False
    literature = literature_paragraphs(snapshot)
    for chapter in chapters:
        section = deepcopy(chapter)
        paragraphs = []
        role = chapter['purpose']
        if role == 'materials_and_methods' and not used_methods:
            # Literature is a reviewed finding, never an actual study method.
            paragraphs = [deepcopy(p) for p in snapshot['methods'] if p.get('origin') != 'literature']
            used_methods = True
        if role in ('introduction', 'discussion', 'other') and not used_literature and literature:
            paragraphs.extend(deepcopy(literature))
            used_literature = True
        if role == 'results':
            for group in snapshot['results_groups']:
                if group['id'] in chapter['result_group_ids']:
                    paragraphs.extend(deepcopy(group.get('paragraphs', [])))
        if role == 'references':
            paragraphs = [dict(id='reference:'+str(index+1), text=reference.get('text') or reference.get('formatted') or reference.get('formatted_reference'),
                               origin='literature', source_ids=[], citations=[], numeric_bindings=[])
                          for index, reference in enumerate(snapshot['references'])]
            paragraphs = [p for p in paragraphs if p['text']]
        section['paragraphs'] = paragraphs if paragraphs or role == 'references' else [pending(chapter)]
        sections.append(section)
    result['sections'] = sections
    result['notice'] = ('School chapter fact draft; missing research and manual content remain pending. No model writing or school export has been performed.'
                        if snapshot['output_language'] == 'en' else '按学校章节组织的事实稿；缺失研究事实及人工内容仍待补充，尚未进行模型写作或学校成品导出。')
    result['issues'] = [deepcopy(i) for i in snapshot['issues'] if i.get('id') != 'scope']
    result['issues'].append(dict(id='scope', kind='limitation', field='scope', message=result['notice'], values=[]))
    result['school_content_report'] = school_content_report(result)
    return result


def school_issues(snapshot):
    """Structural and missing-content checks supplement common numeric/source checks."""
    from app.domain.manuscript_review.checks import issue
    context = snapshot.get('thesis_context')
    if not context:
        return []
    en = snapshot['output_language'] == 'en'
    issues = []
    actual = snapshot.get('sections', [])
    expected = context['chapters']
    if [{k:s.get(k) for k in CHAPTER_FIELDS} for s in actual] != [{k:s[k] for k in CHAPTER_FIELDS} for s in expected]:
        issues.append(issue('structure', 'school:chapters', 'Displayed school chapters differ from their frozen confirmation and mapping.' if en else '展示章节与冻结学校确认版及用途映射不一致。',
                            severity='error', actual=[s.get('id') for s in actual], expected=[s['id'] for s in expected]))
    assigned = set()
    for chapter in actual:
        assigned.update(chapter.get('result_group_ids', []))
        paragraphs = chapter.get('paragraphs', [])
        if (not paragraphs or any(p.get('id', '').startswith('school:') and p.get('id', '').endswith(':pending') for p in paragraphs)) and purpose(chapter) != 'references':
            issues.append(issue('material', 'section:'+chapter['id'], 'School chapter content is missing or remains a supplied-material placeholder.' if en else '学校章节正文缺失或仍为待补充资料占位。', expected=chapter['title']))
    for group in snapshot.get('results_groups', []):
        if group['id'] not in assigned:
            issues.append(issue('material', 'school:group:'+group['id'], 'Saved result group is not assigned to a school results chapter.' if en else '冻结结果组尚未分配到学校结果章节。', expected=group['id']))
    if snapshot.get('references') and not any(purpose(s) == 'references' for s in actual):
        issues.append(issue('structure', 'school:references', 'A references chapter is required to display selected frozen references.' if en else '已选择冻结参考文献，须映射参考文献章节。', severity='error'))
    issues.append(issue('uncertainty', 'school:content', 'School structure and exact local bindings do not verify prose meaning, bilingual quality or school pagination.' if en else '学校结构与本地精确绑定检查不等于正文语义、双语质量或学校分页验收。'))
    return issues


def school_content_report(snapshot):
    from app.domain.manuscript_review.checks import check_snapshot
    # A current material-review report already checked this exact candidate with
    # its explicit precision and strict correction locations. Reuse that proof.
    review = snapshot.get('review') or {}
    if snapshot.get('review_provenance') and review.get('report'):
        issues = deepcopy(review['report']['issues'])
    else:
        # Writing retains exact reviewed paragraphs and their fact bindings; the
        # common review workflow inherits these same metadata from its history.
        previous = review or (snapshot.get('review_history') or [{}])[-1].get('review', {})
        issues = check_snapshot(snapshot, metadata=previous.get('metadata', []))
    return dict(rules_version=RULES_VERSION, issues=issues,
                can_publish=not any(item['severity'] == 'error' for item in issues), scientifically_verified=False)
