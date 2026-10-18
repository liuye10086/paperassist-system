"""Explicit TEST-only crash injection; mounted separately, never part of image."""
import os
from pathlib import Path
import re

if (os.environ.get('PAPERASSIST_ENV') != 'test'
        or os.environ.get('PAPERASSIST_QUEUE_TEST_ALLOWED') != '1'
        or not re.fullmatch(r'pa_test_[0-9a-f]{32}', os.environ.get('PAPERASSIST_DB_SCHEMA', ''))
        or Path('/run/secrets/model-api-key').read_text().strip()):
    raise SystemExit('Statistics crash drill requires isolated TEST without model credentials.')

from app.adapters.task_store import TaskStore
from app.workers.__main__ import main

append_event = TaskStore.append_event


def crash_before_commit(db, task, event_type):
    target = Path('/data/.batch10-crash-task')
    if (task['task_type'] == 'statistics_compute' and event_type == 'succeeded'
            and task['current_attempt'] == 1 and target.exists()
            and target.read_text(encoding='ascii') == task['id']):
        Path('/data/.batch10-crashed').write_text(task['id'], encoding='ascii')
        os._exit(73)
    return append_event(db, task, event_type)


TaskStore.append_event = staticmethod(crash_before_commit)
raise SystemExit(main())
