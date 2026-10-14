"""Test-only process death at parse publication, never copied into the image."""
import os
from pathlib import Path
import re

if (os.environ.get('PAPERASSIST_ENV') != 'test'
        or os.environ.get('PAPERASSIST_QUEUE_TEST_ALLOWED') != '1'
        or not re.fullmatch(r'pa_test_[0-9a-f]{32}', os.environ.get('PAPERASSIST_DB_SCHEMA', ''))):
    raise SystemExit('Parse crash drill requires a UUID test schema.')

from app.adapters.task_store import TaskStore
from app.workers.__main__ import main

append_event = TaskStore.append_event


def crash_before_parse_commit(db, task, event_type):
    if task['task_type'] == 'parse_file' and event_type == 'succeeded' and task['current_attempt'] == 1:
        Path('/data/.test-parse-worker-crashed').write_text('before_commit', encoding='ascii')
        os._exit(73)
    return append_event(db, task, event_type)


TaskStore.append_event = staticmethod(crash_before_parse_commit)
raise SystemExit(main())
