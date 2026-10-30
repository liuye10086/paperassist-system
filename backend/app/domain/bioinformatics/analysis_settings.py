"""Bounded runtime attestation; API hosts never import the Linux science stack."""
import hashlib
import json
import os
from pathlib import Path
from typing import Literal
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator


class BioAnalysisLimits(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid',frozen=True)
    max_observations: int = Field(default=20000,ge=1,le=20000)
    max_features: int = Field(default=100000,ge=1,le=100000)
    max_entries: int = Field(default=10000000,ge=1,le=10000000)
    max_dense_values: int = Field(default=20000000,ge=1,le=20000000)
    max_outputs: int = Field(default=256,ge=1,le=256)
    max_member_bytes: int = Field(default=268435456,ge=1,le=268435456)
    max_output_bytes: int = Field(default=536870912,ge=1,le=536870912)
    max_output_json_bytes: int = Field(default=2097152,ge=1,le=2097152)
    wall_seconds: int = Field(default=1200,ge=1,le=1200)
    cpu_seconds: int = Field(default=900,ge=1,le=900)
    memory_bytes: int = Field(default=2147483648,ge=1,le=2147483648)
    max_clusters: int = Field(default=50,ge=1,le=50)
    max_marker_tests: int = Field(default=1000000,ge=1,le=1000000)


class RuntimeChecks(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')
    numeric: Literal[True]
    isolation: Literal[True]
    hdf5: Literal[True]
    plots: Literal[True]

    @field_validator('numeric','isolation','hdf5','plots',mode='before')
    @classmethod
    def actual_boolean(cls,value):
        if type(value) is not bool:raise ValueError('Boolean probe result required')
        return value


class RuntimeManifest(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')
    schema_version: Literal[1]
    gate_status: Literal['passed']
    engine_version: Literal['visium_explore_v1.0.0']
    environment_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    code_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    lock_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    image_digest: str = Field(min_length=1,max_length=256)
    platform: Literal['linux/amd64','linux/arm64']
    checks: RuntimeChecks
    verified_at: str = Field(min_length=20,max_length=40)


def backend_root():
    return Path(__file__).resolve().parents[3]


def engine_code_digest():
    root=backend_root()/'app'/'adapters'/'bio_engine'
    files=sorted(root.rglob('*.py'),key=lambda p:p.relative_to(root).as_posix())
    if not files:raise ValueError('Missing engine source')
    value=hashlib.sha256()
    for file in files:
        if file.is_symlink():raise ValueError('Engine source symlink')
        value.update(file.relative_to(root).as_posix().encode('utf-8')+b'\0'+file.read_bytes()+b'\0')
    return value.hexdigest()


def engine_lock_digest():
    return hashlib.sha256((backend_root()/'requirements-bio.lock.txt').read_bytes()).hexdigest()


def runtime_identity():
    from app.core.config import local_config
    path=os.environ.get('PAPERASSIST_BIO_RUNTIME_MANIFEST') or local_config().get('PAPERASSIST_BIO_RUNTIME_MANIFEST')
    blocked={'available':False,'blockers':['bio_environment_unavailable'],'status':'not_configured_or_unverified'}
    if not path:return blocked
    try:
        file=Path(path)
        if file.is_symlink() or not file.is_file() or not 0<file.stat().st_size<=65536:return blocked
        with file.open('rb') as stream:content=stream.read(65537)
        if len(content)>65536:return blocked
        manifest=RuntimeManifest.model_validate(json.loads(content))
        verified=datetime.fromisoformat(manifest.verified_at.replace('Z','+00:00'))
        if verified.tzinfo is None:return blocked
        if manifest.code_digest!=engine_code_digest() or manifest.lock_sha256!=engine_lock_digest():
            return {**blocked,'blockers':['bio_environment_unavailable','bio_input_integrity_changed']}
        return {'available':True,'blockers':[],'status':'verified_configuration_not_liveness',**manifest.model_dump()}
    except (OSError,ValueError,TypeError):
        return blocked
