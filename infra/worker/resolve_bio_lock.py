"""Resolve wheel-only Linux pins in an ephemeral CPython 3.11 container."""
import hashlib
import pathlib
import subprocess
import sys
import zipfile
from email.parser import BytesParser

root = pathlib.Path('/source')
wheels = root / 'script/.runtime/client-requirements-b02/bio-wheels'
wheels.mkdir(parents=True,exist_ok=True)
subprocess.run([sys.executable, '-m', 'pip', 'download', '--only-binary=:all:',
                '-r', str(root / 'backend/requirements-bio.in'), '-d', str(wheels)], check=True)
lines = ['# Generated Linux x86_64 CPython 3.11 wheel lock. Do not hand edit.']
for wheel in sorted(wheels.glob('*.whl')):
    with zipfile.ZipFile(wheel) as archive:
        metadata = BytesParser().parsebytes(archive.read(next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))))
    lines.append(f"{metadata['Name']}=={metadata['Version']} --hash=sha256:{hashlib.sha256(wheel.read_bytes()).hexdigest()}")
(root / 'backend/requirements-bio.lock.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
