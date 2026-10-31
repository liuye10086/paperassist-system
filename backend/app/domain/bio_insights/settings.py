"""B04-only ceilings. Overrides may tighten, never expand approved budgets."""
from pydantic import BaseModel, ConfigDict, Field
import hashlib
import json
import os
from pathlib import Path


class BioInsightsLimits(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True)
    compute_wall_seconds: int = Field(default=1800, gt=0, le=1800)
    cpu_seconds: int = Field(default=1500, gt=0, le=1500)
    warmup_seconds: int = Field(default=180, gt=0, le=180)
    memory_bytes: int = Field(default=2147483648, gt=0, le=2147483648)
    address_space_bytes: int = Field(default=3221225472, gt=0, le=3221225472)
    numeric_threads: int = Field(default=1, ge=1, le=1)
    max_input_members: int = Field(default=514, gt=0, le=514)
    max_output_json_bytes: int = Field(default=2097152, gt=0, le=2097152)


INTERPRETER = '/opt/paperassist-bio-insights/bin/python'
RUNTIME_MANIFEST_ENV = 'PAPERASSIST_BIO_INSIGHTS_RUNTIME_MANIFEST'
STAGING_DIRECTORY_ENV = 'PAPERASSIST_BIO_INSIGHTS_STAGING_DIR'


def engine_code_files():
    """All first-party code directly executable in the fixed scientific child."""
    root = Path(__file__).resolve().parents[2]
    paths=list((root/'adapters'/'bio_insights_engine').glob('*.py'))
    paths += [root/name for name in ('__init__.py','adapters/__init__.py','domain/__init__.py',
        'adapters/bio_engine/__init__.py','adapters/bio_engine/manifest.py','adapters/excel_sandbox.py',
        'domain/bio_insights/__init__.py','domain/bio_insights/contracts.py','domain/bio_insights/design.py','domain/bio_insights/settings.py')]
    return sorted(paths,key=lambda path:path.relative_to(root).as_posix())


def engine_code_digest():
    root=Path(__file__).resolve().parents[2]
    digest = hashlib.sha256()
    for path in engine_code_files():
        digest.update(path.relative_to(root).as_posix().encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def engine_lock_digest():
    path = Path(__file__).resolve().parents[3] / 'requirements-bio-insights.lock.txt'
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runtime_identity():
    """Only a fresh, complete actual Linux gate admits numerical methods."""
    blocked = {'available': False, 'reason': 'bio_insights_environment_unavailable'}
    try:
        path = Path(os.environ[RUNTIME_MANIFEST_ENV])
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024**2:
            return blocked
        report = json.loads(path.read_bytes())
        if (report['schema_version'] != 1 or report['status'] != 'passed'
                or report['engine_version'] != 'bio_insights_v1.0.0'
                or report['interpreter'] != INTERPRETER or report['numeric_threads'] != 1
                or report['lock_sha256'] != engine_lock_digest()
                or report['code_digest'] != engine_code_digest()
                or report['packages']['pydeseq2'] != '0.5.4' or report['packages']['gseapy'] != '1.3.1'
                or report['isolation'] != {'network': 'denied', 'file': 'denied', 'fork': 'denied', 'subprocess': 'denied'}
                or any(report['checks'][key] is not True for key in ['aggregation', 'deseq2_fit', 'gsea'])
                or report['peak_rss_kib'] >= BioInsightsLimits().memory_bytes // 1024
                or report['limits'] != BioInsightsLimits().model_dump()):
            return blocked
        identity = {key: report[key] for key in ['engine_version', 'code_digest', 'lock_sha256']}
        environment = {key: report[key] for key in ['python', 'packages', 'native_libraries', 'lock_sha256', 'limits']}
        identity['environment_digest'] = hashlib.sha256(json.dumps(environment, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        return {'available': True, **identity}
    except (KeyError, TypeError, ValueError, OSError):
        return blocked
