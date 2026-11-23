"""Freeze the customer's saved writing requirements and linked materials."""
from collections import defaultdict
import re
from pathlib import PurePath

from app.core.exceptions import StorageError
from app.domain.literature.service import digest
from app.domain.paper_materials import (
    DEFAULT_REVIEW_TOPIC, MATERIAL_KINDS, chapter_heading, paper_material_rows, read_sci_settings, review_section_labels,
    review_topic_heading, sci_finding_label, sci_target_id, thesis_figure_chapters, thesis_target_id,
)
from app.domain.school_templates.service import SchoolTemplateService


def _section(target_id, label, text, **fields):
    return dict(id='paper-' + digest(target_id)[:32], label=label, text=text, **fields)


def auto_figure_section(targets, filename, caption, *, thesis=False):
    """Prefer an unambiguous heading in the supplied description or original name."""
    words = lambda text: ' '.join(re.findall(r'[a-z0-9]+|[\u3400-\u9fff]+', text.casefold()))
    for value in (caption, PurePath(filename).stem):
        text = words(value)
        matches = [section for section in targets.values() if (heading := words(
            chapter_heading(section['label']) if thesis else section['label']))
                   and re.search((r'(?<![a-z0-9])' if heading[0].isascii() else '') + re.escape(heading)
                                 + (r'(?![a-z0-9])' if heading[-1].isascii() else ''), text)]
        if len(matches) == 1:
            return matches[0]
    if thesis:
        for section in targets.values():
            if section.get('purpose') == 'results' or re.search(r'结果|\bresults?\b', section['label'], re.I):
                return section
    return next(iter(targets.values()), None)


def current_plan(service, db, project, school=None):
    if not service.assets.customer or service.assets.assignment is not None:
        return None
    project_id = project['id']
    targets = {}
    figure_chapters = {}
    if project['project_type'] == 'sci':
        settings = read_sci_settings(db, project)
        if not settings:
            return None
        title = settings.get('proposed_title') or project['name']
        kind = settings['article_type']
        keywords = settings['keywords']
        if kind == 'research':
            findings = settings.get('figure_findings', [])
            if settings.get('main_results'):
                findings = [dict(id='legacy-main-result', finding=settings['main_results'])]
            for number, item in enumerate(findings, 1):
                key = sci_target_id('figure', item['id'])
                label = sci_finding_label(number, project['default_output_language'])
                targets[key] = _section(key, label, item['finding'], group_title=label)
        else:
            for item in settings.get('review_sections', []):
                key = sci_target_id('review', item['id'])
                targets[key] = _section(key, item['heading'], item['content'])
            if not targets:
                label = review_topic_heading(project['default_output_language'])
                topic = project['research_topic'] or title
                scope = '\n'.join(dict.fromkeys(filter(None, (topic, settings.get('main_results')))))
                targets[DEFAULT_REVIEW_TOPIC] = _section(DEFAULT_REVIEW_TOPIC, label, scope)
    elif project['project_type'] == 'thesis' and school and school['ready']:
        profile = SchoolTemplateService(service.assets).profile_view(db, project_id, include_requirements=True)
        requirements = profile.get('requirements_json') or {}
        title = requirements.get('title') or project['name']
        kind = 'thesis'
        keywords = requirements.get('keywords', [])
        binding = school['confirmation_id']
        by_chapter = {item['chapter_id']: item for item in requirements.get('chapter_plans', {}).get(binding, [])}
        for chapter in school['chapters']:
            item = by_chapter.get(chapter['id'])
            if item and chapter['id'] not in school['protected_chapter_purposes']:
                key = thesis_target_id(binding, chapter['id'])
                targets[key] = _section(key, chapter['title'].strip(), item['content'],
                                        chapter_id=chapter['id'], purpose=item['purpose'])
        for chapter in thesis_figure_chapters(school):
            key = thesis_target_id(binding, chapter['id'])
            figure_chapters[key] = dict(id='paper-image-' + digest(key)[:32], label=chapter['title'].strip(),
                                        chapter_id=chapter['id'], purpose=by_chapter.get(chapter['id'], {}).get('purpose'))
    else:
        return None

    materials = []
    file_descriptions = {}
    omitted_count = 0
    excluded = set(school['template_source_file_ids']) if kind == 'thesis' else set()
    review = kind == 'narrative_review'
    native_sections = {sci_target_id('section', sid): dict(id=sid)
                       for sid in review_section_labels(project['default_output_language'])} if review else {}
    for note in paper_material_rows(db, service.assets, project_id, include_uploaded_figures=review or kind == 'thesis'):
        if note['file_id'] in excluded:
            continue
        material_kind = MATERIAL_KINDS.get(note['file_type'])
        thesis_figure = kind == 'thesis' and material_kind == 'figure'
        if thesis_figure:
            section = figure_chapters.get(note['target_id']) or auto_figure_section(
                figure_chapters, note['filename'], note['result_text'] or '', thesis=True)
        elif review and material_kind == 'figure':
            section = targets.get(note['target_id']) or native_sections.get(note['target_id'])
            if not section:
                section = auto_figure_section(targets, note['filename'], note['result_text'] or '')
        elif note['target_id'] is None:
            file_descriptions[note['file_id']] = note['result_text']
            continue
        else:
            section = targets.get(note['target_id'])
        if section is None or material_kind is None or (not thesis_figure and section.get('purpose') == 'materials_and_methods'):
            omitted_count += 1
            continue
        file_id = note['file_id']
        selection = dict(kind='original', id=file_id, file_id=file_id,
                         role='image_observation' if material_kind == 'figure' else 'user_results')
        material = dict(section_id=section['id'], filename=note['filename'], kind=material_kind,
                        result=note['result_text'] or '', selection=selection)
        if thesis_figure:
            material['chapter_id'] = section['chapter_id']
            finding = targets.get(note['target_id'])
            if finding and finding['purpose'] == 'results':
                material['finding_section_id'] = finding['id']
        if note['worksheet_names'] is not None:
            material['worksheet_names'] = note['worksheet_names']
        materials.append(material)
    plan = dict(kind=kind, title=title, keywords=keywords, sections=list(targets.values()), materials=materials)
    if review and any(item['kind'] == 'figure' for item in materials):
        plan['review_figure_placement_version'] = 1
    if kind == 'thesis':
        assigned = {item['chapter_id'] for item in materials if 'chapter_id' in item}
        if assigned:
            plan['figure_chapters'] = [dict(id=s['id'], label=s['label'], chapter_id=s['chapter_id'])
                                       for s in figure_chapters.values() if s['chapter_id'] in assigned]
    if project['project_type'] == 'sci':
        plan['target_journal'] = settings.get('target_journal')
    if file_descriptions:
        plan['file_descriptions'] = file_descriptions
    return dict(**plan, token=digest(plan), omitted_count=omitted_count)


def require_current_plan(service, db, project, request, school):
    plan = current_plan(service, db, project, school)
    if plan is None or plan.pop('token') != request.paper_plan_token or request.title != plan['title']:
        raise StorageError('task_source_conflict', '项目需求或图表已更新，请刷新后重新准备稿件。', 409)
    plan.pop('omitted_count')
    planned_files = {item['selection']['file_id'] for item in plan['materials']}
    if any(source.file_id in planned_files for source in request.sources):
        raise StorageError('task_input_invalid', '已关联的图表会随项目需求带入，请移除重复选择。', 422)
    plan_groups = {section['id'] for section in [*plan['sections'], *plan.get('figure_chapters', [])]}
    if {group.id for group in request.results_groups} & plan_groups:
        raise StorageError('task_input_invalid', '项目需求中的内容已分组，请检查补充结果分组。', 422)
    if 'file_descriptions' in plan:
        included = {source.file_id for source in request.sources}
        plan['file_descriptions'] = {file: text for file, text in plan['file_descriptions'].items() if file in included}
    if plan['kind'] == 'narrative_review' and plan['sections'][0]['id'] == 'paper-' + digest(DEFAULT_REVIEW_TOPIC)[:32]:
        plan['sections'][0]['label'] = review_topic_heading(request.output_language)
    require_review_heading_language(plan, request.output_language)
    return plan


def require_review_heading_language(plan, language):
    if not plan or plan['kind'] != 'narrative_review':
        return
    for position, theme in enumerate(plan['sections'], 1):
        heading = theme['label']
        han = re.search(r'[\u3400-\u9fff]', heading)
        latin = re.search(r'[A-Za-z]{2,}', heading)
        if (language == 'zh-CN' and latin and not han) or (language == 'en' and han and not latin):
            raise StorageError('manuscript_review_heading_language', '综述小标题与稿件语种不一致。', 422,
                               params={'position': position})


def result_sections(plan):
    return [section for section in plan['sections'] if section.get('purpose') != 'materials_and_methods']


def finding_paragraph(section, source_ids=()):
    return dict(id='paper-finding:' + section['id'], text=section['text'],
                origin='user_provided', source_ids=list(source_ids), citations=[])


def freeze_groups(service, project, plan, source_lookup, make_figure, language):
    from .illustrations import bind_finding_figures, reference_text
    from .paper_tables import freeze_tables

    by_section = defaultdict(list)
    finding_sources = defaultdict(list)
    for material in plan['materials']:
        by_section[material['section_id']].append(material)
        if 'finding_section_id' in material:
            finding_sources[material['finding_section_id']].append(material['selection']['id'])
    groups = []
    table_count = 0
    sections = result_sections(plan)
    sections.extend(plan.get('figure_chapters', []))
    review_figures = plan.get('review_figure_placement_version') == 1
    if review_figures:
        native = {sid: dict(id=sid, label=label) for sid, label in review_section_labels(language).items()
                  if sid in by_section}
        sections = [*([native['introduction']] if 'introduction' in native else []), *sections,
                    *(row for sid, row in native.items() if sid != 'introduction')]
    for position, section in enumerate(sections, 1):
        materials = by_section[section['id']]
        sources = [item['selection']['id'] for item in materials] + finding_sources[section['id']]
        paragraphs = [finding_paragraph(section, sources)] if 'text' in section else []
        tables = []
        figures = []
        for material in materials:
            identity = material['selection']['id']
            if material['kind'] == 'figure':
                thesis_figure = 'chapter_id' in material
                figure = make_figure(identity, paper_caption=material['result'], optional_caption=thesis_figure)
                if thesis_figure:
                    figure['title'] = 'Thesis illustration' if language == 'en' else '论文配图'
                    if figure['caption_status'] == 'missing':
                        figure['caption'] = 'Image supplied by the author.' if language == 'en' else '作者提供的配图。'
                elif review_figures:
                    figure['title'] = 'Review illustration' if language == 'en' else '综述配图'
                    if figure['caption_status'] == 'missing':
                        figure['caption'] = (f"Illustration supplied for “{section['label']}”." if language == 'en'
                                             else f"用于“{section['label']}”的配图。")
                figures.append(figure)
                continue

            native_tables = freeze_tables(service, project, source_lookup[identity], material.get('worksheet_names'))
            material['tables'] = native_tables
            references = []
            for index, table in enumerate(native_tables):
                table_count += 1
                table_id = f'table:{identity}:{index + 1}'
                reference = dict(kind='table', target_id=table_id, number=table_count, panel_label=None)
                caption = 'Observations' if language == 'en' else '观察记录'
                tables.append(dict(table, id=table_id, number=table_count, title=f'{reference_text(reference, language)}. {caption}',
                                   source_ids=[identity], paper_table_index=index))
                references.append(reference)
            labels = ('; ' if language == 'en' else '；').join(reference_text(item, language) for item in references)
            paragraphs.append(dict(id='paper-material:' + identity,
                                   text=f"{material['result']} ({labels})", origin='user_provided',
                                   source_ids=[identity], citations=[], cross_references=references))
        if plan['kind'] == 'research':
            bind_finding_figures(paragraphs[0], figures, position, language)
        title = sci_finding_label(position, language) if plan['kind'] == 'research' else section['label']
        group = dict(id=section['id'], title=title, paragraphs=paragraphs, tables=tables, figures=figures)
        if 'chapter_id' in section and 'text' not in section:
            group['illustration_chapter_id'] = section['chapter_id']
        groups.append(group)
    return groups, table_count
