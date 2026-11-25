"""Customer thesis intake using the existing school profile and binding."""
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from app.core.exceptions import StorageError
from app.domain.manuscripts.school import SchoolWritablePurpose
from app.domain.research_intake.paper_fields import ContentText, PaperKeywords, ShortText
from .contracts import PROFILE_FIELDS, StrictModel
from .front_matter import content_purposes
from .service import SchoolTemplateService


ThesisLanguage = Literal['zh-CN', 'en']


class ThesisBasics(StrictModel):
    education_level: Literal['本科', '硕士', '博士']
    school: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    title: ShortText
    keywords: PaperKeywords


class ThesisSectionNeed(StrictModel):
    chapter_id: str = Field(min_length=1, max_length=300)
    purpose: SchoolWritablePurpose
    content: ContentText


class ThesisChapterPlan(StrictModel):
    confirmation_id: str = Field(min_length=1, max_length=64)
    sections: list[ThesisSectionNeed] = Field(max_length=300)

    @model_validator(mode='after')
    def distinct_chapters(self):
        if len({item.chapter_id for item in self.sections}) != len(self.sections):
            raise ValueError('Choose each chapter only once.')
        return self


class ThesisRequirementsWrite(StrictModel):
    expected_revision: int = Field(ge=0, lt=2_147_483_647)
    expected_language: ThesisLanguage
    language: ThesisLanguage
    basics: ThesisBasics
    chapter_plan: ThesisChapterPlan | None = None


def initialize_thesis_requirements(db, store, project, basics):
    schools = SchoolTemplateService(store)
    values = dict.fromkeys(PROFILE_FIELDS, '') | {'school': basics['school'], 'education_level': basics['education_level']}
    requirements = {'title': basics['title'], 'keywords': basics['keywords'], 'chapter_plans': {}}
    schools.write_profile(db, project, {'revision': 0}, values, None, requirements=requirements)


def bound_template(schools, db, project, profile):
    if not profile['bound_confirmation_id']:
        return None, None
    saved = db.execute('''SELECT template_version_id FROM school_template_confirmations
        WHERE id=%s AND project_id=%s AND user_id=%s''', (profile['bound_confirmation_id'], project, schools.store.user_id)).fetchone()
    if not saved:
        return None, None
    row = schools.row(db, project, saved['template_version_id'])
    confirmation = schools.confirmation(db, row)
    template = {'name': row['name'], 'confirmation_id': confirmation['id'], 'chapters': confirmation['chapters'],
                'protected_chapter_purposes': content_purposes(confirmation.get('front_matter'))}
    return template, row


def requirements_view(profile, language, stored, template):
    sections = stored.get('chapter_plans', {}).get(template['confirmation_id'], []) if template else []
    return dict(revision=profile['revision'], school=profile['school'], education_level=profile['education_level'],
                language=language, title=stored.get('title', ''), keywords=stored.get('keywords', []),
                template=template, sections=sections)


def thesis_requirements(store, project, changes: ThesisRequirementsWrite | None = None):
    schools = SchoolTemplateService(store)
    with store.connection(write=changes is not None) as db:
        if schools.project(db, project, lock=changes is not None)['project_type'] != 'thesis':
            raise StorageError('thesis_requirements_unavailable', '此需求表仅适用于毕业论文项目。', 403)
        language = db.execute('SELECT default_output_language FROM projects WHERE id=%s AND owner_id=%s',
                              (project, store.owner_id)).fetchone()['default_output_language']
        profile = schools.profile_view(db, project, include_requirements=True)
        stored = profile.pop('requirements_json', None) or {}
        template, row = bound_template(schools, db, project, profile)
        if template is not None:
            sources, _ = schools.validate(db, row)
            original = next(source for source in sources if source['role'] == 'template')
            template['source_file'] = dict(file_id=original['file_id'], filename=original['filename'])
        if changes is None:
            return requirements_view(profile, language, stored, template)

        basics = changes.basics
        plans = dict(stored.get('chapter_plans', {}))
        if changes.chapter_plan is not None:
            if not template or changes.chapter_plan.confirmation_id != template['confirmation_id']:
                raise StorageError('thesis_template_changed', '学校模板绑定已变化，请核对当前模板和章节。', 409)
            sections = {item.chapter_id: item.model_dump(mode='json') for item in changes.chapter_plan.sections}
            chapter_ids = [chapter['id'] for chapter in template['chapters']]
            if sections.keys() - set(chapter_ids):
                raise StorageError('thesis_chapter_unavailable', '请选择当前学校模板中的章节。', 422)
            protected = template['protected_chapter_purposes']
            previous = {item['chapter_id']: item for item in plans.get(template['confirmation_id'], [])}
            for position, chapter in enumerate(template['chapters'], 1):
                key = chapter['id']
                if key in protected and key in sections and sections[key] != previous.get(key):
                    raise StorageError('thesis_chapter_protected', '学校模板已固定该章节用途。', 422,
                                       params={'position': position})
            plans[template['confirmation_id']] = [sections[key] for key in chapter_ids if key in sections]
        values = profile | {'school': basics.school, 'education_level': basics.education_level}
        requirements = stored | {'title': basics.title, 'keywords': basics.keywords, 'chapter_plans': plans}
        if (profile == values and requirements == stored and changes.language == language
                and profile['revision'] in (changes.expected_revision, changes.expected_revision + 1)):
            return requirements_view(profile, language, stored, template)
        if changes.expected_revision != profile['revision'] or changes.expected_language != language:
            raise StorageError('thesis_requirements_changed', '毕业论文需求或学校资料已更新，请核对后继续。', 409)
        if changes.chapter_plan is not None:
            _, task = schools.require_current(db, row)
            if task['status'] != 'succeeded':
                raise StorageError('thesis_template_required', '请先确认并绑定可用的学校模板。', 409)

        # A customer can save thesis details while an older binding is inaccessible.
        binding = db.execute('SELECT bound_confirmation_id FROM thesis_profiles WHERE project_id=%s AND user_id=%s',
                             (project, store.owner_id)).fetchone()
        schools.write_profile(db, project, profile, values, binding['bound_confirmation_id'] if binding else None,
                              requirements=requirements)
        if changes.language != language:
            store.update_project_language(project, changes.language, connection=db)
        return requirements_view(values | {'revision': profile['revision'] + 1}, changes.language, requirements, template)
