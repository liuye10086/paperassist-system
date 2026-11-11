"""Read an operator-retained, hash-matched scientific runtime snapshot."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re

from app.domain.bioinformatics.contracts import digest


ARCHIVE_DIR_ENV = 'PAPERASSIST_BIO_REPRODUCTION_ENVIRONMENTS_DIR'
PROFILES = {
    'standard': (None, ('aggregation', 'deseq2_fit', 'gsea')),
    'bulk_model': ('bulk_model', ('bulk_shared_wald',)),
    'bulk_display': ('bulk_display', ('bulk_saved_values_render',)),
    'bulk_enrichment': ('bulk_display', ('bulk_saved_values_render', 'bulk_offline_resource_import',
                                         'bulk_offline_enrichment', 'bulk_offline_enrichment_render')),
}
IDENTITY_KEYS = ('engine_version', 'code_digest', 'environment_digest', 'lock_sha256')
PROGRAM_NAMES = ('reproduce.py', 'render_worker.py')


@dataclass(frozen=True)
class ArchivedEnvironment:
    proof: dict
    code: tuple[tuple[str, bytes], ...]
    lock: bytes
    interpreter: str
    programs: tuple[tuple[str, bytes], ...]


def _read(root, name, limit=4 * 1024**2):
    relative = PurePosixPath(name)
    if (not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', name)
            or relative.as_posix() != name or any(part in ('.', '..') for part in relative.parts)):
        raise ValueError('Invalid archived path')
    path = root.joinpath(*relative.parts)
    if not path.resolve(strict=True).is_relative_to(root) or not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Invalid archived member')
    return path.read_bytes()


def archived_environment(identity, profile):
    directory = os.getenv(ARCHIVE_DIR_ENV)
    if not directory or not all(isinstance(identity.get(key), str) and re.fullmatch(r'[0-9a-f]{64}', identity[key])
                                for key in ('code_digest', 'environment_digest', 'lock_sha256')):
        return None
    try:
        base = Path(directory).resolve(strict=True)
        root = (base / identity['code_digest'] / identity['environment_digest']).resolve(strict=True)
        if not root.is_relative_to(base):
            return None
        reported_profile, required_checks = PROFILES[profile]
        proof_name = 'runtime-' + (reported_profile or 'standard') + '.json'
        report = json.loads(_read(root, proof_name))
        environment = {key: report[key] for key in ('python', 'packages', 'native_libraries', 'lock_sha256', 'limits')}
        if (report['schema_version'] != 1 or report['status'] != 'passed' or report.get('profile') != reported_profile
                or report['numeric_threads'] != 1 or report['isolation'] != dict(network='denied', file='denied', fork='denied', subprocess='denied')
                or any(report['checks'].get(check) is not True for check in required_checks)
                or any(report[key] != identity[key] for key in ('engine_version', 'code_digest', 'lock_sha256'))
                or digest(environment) != identity['environment_digest']):
            return None
        lock = _read(root, 'requirements-bio-insights.lock.txt')
        names = json.loads(_read(root, 'code-files.json'))
        if (hashlib.sha256(lock).hexdigest() != identity['lock_sha256'] or not isinstance(names, list)
                or not 1 <= len(names) <= 256 or names != sorted(set(names))):
            return None
        code = []
        code_digest = hashlib.sha256()
        for name in names:
            content = _read(root, 'app/' + name)
            code_digest.update(name.encode() + b'\0' + content + b'\0')
            code.append((name, content))
        if code_digest.hexdigest() != identity['code_digest']:
            return None
        proof = dict(environment=environment, runtime_identity={'available': True, **{key: identity[key] for key in IDENTITY_KEYS}},
                     gate_checks=report['checks'], isolation=report['isolation'], evidence_scope='archived_actual_locked_runtime_gate')
        programs = tuple((name, _read(root, name)) for name in PROGRAM_NAMES)
        return ArchivedEnvironment(proof, tuple(code), lock, report['interpreter'], programs)
    except (OSError, ValueError, TypeError, KeyError):
        return None
