"""Bounded manual rules referencing immutable analysis evidence, never example values."""
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.exceptions import StorageError


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)


class ManualField(Strict):
    id:str=Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$')
    label:str=Field(min_length=1,max_length=300)
    kind:Literal['text','identity','signature','date']
    required:bool
    source_id:str=Field(min_length=1,max_length=300)
    style_source_id:str|None=Field(default=None,min_length=1,max_length=300)
    section_id:str=Field(min_length=1,max_length=300)
    chapter_id:str|None=Field(default=None,min_length=1,max_length=300)


class ContentRequirement(Strict):
    id:str=Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$')
    kind:Literal['declaration','acknowledgements']
    required:bool
    chapter_id:str=Field(min_length=1,max_length=300)
    source_id:str=Field(min_length=1,max_length=300)


class FrontMatter(Strict):
    schema_version:Literal[1]
    cover_section_id:str=Field(min_length=1,max_length=300)
    fields:list[ManualField]=Field(max_length=100)
    content_requirements:list[ContentRequirement]=Field(max_length=100)

    @model_validator(mode='after')
    def unique(self):
        for entries in (self.fields,self.content_requirements):
            if len({entry.id for entry in entries})!=len(entries):raise ValueError('Duplicate front matter identifiers.')
        if any(not f.label.strip() for f in self.fields):raise ValueError('Empty front matter label.')
        return self


def sources(analysis):
    if not analysis:return []
    result=deepcopy(analysis.get('front_matter_sources',[]))
    # Supplemental documents/text already belong to the sealed analysis SHA.
    result.extend(dict(id='note:'+note['id'],source=deepcopy(note['source']),section_id=None,
        suggested_label=None,style={},style_sources={}) for note in analysis.get('notes',[]))
    return result


def content_purposes(front):
    """One confirmed chapter can satisfy only one content kind's purpose."""
    result={}
    if front is None:return result
    for requirement in front['content_requirements']:
        expected={'declaration':'manual','acknowledgements':'acknowledgements'}.get(requirement['kind'])
        chapter_id=requirement['chapter_id']
        if expected is None or chapter_id in result and result[chapter_id]!=expected:
            raise ValueError('Incompatible front matter content kinds for one chapter.')
        result[chapter_id]=expected
    return result


def validate_content_purposes(front,chapters):
    if front is None:return
    expected=content_purposes(front)
    actual={c['id']:c['purpose'] for c in chapters}
    if any(actual.get(identity)!=purpose for identity,purpose in expected.items()):
        raise ValueError('Actual school chapter purpose conflicts with confirmed content requirement.')


def validate_front_matter(front,analysis,chapters):
    body=FrontMatter.model_validate(front).model_dump(mode='json')
    by_id={item['id']:item for item in sources(analysis)}
    section_ids={s['id'] for s in analysis.get('sections',[])}
    chapter_ids={c['id'] for c in chapters}
    def invalid():return StorageError('task_input_invalid','前置规则必须引用固定分析中的来源、分节和确认章节。',422)
    if body['cover_section_id'] not in section_ids:raise invalid()
    for field in body['fields']:
        original=by_id.get(field['source_id'])
        if (not original or field['section_id'] not in section_ids
            or original.get('section_id') is not None and field['section_id']!=original['section_id']
            or field['chapter_id'] is not None and field['chapter_id'] not in chapter_ids
            or field['style_source_id'] is not None and field['style_source_id'] not in by_id):raise invalid()
    for requirement in body['content_requirements']:
        if requirement['source_id'] not in by_id or requirement['chapter_id'] not in chapter_ids:raise invalid()
    try:content_purposes(body)
    except ValueError as exc:raise StorageError('task_input_invalid','同一确认章节不能同时用作声明与致谢。',422) from exc
    return body


def resolved_sources(front,analysis):
    ids={f['source_id'] for f in front['fields']}|{f['style_source_id'] for f in front['fields'] if f['style_source_id']}|{r['source_id'] for r in front['content_requirements']}
    return {s['id']:s for s in sources(analysis) if s['id'] in ids}


def resolved_sections(analysis,rules):
    result={s['id']:deepcopy(s) for s in analysis['sections']}
    for section in result.values():
        for rule in rules:
            prefix=section['id']+'.'
            if rule['category']=='page' and rule['id'].startswith(prefix):section['page'][rule['id'][len(prefix):]]=deepcopy(rule['value'])
    return result
