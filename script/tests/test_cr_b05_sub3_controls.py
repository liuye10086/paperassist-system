"""Subpackage-three ownership selection; old algorithms are not rerun."""
import importlib.util
import ipaddress
from pathlib import Path
from uuid import uuid4

import pytest


def runner(monkeypatch, batch):
    monkeypatch.setenv('PAPERASSIST_CR_B05_SUBPACKAGE', batch)
    spec = importlib.util.spec_from_file_location('sub3_control_test', Path(__file__).parents[1] / 'dev/cr_b05_runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sub3_uses_new_resources_and_accepted_sub2_base(monkeypatch):
    m = runner(monkeypatch, '3')
    state = m.new_state('pa_test_' + uuid4().hex, 'pa_test_' + uuid4().hex)
    assert m.RUNTIME.name == 'client-requirements-b05-sub3'
    assert m.WORKER_IMAGE == 'paperassist-client-b05-sub3-worker:local'
    assert m.BASE_IMAGE_ID == 'sha256:f120beafbe360d93f5f46163a0271b3810977ff99bf498fd3108004a1715428a'
    assert state['url'] == 'http://127.0.0.87:18087'
    assert 'cr-b05-sub3-' in state['assets']
    old = runner(monkeypatch, '2')
    with pytest.raises(ValueError, match='ownership'):
        old.validate_state(state)


def test_sub3_network_is_separate_and_pdf_remains_internal(monkeypatch):
    m = runner(monkeypatch, '3')
    selected = m.cr_b05_networks.fixed_networks('sub3-explicit-ipam')
    assert selected['pdf-internal']['internal'] is True
    actual = [ipaddress.ip_network(x['ipam']['config'][0]['subnet']) for x in selected.values()]
    previous = [ipaddress.ip_network(s) for name, profile in m.cr_b05_networks.PROFILES.items()
                if name != 'sub3-explicit-ipam' for s, _, _ in profile.values()]
    assert all(not a.overlaps(b) for a in actual for b in previous)
