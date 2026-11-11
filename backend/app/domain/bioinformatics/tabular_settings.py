"""Tabular attestation in the locked scientific environment."""
import hashlib
import json
import os
import re
from pathlib import Path
from .tabular_contracts import ENGINE_VERSION


TABULAR_RUNTIME_MANIFEST_ENV = 'PAPERASSIST_BIO_TABULAR_RUNTIME_MANIFEST'
ISOLATION_CHECKS = ('network', 'file', 'fork', 'subprocess')
TABULAR_CHECKS = ('tabular_import', 'tabular_qc', 'tabular_compute')
MAX_TABULAR_RECEIPT_BYTES = 64 * 1024


def engine_code_digest():
    from app.domain.bio_insights.settings import engine_code_digest as insight_digest
    root=Path(__file__).resolve().parents[2];sha=hashlib.sha256(insight_digest().encode())
    for name in ('domain/bioinformatics/tabular_contracts.py','domain/bioinformatics/tabular_settings.py',
                 'adapters/bio_engine/tabular_assays.py','adapters/bio_engine/tabular_worker.py','adapters/bio_engine/tabular_probe.py'):
        path=root/name;sha.update(name.encode()+b'\0'+path.read_bytes()+b'\0')
    return sha.hexdigest()


def scoped_runtime_identity(path):
    from app.domain.bio_insights.settings import BioInsightsLimits, INTERPRETER, engine_lock_digest
    from .settings import BioLimits

    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_TABULAR_RECEIPT_BYTES:
        raise ValueError('Invalid tabular runtime receipt')
    report = json.loads(path.read_bytes())
    limits = BioInsightsLimits()
    peak = report['peak_rss_kib']
    identity = report['runtime_identity']
    if (type(report['schema_version']) is not int or report['schema_version'] != 1
            or report['status'] != 'passed' or report['profile'] != 'tabular' or report['platform'] != 'linux'
            or report['interpreter'] != INTERPRETER or type(report['numeric_threads']) is not int
            or report['numeric_threads'] != limits.numeric_threads or report['limits'] != limits.model_dump()
            or report['bulk_limits'] != BioLimits().model_dump()
            or report['isolation'] != dict.fromkeys(ISOLATION_CHECKS, 'denied')
            or any(report['checks'][key] is not True for key in TABULAR_CHECKS)
            or type(peak) is not int or not 0 < peak < limits.memory_bytes // 1024
            or not re.fullmatch(r'[a-f0-9]{64}', identity['environment_digest'])):
        raise ValueError('Invalid tabular runtime receipt')
    expected = dict(available=True, blockers=[], engine_version=ENGINE_VERSION, code_digest=engine_code_digest(),
                    lock_sha256=engine_lock_digest(), environment_digest=identity['environment_digest'])
    if identity != expected or identity['available'] is not True:
        raise ValueError('Invalid tabular runtime identity')
    return expected


def runtime_identity():
    from app.domain.bio_insights.settings import RUNTIME_MANIFEST_ENV, runtime_identity as insight_runtime

    blocked = dict(available=False, blockers=['bio_environment_unavailable'])
    try:
        scoped = os.environ.get(TABULAR_RUNTIME_MANIFEST_ENV)
        if scoped:
            return scoped_runtime_identity(Path(scoped))
        runtime = insight_runtime()
        if not runtime.get('available'):
            return blocked
        report = json.loads(Path(os.environ[RUNTIME_MANIFEST_ENV]).read_bytes())
        code = engine_code_digest()
        if report['tabular_code_digest'] != code or any(
            report['checks'][key] is not True for key in ('tabular_import', 'tabular_compute')
        ):
            return blocked
        return {**runtime, 'blockers': [], 'engine_version': ENGINE_VERSION, 'code_digest': code}
    except (OSError, KeyError, TypeError, ValueError):
        return blocked
