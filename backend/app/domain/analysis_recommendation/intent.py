"""Bounded candidates anchored only in the actual outbound summary."""
from typing import Literal
import re
from pydantic import Field
from app.domain.correlation.contracts import StrictModel, ColumnId


class SummaryEvidence(StrictModel):
    start: int = Field(ge=0,le=4000)
    end: int = Field(ge=1,le=4000)
    quote: str = Field(min_length=1,max_length=1000)


class FieldRole(StrictModel):
    column: ColumnId
    role: Literal['outcome','exposure','group','covariate','identifier','time','status','score','other']


class ResearchIntent(StrictModel):
    objective: str = Field(max_length=2000)
    material_relationship: str = Field(max_length=2000)
    field_roles: list[FieldRole] = Field(max_length=10)
    population_conditions: list[str] = Field(max_length=10)
    chart_preferences: list[Literal['boxplot','correlation_heatmap','scatter','line','bar','violin','forest','roc_curve','kaplan_meier']] = Field(max_length=9)
    explanation_focus: list[str] = Field(max_length=10)
    output_language: Literal['zh-CN','en']
    missing_information: list[str] = Field(max_length=10)
    conflicts: list[str] = Field(max_length=10)
    evidence: list[SummaryEvidence] = Field(max_length=10)


def validate_intent(intent,request):
    text=request['research_summary']
    if intent['output_language']!=request['output_language']:
        raise ValueError('Intent language crossed the approved boundary.')
    if any(role['column'] not in request['candidate_columns'] for role in intent['field_roles']):
        raise ValueError('Intent references an unselected column.')
    if len({role['column'] for role in intent['field_roles']})!=len(intent['field_roles']):
        raise ValueError('Repeated intent role.')
    for evidence in intent['evidence']:
        if not 0<=evidence['start']<evidence['end']<=len(text) or text[evidence['start']:evidence['end']]!=evidence['quote']:
            raise ValueError('Intent evidence is absent from the actual outbound summary.')
    for key in ('population_conditions','explanation_focus','missing_information','conflicts'):
        if any(not s.strip() or len(s)>1000 for s in intent[key]):
            raise ValueError('Intent text exceeds the bounded contract.')
    texts=[intent['objective'],intent['material_relationship'],*intent['population_conditions'],*intent['explanation_focus']]
    if any(re.search(r'\b(?:SELECT\s+.+?\s+FROM|__import__\s*\(|eval\s*\(|exec\s*\(|lambda\s+\w+\s*:)',s,re.I|re.S) for s in texts):
        raise ValueError('Executable expressions are not research candidates.')
    if (intent['objective'] or intent['material_relationship'] or intent['field_roles'] or intent['population_conditions']) and not intent['evidence']:
        raise ValueError('Identified intent requires summary evidence.')
