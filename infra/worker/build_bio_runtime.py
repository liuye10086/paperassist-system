"""Build the fixed bio environment or Worker using verified local wheels.

Populate the wheel directory using resolve_bio_lock.py in the pinned Python
container. This helper runs only fixed Docker build arguments, never shell code.
"""
import argparse
import hashlib
from pathlib import Path
import re
import subprocess


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--worker',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[2]
    runtime=root/'script/.runtime/client-requirements-b02'
    wheels=runtime/'bio-wheels'
    lock=root/'backend/requirements-bio.lock.txt'
    if not wheels.is_dir():raise SystemExit('Missing fixed Linux wheel cache; run resolve_bio_lock.py in pinned Linux container first.')
    available={hashlib.sha256(p.read_bytes()).hexdigest() for p in wheels.glob('*.whl')}
    expected=re.findall(r'--hash=sha256:([0-9a-f]{64})',lock.read_text(encoding='utf8'))
    if not expected or not set(expected)<=available:raise SystemExit('Linux wheel cache is incomplete or corrupt; no installation/build performed.')
    source=(root/'infra/worker/Dockerfile').read_text(encoding='utf8')
    source=source.replace('RUN python -m venv','COPY --from=bio_wheels / /wheels\nRUN python -m venv',1)
    source=source.replace('pip install --require-hashes','pip install --no-index --find-links=/wheels --require-hashes',1)
    generated=runtime/'Dockerfile.bio-offline'
    generated.write_text(source,encoding='utf8')
    tag='paperassist-client-b02-worker:local' if args.worker else 'paperassist-bio-runtime:cr-b02-final'
    command=['docker','buildx','build','--load','--build-context',f'bio_wheels={wheels}',
             '-f',str(generated),'-t',tag]
    if not args.worker:command+=['--target','bio-runtime']
    subprocess.run([*command,str(root)],cwd=root,check=True)
    print(tag)


if __name__=='__main__':main()
