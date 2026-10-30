"""Verify collected raw notices and their current local build-input bindings."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root=ROOT):
    contexts = []
    for index in sorted((root / 'third_party').glob('*/index.json')):
        value = json.loads(index.read_text(encoding='utf-8'))
        names, texts, references = set(), set(), 0
        for row in value['components']:
            if row['name'] in names:
                raise ValueError('Duplicate component')
            names.add(row['name'])
            for item in row['files']:
                relative = PurePosixPath(item['text'])
                if relative.is_absolute() or '..' in relative.parts or '\\' in item['text'] or ':' in item['text']:
                    raise ValueError('Unsafe notice path')
                path = index.parent / item['text']
                if path.is_symlink() or not path.is_file() or path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
                    raise ValueError('Notice differs: ' + str(path))
                texts.add(item['text'])
                references += 1
        if texts != {p.relative_to(index.parent).as_posix() for p in (index.parent / 'texts').iterdir()}:
            raise ValueError('Unindexed notice file')
        contexts.append(dict(context=index.parent.name, index=index.relative_to(root).as_posix(), index_sha256=sha(index),
            components=len(names), references=references, unique_texts=len(texts), source=value['source']))
    if {x['context'] for x in contexts} != {'python-windows','python-linux','frontend','system-app','system-renderer','system-postgres','system-broker'}:
        raise ValueError('Missing local collection context')
    requirements = {}
    for line in (root / 'backend/requirements.txt').read_text().splitlines():
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^ #]+)', line.strip())
        if match:
            requirements[re.sub('[-_.]+', '-', match[1]).lower()] = match[2]
    for context in ('python-windows', 'python-linux'):
        rows = json.loads((root / 'third_party' / context / 'index.json').read_text(encoding='utf-8'))['components']
        installed = {re.sub('[-_.]+', '-', r['name']).lower(): r['version'] for r in rows}
        if any(installed.get(name) != version for name, version in requirements.items()):
            raise ValueError(context + ' differs from requirements')
    frontend = json.loads((root / 'third_party/frontend/index.json').read_text(encoding='utf-8'))
    if frontend['source']['lock_sha256'] != sha(root / 'frontend/package-lock.json'):
        raise ValueError('Frontend lock differs')
    if any(r['installed_version'] and r['installed_version'] != r['version'] for r in frontend['components']):
        raise ValueError('Installed frontend version differs')
    return dict(schema_version=1, status='local_materials_partial', s10_be46_satisfied=False,
        requirements_sha256=sha(root / 'backend/requirements.txt'), pinned_python_components=len(requirements),
        frontend_lock_sha256=sha(root / 'frontend/package-lock.json'), contexts=contexts,
        unresolved=['flatbuffers complete version-bound license and applicable NOTICE',
            'tqdm full MPL-2.0 text and provenance binding',
            'OCR embedded character dictionary explicit attribution/applicability',
            'seven installed frontend build/test packages without separate local license text',
            'mounted Windows fonts and local assets redistribution conditions',
            'system/binary embedded notices applicability and source obligations not fully reconciled'],
        network_requests=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-manifest', action='store_true')
    args = parser.parse_args()
    value = verify()
    if args.write_manifest:
        (ROOT / 'third_party/manifest.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    else:
        saved = json.loads((ROOT / 'third_party/manifest.json').read_text(encoding='utf-8'))
        if saved != value:
            raise ValueError('Aggregate manifest differs from current evidence')
    print(json.dumps(dict(status=value['status'], contexts=len(value['contexts']), references=sum(r['references'] for r in value['contexts']),
        unique_texts=sum(r['unique_texts'] for r in value['contexts']), pinned_python_components=value['pinned_python_components'], unresolved=len(value['unresolved']))))


if __name__ == '__main__':
    main()
