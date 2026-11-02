"""Fixed B05 generation networks and read-only preflight; never manages Docker resources."""
from datetime import datetime, timezone
import ipaddress
import json
import re
import subprocess
from uuid import uuid4

RETAINED_GENERATIONS = {'', 'r2149bab47a00', 'raf5cf7e2e2cb', 'ra5dcf87b42fc'}
SUBNETS = {'default': ('10.246.88.0/28', '10.246.88.1', False),
           'pdf-internal': ('10.246.85.0/28', '10.246.85.1', True)}
PROFILES = {'r5-explicit-ipam': SUBNETS,
            'r6-explicit-ipam': {'default': ('10.246.89.0/28', '10.246.89.1', False),
                                 'pdf-internal': ('10.246.86.0/28', '10.246.86.1', True)},
            'sub2-explicit-ipam': {'default': ('10.246.90.0/28', '10.246.90.1', False),
                                   'pdf-internal': ('10.246.87.0/28', '10.246.87.1', True)},
            'sub2-refresh-ipam': {'default': ('10.246.91.0/28', '10.246.91.1', False),
                                 'pdf-internal': ('10.246.92.0/28', '10.246.92.1', True)},
            'sub3-explicit-ipam': {'default': ('10.246.93.0/28', '10.246.93.1', False),
                                   'pdf-internal': ('10.246.94.0/28', '10.246.94.1', True)},
            'sub3-identity-ipam': {'default': ('10.246.95.0/28', '10.246.95.1', False),
                                   'pdf-internal': ('10.246.96.0/28', '10.246.96.1', True)},
            'sub4-explicit-ipam': {'default': ('10.246.97.0/28', '10.246.97.1', False),
                                   'pdf-internal': ('10.246.98.0/28', '10.246.98.1', True)}}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_profile(state, image_id=None):
    if 'network_profile' not in state:
        return False
    profile = state['network_profile']
    require(isinstance(profile, dict) and set(profile) == {'profile', 'generation', 'image_digest'}, 'Invalid R5 network profile fields')
    image = profile['image_digest']; generation = profile['generation']
    require(isinstance(profile['profile'],str) and profile['profile'] in PROFILES and isinstance(image, str)
            and re.fullmatch(r'sha256:[a-f0-9]{64}', image), 'Invalid R5 immutable network image')
    require(profile['profile'] != 'r6-explicit-ipam' or generation != 'rb3f09e1f30eb', 'R6 profile cannot replace the retained R5 generation')
    require(isinstance(generation, str) and generation not in RETAINED_GENERATIONS
            and generation == 'r' + image[7:19] and generation == state.get('service_generation')
            and image == state.get('worker_image_id') and (image_id is None or image == image_id), 'R5 network generation/image differs or is retained')
    return True


def fixed_networks(profile='r5-explicit-ipam'):
    return {name: dict(driver='bridge', internal=internal, ipam=dict(driver='default', config=[dict(subnet=subnet, gateway=gateway)]))
            for name, (subnet, gateway, internal) in PROFILES[profile].items()}


def check_snapshot(state, project, networks, windows):
    require(validate_profile(state), 'R5 profile required')
    subnets=PROFILES[state['network_profile']['profile']]
    require(isinstance(state.get('stack_project'), str)
            and project == state['stack_project'] + '-' + state['service_generation'], 'R5 network project differs')
    require(isinstance(networks, list) and networks, 'Docker network inventory is missing')
    require(isinstance(windows, dict) and set(windows) == {'routes', 'addresses'}
            and isinstance(windows['routes'], list) and windows['routes']
            and isinstance(windows['addresses'], list) and windows['addresses'], 'Windows IPv4 inventory is missing')
    names = set(); ids = set()
    for network in networks:
        require(isinstance(network, dict) and all(k in network for k in ('Name','Id','Driver','Scope','Internal','Labels','IPAM')), 'Incomplete Docker network inspection')
        name = network['Name']; identity = network['Id']; ipam = network['IPAM']
        require(isinstance(name, str) and name and name not in names and isinstance(identity, str)
                and re.fullmatch(r'[a-f0-9]{64}', identity) and identity not in ids, 'Duplicate or invalid Docker network identity')
        names.add(name); ids.add(identity)
        require(isinstance(ipam, dict) and 'Config' in ipam and isinstance(network['Internal'], bool), 'Incomplete Docker IPAM')
        configs = ipam['Config']
        require(configs is None or isinstance(configs, list), 'Invalid Docker IPAM config')
        require(network['Driver'] in ('host','null') or bool(configs), 'Docker subnet inventory is missing')
        owned = next((key for key in subnets if name == project + '_' + key), None)
        if owned:
            subnet, gateway, internal = subnets[owned]
            labels = network['Labels']
            require(isinstance(labels, dict) and labels.get('com.docker.compose.project') == project
                    and labels.get('com.docker.compose.network') == owned and network['Driver'] == 'bridge'
                    and network['Scope'] == 'local' and network['Internal'] is internal
                    and ipam.get('Driver') == 'default' and configs == [dict(Subnet=subnet, Gateway=gateway)], 'Existing R5 network ownership/configuration differs')
        for config in configs or []:
            require(isinstance(config, dict) and isinstance(config.get('Subnet'), str), 'Missing Docker subnet')
            observed = ipaddress.ip_network(config['Subnet'])
            if observed.version != 4:
                continue
            for logical, (subnet, _, _) in subnets.items():
                require(not observed.overlaps(ipaddress.ip_network(subnet)) or owned == logical, 'R5 subnet overlaps retained/foreign Docker network: ' + name)
    for route in windows['routes']:
        require(isinstance(route, dict) and isinstance(route.get('DestinationPrefix'), str), 'Invalid Windows IPv4 route')
        observed = ipaddress.ip_network(route['DestinationPrefix'], strict=False)
        require(observed.version == 4, 'Unexpected Windows route family')
        if observed.prefixlen:
            require(not any(observed.overlaps(ipaddress.ip_network(s)) for s, _, _ in subnets.values()), 'R5 subnet overlaps Windows route')
    for address in windows['addresses']:
        require(isinstance(address, dict) and isinstance(address.get('IPAddress'), str)
                and type(address.get('PrefixLength')) is int, 'Invalid Windows IPv4 address')
        observed = ipaddress.ip_network(address['IPAddress'] + '/' + str(address['PrefixLength']), strict=False)
        require(observed.version == 4 and not any(observed.overlaps(ipaddress.ip_network(s)) for s, _, _ in subnets.values()), 'R5 subnet overlaps Windows interface')
    return fixed_networks(state['network_profile']['profile'])


def windows_snapshot():
    command = "$ErrorActionPreference='Stop';[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new();@{routes=@(Get-NetRoute -AddressFamily IPv4 | Select-Object DestinationPrefix,NextHop,InterfaceAlias);addresses=@(Get-NetIPAddress -AddressFamily IPv4 | Select-Object IPAddress,PrefixLength,InterfaceAlias)} | ConvertTo-Json -Depth 4 -Compress"
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                            capture_output=True, text=True, encoding='utf-8-sig', errors='strict', check=True, timeout=30)
    return json.loads(result.stdout)


def preflight(state, project, image_id, docker, runtime, write):
    if not validate_profile(state, image_id):
        return {}
    captured = datetime.now(timezone.utc)
    evidence = dict(captured_utc=captured.isoformat(), project=project, profile=state['network_profile'],
                    read_only=True, status='checking')
    path = runtime / ('network-preflight-' + state['service_generation'] + '-' + captured.strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid4().hex[:8] + '.json')
    try:
        ids = docker(['network', 'ls', '--no-trunc', '--format', '{{.ID}}'], timeout=30).split()
        require(ids and len(ids) == len(set(ids)) and all(re.fullmatch(r'[a-f0-9]{64}', value) for value in ids), 'Incomplete Docker network list')
        evidence['networks'] = json.loads(docker(['network', 'inspect', *ids], timeout=30))
        require(isinstance(evidence['networks'], list)
                and all(isinstance(n, dict) for n in evidence['networks'])
                and {n.get('Id') for n in evidence['networks']} == set(ids), 'Docker inspect does not cover the complete network list')
        evidence['windows'] = windows_snapshot()
        config = check_snapshot(state, project, evidence['networks'], evidence['windows'])
        evidence.update(status='verified', networks_override=config)
    except Exception as exc:
        evidence.update(status='failed', error=type(exc).__name__ + ': ' + str(exc))
        write(path, json.dumps(evidence, ensure_ascii=False, indent=2))
        raise
    write(path, json.dumps(evidence, ensure_ascii=False, indent=2))
    return config
