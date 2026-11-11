"""Retain the exact code, lock and attestation of a scientific worker before upgrade."""
import argparse
import json
import os
from pathlib import Path

import app
from app.domain.bio_insights import settings


def write_fixed(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('xb') as stream:
            stream.write(content)
    except FileExistsError:
        if path.read_bytes() != content:
            raise ValueError('Conflicting retained runtime member: ' + str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('profile', choices=('standard', 'bulk_model', 'bulk_display', 'bulk_enrichment'))
    args = parser.parse_args()
    profile = args.profile
    identity = settings.runtime_identity(**({profile: True} if profile != 'standard' else {}))
    if not identity['available']:
        raise ValueError('The selected worker and runtime proof do not match')
    manifest_env = ('RUNTIME_MANIFEST_ENV' if profile == 'standard' else 'BULK_MODEL_MANIFEST_ENV'
                    if profile == 'bulk_model' else 'BULK_DISPLAY_MANIFEST_ENV')
    app_root = Path(app.__file__).resolve().parent
    target = args.directory.resolve() / identity['code_digest'] / identity['environment_digest']
    files = settings.engine_code_files()
    names = [path.relative_to(app_root).as_posix() for path in files]
    for path, name in zip(files, names, strict=True):
        write_fixed(target / 'app' / name, path.read_bytes())
    write_fixed(target / 'requirements-bio-insights.lock.txt', (app_root.parent / 'requirements-bio-insights.lock.txt').read_bytes())
    write_fixed(target / 'code-files.json', json.dumps(names).encode('utf-8'))
    for name in ('reproduce.py', 'render_worker.py'):
        write_fixed(target / name, (app_root / 'reproduction_assets/bio_insights' / name).read_bytes())
    proof = Path(os.environ[getattr(settings, manifest_env)]).read_bytes()
    proof_profile = 'bulk_display' if profile == 'bulk_enrichment' else profile
    write_fixed(target / f'runtime-{proof_profile}.json', proof)
    print(f'Retained {profile} {identity["code_digest"]} {identity["environment_digest"]}')


if __name__ == '__main__':
    main()
