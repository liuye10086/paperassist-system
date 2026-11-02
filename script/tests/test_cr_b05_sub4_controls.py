"""Only the newly added batch ownership and retained-source preparation."""
import importlib.util
import ipaddress
from pathlib import Path
from uuid import uuid4


def test_sub4_owns_new_paths_and_exact_accepted_base(monkeypatch):
    monkeypatch.setenv('PAPERASSIST_CR_B05_SUBPACKAGE', '4')
    spec = importlib.util.spec_from_file_location('sub4_controls', Path(__file__).parents[1]/'dev/cr_b05_runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    state = module.new_state('pa_test_'+uuid4().hex, 'pa_test_'+uuid4().hex)
    assert state['url'] == 'http://127.0.0.88:18088'
    assert module.RUNTIME.name == 'client-requirements-b05-sub4'
    assert module.BASE_IMAGE_ID == 'sha256:9044d608aaad22e9e185ca225d5ba91f5c28d6d1b6bc143305fc519ca8a655c0'
    module.configure(state)
    assert module.os.environ['PAPERASSIST_SINGLE_CELL_RUNTIME_MANIFEST'] == str(module.SINGLE_CELL_GATE)


def test_sub4_fixed_networks_do_not_reuse_retained_subnets():
    import sys
    sys.path.insert(0, str(Path(__file__).parents[1]/'dev'))
    import cr_b05_networks as networks
    current = networks.fixed_networks('sub4-explicit-ipam')
    assert current['pdf-internal']['internal'] is True
    selected = [ipaddress.ip_network(x['ipam']['config'][0]['subnet']) for x in current.values()]
    old = [ipaddress.ip_network(subnet) for name, values in networks.PROFILES.items()
           if name != 'sub4-explicit-ipam' for subnet, _, _ in values.values()]
    assert all(not a.overlaps(b) for a in selected for b in old)
