import copy
import importlib.util
import json
from pathlib import Path
import pytest


def module():
    path = Path(__file__).resolve().parents[1] / 'dev/cr_b05_networks.py'
    assert path.is_file(), 'R5 bounded network profile is not implemented'
    spec = importlib.util.spec_from_file_location('r5_networks_test', path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def state():
    image = 'sha256:' + 'b' * 64
    return dict(stack_project='owned', service_generation='r'+'b'*12, worker_image_id=image,
                network_profile=dict(profile='r5-explicit-ipam', generation='r'+'b'*12, image_digest=image))


def windows():
    return dict(routes=[dict(DestinationPrefix='0.0.0.0/0'), dict(DestinationPrefix='192.168.88.0/24')],
                addresses=[dict(IPAddress='192.168.88.99', PrefixLength=24)])


def network(name='other', subnet='172.18.0.0/16', internal=False, project='other', logical='default'):
    return dict(Name=name, Id='a'*64, Driver='bridge', Scope='local', Internal=internal,
                Labels={'com.docker.compose.project':project, 'com.docker.compose.network':logical},
                IPAM=dict(Driver='default', Config=[dict(Subnet=subnet, Gateway=subnet.split('/')[0][:-1]+'1')]))


def test_fixed_profile_and_no_profile_preserve_original_behavior(tmp_path):
    m=module();s=state();before=copy.deepcopy(s)
    assert m.validate_profile(s,s['worker_image_id']) is True
    config=m.check_snapshot(s,'owned-r'+'b'*12,[network()],windows())
    assert s==before and set(config)=={'default','pdf-internal'}
    assert config['default']['ipam']['config']==[dict(subnet='10.246.88.0/28',gateway='10.246.88.1')]
    assert config['pdf-internal']['internal'] is True
    assert config['pdf-internal']['ipam']['config']==[dict(subnet='10.246.85.0/28',gateway='10.246.85.1')]
    assert all('external' not in v and 'name' not in v for v in config.values())
    assert m.preflight({},'old','sha256:'+'c'*64,lambda *a,**k:pytest.fail('Docker called'),tmp_path,lambda *a:pytest.fail('Evidence written'))=={}

def test_r6_profile_uses_separate_subnets_and_keeps_r5_networks():
    m=module();s=state();s['network_profile']['profile']='r6-explicit-ipam'
    config=m.check_snapshot(s,'owned-r'+'b'*12,[network('retained-r5','10.246.88.0/28')],windows())
    assert config['default']['ipam']['config']==[dict(subnet='10.246.89.0/28',gateway='10.246.89.1')]
    assert config['pdf-internal']['internal'] is True
    assert config['pdf-internal']['ipam']['config']==[dict(subnet='10.246.86.0/28',gateway='10.246.86.1')]
    assert m.fixed_networks()['default']['ipam']['config'][0]['subnet']=='10.246.88.0/28'

def test_r6_profile_still_rejects_overlap_and_r5_image():
    m=module();s=state();s['network_profile']['profile']='r6-explicit-ipam'
    with pytest.raises(ValueError,match='overlap'):
        m.check_snapshot(s,'owned-r'+'b'*12,[network(subnet='10.246.86.0/28')],windows())
    image='sha256:b3f09e1f30ebdc41a4bb82dbc915058bdf0a6438ce4ddb691ab16f6fbb104695'
    s.update(worker_image_id=image,service_generation='rb3f09e1f30eb')
    s['network_profile'].update(image_digest=image,generation='rb3f09e1f30eb')
    with pytest.raises(ValueError):m.validate_profile(s,image)


@pytest.mark.parametrize('change',[
    lambda s:s.update(network_profile=None),
    lambda s:s['network_profile'].update(extra=True),
    lambda s:s['network_profile'].update(subnet='10.0.0.0/8'),
    lambda s:s['network_profile'].update(profile='custom'),
    lambda s:s['network_profile'].update(generation='r'+'c'*12),
    lambda s:s.update(worker_image_id='sha256:'+'c'*64),
    lambda s:s.update(service_generation=''),
    lambda s:s.update(service_generation='ra5dcf87b42fc',worker_image_id='sha256:a5dcf87b42fc'+'a'*52,
                        network_profile=dict(profile='r5-explicit-ipam',generation='ra5dcf87b42fc',image_digest='sha256:a5dcf87b42fc'+'a'*52)),
])
def test_profile_rejects_foreign_or_retained_identity(change):
    m=module();s=state();change(s)
    with pytest.raises(ValueError):m.validate_profile(s)


@pytest.mark.parametrize('subnet',['10.246.88.0/28','10.246.88.0/24','10.246.85.4/30'])
def test_docker_overlaps_fail_closed(subnet):
    with pytest.raises(ValueError):module().check_snapshot(state(),'owned-r'+'b'*12,[network(subnet=subnet)],windows())


@pytest.mark.parametrize('where,value',[('routes',dict(DestinationPrefix='10.246.85.3/32')),
    ('routes',dict(DestinationPrefix='10.246.0.0/16')),('addresses',dict(IPAddress='10.246.88.12',PrefixLength=24))])
def test_windows_routes_and_interface_ranges_reject_overlap(where,value):
    w=windows();w[where].append(value)
    with pytest.raises(ValueError):module().check_snapshot(state(),'owned-r'+'b'*12,[network()],w)


def test_exact_owned_networks_are_idempotent_but_foreign_attributes_rejected():
    m=module();project='owned-r'+'b'*12
    rows=[network(project+'_'+logical,subnet,internal,project,logical) for logical,subnet,internal in
          [('default','10.246.88.0/28',False),('pdf-internal','10.246.85.0/28',True)]]
    rows[1]['Id']='c'*64
    assert m.check_snapshot(state(),project,rows,windows())
    for target,field,value in [(0,'Driver','overlay'),(1,'Internal',False),(0,'Labels',{}),
                               (0,'Name','foreign'),(0,'IPAM',dict(Driver='default',Config=[dict(Subnet='10.246.88.0/28',Gateway='10.246.88.2')]))]:
        changed=copy.deepcopy(rows);changed[target][field]=value
        with pytest.raises(ValueError):m.check_snapshot(state(),project,changed,windows())


@pytest.mark.parametrize('rows,w',[(None,windows()),([],windows()),([{'Name':'bad'}],windows()),
    ([network()],{}),([network()],dict(routes=[],addresses=[])),
    ([network()],dict(routes=[dict(DestinationPrefix='bad')],addresses=[]))])
def test_incomplete_inventory_fails_closed(rows,w):
    with pytest.raises(ValueError):module().check_snapshot(state(),'owned-r'+'b'*12,rows,w)


def test_preflight_records_timestamp_and_rejects_before_override_on_conflict(monkeypatch,tmp_path):
    m=module();s=state();calls=[];saved=[]
    def docker(args,**kwargs):
        calls.append(args)
        return 'a'*64+'\n' if args[:2]==['network','ls'] else json.dumps([network(subnet='10.246.88.0/24')])
    monkeypatch.setattr(m,'windows_snapshot',windows)
    with pytest.raises(ValueError):m.preflight(s,'owned-r'+'b'*12,s['worker_image_id'],docker,tmp_path,lambda p,v:saved.append((p,json.loads(v))))
    assert len(saved)==1 and saved[0][1]['status']=='failed' and saved[0][1]['captured_utc']
    assert saved[0][0].parent==tmp_path
    assert all(args[0]=='network' and args[1] in ('ls','inspect') for args in calls)


def test_inspect_must_cover_every_listed_network(monkeypatch,tmp_path):
    m=module();s=state();saved=[]
    monkeypatch.setattr(m,'windows_snapshot',windows)
    def docker(args,**kwargs):return 'a'*64+'\n'+'c'*64 if args[1]=='ls' else json.dumps([network()])
    with pytest.raises(ValueError):m.preflight(s,'owned-r'+'b'*12,s['worker_image_id'],docker,tmp_path,lambda p,v:saved.append(json.loads(v)))
    assert saved[0]['status']=='failed'


@pytest.mark.parametrize('generation',['r2149bab47a00','raf5cf7e2e2cb','ra5dcf87b42fc'])
def test_all_retained_generations_are_rejected(generation):
    s=state();image='sha256:'+generation[1:]+'a'*52
    s.update(service_generation=generation,worker_image_id=image)
    s['network_profile'].update(generation=generation,image_digest=image)
    with pytest.raises(ValueError):module().validate_profile(s)


def test_actual_image_must_match_profile_and_query_failures_are_recorded(monkeypatch,tmp_path):
    m=module();s=state();saved=[]
    with pytest.raises(ValueError):m.validate_profile(s,'sha256:'+'c'*64)
    def failed(*args,**kwargs):raise RuntimeError('inventory unavailable')
    monkeypatch.setattr(m,'windows_snapshot',lambda:pytest.fail('Windows queried after Docker failure'))
    with pytest.raises(RuntimeError):m.preflight(s,'owned-r'+'b'*12,s['worker_image_id'],failed,tmp_path,lambda p,v:saved.append(json.loads(v)))
    assert saved[0]['status']=='failed' and 'inventory unavailable' in saved[0]['error']


def test_foreign_project_with_same_image_suffix_is_rejected():
    with pytest.raises(ValueError):module().check_snapshot(state(),'foreign-r'+'b'*12,[network()],windows())


def test_success_evidence_and_builtin_no_subnet_networks(monkeypatch,tmp_path):
    m=module();s=state();saved=[]
    rows=[network(),dict(Name='host',Id='c'*64,Driver='host',Scope='local',Internal=False,Labels={},IPAM={'Config':None})]
    def docker(args,**kwargs):return 'a'*64+'\n'+'c'*64 if args[1]=='ls' else json.dumps(rows)
    monkeypatch.setattr(m,'windows_snapshot',windows)
    config=m.preflight(s,'owned-r'+'b'*12,s['worker_image_id'],docker,tmp_path,lambda p,v:saved.append(json.loads(v)))
    assert saved[0]['status']=='verified' and saved[0]['networks_override']==config


def test_workers_network_failure_precedes_compose_write_and_up(monkeypatch,tmp_path):
    from test_cr_b05_runner import runner, state as runner_state
    from types import SimpleNamespace
    m=runner();s=runner_state(m);s.update({k:v for k,v in state().items() if k!='stack_project'},clone_status='verified')
    for key in ('staging','research_staging','bio_staging'):s[key]=str(tmp_path/key)
    monkeypatch.setattr(m,'read_state',lambda:s)
    monkeypatch.setattr(m,'configure',lambda _:None)
    monkeypatch.setattr(m,'probe',lambda:{'available':True})
    from app.domain.bioinformatics import analysis_settings
    from app.domain.bio_insights import settings
    monkeypatch.setattr(analysis_settings,'runtime_identity',lambda:{'available':True})
    monkeypatch.setattr(settings,'quantitative_runtime_identity',lambda:{'available':True})
    for name in ('GATE','BIO_GATE'):
        path=tmp_path/(name+'.json');path.write_text(json.dumps(dict(image_digest=s['worker_image_id'])))
        monkeypatch.setattr(m,name,path)
    monkeypatch.setenv('PAPERASSIST_BIO_RUNTIME_MANIFEST',str(tmp_path/'BIO_GATE.json'))
    monkeypatch.setattr(m.worker_stack,'docker',lambda args,**kw:s['worker_image_id'] if args[0]=='image' else '8000000' if '64m' in args else 'same-source')
    monkeypatch.setattr(m,'source_digest',lambda:'same-source')
    monkeypatch.setattr(m.worker_stack,'prepare',lambda *a,**kw:SimpleNamespace(project=s['stack_project']+'-'+s['service_generation']))
    monkeypatch.setattr(m,'active_stack',lambda _,stack:stack)
    monkeypatch.setattr(m.worker_stack,'owned_containers',lambda _:[])
    monkeypatch.setattr(m,'ROOT',tmp_path)
    b04=tmp_path/'script/.runtime/client-requirements-b04';b04.mkdir(parents=True)
    (b04/'state.json').write_text(json.dumps(dict(pdf_image_id='sha256:'+'d'*64)))
    writes=[];ups=[]
    monkeypatch.setattr(m.worker_stack,'private_write',lambda *args:writes.append(args))
    monkeypatch.setattr(m,'compose',lambda *args,**kwargs:ups.append(args))
    def conflict(*args):raise ValueError('R5 subnet overlaps Windows route')
    monkeypatch.setattr(m.cr_b05_networks,'preflight',conflict)
    with pytest.raises(ValueError,match='overlaps'):m.workers()
    assert not writes and not ups
