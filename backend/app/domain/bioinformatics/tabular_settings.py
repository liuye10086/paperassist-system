"""B05 attestation in the existing locked B04 scientific environment."""
import hashlib
import json
import os
from pathlib import Path
from .tabular_contracts import ENGINE_VERSION


def engine_code_digest():
    from app.domain.bio_insights.settings import engine_code_digest as insight_digest
    root=Path(__file__).resolve().parents[2];sha=hashlib.sha256(insight_digest().encode())
    for name in ('domain/bioinformatics/tabular_contracts.py','domain/bioinformatics/tabular_settings.py',
                 'adapters/bio_engine/tabular_assays.py','adapters/bio_engine/tabular_worker.py','adapters/bio_engine/tabular_probe.py'):
        path=root/name;sha.update(name.encode()+b'\0'+path.read_bytes()+b'\0')
    return sha.hexdigest()


def runtime_identity():
    from app.domain.bio_insights.settings import runtime_identity as insight_runtime,RUNTIME_MANIFEST_ENV
    blocked=dict(available=False,blockers=['bio_environment_unavailable'])
    runtime=insight_runtime()
    if not runtime.get('available'):return blocked
    try:
        report=json.loads(Path(os.environ[RUNTIME_MANIFEST_ENV]).read_bytes())
        code=engine_code_digest()
        if report['tabular_code_digest']!=code or any(report['checks'].get(key) is not True for key in ('tabular_import','tabular_compute')):return blocked
        return {**runtime,'blockers':[],'engine_version':ENGINE_VERSION,'code_digest':code}
    except (OSError,KeyError,ValueError):return blocked
