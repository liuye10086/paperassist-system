"""Sealed-code TestClient reads with real sessions, byte checks and a socket guard."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
import zipfile

from app.maintenance import backup_manifest as manifest
from app.maintenance import recovery_drill as drill


def response_digest(value, kind='json'):
    if kind == 'storage':
        value = {key: item for key, item in value.items() if key not in {'disk', 'reconciled_at'}}
    return manifest.digest(value)


def install_network_guard(port):
    observations = dict(blocked_connections=0, mechanism='Python socket audit guard allows 127.0.0.1/::1; libpq database identity and port validated separately', database_port=port)
    def guard(event, args):
        if event == 'socket.connect':
            address = args[1]
            if not (isinstance(address, tuple) and len(address) >= 2 and address[0] in ('127.0.0.1', '::1')):
                observations['blocked_connections'] += 1
                raise drill.DrillError('network_connection_forbidden')
    sys.addaudithook(guard)
    return observations


def safe_url(url):
    parsed = urlsplit(url)
    drill.require(url.startswith('/api/v1/') and not parsed.scheme and not parsed.netloc and not parsed.fragment
                  and '\\' not in url and '..' not in url, 'unsafe_api_url')
    return url


def verify(expected, credentials, downloads):
    from fastapi.testclient import TestClient
    from app.main import app
    downloads.mkdir(exist_ok=False)
    requests, byte_receipts, identities = [], [], []
    def get(client, url, status=200):
        response = client.get(safe_url(url))
        drill.require(response.status_code == status, 'http_status_mismatch')
        requests.append(dict(request_id=response.headers.get('x-request-id'), method='GET', status=status))
        return response
    with TestClient(app) as anonymous:
        get(anonymous, expected['projects'][0]['url'], 401)
        get(anonymous, expected['downloads'][0]['download_url'], 401)
    for alias, account in expected['accounts'].items():
        with TestClient(app) as client:
            client.headers.update({'X-PaperAssist-Client': 'web', 'Origin': 'http://testserver'})
            login = client.post('/api/v1/auth/login', json=credentials[alias])
            drill.require(login.status_code == 200, 'restored_login_failed')
            requests.append(dict(request_id=login.headers.get('x-request-id'), method='POST', status=200))
            client.headers['X-CSRF-Token'] = login.json()['csrf_token']
            me = get(client, '/api/v1/auth/me').json()['user']
            drill.require(me['id'] == account['id'], 'restored_identity_mismatch')
            identities.append(dict(alias=alias, id=me['id']))
            for item in expected['reads']:
                if item['owner_alias'] == alias:
                    value = get(client, item['url']).json()
                    drill.require(response_digest(value, item.get('kind', 'json')) == item['sha256'], 'api_value_mismatch')
            for project in expected['projects']:
                if project['owner_alias'] != alias:
                    get(client, project['url'], 404)
            for index, item in enumerate(expected['downloads']):
                if item['owner_alias'] != alias:
                    get(client, item['download_url'], 404)
                    continue
                metadata = get(client, item['metadata_url']).json()
                if item['kind'] != 'original':
                    drill.require(metadata['download_url'] == item['download_url'] and metadata['sha256'] == item['sha256']
                                  and metadata['size_bytes'] == item['size_bytes'], 'download_metadata_mismatch')
                content = get(client, item['download_url']).content
                digest = hashlib.sha256(content).hexdigest()
                drill.require(len(content) == item['size_bytes'] and digest == item['sha256'], 'download_bytes_mismatch')
                if item['kind'] == 'pdf':
                    drill.require(content.startswith(b'%PDF-'), 'invalid_pdf')
                else:
                    with zipfile.ZipFile(io.BytesIO(content)) as archive:
                        drill.require('word/document.xml' in archive.namelist(), 'invalid_docx')
                target = downloads / (str(index) + ('.pdf' if item['kind'] == 'pdf' else '.docx'))
                with target.open('xb') as stream:
                    stream.write(content)
                drill.require(drill.sha(target) == digest, 'saved_download_mismatch')
                byte_receipts.append(dict(kind=item['kind'], project_id=item['project_id'], bytes=len(content), sha256=digest))
    return dict(status='passed', identities=identities, requests=requests, downloads=byte_receipts,
                authenticated=True, cross_owner_denied=True, source_api_reads=len(expected['reads']), workers_started=0)


def main():
    parser = argparse.ArgumentParser()
    for name in ('expected', 'credentials', 'output', 'downloads'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    from app.db.database import get_database_config
    config = get_database_config()
    drill.require(config.environment == 'test' and config.url.host == '127.0.0.1' and config.url.port != 5432, 'unsafe_http_database')
    guard = install_network_guard(config.url.port)
    try:
        result = verify(manifest.read_json(args.expected), manifest.read_json(args.credentials), args.downloads)
        drill.require(guard['blocked_connections'] == 0, 'unexpected_network_attempt')
        result['network'] = guard
        drill.write_json(args.output, result)
        return 0
    except Exception as exc:
        drill.write_json(args.output, dict(status='failed', failure=str(exc) if isinstance(exc, drill.DrillError) else 'http_verification_failed', network=guard))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
