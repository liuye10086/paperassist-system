"""Frozen public provenance for dataset analyses; contains no object path."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator
from app.core.exceptions import StorageError
from app.domain.datasets.contracts import STRUCTURE_PARSER_VERSION

ENGINE = 'descriptive_statistics_v1'
DATASET_ENGINE = 'descriptive_statistics_dataset_v1'


class DatasetAnalysisSource(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    kind: Literal['dataset_version']
    schema_version: Literal[1]
    dataset_id: str = Field(min_length=1)
    structure_id: str = Field(min_length=1)
    dataset_version: int = Field(ge=1)
    file_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    dataset_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    dataset_size_bytes: int = Field(gt=0)
    dataset_schema_version: Literal[1]
    sheet_index: int = Field(ge=0, le=49)
    sheet_name: str = Field(min_length=1, max_length=31)
    parser_version: str = Field(min_length=1)


    @model_validator(mode='before')
    @classmethod
    def strict_schema(cls, value):
        if isinstance(value, dict) and any(type(value.get(key)) is not int for key in ('schema_version', 'dataset_schema_version')):
            raise ValueError('Invalid schema version')
        if isinstance(value, dict) and value.get('parser_version') != STRUCTURE_PARSER_VERSION:
            raise ValueError('Unsupported dataset parser version')
        return value


class PreparedDatasetAnalysisSource(DatasetAnalysisSource):
    kind: Literal['prepared_dataset_version']
    parent_dataset_id: str = Field(min_length=1)
    parent_dataset_version: int = Field(ge=1)
    transform_version: Literal['excel_prepare_v1']


AnyDatasetAnalysisSource = PreparedDatasetAnalysisSource | DatasetAnalysisSource


class OptionalAnalysisSource(BaseModel):
    source: AnyDatasetAnalysisSource | None = None

    @model_serializer(mode='wrap')
    def serialize_source(self, handler):
        value = handler(self)
        if self.source is None:
            value.pop('source', None)
        return value


def source_dict(value):
    if isinstance(value, DatasetAnalysisSource):
        value = value.model_dump()
    try:
        model = PreparedDatasetAnalysisSource if isinstance(value, dict) and value.get('kind') == 'prepared_dataset_version' else DatasetAnalysisSource
        return model.model_validate(value).model_dump()
    except (ValueError, TypeError) as exc:
        raise StorageError('source_conflict', '分析数据来源合同无效。', 409) from exc


def raw_dataset_source(row, sheet, file_id):
    return DatasetAnalysisSource(kind='dataset_version', schema_version=1,
        dataset_id=row['id'], structure_id=row['structure_id'], dataset_version=row['version'],
        file_id=file_id, source_sha256=row['source_sha256'], dataset_sha256=row['sha256'],
        dataset_size_bytes=row['size_bytes'], dataset_schema_version=1, sheet_index=sheet.index,
        sheet_name=sheet.name, parser_version=row['parser_version']).model_dump()


def prepared_dataset_source(row, parent_source):
    parent = DatasetAnalysisSource.model_validate(parent_source).model_dump()
    if row['parent_dataset_id'] != parent['dataset_id']:
        raise StorageError('source_conflict', '整理数据的原始来源不一致。', 409)
    return PreparedDatasetAnalysisSource.model_validate({**parent,
        'kind': 'prepared_dataset_version', 'dataset_id': row['id'], 'dataset_version': row['version'],
        'dataset_sha256': row['sha256'], 'dataset_size_bytes': row['size_bytes'],
        'parent_dataset_id': parent['dataset_id'], 'parent_dataset_version': parent['dataset_version'],
        'transform_version': 'excel_prepare_v1'}).model_dump()


def statistics_engine(value):
    source = value.get('source') if isinstance(value, dict) else getattr(value, 'source', None)
    if source is None:
        return ENGINE
    frozen = source_dict(source)
    own = value if isinstance(value, dict) else value.model_dump()
    for key in ('file_id', 'source_sha256'):
        if key in own and own[key] != frozen[key]:
            raise StorageError('source_conflict', '分析记录与冻结数据来源不一致。', 409)
    selection = own.get('selection')
    if selection is not None and selection.get('sheet_name') != frozen['sheet_name']:
        raise StorageError('source_conflict', '分析工作表与冻结数据来源不一致。', 409)
    return DATASET_ENGINE
