"""Test-only combined transports and original-reader guard for dataset lineage."""
import os
from pathlib import Path
import re

if (os.environ.get('PAPERASSIST_ENV') != 'test'
        or os.environ.get('PAPERASSIST_QUEUE_TEST_ALLOWED') != '1'
        or not re.fullmatch(r'pa_test_[0-9a-f]{32}', os.environ.get('PAPERASSIST_DB_SCHEMA', ''))):
    raise SystemExit('Dataset analysis bootstrap requires an isolated test schema.')

# Both factories use the real SDK over in-memory MockTransport. Their existing
# test hooks are composed so PNG candidate and explanation receipt crashes are
# exercised by the same independently restarted Linux worker.
import plot_bootstrap  # noqa: E402,F401
import explanation_bootstrap  # noqa: E402,F401
from app.adapters.file_objects import LocalFileObjects  # noqa: E402
from app.workers.__main__ import main  # noqa: E402

original = LocalFileObjects.original


def guarded_original(self, record):
    if Path('/data/.forbid-original-reader').exists():
        with Path('/data/.unexpected-original-read').open('a', encoding='ascii') as stream:
            stream.write('original\n')
        raise AssertionError('Dataset analysis must never read the original workbook.')
    return original(self, record)


LocalFileObjects.original = guarded_original

if __name__ == '__main__':
    raise SystemExit(main())
