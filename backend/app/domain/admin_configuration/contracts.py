"""Closed shapes. Compatibility is evaluated separately and recorded as evidence."""
import re
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.exceptions import StorageError

Token = Annotated[str, Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_.:-]+$')]
Positive = Annotated[int, Field(ge=1, le=1_000_000_000_000)]
Money = Annotated[int, Field(ge=0, le=1_000_000_000_000)]
Category = Literal['experiment','statistics','figure','method','literature','format','structure','expression','uncategorized']
CATEGORIES = ['experiment','statistics','figure','method','literature','format','structure','expression','uncategorized']


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


def safe_text(value):
    # Text remains data. Do not store recognizable credentials or executable locations.
    if re.search(r'(?i)(?:sk-[a-z0-9_-]{6,}|bearer\s+\S+|api[_ -]?key\s*[:=]|https?://|[a-z]:[\\/]|\\\\|/(?:etc|home|users|tmp)/|<script|\x00)', value):
        raise ValueError('Unsafe configuration text.')
    return value


class Price(Strict):
    version: Token
    currency: Literal['USD'] = 'USD'
    model: Token
    input_micro_usd_per_million: Money
    cached_input_micro_usd_per_million: Money
    output_micro_usd_per_million: Money
    cache_write_micro_usd_per_million: Money | None = None


class Policy(Strict):
    model: Token
    prompt_version: Token
    max_output_tokens: Positive
    timeout_seconds: Annotated[int, Field(ge=1, le=3600)] = 45
    tools: list[Literal['code_interpreter']] = Field(default_factory=list, max_length=1)
    output_format: Token
    price: Price


class Execution(Strict):
    policy: Policy
    input_token_allowance: Positive
    task_limit_micro_usd: Money


class PlotExecution(Execution):
    tool_reserve_micro_usd: Positive
    tool_reserve_version: Token


class Entry(Strict):
    execution: Execution
    price_source: Literal['installed_code','deployment_policy','synthetic_fixture']
    price_verified_on: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')] | None = None
    price_status: Literal['unverified','synthetic'] = 'unverified'


class PlotEntry(Entry):
    execution: PlotExecution


class Credential(Strict):
    alias: Literal['openai-default','ncbi-default']
    revision: Literal['deployment-v1']


class Models(Strict):
    explanation: Entry | None = None
    recommendation: Entry | None = None
    plot: PlotEntry | None = None
    writing: Entry
    literature: Entry | None = None
    credential: Credential | None = None
    real_calls_enabled: Literal[False] = False
    batch_max_posts: Annotated[int, Field(ge=1, le=6)] = 6
    max_corrections: Annotated[int, Field(ge=0, le=2)] = 2
    batch_cap_micro_usd: Annotated[int, Field(ge=1, le=12000000)] = 12000000


class Prompts(Strict):
    writing_template: Literal['sci-writing-v2'] = 'sci-writing-v2'
    workflow: Literal['installed-v1'] = 'installed-v1'
    writing_instruction: str = Field(default='', max_length=1000)
    explanation_instruction: str = Field(default='', max_length=1000)
    recommendation_instruction: str = Field(default='', max_length=1000)
    plot_instruction: str = Field(default='', max_length=1000)
    literature_instruction: str = Field(default='', max_length=1000)

    @field_validator('*')
    @classmethod
    def text(cls, value): return safe_text(value)


class Ncbi(Strict):
    identity: Credential | None = None
    enabled: Literal[False] = False
    interval_seconds: Annotated[float, Field(ge=0.5, le=60)] = 0.5
    cache_ttl_seconds: Annotated[int, Field(ge=0, le=86400)] = 86400
    timeout_seconds: Annotated[int, Field(ge=1, le=30)] = 30


class Basic(Strict):
    max_upload_bytes: Annotated[int, Field(ge=1, le=10485760)] = 10485760
    max_uncompressed_bytes: Annotated[int, Field(ge=1, le=67108864)] = 67108864
    max_sheets: Annotated[int, Field(ge=1, le=50)] = 50
    max_rows: Annotated[int, Field(ge=1, le=100000)] = 100000
    max_columns: Annotated[int, Field(ge=1, le=256)] = 256
    max_cells: Annotated[int, Field(ge=1, le=1000000)] = 1000000
    worker_concurrency: Annotated[int, Field(ge=1, le=2)] = 1


class Journals(Strict):
    source_mode: Literal['local_only'] = 'local_only'
    metrics_enabled: Literal[False] = False
    update_mode: Literal['manual'] = 'manual'
    recommendation_version: Literal['journal_recommendation_v1'] = 'journal_recommendation_v1'
    format_version: Literal['journal-format-v1'] = 'journal-format-v1'
    default_count: Annotated[int, Field(ge=1, le=5)] = 3
    max_count: Annotated[int, Field(ge=1, le=5)] = 5
    source_label: str = Field(default='local-owner-material', max_length=80)
    update_plan: str = Field(default='', max_length=300)
    update_result: Literal['not_started','recorded','failed'] = 'not_started'
    update_note: str = Field(default='', max_length=300)
    require_verification: Literal[True] = True

    @field_validator('source_label','update_plan','update_note')
    @classmethod
    def text(cls, value): return safe_text(value)


class HeadingAlias(Strict):
    text: str = Field(min_length=1, max_length=40)
    role: Literal['heading1','heading2','heading3','body']

    @field_validator('text')
    @classmethod
    def text_value(cls, value): return safe_text(value)


class Schools(Strict):
    parser_version: Literal['school-template-openxml-v1'] = 'school-template-openxml-v1'
    quality_version: Literal['school-quality-v1'] = 'school-quality-v1'
    formats: list[Literal['docx']] = Field(default_factory=lambda:['docx'], min_length=1, max_length=1)
    conflict_policy: Literal['require_confirmation'] = 'require_confirmation'
    heading_aliases: list[HeadingAlias] = Field(default_factory=list, max_length=12)

    @model_validator(mode='after')
    def distinct_aliases(self):
        names=[alias.text.strip() for alias in self.heading_aliases]
        if any(not name for name in names) or len(names)!=len(set(names)):
            raise ValueError('Heading literals must be nonempty and distinct.')
        return self


class Review(Strict):
    category_order: list[Category] = Field(min_length=9, max_length=9)
    keywords: dict[Category, list[Annotated[str, Field(min_length=1, max_length=40)]]]
    handling_notes: dict[Category, Annotated[str, Field(max_length=300)]]
    default_language: Literal['zh-CN','en'] = 'zh-CN'
    document_version: Literal['review-documents-v1'] = 'review-documents-v1'
    require_confirmation: Literal[True] = True

    @field_validator('category_order')
    @classmethod
    def categories(cls,value):
        if set(value)!=set(CATEGORIES): raise ValueError('All categories are required.')
        return value

    @field_validator('keywords','handling_notes')
    @classmethod
    def mappings(cls,value):
        if set(value)!=set(CATEGORIES): raise ValueError('All categories are required.')
        for item in value.values():
            if isinstance(item,list):
                if len(item)>20: raise ValueError('Too many literal keywords.')
                for word in item: safe_text(word)
            else: safe_text(item)
        return value


class Bundle(Strict):
    schema_version: Literal[1] = 1
    models: Models
    prompts: Prompts
    ncbi: Ncbi
    basic: Basic
    journals: Journals
    schools: Schools
    review: Review


def parse_bundle(value):
    try:
        parsed=Bundle.model_validate(value).model_dump(mode='json')
        def inspect(item):
            if isinstance(item,str):safe_text(item)
            elif isinstance(item,dict):
                for child in item.values():inspect(child)
            elif isinstance(item,list):
                for child in item:inspect(child)
        inspect(parsed)
        return parsed
    except (ValueError, TypeError):
        raise StorageError('configuration_invalid','配置包含未知字段、非法值或不允许保存的内容。',422) from None
