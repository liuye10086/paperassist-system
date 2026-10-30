"""Bio sources deliberately remain outside the legacy rectangular-data union."""
import hashlib
import json
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.core.exceptions import StorageError
from app.domain.bioinformatics.settings import BioLimits

from app.domain.bioinformatics.parser_contracts import PARSER_VERSION
WORKFLOW_VERSION = 'bio_import_v1'
WORKFLOW_VERSION_V2 = 'bio_import_v2'
PARSER_VERSION_V2 = 'geo_visium_import_v2'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def conflict(code='bio_source_conflict'):
    return StorageError(code, '生信数据来源、版本或完整性已变化，请重新载入核对。', 409)


def member_filename(member):
    key=member.get('key','')
    if key.startswith('matrix_') or key.endswith('_index'):
        return key+'.'+member['format']
    name=member['source_member_name'].replace('\\','/').rsplit('/',1)[-1]
    # Preserved member names describe provenance; decoded leaf bytes are not gzip.
    if member['compression']=='none' and name.lower().endswith('.gz'):
        name=name[:-3]
    return name or key+'.'+member['format']


class BioImportRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    file_ids: list[str] = Field(min_length=1, max_length=10)
    assay: Literal['visium']
    name: str = Field(min_length=1, max_length=200)
    dataset_id: str | None = Field(default=None, max_length=64)
    expected_dataset_revision: int = Field(ge=0, le=2147483646)
    roles: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode='after')
    def unique_sources(self):
        if len(self.file_ids) != len(set(self.file_ids)) or set(self.roles) - set(self.file_ids):
            raise ValueError('Source files or roles are inconsistent')
        if (self.dataset_id is None) != (self.expected_dataset_revision == 0):
            raise ValueError('An existing dataset requires its revision')
        if any(not value or len(value) > 80 for value in self.roles.values()):
            raise ValueError('Invalid source role')
        return self


class BioImportRequestV2(BioImportRequest):
    matrix_representation: Literal['mtx', '10x_h5']
    compare_alternate: bool = True


class BioImportInputVersion(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True)
    kind: Literal['bio_import']
    import_id: str
    dataset_id: str
    workflow_version: Literal['bio_import_v1']
    source_file_ids: list[str]
    parser_version: str
    output_language: Literal['zh-CN', 'en']


class BioImportInputVersionV2(BioImportInputVersion):
    workflow_version: Literal['bio_import_v2']
    matrix_representation: Literal['mtx', '10x_h5']
    compare_alternate: bool
    engine_version: Literal['visium_explore_v1.0.0']
    environment_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    code_digest: str = Field(pattern=r'^[0-9a-f]{64}$')


class BioDatasetSourceV1(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True)
    kind: Literal['bio_dataset_version'] = 'bio_dataset_version'
    schema_version: Literal[1] = 1
    project_id: str
    dataset_id: str
    dataset_version_id: str
    version: int = Field(ge=1)
    manifest_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    parser_version: str
    source_file_ids: list[str] = Field(min_length=1,max_length=10)


class BioConfirmRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    task_revision: int = Field(ge=1, lt=2147483647)
    checkpoint_id: str = Field(min_length=1, max_length=64)
    wait_id: str = Field(min_length=1, max_length=64)
    candidate_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    expected_dataset_revision: int = Field(ge=1)


def validate_snapshot(task):
    try:
        value = task['input_snapshot']
        required = {'schema_version','kind','workflow_version','project_id','import_id','dataset_id','name','assay',
                    'parser_version','expected_dataset_revision','output_language','files','settings'}
        workflow = value.get('workflow_version')
        parser_version = PARSER_VERSION
        if workflow == WORKFLOW_VERSION_V2:
            from app.domain.bioinformatics.analysis_settings import BioAnalysisLimits
            required |= {'matrix_representation', 'compare_alternate', 'analysis_limits',
                         'engine_version', 'environment_digest', 'code_digest'}
            parser_version = PARSER_VERSION_V2
            limits = BioAnalysisLimits.model_validate(value['analysis_limits'])
            if (value['matrix_representation'] not in ('mtx', '10x_h5') or type(value['compare_alternate']) is not bool
                    or value['engine_version'] != 'visium_explore_v1.0.0' or limits.model_dump() != value['analysis_limits']
                    or not all(type(value[k]) is str and re.fullmatch(r'[a-f0-9]{64}', value[k])
                               for k in ('environment_digest', 'code_digest'))):
                raise ValueError('Invalid versioned H5 import')
        if (set(value) != required or type(value['schema_version']) is not int or value['schema_version'] != 1
                or value['kind'] != 'bio_import' or workflow not in (WORKFLOW_VERSION, WORKFLOW_VERSION_V2)
                or task['workflow_version'] != workflow or task['task_type'] != 'bio_import'
                or value['project_id'] != task['project_id'] or value['assay'] != 'visium'
                or not 1 <= len(value['files']) <= 10 or value['parser_version'] != parser_version
                or value['expected_dataset_revision'] < 1 or task['input_digest'] != digest(value)):
            raise ValueError('Frozen import identity differs')
        BioLimits.model_validate(value['settings'])
        return value
    except (TypeError, KeyError, ValueError) as exc:
        raise conflict() from exc


def input_version(task):
    value = validate_snapshot(task)
    model = BioImportInputVersionV2 if value['workflow_version'] == WORKFLOW_VERSION_V2 else BioImportInputVersion
    extra = {key: value[key] for key in ('matrix_representation', 'compare_alternate', 'engine_version',
                                        'environment_digest', 'code_digest')} if model is BioImportInputVersionV2 else {}
    return model(kind='bio_import', import_id=value['import_id'], dataset_id=value['dataset_id'],
        workflow_version=value['workflow_version'], source_file_ids=[f['id'] for f in value['files']],
        parser_version=value['parser_version'], output_language=value['output_language'], **extra).model_dump(mode='json')


def validate_v2_representation(task, result):
    snapshot = task['input_snapshot']
    if snapshot['workflow_version'] != WORKFLOW_VERSION_V2:
        return
    try:
        representation = result['manifest']['representation']
        if (representation['selected'] != snapshot['matrix_representation']
                or representation['matrix_representation'] != representation['selected']
                or type(representation['compare_alternate']) is not bool
                or representation['compare_alternate'] != snapshot['compare_alternate']):
            raise ValueError()
        comparison = representation['comparison']['status']
        if comparison == 'mismatch':
            raise StorageError('bio_h5_matrix_mismatch', 'H5 与 MTX 的矩阵内容不一致。', 409)
        if comparison not in ('identical', 'order_reindexed_equal', 'not_comparable'):
            raise ValueError()
        if representation['selected'] == '10x_h5' and representation['h5_internal_check'] != 'verified':
            raise ValueError()
        chosen = representation['chosen_source']
        members = result.get('outputs', result.get('members', []))
        if (chosen['source_file_id'] not in {f['id'] for f in snapshot['files']}
                or not any(all(member.get(k) == chosen[k] for k in ('source_file_id', 'source_member_name', 'sha256'))
                           for member in members)):
            raise ValueError()
    except (KeyError, TypeError, ValueError) as exc:
        raise conflict() from exc
