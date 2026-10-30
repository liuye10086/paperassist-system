"""Scoped legacy smoke checks in the existing fixed Linux Worker image.

Each pytest case creates its own random PostgreSQL test schema. No acceptance
schema is selected, and no running service or protected asset is mounted.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'script' / 'dev'))
import cr_b02_runner as control

CASES = [
    'tests/api/test_excel.py::test_reads_all_sheets_and_only_twenty_rows',
    'tests/api/test_projects.py::test_empty_projects_then_create_both_types',
    'tests/api/test_projects.py::test_upload_list_reopen_and_download_original',
    'tests/integration/test_reports.py::test_export_reuses_saved_content_and_png_without_api',
    'tests/integration/test_storage_transactional_producers.py::test_dataset_manifest_admits_all_sheets_before_first_byte',
    'tests/integration/test_storage_transactional_producers.py::test_sync_producer_rejects_quota_then_counts_bytes_and_replays_read',
]

ENTRY = '''
import os
from dotenv import dotenv_values
from sqlalchemy.engine import make_url
for file,key in [('/app/.env','PAPERASSIST_TEST_DATABASE_URL'),('/app/.env.migrations','PAPERASSIST_TEST_MIGRATION_DATABASE_URL')]:
    value=dotenv_values(file,interpolate=False)[key]
    url=make_url(value)
    if url.database!='paperassist_system_test' or url.host not in ('localhost','127.0.0.1'):
        raise RuntimeError('An explicit local test endpoint is required')
    os.environ[key]=url.set(host='host.docker.internal').render_as_string(hide_password=False)
os.environ.update(PAPERASSIST_ENV='test',PAPERASSIST_NCBI_ENABLED='0',PAPERASSIST_WRITING_LIVE_ENABLED='0',OPENAI_API_KEY='',OPENAI_API_KEY_FILE='')
import pytest,sys
raise SystemExit(pytest.main(sys.argv[1:]))
'''


def main():
    state = control.read_state()
    image = state['worker_image_id']
    if not image.startswith('sha256:') or len(image) != 71:
        raise ValueError('A fixed Worker image is required')
    directory = control.RUNTIME / 'verifications' / ('legacy-linux-' + uuid4().hex)
    directory.mkdir(parents=True)
    control.worker_stack.protect_directory(directory)
    command = ['docker','run','--rm','--memory','2g','--cpus','1','--read-only',
        '--tmpfs','/tmp:rw,nosuid,nodev,size=768m','--workdir','/app']
    for source,target in [('backend/tests','/app/tests'),('backend/alembic','/app/alembic'),
                          ('backend/alembic.ini','/app/alembic.ini'),('backend/.env','/app/.env'),
                          ('backend/.env.migrations','/app/.env.migrations')]:
        command += ['--mount', 'type=bind,source='+str(ROOT/source)+',target='+target+',readonly']
    command += ['--mount','type=bind,source='+str(directory)+',target=/evidence','--entrypoint','python',image,
        '-B','-c',ENTRY,*CASES,'-q','-p','no:cacheprovider','--tb=short',
        '--basetemp=/evidence/pytest-temp','--junitxml=/evidence/results.xml']
    result = subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
    control.worker_stack.private_write(directory/'stdout.txt',result.stdout)
    control.worker_stack.private_write(directory/'stderr.txt',result.stderr)
    report = {'image':image,'cases':CASES,'exit_code':result.returncode,
        'source_digest':control.source_digest(),'entry_sha256':hashlib.sha256(ENTRY.encode()).hexdigest(),
        'scope':'New random test schemas; existing acceptance and protected assets not mounted'}
    control.worker_stack.private_write(directory/'report.json',json.dumps(report,indent=2))
    print(json.dumps({'exit_code':result.returncode,'evidence':str(directory)},ensure_ascii=False),flush=True)
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
