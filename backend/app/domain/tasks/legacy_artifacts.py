"""Claim only an artifact proven to belong to this exact original response."""
import hashlib
import json
import re
from urllib.parse import quote

from app.domain.tasks.legacy import job_data


def _json(value):
    result = json.loads(value)
    if not isinstance(result, dict):
        raise ValueError('Invalid object.')
    return result


def _bound_source(row, job):
    result = _json(row['result_json'])
    if (job['id'] != row['id'] or job['analysis_run_id'] != row['analysis_run_id']
            or result['id'] != row['analysis_run_id'] or result['file_id'] != row['file_id']
            or result['setup_revision'] != row['setup_revision']
            or result['source_sha256'] != row['file_sha256']):
        raise ValueError('Source mismatch.')
    return result


def _figure_matches(figure_row, figure, row, result, renderer):
    return (figure['id'] == figure_row['id'] and figure_row['analysis_run_id'] == row['analysis_run_id']
        and figure['analysis_run_id'] == row['analysis_run_id'] and figure['file_id'] == row['file_id']
        and figure['source_sha256'] == result['source_sha256'] and figure['setup_revision'] == row['setup_revision']
        and figure['engine']['id'] == renderer and figure_row['renderer_version'] == renderer
        and figure['verification']['status'] == 'matched'
        and bool(re.fullmatch(r'[0-9a-f]{64}', figure['sha256'])))


def exact_legacy_artifact(db, row):
    job = job_data(row)
    if job.get('status') != 'completed':
        return None
    try:
        result = _bound_source(row, job)
        response_id = job['response_id']
        if not isinstance(response_id, str) or not response_id.strip():
            return None
        if row['kind'] == 'plot':
            candidate = db.execute('SELECT * FROM figures WHERE analysis_run_id=%s AND renderer_version=%s',
                (row['analysis_run_id'], row['renderer_version'])).fetchone()
            if not candidate:
                return None
            figure = _json(candidate['figure_json'])
            container = job['container_id']
            if (not isinstance(container, str) or not container.strip()
                    or not _figure_matches(candidate, figure, row, result, row['renderer_version'])
                    or figure['provenance']['response_id'] != response_id
                    or figure['provenance']['container_id'] != container
                    or job['payload']['analysis_run_id'] != result['id']
                    or job['payload']['source_sha256'] != result['source_sha256']
                    or job['expected']['analysis_run_id'] != result['id']
                    or job['expected']['source_sha256'] != result['source_sha256']
                    or any(figure.get(key) != value for key, value in job['expected'].items())):
                return None
            # Only complete safe public display material can be claimed.
            if not isinstance(figure['title'], str) or not isinstance(figure['caption'], str):
                return None
            return figure
        from app.domain.explanation_content import build_payload
        from app.domain.boxplot import RENDERER
        figure_row = db.execute('SELECT * FROM figures WHERE id=%s AND analysis_run_id=%s',
            (row['figure_id'], row['analysis_run_id'])).fetchone()
        if not figure_row:
            return None
        figure = _json(figure_row['figure_json'])
        if not _figure_matches(figure_row, figure, row, result, RENDERER) or job['figure_id'] != figure['id']:
            return None
        payload = build_payload(result, figure)
        if payload != job['payload']:
            return None
        candidate = db.execute('SELECT * FROM explanations WHERE figure_id=%s AND engine_version=%s',
            (row['figure_id'], row['engine_version'])).fetchone()
        if not candidate:
            return None
        value = _json(candidate['explanation_json'])
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, allow_nan=False,
            sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
        if (candidate['analysis_run_id'] != row['analysis_run_id'] or candidate['figure_id'] != figure['id']
                or value['id'] != candidate['id'] or value['analysis_run_id'] != result['id']
                or value['figure_id'] != figure['id'] or value['figure_sha256'] != figure['sha256']
                or value['source_sha256'] != result['source_sha256'] or value['setup_revision'] != row['setup_revision']
                or value['engine']['id'] != row['engine_version']
                or value['provenance']['response_id'] != response_id
                or value['provenance']['input_sha256'] != digest):
            return None
        if (not isinstance(value['sections'], list) or not value['sections']
                or any(not isinstance(section[key], str) for section in value['sections'] for key in ('key', 'title', 'text'))
                or not isinstance(value['limitations'], list) or any(not isinstance(item, str) for item in value['limitations'])):
            return None
        return value
    except (KeyError, TypeError, ValueError):
        # Missing/corrupt attribution evidence means unconfirmed, never latest.
        return None


def legacy_artifacts(row, artifact):
    result = {'figure': None, 'explanation': None, 'report': None}
    if artifact is None:
        return result
    if row['kind'] == 'plot':
        prefix = '/api/v1/projects/{}/files/{}/analysis-runs/{}'.format(*[
            quote(row[key], safe='') for key in ('project_id', 'file_id', 'analysis_run_id')])
        result['figure'] = {key: artifact[key] for key in ('title', 'caption')}
        result['figure']['download_url'] = prefix + '/figures/' + quote(artifact['id'], safe='') + '/download'
    else:
        result['explanation'] = {'sections': [{key: section[key] for key in ('key', 'title', 'text')}
            for section in artifact['sections']], 'limitations': artifact['limitations']}
    return result
