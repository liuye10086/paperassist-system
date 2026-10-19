"""Opt-in TEST worker injection; no real model or NCBI request is permitted."""
import os
import re

if (os.environ.get('PAPERASSIST_ENV') != 'test' or os.environ.get('PAPERASSIST_QUEUE_TEST_ALLOWED') != '1'
        or not re.fullmatch(r'pa_test_[0-9a-f]{32}', os.environ.get('PAPERASSIST_DB_SCHEMA', ''))):
    raise SystemExit('Synthetic assistance requires an isolated test stack.')

import requests
from tests.integration.test_literature_assistance import SyntheticProvider
from app.domain.literature_assistance import execution
from app.workers.__main__ import main


def forbidden(*args, **kwargs):
    raise AssertionError('Real HTTP forbidden in the offline queue test.')


requests.Session.request = forbidden
mode = os.environ.get('PAPERASSIST_OFFLINE_ASSISTANCE_PHASE')
if mode not in ('pending', 'complete'):
    raise SystemExit('Explicit synthetic response phase required.')
provider = SyntheticProvider(pending=mode == 'pending', get_failures=1 if mode == 'complete' else 0)
original = execution.run_assistance_task


def run(*args, **kwargs):
    return original(*args, **kwargs, provider_factory=lambda: provider)


execution.run_assistance_task = run
raise SystemExit(main())
