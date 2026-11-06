"""Real publication/read/download with synthetic worker leaves, not numerical evidence."""
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from tests.api.test_projects import client, create_project
from tests.integration.test_bio_analysis_wait import create, run, confirm, payload_engine


def figure_engine(*, legacy_pdf=False, missing=None):
    def engine(payload, output, mode):
        result = payload_engine(payload, output, mode)
        contents = dict(png=('png', b'synthetic PNG fixture'), data=('json', b'{"values":[1]}'),
                        manifest=('json', json.dumps(dict(config=dict(kind='pca', panel='scores'),
                                                          dpi=150, width_inches=6, height_inches=5)).encode()))
        if legacy_pdf:
            contents['pdf'] = ('pdf', b'%PDF-1.4 retained legacy fixture')
        for suffix, (fmt, content) in contents.items():
            if suffix == missing:
                continue
            key = 'pca_' + suffix
            path = Path(output) / (key + '.' + fmt)
            path.write_bytes(content)
            result['outputs'].append(dict(key=key, path=str(path), role='figure_' + suffix, format=fmt,
                                          size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest()))
        return result
    return engine


def compute(client, monkeypatch, tmp_path, engine):
    base, created, staging, _ = create(client, monkeypatch, tmp_path)
    assert run(created['task'], staging)['status'] == 'waiting_confirmation'
    queued = confirm(client, base, created, client.get(base + '/bio-analysis-runs/' + created['id']).json())
    assert queued.status_code == 202, queued.text
    return base, run(queued.json(), staging, engine)


@pytest.mark.parametrize('legacy_pdf', [False, True])
def test_default_figure_current_png_contract_and_retained_pdf_download(client, monkeypatch, tmp_path, legacy_pdf):
    base, done = compute(client, monkeypatch, tmp_path, figure_engine(legacy_pdf=legacy_pdf))
    assert done['status'] == 'succeeded', done
    response = client.get(base + '/bio-processed-datasets/' + done['result_bio_processed_dataset_version_id'])
    assert response.status_code == 200, response.text
    figure, = response.json()['figures']
    detail = client.get(base + '/bio-figures/' + figure['id'])
    assert detail.status_code == 200 and detail.json() == figure
    assert {m['key'] for m in figure['members']} == {'pca_png', 'pca_data', 'pca_manifest'}
    if legacy_pdf:
        # Simulate a member registered before PDF retirement; new publication above never registers it.
        from app.db.database import database_connection
        with database_connection(write=True) as db:
            db.execute('''INSERT INTO bio_figure_members
                (id,figure_version_id,project_id,created_by,created_at,schema_version,key,format,size_bytes,sha256,storage_object_id)
                SELECT %s,%s,project_id,created_by,created_at,schema_version,key,format,size_bytes,sha256,storage_object_id
                FROM bio_analysis_artifacts WHERE processed_dataset_version_id=%s AND key='pca_pdf' ''',
                (str(uuid4()),figure['id'],done['result_bio_processed_dataset_version_id']))
        figure = client.get(base + '/bio-figures/' + figure['id']).json()
        assert any(m['format'] == 'pdf' for m in figure['members'])
    other_base = '/api/v1/projects/' + create_project(client)['id']
    assert client.get(other_base + '/bio-figures/' + figure['id']).status_code == 404
    for member in figure['members']:
        download = client.get(member['download_url'])
        assert download.status_code == 200 and len(download.content) == member['size_bytes']
        assert hashlib.sha256(download.content).hexdigest() == member['sha256']
        assert client.get(member['download_url'].replace(base, other_base)).status_code == 404
        if member['format'] == 'pdf':
            assert download.content == b'%PDF-1.4 retained legacy fixture'
    assert client.get(base + '/bio-figures/' + figure['id'] + '/members/' + str(uuid4()) + '/download').status_code == 404


@pytest.mark.parametrize('missing', ['data', 'manifest'])
def test_default_figure_rejects_missing_required_companion(client, monkeypatch, tmp_path, missing):
    from app.db.database import database_connection
    _, done = compute(client, monkeypatch, tmp_path, figure_engine(missing=missing))
    assert done['status'] == 'failed' and done['error_code'] == 'bio_output_invalid', done
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM bio_processed_dataset_versions').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM bio_figure_members').fetchone()['n'] == 0
