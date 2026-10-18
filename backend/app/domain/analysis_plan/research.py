"""Explicit local research declarations; never interpret free text as executable intent."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


RESEARCH_WORKFLOW_VERSION = 'analysis_plan_v2'
RESEARCH_RULES_VERSION = 'analysis_plan_rules_v2'


class ResearchRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    question: str = Field(min_length=1, max_length=4000)
    output_language: Literal['zh-CN', 'en']
    population: str = Field(max_length=2000)
    study_design: str = Field(max_length=2000)
    observation_unit: str = Field(max_length=2000)
    observation_structure: Literal['unknown', 'independent', 'paired', 'repeated']
    relationship_description: str = Field(max_length=2000)
    output_requirements: str = Field(max_length=2000)

    @field_validator('question')
    @classmethod
    def question_is_not_blank(cls, value):
        if not value.strip():
            raise ValueError('Research question must contain text.')
        return value


def missing_research(value):
    request = ResearchRequest.model_validate(value, strict=True)
    fields = [field for field in ('population', 'study_design', 'observation_unit')
              if not getattr(request, field).strip()]
    if request.observation_structure == 'unknown':
        fields.append('observation_structure')
    if request.observation_structure in ('paired', 'repeated') and not request.relationship_description.strip():
        fields.append('relationship_description')
    return fields
