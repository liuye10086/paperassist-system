"""Explicit test-container entry point: crash after rename, before DB commit.

This file is not copied into the production image. The real-queue test mounts it
only in its UUID-scoped test stack, with synthetic inputs and temporary assets.
"""
import os
from pathlib import Path
import re

if (os.environ.get('PAPERASSIST_ENV') != 'test'
        or os.environ.get('PAPERASSIST_QUEUE_TEST_ALLOWED') != '1'
        or not re.fullmatch(r'pa_test_[0-9a-f]{32}', os.environ.get('PAPERASSIST_DB_SCHEMA', ''))):
    raise SystemExit('Crash bootstrap requires the isolated real-queue test environment.')

from app.adapters.task_store import TaskStore
from app.workers.__main__ import main

append_event = TaskStore.append_event


def crash_first_publication(db, task, event_type):
    if event_type == 'succeeded' and task['current_attempt'] == 1:
        Path('/data/.test-worker-crashed').write_text('before_commit', encoding='ascii')
        # Real process termination: no Python finally blocks or mocked rollback.
        os._exit(73)
    return append_event(db, task, event_type)


TaskStore.append_event = staticmethod(crash_first_publication)
raise SystemExit(main())
