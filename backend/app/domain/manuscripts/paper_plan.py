"""Freeze the customer's saved writing requirements and linked materials."""
from collections import defaultdict
import re

from app.core.exceptions import StorageError
from app.domain.literature.service import digest
from app.domain.paper_materials import (
    MATERIAL_KINDS, paper_material_rows, read_sci_settings, sci_finding_label, sci_target_id, thesis_target_id,
)
from app.domain.school_templates.service import SchoolTemplateService


def _section(target_id, label, text, **fields):
    return dict(id='paper-' + digest(target_id)[:32], label=label, text=text, **fields)


def current_plan(service, db, project, school=None):
    if not service.assets.customer or service.assets.assignment is not None:
        return None
    project_id = project['id']
    targets = {}
    if project['project_type'] == 'sci':
        settings = read_sci_settings(db, project)
        title = settings.get('proposed_title')
        if not title:
            return None
        kind = settings['article_type']
        keywords = settings['keywords']
        if kind == 'research':
            for number, item in enumerate(settings['figure_findings'], 1):
                key = sci_target_id('figure', item['id'])
                label = sci_finding_label(number, project['default_output_language'])
                targets[key] = _section(key, label, item['finding'], group_title=label)
        else:
            for item in settings['review_sections']:
                key = sci_target_id('review', item['id'])
                targets[key] = _section(key, item['heading'], item['content'])
    elif project['project_type'] == 'thesis' and school and school['ready']:
        profile = SchoolTemplateService(service.assets).profile_view(db, project_id, include_requirements=True)
        requirements = profile.get('requirements_json') or {}
        title = requirements.get('title')
        if not title:
            return None
        kind = 'thesis'
        keywords = requirements['keywords']
        binding = school['confirmation_id']
        by_chapter = {item['chapter_id']: item for item in requirements.get('chapter_plans', {}).get(binding, [])}
        for chapter in school['chapters']:
            item = by_chapter.get(chapter['id'])
            if item and chapter['id'] not in school['protected_chapter_purposes']:
                key = thesis_target_id(binding, chapter['id'])
                targets[key] = _section(key, chapter['title'].strip(), item['content'],
                                        chapter_id=chapter['id'], purpose=item['purpose'])
    else:
        return None

    materials = []
    omitted_count = 0
    excluded = set(school['template_source_file_ids']) if kind == 'thesis' else set()
    for note in paper_material_rows(db, service.assets, project_id):
        section = targets.get(note['target_id'])
        material_kind = MATERIAL_KINDS.get(note['file_type'])
        if (section is None or section.get('purpose') == 'materials_and_methods'
                or material_kind is None or note['file_id'] in excluded):
            omitted_count += 1
            continue
        file_id = note['file_id']
        selection = dict(kind='original', id=file_id, file_id=file_id,
                         role='image_observation' if material_kind == 'figure' else 'user_results')
        material = dict(section_id=section['id'], filename=note['filename'], kind=material_kind,
                        result=note['result_text'], selection=selection)
        if note['worksheet_names'] is not None:
            material['worksheet_names'] = note['worksheet_names']
        materials.append(material)
    plan = dict(kind=kind, title=title, keywords=keywords, sections=list(targets.values()), materials=materials)
    if project['project_type'] == 'sci':
        plan['target_journal'] = settings['target_journal']
    # The token covers the input the customer saw. Unlinked files do not change it.
    return dict(**plan, token=digest(plan), omitted_count=omitted_count)


def require_current_plan(service, db, project, request, school):
    plan = current_plan(service, db, project, school)
    if plan is None or plan.pop('token') != request.paper_plan_token or request.title != plan['title']:
        raise StorageError('task_source_conflict', '项目需求或图表已更新，请刷新后重新准备稿件。', 409)
    plan.pop('omitted_count')
    planned_files = {item['selection']['file_id'] for item in plan['materials']}
    if any(source.file_id in planned_files for source in request.sources):
        raise StorageError('task_input_invalid', '已关联的图表会随项目需求带入，请移除重复选择。', 422)
    if {group.id for group in request.results_groups} & {section['id'] for section in plan['sections']}:
        raise StorageError('task_input_invalid', '项目需求中的内容已分组，请检查补充结果分组。', 422)
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
    for material in plan['materials']:
        by_section[material['section_id']].append(material)
    groups = []
    table_count = 0
    for position, section in enumerate(result_sections(plan), 1):
        materials = by_section[section['id']]
        paragraphs = [finding_paragraph(section, (item['selection']['id'] for item in materials))]
        tables = []
        figures = []
        for material in materials:
            identity = material['selection']['id']
            if material['kind'] == 'figure':
                figures.append(make_figure(identity, paper_caption=material['result']))
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
        groups.append(dict(id=section['id'], title=title,
                           paragraphs=paragraphs, tables=tables, figures=figures))
    return groups, table_count
