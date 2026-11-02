"""Only the new batch selection contract; accepted controller tests are reused."""
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest


def load_runner(monkeypatch, batch):
    monkeypatch.setenv('PAPERASSIST_CR_B05_SUBPACKAGE', batch)
    path = Path(__file__).resolve().parents[1] / 'dev/cr_b05_runner.py'
    spec = importlib.util.spec_from_file_location('b05_sub2_controls', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sub2_uses_separate_resources_and_accepted_base(monkeypatch):
    runner = load_runner(monkeypatch, '2')
    state = runner.new_state('pa_test_' + uuid4().hex, 'pa_test_' + uuid4().hex)
    assert runner.RUNTIME.name == 'client-requirements-b05-sub2'
    assert runner.WORKER_IMAGE == 'paperassist-client-b05-sub2-worker:local'
    assert runner.BASE_IMAGE_ID == 'sha256:eccd306a00484da13842ff6bd7c8f618ee1edb96178e17e80b28bd44f4f62a81'
    assert state['url'] == 'http://127.0.0.86:18086'
    assert 'cr-b05-sub2-' in state['assets']
    assert Path(state['runtime_manifest']).parent == runner.RUNTIME


def test_sub2_refuses_sub1_mutable_state(monkeypatch):
    old = load_runner(monkeypatch, '1')
    state = old.new_state('pa_test_' + uuid4().hex, 'pa_test_' + uuid4().hex)
    new = load_runner(monkeypatch, '2')
    with pytest.raises(ValueError, match='ownership'):
        new.validate_state(state)


def test_sub1_default_contract_is_unchanged(monkeypatch):
    runner = load_runner(monkeypatch, '1')
    state = runner.new_state('pa_test_' + uuid4().hex, 'pa_test_' + uuid4().hex)
    assert runner.RUNTIME.name == 'client-requirements-b05'
    assert state['url'] == 'http://127.0.0.85:18085'
    assert runner.WORKER_IMAGE == 'paperassist-client-b05-worker:local'


def test_unknown_subpackage_is_rejected(monkeypatch):
    with pytest.raises(ValueError, match='subpackage'):
        load_runner(monkeypatch, '4')


def test_sub2_network_profile_is_distinct_from_retained_profiles(monkeypatch):
    runner = load_runner(monkeypatch, '2')
    networks = runner.cr_b05_networks
    actual = networks.fixed_networks('sub2-explicit-ipam')
    assert actual['default']['ipam']['config'][0]['subnet'] == '10.246.90.0/28'
    assert actual['pdf-internal']['ipam']['config'][0]['subnet'] == '10.246.87.0/28'
    assert actual['pdf-internal']['internal'] is True
    import ipaddress
    new = [ipaddress.ip_network(v['ipam']['config'][0]['subnet']) for v in actual.values()]
    old = [ipaddress.ip_network(s) for key, profile in networks.PROFILES.items() if key != 'sub2-explicit-ipam' for s, _, _ in profile.values()]
    assert all(not a.overlaps(b) for a in new for b in old)


def probe_module(monkeypatch):
    load_runner(monkeypatch, '2')
    path = Path(__file__).resolve().parents[1] / 'dev/cr_b05_sub2_probe.py'
    spec = importlib.util.spec_from_file_location('b05_sub2_probe_test', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def probe_inputs(module):
    old = dict(status='passed', code_digest='accepted-code', lock_sha256='same-lock',
               python='fixed-python', packages={'scipy':'fixed'}, native_libraries=[], limits={'numeric_threads':1},
               checks={'deseq2_fit':True,'gsea':True})
    baseline = dict(insight_code_digest='accepted-code', insight_lock_digest='same-lock')
    environment = {k:old[k] for k in ('python','packages','native_libraries','lock_sha256','limits')}
    actual = dict(runtime_identity=dict(available=True, code_digest='new-code', lock_sha256='same-lock',
                   environment_digest=module.digest(environment)),
                  checks=dict(qpcr_relative_quantification=True, qpcr_paired_figure=True),evidence_scope='actual new qPCR')
    parent = dict(checks={'qpcr_parent_validation':True},validated_names=['delta-delta-cq','efficiency','efficiency-reference-change','paired-figure'])
    return old,baseline,actual,parent


def test_inherited_checks_are_identified_and_do_not_replace_new_qpcr_evidence(monkeypatch):
    m=probe_module(monkeypatch);old,base,new,parent=probe_inputs(m)
    value=m.inherited_report(old,base,new,parent,'new-tabular','new-image',{'source':'accepted evidence'})
    assert value['reused_checks']==['deseq2_fit','gsea']
    assert value['checks']=={**old['checks'],**new['checks'],**parent['checks']}
    assert value['code_digest']=='new-code' and old['code_digest']=='accepted-code'
    parent['checks']['qpcr_parent_validation']=False
    with pytest.raises(ValueError,match='incomplete'):m.inherited_report(old,base,new,parent,'t','i',{})


def test_changed_environment_cannot_reuse_accepted_scientific_checks(monkeypatch):
    m=probe_module(monkeypatch);old,base,new,parent=probe_inputs(m)
    new['runtime_identity']['environment_digest']='different-environment'
    with pytest.raises(ValueError,match='environment differs'):m.inherited_report(old,base,new,parent,'t','i',{})


def test_sub2_refresh_has_distinct_fixed_subnets_and_explicit_rebind_option(monkeypatch):
    runner=load_runner(monkeypatch,'2');networks=runner.cr_b05_networks
    actual=networks.fixed_networks('sub2-refresh-ipam')
    assert actual['default']['ipam']['config']==[dict(subnet='10.246.91.0/28',gateway='10.246.91.1')]
    assert actual['pdf-internal']['ipam']['config']==[dict(subnet='10.246.92.0/28',gateway='10.246.92.1')]
    assert actual['pdf-internal']['internal'] is True
    m=probe_module(monkeypatch)
    args=m.parse_args(['--rebind-unchanged-science','--network-profile','sub2-refresh-ipam'])
    assert args.rebind_unchanged_science and args.network_profile=='sub2-refresh-ipam'
    with pytest.raises(SystemExit):m.parse_args(['--network-profile','sub2-refresh-ipam'])
