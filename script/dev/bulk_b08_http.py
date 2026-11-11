"""Drive the real Bulk upload, QC and model APIs from an isolated acceptance harness."""
from __future__ import annotations

import hashlib
from pathlib import Path
import time
from uuid import uuid4

import httpx


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checked(response, expected=200):
    if response.status_code == expected:
        return response
    response.read()
    try:
        detail = response.json().get('detail', {})
        code = detail.get('code') if isinstance(detail, dict) else 'validation_error'
    except (AttributeError, ValueError):
        code = 'non_json_response'
    raise RuntimeError((response.request.method, response.request.url.path, response.status_code, code))


class BulkHttp:
    def __init__(self, url, origin):
        self.client = httpx.Client(base_url=url, headers={'Origin': origin, 'X-PaperAssist-Client': 'web'},
                                   timeout=300.0, trust_env=False)

    def login(self, email, password):
        response = self.post('/api/v1/auth/login', dict(email=email, password=password))
        self.client.headers['X-CSRF-Token'] = response['csrf_token']

    def get(self, path, **params):
        return checked(self.client.get(path, params=params)).json()

    def post(self, path, body, expected=200, key=None):
        headers = {'Idempotency-Key': key} if key else {}
        return checked(self.client.post(path, json=body, headers=headers), expected).json()

    def download(self, path, destination, *, body=None):
        method = 'GET' if body is None else 'POST'
        with self.client.stream(method, path, json=body) as response:
            checked(response)
            with destination.open('wb') as stream:
                for chunk in response.iter_bytes():
                    stream.write(chunk)
            return dict(response.headers)

    def wait(self, path, expected, *, timeout=1680, on_status=None):
        deadline = time.monotonic() + timeout
        prior = None
        while time.monotonic() < deadline:
            result = self.get(path)
            task = result.get('task', result)
            status = task['status']
            if status != prior and on_status:
                on_status(task)
            if status == expected:
                return result
            if status in ('failed', 'cancelled', 'succeeded', 'waiting_confirmation'):
                raise RuntimeError((path, status, task.get('error_code'), task.get('id')))
            prior = status
            time.sleep(0.35)
        raise TimeoutError((path, expected, prior))

    def create_project(self, name):
        project = self.post('/api/v1/projects', dict(name=name, research_topic=name, project_type='research',
                            delivery_kinds=['analysis', 'sci_draft']), 201, str(uuid4()))
        return '/api/v1/projects/' + project['id']

    def upload_counts(self, project, matrix, samples):
        paths = [matrix, samples]
        items = [dict(client_id=str(uuid4()), filename=path.name, size_bytes=path.stat().st_size) for path in paths]
        batch = self.post(project + '/bio-upload-batches', dict(items=items), 201, str(uuid4()))
        files = []
        for path, item in zip(paths, items):
            url = project + f"/bio-upload-batches/{batch['id']}/items/{item['client_id']}"
            with path.open('rb') as stream:
                result = checked(self.client.post(url, files={'file': (path.name, stream, 'text/plain')}), 202).json()
            files.append(result['file_id'])
        return files

    def begin_import(self, project, files, sample_ids, mapping, scale, *, matrix_format='tsv',
                     sample_format='tsv', feature_id_column='feature_id', name='Bulk counts'):
        matrix, samples = files
        body = dict(workflow_version='bio_import_v3', file_ids=files, assay='bulk_rna_counts', name=name,
                    expected_dataset_revision=0,
                    tables=[dict(file_id=matrix, role='quantitative_matrix', format=matrix_format),
                            dict(file_id=samples, role='sample_metadata', format=sample_format)],
                    feature_id_column=feature_id_column, sample_columns=sample_ids, sample_metadata_mapping=mapping,
                    scale=dict(kind='raw_counts', unit='counts', input_origin='bulk_rna', **scale))
        result = self.post(project + '/bio-imports', body, 202, str(uuid4()))
        return project + '/bio-imports/' + result['id']

    def finish_import(self, path, pending):
        return self.post(path + '/confirm', dict(task_revision=pending['task']['revision'],
                         checkpoint_id=pending['checkpoint_id'], wait_id=pending['wait_id'],
                         candidate_sha256=pending['candidate']['sha256'],
                         expected_dataset_revision=pending['expected_dataset_revision']), 202, str(uuid4()))

    def save_design(self, project, sample_conditions):
        conditions = {name: 'condition_' + str(index) for index, name in enumerate(dict.fromkeys(sample_conditions.values()))}
        design = dict(schema_version=1, experiments=[dict(id='bulk', data_type='bulk_rna')],
                      groups=[dict(id=key, experiment_id='bulk', name=name) for name, key in conditions.items()],
                      samples=[dict(id=sid, experiment_id='bulk', group_id=conditions[group])
                               for sid, group in sample_conditions.items()])
        response = self.post(project + '/research-designs', dict(expected_revision=1, operation='save',
                             material_refs=[], content=design), 201, str(uuid4()))
        return response['version']['id']

    def begin_qc(self, project, raw_source, design_version_id, *, params=None):
        if params is None:
            params = dict(normalization='vst', transform='none', scaling='none', pca_components=3,
                          seed=0, output_language='en')
        recipe = self.post(project + '/bio-analysis-setups', dict(recipe_code='tabular_quantitative_v1',
                           name='Bulk sample QC and VST', raw_source=raw_source, expected_revision=0,
                           design_version_id=design_version_id, params=params), 201, str(uuid4()))
        result = self.post(project + '/bio-analysis-runs', dict(raw_source=raw_source,
                           recipe_version_id=recipe['id'], expected_setup_revision=1), 202, str(uuid4()))
        return project + '/bio-analysis-runs/' + result['id']

    def finish_qc(self, path, pending):
        return self.post(path + '/confirm', dict(task_revision=pending['task']['revision'],
                         checkpoint_id=pending['checkpoint_id'], wait_id=pending['wait_id'],
                         candidate_sha256=pending['candidate']['sha256'], expected_setup_revision=1), 202, str(uuid4()))

    def confirm_model(self, project, processed, config, *, name='Bulk reviewed model'):
        source = dict(source_kind='bio_processed_dataset_version', source_id=processed['id'],
                      sha256=processed['manifest_sha256'], role='processed')
        body = dict(name=name, kind='comparison', decision='draft', expected_revision=0, sources=[source], config=config)
        path = project + '/bio-insight-plans'
        preview = self.post(path + '/preview', body)
        if not preview['executable']:
            raise RuntimeError(('Model preview blocked', preview.get('blockers')))
        plan = self.post(path, dict(body, decision='confirmed', reviewed_design_sha256=preview['reviewed_design_sha256']),
                         201, str(uuid4()))
        return preview, plan

    def submit_model(self, project, plan, key):
        body = dict(plan_version_id=plan['id'], expected_plan_revision=1, source_digest=plan['source_digest'])
        return self.post(project + '/bio-insight-runs', body, 202, key)
