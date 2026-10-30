"""Collect installed notices offline; never fetch dependencies or remove containers.

Each invocation creates a new evidence directory. Original bytes are stored by
SHA-256; the index preserves component, version and source path separately.
"""
from __future__ import annotations
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

ROOT = Path.cwd() if __file__ == '<stdin>' else Path(__file__).resolve().parents[2]
NOTICE = re.compile(r'licen[cs]e|copying|notice|copyright|authors', re.I)
CODE_SUFFIXES = {'.py', '.pyc', '.pyo', '.js', '.ts', '.mjs', '.cjs', '.so', '.dll', '.pyd', '.exe'}


def notice_path(path):
    parts = Path(path).parts
    if Path(path).suffix.lower() in CODE_SUFFIXES:
        return False
    return bool(NOTICE.search(parts[-1])) or any(p.lower() in ('licenses', 'licences') for p in parts[:-1])


def file_entry(path, source):
    data = path.read_bytes()
    return dict(source=source, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), base64=base64.b64encode(data).decode())


def python_components():
    rows = []
    for dist in sorted(metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
        files = []
        for name in dist.files or []:
            if notice_path(str(name)):
                path = Path(dist.locate_file(name))
                if path.is_file() and path.stat().st_size <= 4 * 1024 * 1024:
                    files.append(file_entry(path, str(name).replace('\\', '/')))
        rows.append(dict(name=dist.metadata['Name'], version=dist.version,
            license_expression=dist.metadata.get('License-Expression'), license_metadata=dist.metadata.get('License'),
            license_files_declared=dist.metadata.get_all('License-File') or [],
            sources=dist.metadata.get_all('Project-URL') or [dist.metadata.get('Home-page')],
            classifiers=dist.metadata.get_all('Classifier') or [], files=files))
    return rows


def frontend_components(root):
    lock = json.loads((root / 'package-lock.json').read_text(encoding='utf-8'))
    rows = []
    for name, entry in lock['packages'].items():
        if not name:
            continue
        folder = root / name
        files = []
        if folder.is_dir():
            for path in sorted(folder.rglob('*')):
                relative = path.relative_to(folder)
                if 'node_modules' in relative.parts or path.is_symlink():
                    continue
                if path.is_file() and notice_path(str(relative)) and path.stat().st_size <= 4 * 1024 * 1024:
                    files.append(file_entry(path, (Path(name) / relative).as_posix()))
        installed = None
        if (folder / 'package.json').is_file():
            installed = json.loads((folder / 'package.json').read_text(encoding='utf-8')).get('version')
        rows.append(dict(name=name, version=entry.get('version'), installed_version=installed,
            development=bool(entry.get('dev')), optional=bool(entry.get('optional')), resolved=entry.get('resolved'),
            integrity=entry.get('integrity'), license_metadata=entry.get('license'), files=files))
    return rows


def run(args, **kwargs):
    return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs).stdout


SYSTEM_PROBE = r'''
set -eu
if command -v dpkg-query >/dev/null; then
  printf 'DPKG\t'; dpkg-query -W -f='${Package}\t${Version}\n' | base64 | tr -d '\n'; printf '\n'
elif test -f /lib/apk/db/installed; then
  printf 'APK\t'; base64 /lib/apk/db/installed | tr -d '\n'; printf '\n'
fi
for d in /usr/share/doc /usr/share/licenses /usr/local/share/licenses /usr/local/lib/python3.11 /opt; do
  if test -d "$d"; then
    find "$d" \( -iname 'license*' -o -iname 'licence*' -o -iname 'copying*' -o -iname 'notice*' -o -iname 'copyright*' \) \( -type f -o -type l \) -size -4096k | while IFS= read -r f; do
      if test -f "$f"; then
        printf 'FILE\t'; printf '%s' "$f" | base64 | tr -d '\n'; printf '\t'; base64 "$f" | tr -d '\n'; printf '\n'
      fi
    done
  fi
done
'''


def collect_image(image, python):
    identity = run(['docker', 'image', 'inspect', image, '--format', '{{.Id}}']).decode().strip()
    name = 'pa-notices-' + uuid4().hex[:16]
    args = ['docker', 'run', '--pull=never', '--network=none', '--read-only', '--name', name, '--entrypoint', 'python' if python else 'sh', '-i', identity]
    if python:
        probe = Path(__file__).read_bytes() + b'\nprint(json.dumps(python_components()))\n'
        raw = run(args + ['-'], input=probe, timeout=180)
        rows = json.loads(raw)
    else:
        raw = run(args + ['-s'], input=SYSTEM_PROBE.encode(), timeout=180)
        files, package_db = [], {}
        for line in raw.decode().splitlines():
            parts = line.split('\t')
            if parts[0] == 'FILE':
                data = base64.b64decode(parts[2])
                files.append(dict(source=base64.b64decode(parts[1]).decode(), bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), base64=parts[2]))
            elif parts[0] in ('DPKG', 'APK'):
                package_db[parts[0]] = base64.b64decode(parts[1]).decode()
        rows = [dict(name='image-system-and-embedded-notices', version=identity, package_database=package_db, files=files)]
    state = json.loads(run(['docker', 'inspect', name, '--format', '{{json .State}}']))
    return rows, dict(image_requested=image, image_id=identity, retained_container=name, state=state['Status'], exit_code=state['ExitCode'])


def materialize(rows, target):
    directory = target / 'texts'
    directory.mkdir()
    for row in rows:
        for item in row['files']:
            data = base64.b64decode(item.pop('base64'), validate=True)
            if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256']:
                raise ValueError('Notice content differs from evidence')
            item['text'] = 'texts/' + item['sha256'] + '.txt'
            path = target / item['text']
            if path.exists():
                if path.read_bytes() != data:
                    raise ValueError('Content hash collision')
            else:
                path.write_bytes(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=['python-host', 'python-image', 'frontend', 'system-image'], required=True)
    parser.add_argument('--image')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Use a new output directory; historical evidence is retained')
    if args.kind.endswith('image') and not args.image:
        parser.error('--image required')
    if args.kind == 'python-host':
        rows, source = python_components(), dict(python=sys.version, executable=sys.executable)
    elif args.kind == 'frontend':
        rows, source = frontend_components(ROOT / 'frontend'), dict(lock_sha256=hashlib.sha256((ROOT / 'frontend/package-lock.json').read_bytes()).hexdigest())
    else:
        rows, source = collect_image(args.image, args.kind == 'python-image')
    args.output.mkdir(parents=True)
    materialize(rows, args.output)
    result = dict(schema_version=1, kind=args.kind, captured_at=datetime.now(timezone.utc).isoformat(), source=source, network_requests=0, components=rows)
    (args.output / 'index.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(kind=args.kind, components=len(rows), references=sum(len(r['files']) for r in rows), unique_texts=len(list((args.output / 'texts').iterdir())), without_files=[r['name'] for r in rows if not r['files']])))


if __name__ == '__main__':
    # The image probe defines the same helpers but must not execute this CLI.
    if __file__ != '<stdin>':
        main()
