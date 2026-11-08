import json
import os
import re
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .contracts import WorkflowProfile
from .provider import ProviderError

SUPPORTED_PROVIDERS = frozenset({'aws_healthomics'})


def bucket_name(value):
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', value) or '..' in value or re.fullmatch(r'\d+\.\d+\.\d+\.\d+', value):
        raise ProviderError('invalid_bucket')
    return value


class CloudSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    enabled: bool = False
    provider: str = 'aws_healthomics'
    region: str = 'ap-southeast-1'
    input_bucket: str = ''
    output_bucket: str = ''
    role_arn: str = ''
    profiles: list[WorkflowProfile] = Field(default_factory=list)

    @model_validator(mode='after')
    def configured(self):
        if self.provider not in SUPPORTED_PROVIDERS:
            raise ValueError('unsupported_provider')
        if self.enabled:
            bucket_name(self.input_bucket)
            bucket_name(self.output_bucket)
            if not re.fullmatch(r'[a-z]{2}-[a-z]+-\d', self.region) or not re.fullmatch(r'arn:aws:iam::\d{12}:role/[A-Za-z0-9_+=,.@/\-]+', self.role_arn):
                raise ValueError('invalid_cloud_configuration')
        if len({p.id for p in self.profiles}) != len(self.profiles):
            raise ValueError('duplicate_profile')
        return self


def load_settings():
    path = os.environ.get('PAPERASSIST_BIO_CLOUD_CONFIG_FILE', '')
    if not path:
        return CloudSettings()
    try:
        return CloudSettings.model_validate(json.loads(Path(path).read_text(encoding='utf-8')))
    except Exception:
        raise ProviderError('invalid_cloud_configuration') from None
