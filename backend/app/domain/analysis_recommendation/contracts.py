"""Metadata-only recommendation requests and a non-executable model response."""
from typing import Literal
import re
from pydantic import Field, model_validator
from app.domain.correlation.contracts import StrictModel, ColumnId

VERSION = 'analysis_recommendation_v1'
VERSION_V2 = 'analysis_recommendation_v2'
VERSION_V3 = 'analysis_recommendation_v3'
VERSION_V4 = 'analysis_recommendation_v4'
VERSION_V5 = 'analysis_recommendation_v5'
COMPARISON_METHODS = ['welch_t','mann_whitney_u','paired_t','wilcoxon','welch_anova','kruskal_wallis']
MODELING_METHODS = ['ols','logistic','roc_auc','kaplan_meier']


class PreviewRequest(StrictModel):
    dataset_id: str = Field(min_length=1, max_length=64)
    sheet_name: str = Field(min_length=1, max_length=31)
    candidate_columns: list[ColumnId] = Field(min_length=1, max_length=10)
    output_language: Literal['zh-CN', 'en']
    research_summary: str = Field(max_length=4000)

    @model_validator(mode='after')
    def unique_columns(self):
        if len(set(self.candidate_columns)) != len(self.candidate_columns):
            raise ValueError('Candidate fields must be unique.')
        return self


class CreateRequest(PreviewRequest):
    external_processing: dict


class PreviewRequestV2(PreviewRequest):
    schema_version: Literal[2]

    @model_validator(mode='before')
    @classmethod
    def exact_version(cls,value):
        if isinstance(value,dict) and type(value.get('schema_version')) is not int:raise ValueError('Version must be an integer.')
        return value


class CreateRequestV2(PreviewRequestV2):
    external_processing: dict


class PreviewRequestV3(PreviewRequestV2):
    schema_version: Literal[3]


class CreateRequestV3(PreviewRequestV3):
    external_processing: dict


class PreviewRequestV4(PreviewRequestV3):
    schema_version: Literal[4]


class CreateRequestV4(PreviewRequestV4):
    external_processing: dict


class PreviewRequestV5(PreviewRequestV4):
    schema_version: Literal[5]

class CreateRequestV5(PreviewRequestV5):
    external_processing: dict

def request_model(value, *, create=False):
    if hasattr(value,'model_dump'):value=value.model_dump(mode='json')
    if isinstance(value,dict) and value.get('schema_version')==5:
        return CreateRequestV5 if create else PreviewRequestV5
    if isinstance(value,dict) and value.get('schema_version')==4:
        return CreateRequestV4 if create else PreviewRequestV4
    if isinstance(value,dict) and value.get('schema_version')==3:
        return CreateRequestV3 if create else PreviewRequestV3
    modern=isinstance(value,dict) and value.get('schema_version')==2
    return (CreateRequestV2 if create else PreviewRequestV2) if modern else (CreateRequest if create else PreviewRequest)


def parse_request(value, *, create=False):
    if hasattr(value,'model_dump'):value=value.model_dump(mode='json')
    return request_model(value,create=create).model_validate(value,strict=True)


def request_version(value):
    version=parse_request(value,create='external_processing' in value).model_dump().get('schema_version',1)
    return {1:VERSION,2:VERSION_V2,3:VERSION_V3,4:VERSION_V4,5:VERSION_V5}[version]


def call_key(value):
    version=parse_request(value,create='external_processing' in value).model_dump().get('schema_version',1)
    return f'analysis_recommendation:v{version}'


class RecommendationDraft(StrictModel):
    schema_version: Literal[1]
    method: Literal['descriptive', 'pearson', 'spearman'] | None
    mode: Literal['pair', 'matrix'] | None
    columns: list[ColumnId] = Field(max_length=10)
    output_language: Literal['zh-CN', 'en']
    rationale: list[str] = Field(max_length=10)
    assumptions: list[str] = Field(max_length=10)
    missing_information: list[str] = Field(max_length=10)

    @model_validator(mode='after')
    def safe_shape(self):
        if len(set(self.columns)) != len(self.columns): raise ValueError('Repeated field.')
        if any(not s.strip() or len(s)>1000 for group in (self.rationale,self.assumptions,self.missing_information) for s in group):
            raise ValueError('Recommendation text is invalid.')
        if self.method is None:
            if not self.missing_information or self.mode is not None or self.columns:
                raise ValueError('Unsupported requests require missing information without a fallback method.')
        elif self.method == 'descriptive':
            if self.mode is not None or not 1<=len(self.columns)<=2: raise ValueError('Invalid descriptive fields.')
        elif self.mode not in ('pair','matrix') or not 2<=len(self.columns)<=10 or self.mode=='pair' and len(self.columns)!=2:
            raise ValueError('Invalid correlation fields.')
        return self


class ComparisonRoles(StrictModel):
    numeric_column: ColumnId | None
    group_column: ColumnId | None
    pair_id_column: ColumnId | None
    before_column: ColumnId | None
    after_column: ColumnId | None


class RecommendationDraftV2(StrictModel):
    schema_version: Literal[2]
    method: Literal['descriptive','pearson','spearman','welch_t','mann_whitney_u','paired_t','wilcoxon','welch_anova','kruskal_wallis'] | None
    mode: Literal['pair','matrix','independent','paired','multiple'] | None
    columns: list[ColumnId] = Field(max_length=10)
    roles: ComparisonRoles
    output_language: Literal['zh-CN','en']
    rationale: list[str] = Field(max_length=10)
    assumptions: list[str] = Field(max_length=10)
    missing_information: list[str] = Field(max_length=10)

    @model_validator(mode='before')
    @classmethod
    def exact_version(cls,value):
        if isinstance(value,dict) and type(value.get('schema_version')) is not int:raise ValueError('Version must be an integer.')
        return value

    @model_validator(mode='after')
    def safe_shape(self):
        if len(set(self.columns))!=len(self.columns):raise ValueError('Repeated field.')
        if any(not s.strip() or len(s)>1000 for texts in (self.rationale,self.assumptions,self.missing_information) for s in texts):raise ValueError('Invalid recommendation text.')
        roles=self.roles.model_dump();chosen=[c for c in roles.values() if c is not None]
        if self.method in COMPARISON_METHODS:
            design='paired' if self.method in ('paired_t','wilcoxon') else 'multiple' if self.method in ('welch_anova','kruskal_wallis') else 'independent'
            expected={'pair_id_column','before_column','after_column'} if design=='paired' else {'numeric_column','group_column'}
            if self.mode!=design or {key for key,value in roles.items() if value is not None}!=expected or len(set(chosen))!=len(chosen) or set(self.columns)!=set(chosen):raise ValueError('Invalid comparison role mapping.')
        else:
            if chosen:raise ValueError('Noncomparison recommendation cannot carry comparison roles.')
            legacy={key:getattr(self,key) for key in ('method','mode','columns','output_language','rationale','assumptions','missing_information')}
            RecommendationDraft.model_validate(dict(schema_version=1,**legacy),strict=True)
        return self


class ModelingRoles(ComparisonRoles):
    outcome_column: ColumnId | None
    score_column: ColumnId | None
    id_column: ColumnId | None
    time_column: ColumnId | None
    status_column: ColumnId | None
    covariate_columns: list[ColumnId] = Field(max_length=8)


class RecommendationDraftV3(StrictModel):
    schema_version: Literal[3]
    method: Literal['descriptive','pearson','spearman','welch_t','mann_whitney_u','paired_t','wilcoxon',
                    'welch_anova','kruskal_wallis','ols','logistic','roc_auc','kaplan_meier'] | None
    mode: Literal['pair','matrix','independent','paired','multiple','regression','roc','survival'] | None
    columns: list[ColumnId] = Field(max_length=10)
    roles: ModelingRoles
    output_language: Literal['zh-CN','en']
    rationale: list[str] = Field(max_length=10)
    assumptions: list[str] = Field(max_length=10)
    missing_information: list[str] = Field(max_length=10)

    @model_validator(mode='before')
    @classmethod
    def exact_version(cls,value):
        if isinstance(value,dict) and type(value.get('schema_version')) is not int:
            raise ValueError('Version must be an integer.')
        return value

    @model_validator(mode='after')
    def safe_shape(self):
        if len(set(self.columns))!=len(self.columns):raise ValueError('Repeated field.')
        if any(not s.strip() or len(s)>1000 for texts in (self.rationale,self.assumptions,self.missing_information) for s in texts):
            raise ValueError('Invalid recommendation text.')
        roles=self.roles.model_dump()
        if self.method not in MODELING_METHODS:
            extra=set(ModelingRoles.model_fields)-set(ComparisonRoles.model_fields)
            if any(roles[k] for k in extra):raise ValueError('Unrelated modeling roles.')
            value=self.model_dump();value.pop('intent',None);value.pop('source_reference',None);value.update(schema_version=2,roles={k:roles[k] for k in ComparisonRoles.model_fields})
            RecommendationDraftV2.model_validate(value,strict=True)
            return self
        active={k for k,v in roles.items() if v is not None and v!=[]}
        chosen=[v for k,v in roles.items() if k!='covariate_columns' and v is not None]+roles['covariate_columns']
        if self.method in ('ols','logistic'):
            required={'outcome_column','covariate_columns'};optional={'id_column'};mode='regression'
        elif self.method=='roc_auc':required={'outcome_column','score_column'};optional=set();mode='roc'
        else:required={'id_column','time_column','status_column'};optional={'group_column'};mode='survival'
        if (self.mode!=mode or not required<=active or active-required-optional
                or len(chosen)!=len(set(chosen)) or set(chosen)!=set(self.columns)):
            raise ValueError('Invalid modeling role mapping.')
        return self


from app.domain.analysis_recommendation.intent import ResearchIntent, validate_intent


class RecommendationDraftV4(RecommendationDraftV3):
    schema_version: Literal[4]
    intent: ResearchIntent

    @model_validator(mode='after')
    def bounded_intent(self):
        return self


class SourceEvidence(StrictModel):
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    quote: str = Field(min_length=1,max_length=4000)

class SourceAlias(StrictModel):
    code: Literal['F1','S1','D1']
    level: Literal['file','sheet','dataset']

class SourceReference(StrictModel):
    status: Literal['matched','unspecified','ambiguous','other']
    references: list[SourceAlias] = Field(max_length=3)
    evidence: list[SourceEvidence] = Field(max_length=10)

class RecommendationDraftV5(RecommendationDraftV4):
    schema_version: Literal[5]
    source_reference: SourceReference

def alias_in_summary(code,summary):
    return bool(re.search(r'(?<![A-Za-z0-9_])'+re.escape(code)+r'(?![A-Za-z0-9_])',summary))

def validate_source_reference(value,summary):
    parsed=SourceReference.model_validate(value,strict=True).model_dump(mode='json')
    aliases={'F1':'file','S1':'sheet','D1':'dataset'}
    refs=parsed['references']
    if len({r['code'] for r in refs})!=len(refs):raise ValueError('Repeated source alias.')
    for ref in refs:
        if aliases[ref['code']]!=ref['level'] or not alias_in_summary(ref['code'],summary):raise ValueError('Unapproved source alias.')
    for evidence in parsed['evidence']:
        if evidence['end']<=evidence['start'] or evidence['end']>len(summary) or summary[evidence['start']:evidence['end']]!=evidence['quote']:
            raise ValueError('Source quote differs from the approved summary.')
    if parsed['status']=='matched' and (not refs or not parsed['evidence'] or any(not any(alias_in_summary(r['code'],e['quote']) for e in parsed['evidence']) for r in refs)):
        raise ValueError('Matched sources require exact alias evidence.')
    return parsed

def draft_model(request):
    return {1:RecommendationDraft,2:RecommendationDraftV2,3:RecommendationDraftV3,4:RecommendationDraftV4,5:RecommendationDraftV5}[request.get('schema_version',1)]


def validate_draft(value, request, *, require_explanation=False):
    parsed=draft_model(request).model_validate(value, strict=True).model_dump(mode='json')
    if (parsed['output_language']!=request['output_language']
            or not set(parsed['columns']).issubset(request['candidate_columns'])):
        raise ValueError('Recommendation crossed the approved candidate or language boundary.')
    if (require_explanation or request.get('schema_version') in (2,3,4,5)) and parsed['method'] is not None and (not parsed['rationale'] or not parsed['assumptions']):
        raise ValueError('New actionable recommendations require rationale and assumptions.')
    if request.get('schema_version') in (4,5):
        validate_intent(parsed['intent'],request)
        compatible={'forest':('ols','logistic'),'roc_curve':('roc_auc',),'kaplan_meier':('kaplan_meier',),
                    'correlation_heatmap':('pearson','spearman'),'scatter':('pearson','spearman')}
        if parsed['method'] is not None and any(chart in compatible and parsed['method'] not in compatible[chart]
                for chart in parsed['intent']['chart_preferences']):
            raise ValueError('Chart candidate requires an incompatible calculation.')
    if request.get('schema_version')==5:validate_source_reference(parsed['source_reference'],request['research_summary'])
    return parsed
