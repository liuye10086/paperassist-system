"""Mounted only by the opt-in isolated queue test; never part of the worker image."""
import os
import re
from types import SimpleNamespace

if (os.environ.get('PAPERASSIST_ENV')!='test' or os.environ.get('PAPERASSIST_QUEUE_TEST_ALLOWED')!='1'
        or not re.fullmatch(r'pa_test_[0-9a-f]{32}',os.environ.get('PAPERASSIST_DB_SCHEMA',''))):
    raise SystemExit('Synthetic literature provider requires an isolated test stack.')

import requests
from tests.helpers.literature import SyntheticNcbi
from app.domain.literature import execution
from app.workers.__main__ import main


def forbidden(*args,**kwargs):
    raise AssertionError('Real HTTP is forbidden in the synthetic literature queue test.')


requests.Session.request = forbidden
provider = SyntheticNcbi(25,fail_fetches=1)
provider.settings = SimpleNamespace(enabled=True)
execution.NcbiClient = lambda: provider
raise SystemExit(main())
