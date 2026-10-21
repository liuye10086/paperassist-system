"""Identity-based figure/table references for new fact drafts only."""
import re


def panel_labels(figure):
    labels = [p['label'] for p in figure.get('panels', [])]
    canonical = [value.strip().upper() for value in labels]
    valid = all(re.fullmatch('[A-Z]', value) for value in labels) and len(canonical) == len(set(canonical))
    return labels if valid else None


def reference_text(reference, language):
    en = language == 'en'
    prefix = ('Figure ' if en else '图 ') if reference['kind'] == 'figure' else ('Table ' if en else '表 ')
    return prefix + str(reference['number']) + (reference.get('panel_label') or '')


def attach_references(groups, language, issue):
    """Derived links describe source placement; no image-derived scientific claim."""
    en = language == 'en'
    for group in groups:
        for paragraph, table in zip(group['paragraphs'], group['tables']):
            paragraph['cross_references'] = [dict(kind='table',target_id=table['id'],number=table['number'],panel_label=None)]
        references = []
        for figure in group['figures']:
            references.append(dict(kind='figure',target_id=figure['id'],number=figure['number'],panel_label=None))
            labels = panel_labels(figure)
            if labels is None:
                issue('panels:'+figure['id'],'conflict',figure['id'],
                    ('Panel labels must be unique letters A–Z; ambiguous panel references were not generated. '
                     if en else '分面标签须为不重复的大写A–Z；歧义分面未生成正文子图引用。') + reference_text(references[-1],language),
                    [p['label'] for p in figure.get('panels',[])])
            else:
                references.extend(dict(kind='figure',target_id=figure['id'],number=figure['number'],panel_label=value) for value in labels)
        if references:
            group['paragraphs'].append(dict(id='illustrations:'+group['id'],origin='image_observation',
                source_ids=list(dict.fromkeys(s for figure in group['figures'] for s in figure['source_ids'])),citations=[],
                cross_references=references,
                text=('Saved image observations: ' if en else '已保存图片观察：')
                + ('; ' if en else '；').join(reference_text(r,language) for r in references)
                + ('. These references identify the saved images and supplied panels; no statistical values were inferred from pixels.'
                   if en else '。这些引用对应已保存图片及用户提供的分面说明；未从像素推断统计值。')))
    for item in check_references(groups,language):
        issue(item['id'],item['kind'],item['field'],item['message'],item['values'])


def check_bindings(groups, language):
    targets = {(kind,item['id']):item for group in groups for kind,key in (('figure','figures'),('table','tables')) for item in group[key]}
    issues = []
    for group in groups:
        for paragraph in group['paragraphs']:
            for index, reference in enumerate(paragraph.get('cross_references', [])):
                target = targets.get((reference.get('kind'),reference.get('target_id')))
                panel = reference.get('panel_label')
                valid = (target is not None and reference.get('number') == target.get('number')
                         and (panel is None or reference.get('kind') == 'figure' and panel in (panel_labels(target) or [])))
                expected = reference_text(reference,language) if valid else ''
                if valid and not re.search(re.escape(expected)+r'(?![A-Za-z0-9])',paragraph.get('text','')):
                    valid=False
                if not valid:
                    issues.append(dict(id=f'reference:{paragraph["id"]}:{index}',kind='conflict',field=paragraph['id'],values=[],
                        message='A body reference does not match its saved figure, table number or panel; verification required.'
                        if language=='en' else '正文引用与其冻结图表、编号或分面不一致，待核实。'))
    return issues


BODY_REFERENCE = re.compile(r'(?<![A-Za-z])(?P<kind>Figure|Fig\.?|Table|图|表)\s*(?P<number>[0-9]+)(?:\s*\(?(?P<panel>[A-Za-z])\)?)?(?![A-Za-z0-9])',re.I)


def check_references(groups, language, extra_paragraphs=()):
    """Report explicit textual references without rewriting user prose or guessing a target."""
    issues=check_bindings(groups,language)
    targets={(kind,item['number']):item for group in groups for kind,key in (('figure','figures'),('table','tables')) for item in group[key]}
    texts=[(p['id'],p['text']) for group in groups for p in group['paragraphs'] if p['origin']!='literature']
    texts.extend((p['id'],p['text']) for p in extra_paragraphs if p['origin']=='user_provided')
    for group in groups:
        for figure in group['figures']:
            if figure.get('caption_origin')=='user_provided': texts.append(('caption:'+figure['id'],figure['caption']))
            texts.extend((f'panel:{figure["id"]}:{i}',p['description']) for i,p in enumerate(figure.get('panels',[])))
    for field,text in texts:
        for index, match in enumerate(BODY_REFERENCE.finditer(text)):
            kind='table' if match['kind'].lower() in ('table','表') else 'figure'
            number=int(match['number']);panel=match['panel'].upper() if match['panel'] else None
            target=targets.get((kind,number))
            if target is not None and (panel is None or kind=='figure' and panel in (panel_labels(target) or [])):
                continue
            issues.append(dict(id=f'body-reference:{field}:{index}',kind='conflict',field=field,values=[match.group()],
                message=(f'Unmatched body or caption reference: {match.group()}. Verify the number and supplied panel; original text retained.'
                    if language=='en' else f'正文或图注引用无法对应：{match.group()}。请核对编号和已提供分面；原文保留。')))
    return issues


def rendered_groups(snapshot, paragraphs=None):
    """Check displayed prose against frozen targets without modifying factual groups."""
    if paragraphs is None:
        paragraphs=[p for s in snapshot.get('sections',[]) for p in s['paragraphs']]
    groups=[{**g,'paragraphs':[],
             'tables':[t for t in g.get('tables',[]) if 'number' in t],
             'figures':[f for f in g.get('figures',[]) if 'number' in f]}
            for g in snapshot.get('results_groups',[])]
    return [*groups,dict(id='rendered-sections',paragraphs=paragraphs,tables=[],figures=[])]
