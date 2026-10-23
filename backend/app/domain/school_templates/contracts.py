from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator

WORKFLOW='school_template_v1'
PARSER_VERSION='school-template-openxml-v1'
PROFILE_FIELDS=('school','department','major','degree_type','education_level','applicable_version')

class StrictModel(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)

class ProfileRequest(StrictModel):
    expected_revision:int=Field(ge=0,le=2147483646)
    school:str=Field(max_length=300)
    department:str=Field(max_length=300)
    major:str=Field(max_length=300)
    degree_type:str=Field(max_length=100)
    education_level:str=Field(max_length=100)
    applicable_version:str=Field(max_length=300)

class TemplateRequest(StrictModel):
    previous_version_id:str|None=Field(default=None,min_length=1,max_length=64)
    name:str=Field(min_length=1,max_length=300)
    school:str=Field(min_length=1,max_length=300)
    version_label:str=Field(default='',max_length=300)
    template_file_id:str=Field(min_length=1,max_length=64)
    supplement_file_ids:list[str]=Field(default_factory=list,max_length=10)
    manuscript_file_ids:list[str]=Field(default_factory=list,max_length=10)
    supplement_text:str=Field(default='',max_length=50000)

    @model_validator(mode='after')
    def distinct_sources(self):
        ids=[self.template_file_id,*self.supplement_file_ids,*self.manuscript_file_ids]
        if len(ids)!=len(set(ids)) or any(not i or len(i)>64 for i in ids): raise ValueError('请选择不同的来源文件。')
        if not self.name.strip() or not self.school.strip(): raise ValueError('名称及学校不能为空。')
        return self

class Decision(StrictModel):
    conflict_id:str=Field(min_length=1,max_length=300)
    option_id:str=Field(min_length=1,max_length=300)

class Chapter(StrictModel):
    id:str=Field(min_length=1,max_length=300)
    title:str=Field(min_length=1,max_length=500)
    level:int=Field(ge=1,le=9)

class TextDecision(StrictModel):
    id:Literal['latin_font','heading1_line_spacing']
    choice:Literal['text','attributes']
    source_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')

class ConfirmRequest(StrictModel):
    text_decisions:list[TextDecision]=Field(default_factory=list,max_length=2)
    analysis_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    decisions:list[Decision]=Field(max_length=500)
    chapters:list[Chapter]=Field(min_length=1,max_length=300)

    @model_validator(mode='after')
    def distinct(self):
        for ids in ([x.conflict_id for x in self.decisions],[x.id for x in self.chapters]):
            if len(ids)!=len(set(ids)): raise ValueError('标识不可重复。')
        if any(not x.title.strip() for x in self.chapters): raise ValueError('章节标题不能为空。')
        return self

class BindingRequest(StrictModel):
    confirmation_id:str=Field(min_length=1,max_length=64)
    expected_revision:int=Field(ge=0,le=2147483646)

class SchoolTemplateInputVersion(StrictModel):
    kind:Literal['school_template']='school_template'
    template_version_id:str
    parser_version:str
    workflow_version:Literal['school_template_v1']=WORKFLOW

class EmptyRequest(StrictModel): pass
