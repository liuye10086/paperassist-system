"""Real isolated queue acceptance; no numerical stubs or external model calls."""
import argparse
import csv
import gzip
import hashlib
import io
import json
import re
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'script' / 'dev'))
import cr_b02_runner as control


class Verification:
    def __init__(self, state, phase, *, fresh=False, restart_at_qc=False):
        import httpx
        self.state, self.phase, self.restart_at_qc = state, phase, restart_at_qc
        pointer = control.RUNTIME / (phase + '-verification-current.json')
        if pointer.exists() and not fresh:
            self.progress_path = Path(json.loads(pointer.read_text())['progress'])
            self.progress = json.loads(self.progress_path.read_text(encoding='utf-8'))
            if self.progress['schema'] != state['schema']:
                raise RuntimeError('Retained verification belongs to another schema; use --fresh')
        else:
            directory = control.RUNTIME / 'verifications' / (phase + '-' + uuid4().hex)
            directory.mkdir(parents=True)
            control.worker_stack.protect_directory(directory)
            self.progress_path = directory / 'progress.json'
            self.progress = {'schema': state['schema'], 'phase': phase, 'actions': {},
                             'user_acceptance': 'pending', 'biological_validation': 'not_performed'}
            control.worker_stack.private_write(pointer, json.dumps({'progress': str(self.progress_path)}))
            self.save()
        credentials = json.loads((control.run_directory(state) / 'credentials.json').read_text(encoding='utf-8'))['review']
        self.client = httpx.Client(base_url=state['url'], timeout=300, trust_env=False,
            headers={'Origin': state['url'], 'X-PaperAssist-Client': 'web'})
        response = self.client.post('/api/v1/auth/login', json={k: credentials[k] for k in ('email', 'password')})
        self.check(response, 200)
        self.client.headers['X-CSRF-Token'] = response.json()['csrf_token']

    def save(self):
        control.worker_stack.private_write(self.progress_path, json.dumps(self.progress, ensure_ascii=False, indent=2) + '\n')

    @staticmethod
    def check(response, expected=200):
        if response.status_code != expected:
            try:
                code = response.json().get('detail', {}).get('code', 'unexpected_response')
            except (ValueError, AttributeError):
                code = 'unexpected_response'
            raise RuntimeError(f'HTTP {response.status_code}, expected {expected}: {code}')
        return response

    def get(self, path):
        return self.check(self.client.get(path)).json()

    def post(self, label, path, body, *, kind=None, lookup=None, expected=201):
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        entry = self.progress['actions'].get(label)
        if entry:
            if entry['digest'] != digest or entry['path'] != path:
                raise RuntimeError('Retained request body differs; preserve it and use an explicit --fresh verification')
            if entry.get('response') is not None:
                return entry['response']
            target = lookup or self.base + '/bio-requests/' + entry['key'] + '?kind=' + str(kind)
            response = self.client.get(target)
            if response.status_code != 200:
                raise RuntimeError('Unknown POST outcome retained; resolve the original request key before continuing')
            value = response.json()
            detail = {'recipe': '/bio-analysis-setups/{root_id}/recipes/{id}', 'map': '/bio-observation-maps/{root_id}/versions/{id}',
                'run': '/bio-analysis-runs/{id}', 'annotation': '/bio-annotation-sets/{root_id}/versions/{id}',
                'figure': '/bio-figures/{id}', 'import': '/bio-imports/{id}'}.get(kind)
            if detail:
                value = self.get(self.base + detail.format(**value))
            elif kind in ('confirmation', 'import_confirmation'):
                value = self.get('/api/v1/tasks/' + value['task_id'])
            entry['response'] = value
            self.save()
            return value
        key = 'b02-' + uuid4().hex
        entry = {'path': path, 'digest': digest, 'key': key, 'state': 'submitting'}
        self.progress['actions'][label] = entry
        self.save()
        response = self.client.post(path, json=body, headers={'Idempotency-Key': key})
        if response.status_code != expected:
            entry.update(state='rejected', http_status=response.status_code)
            self.save()
            self.check(response, expected)
        entry.update(state='returned', response=response.json())
        self.save()
        return entry['response']

    def wait(self, task, wanted):
        deadline = time.monotonic() + 1500
        previous = None
        while time.monotonic() < deadline:
            current = self.get('/api/v1/tasks/' + task['id'])
            if current['status'] != previous:
                print(json.dumps({'phase': self.phase, 'task_id': task['id'], 'status': current['status']}, ensure_ascii=False), flush=True)
                previous = current['status']
            if current['status'] == wanted:
                return current
            if current['status'] == 'failed':
                raise RuntimeError('Real queue task failed: ' + str(current['error_code']))
            time.sleep(.75)
        raise RuntimeError('Real queue wait timed out; task and runtime material retained')

    def upload(self, contents):
        descriptors = self.progress.get('upload_descriptors')
        if descriptors is None:
            descriptors = [dict(client_id=str(uuid4()), filename=name, size_bytes=len(content)) for name, content in contents]
            self.progress['upload_descriptors'] = descriptors
            self.save()
        if [(d['filename'], d['size_bytes']) for d in descriptors] != [(name, len(value)) for name, value in contents]:
            raise RuntimeError('Input identity changed; retained upload is not reused')
        batch = self.post('upload-batch', self.base + '/bio-upload-batches', {'items': descriptors})
        for descriptor, (name, content) in zip(descriptors, contents):
            current = self.get(self.base + '/bio-upload-batches/' + batch['id'])
            item = next(i for i in current['items'] if i['id'] == descriptor['client_id'])
            if not item['file_id']:
                response = self.client.post(self.base + '/bio-upload-batches/' + batch['id'] + '/items/' + item['id'],
                    files={'file': (name, content)})
                self.check(response, 202)
                item = response.json()
            file = next(file for file in self.get(self.base + '/files') if file['id'] == item['file_id'])
            if file['sha256'] != hashlib.sha256(content).hexdigest():
                raise RuntimeError('Original upload hash differs')
        return [i['file_id'] for i in self.get(self.base + '/bio-upload-batches/' + batch['id'])['items']]

    def import_raw(self, files, *, version2=False, original=None):
        label = 'import-v2' if version2 else 'import-v1'
        completed = self.progress.get(label)
        if completed and completed.get('result_source'):
            return completed['result_source']
        body = dict(file_ids=files, assay='visium', name='GSE262082 retained originals' if self.phase == 'gse' else 'Synthetic spatial original',
                    expected_dataset_revision=0)
        if version2:
            root = next(x for x in self.get(self.base + '/bio-datasets')['items'] if x['id'] == original['dataset_id'])
            body.update(dataset_id=root['id'], expected_dataset_revision=root['revision'],
                        matrix_representation='10x_h5', compare_alternate=True)
        imported = self.post(label, self.base + '/bio-imports', body, kind='import', expected=202)
        confirmation = self.progress['actions'].get(label + '-confirm', {})
        queued = confirmation.get('response')
        if queued is None:
            self.wait(imported['task'], 'waiting_confirmation')
            review = self.get(self.base + '/bio-imports/' + imported['id'])
            confirm = dict(task_revision=review['task']['revision'], checkpoint_id=review['checkpoint_id'], wait_id=review['wait_id'],
                           candidate_sha256=review['candidate']['sha256'], expected_dataset_revision=review['expected_dataset_revision'])
            queued = self.post(label + '-confirm', self.base + '/bio-imports/' + imported['id'] + '/confirm', confirm,
                               kind='import_confirmation', expected=202)
        self.wait(queued, 'succeeded')
        value = self.get(self.base + '/bio-imports/' + imported['id'])
        self.progress[label] = value
        self.save()
        return value['result_source']

    def run_analysis(self, raw_source, mapping, params, *, label='analysis'):
        completed = self.progress.get(label)
        if completed and completed.get('result'):
            return completed['result']
        recipe = self.post('analysis-recipe', self.base + '/bio-analysis-setups', dict(name=self.phase + ' engineering exploration',
            raw_source=raw_source, expected_revision=0, observation_map_version_id=mapping['id'] if mapping else None,
            design_version_id=None, params=params), kind='recipe')
        run = self.post(label + '-run', self.base + '/bio-analysis-runs', dict(raw_source=raw_source, recipe_version_id=recipe['id'],
            expected_setup_revision=recipe['revision']), kind='run', expected=202)
        confirmation = self.progress['actions'].get(label + '-confirm', {})
        queued = confirmation.get('response')
        if queued is None:
            self.wait(run['task'], 'waiting_confirmation')
            view = self.get(self.base + '/bio-analysis-runs/' + run['id'])
            if self.restart_at_qc and not self.progress.get('worker_restart_at_qc'):
                self.restart_waiting_worker(view)
            confirm = dict(task_revision=view['task']['revision'], checkpoint_id=view['checkpoint_id'], wait_id=view['wait_id'],
                candidate_sha256=view['candidate']['sha256'], expected_setup_revision=view['expected_setup_revision'])
            queued = self.post(label + '-confirm', self.base + '/bio-analysis-runs/' + run['id'] + '/confirm', confirm,
                               kind='confirmation', expected=202)
        done = self.wait(queued, 'succeeded')
        result = self.get(self.base + '/bio-processed-datasets/' + done['result_bio_processed_dataset_version_id'])
        self.progress[label] = dict(run_id=run['id'], recipe=recipe, result=result)
        self.save()
        return result

    def restart_waiting_worker(self, view):
        """Only the batch-owned Worker, while its human wait holds no lease."""
        from app.db.database import database_connection
        with database_connection() as db:
            attempt = db.execute('SELECT * FROM task_attempts WHERE task_id=%s ORDER BY attempt_no DESC LIMIT 1',
                                 (view['task']['id'],)).fetchone()
            if not attempt or attempt['lease_owner'] is not None or attempt['finished_at'] is None:
                raise RuntimeError('QC wait still owns a Worker lease')
        stack = control.worker_stack.load(control.ROOT, test_id=self.state['schema'][8:])
        if stack is None:
            raise RuntimeError('This batch has no owned Worker stack')
        before = control.worker_stack.owned_containers(stack)
        if not any(c['service']=='worker' and c['status']=='running' for c in before):
            raise RuntimeError('This batch Worker is not running')
        override = Path(self.state['worker_override'])
        control.compose(stack, override, ['stop','--timeout','30','worker'], timeout=60)
        try:
            retained = self.get(self.base + '/bio-analysis-runs/' + view['id'])
            for field in ('checkpoint_id','wait_id'):
                if retained[field] != view[field]:
                    raise RuntimeError('QC wait identity changed during Worker restart')
            if retained['task']['status'] != 'waiting_confirmation' or retained['candidate']['sha256'] != view['candidate']['sha256']:
                raise RuntimeError('QC candidate changed during Worker restart')
        finally:
            control.compose(stack, override, ['up','-d','--no-build','--wait','--wait-timeout','90','worker'], timeout=150)
        self.progress['worker_restart_at_qc'] = {'task_id':view['task']['id'],'checkpoint_id':view['checkpoint_id'],
            'wait_id':view['wait_id'],'candidate_sha256':view['candidate']['sha256'],'wait_releases_lease':True,
            'containers_after':control.worker_stack.owned_containers(stack)}
        self.save()

    def download(self, member):
        sha, size = hashlib.sha256(), 0
        with self.client.stream('GET', member['download_url']) as response:
            self.check(response)
            media = None
            if member.get('format'):
                media = ({'png':'image/png','jpeg':'image/jpeg','jpg':'image/jpeg'}
                    if '/bio-datasets/' in member['download_url'] else
                    {'png':'image/png','pdf':'application/pdf','json':'application/json',
                     'tsv':'text/tab-separated-values','txt':'text/plain','py':'text/plain'}
                    ).get(member['format'],'application/octet-stream')
            if media and response.headers.get('content-type','').split(';',1)[0] != media:
                raise RuntimeError('Published member MIME differs from its fixed format')
            if 'attachment' not in response.headers.get('content-disposition',''):
                raise RuntimeError('Published member lacks its download disposition')
            for block in response.iter_bytes():
                sha.update(block)
                size += len(block)
        if sha.hexdigest() != member['sha256'] or size != member['size_bytes']:
            raise RuntimeError('Published member bytes differ from fixed identity')

    def exercise(self, contents, *, analysis_attempt=None):
        project = self.post('project', '/api/v1/projects', dict(name='CR-B02 ' + ('GSE262082 统一验收' if self.phase == 'gse' else 'Synthetic queue acceptance'),
            research_topic='Spatial exploratory analysis; independent donor design pending', project_type='research',
            delivery_kinds=['analysis']), lookup='/api/v1/project-create-requests/' + self.progress.get('actions', {}).get('project', {}).get('key', 'missing'))
        self.base = '/api/v1/projects/' + project['id']
        self.progress['project_id'] = project['id']
        self.save()
        files = self.upload(contents)
        raw = self.import_raw(files)
        if self.phase == 'gse':
            raw = self.import_raw(files, version2=True, original=raw)
        mapping = None
        if self.phase == 'synthetic':
            rows = [{'barcode': f'SYNTH_{i:03d}-1', 'section': {'status': 'known', 'value': 'section_A' if i < 30 else 'section_B'},
                     'batch': {'status': 'known', 'value': 'synthetic_batch'}} for i in range(60)]
            mapping = self.post('mapping', self.base + '/bio-observation-maps', dict(name='Engineering section mapping, donor unknown',
                raw_source=raw, expected_revision=0, design_version_id=None, rows=rows), kind='map')
        capability = self.get(self.base + '/bio-analysis-capabilities?dataset_id=' + raw['dataset_id'] + '&version_id=' + raw['dataset_version_id'])
        if not capability['available']:
            raise RuntimeError('Actual runtime/source capability blocked: ' + str(capability['blockers']))
        params = capability['default_params']
        selected = analysis_attempt or self.progress.get('active_analysis_attempt', 'analysis')
        self.progress['active_analysis_attempt'] = selected
        self.save()
        result = self.run_analysis(raw, mapping, params, label=selected)
        self.progress['analysis'] = self.progress[selected]
        self.save()
        observations = self.get(self.base + '/bio-processed-datasets/' + result['id'] + '/tables/observations?page_size=100')
        gene_rows = self.get(self.base + '/bio-processed-datasets/' + result['id'] + '/tables/features?page_size=100')
        kept = [row for row in observations['items'] if str(row.get('kept')).lower() == 'true']
        if self.phase == 'synthetic' and observations['total'] != 60:
            raise RuntimeError('Synthetic raw observation axis was changed')
        gene = next(row['feature_id'] for row in gene_rows['items'] if str(row.get('kept')).lower() == 'true')
        cluster = str(next(row['cluster'] for row in kept if row.get('cluster') is not None))
        marker = next((m for m in result['members'] if m['key'] == 'markers'), None)
        annotation = self.post('annotation', self.base + '/bio-annotation-sets', dict(name='Engineering demonstration; researcher confirmation pending',
            raw_source=raw, processed_dataset_version_id=result['id'], expected_revision=0,
            labels=[dict(id='engineering_region', name='Engineering region pending review', status='proposed', note='Not a validated cell type', cluster_ids=[cluster])],
            regions=[dict(id='engineering_polygon', label_id='engineering_region', section=None,
                          points=[[0.,0.],[80.,0.],[80.,80.],[0.,80.]], priority=1)], overlap_policy='ambiguity',
            evidence=[dict(label_id='engineering_region', kind='marker', analysis_artifact_id=marker['id'], file_id=None, note='Exploratory marker table only')] if marker else []), kind='annotation')
        source = result['source']
        figure = self.post('gene-figure', self.base + '/bio-figures', dict(processed_source=source,
            annotation_version_id=None, expected_version=0, config=dict(kind='spatial_gene', panel='default', gene_ids=[gene], layer='log1p',
                title='Engineering expression example', palette='magma', vmin=0., vmax=None, width=1800, height=1500, dpi=300, output_language='en')), kind='figure', expected=202)
        self.wait(figure['task'], 'succeeded')
        figure = self.get(self.base + '/bio-figures/' + figure['id'])
        for member in [*result['members'], *figure['members']]:
            self.download(member)
        self.progress.update(raw_source=raw, processed_source=source, annotation=annotation, figure=figure, status='passed',
            observations_total=observations['total'], visible_kept=len(kept), verified_result_members=len(result['members']),
            verified_figure_members=len(figure['members']), scientific_scope='Exploratory spot analysis; no donor-level or cell-type validation')
        self.save()
        return {key: self.progress[key] for key in ['phase','project_id','status','raw_source','processed_source','verified_result_members','verified_figure_members']}


def synthetic_bundle():
    import numpy as np
    from PIL import Image
    from tests.helpers.bio_fixtures import bundle_from_parts
    counts = np.random.default_rng(1729).poisson(2, size=(60, 40)).astype('int64')
    counts[:30,:10] += 20
    counts[30:,10:20] += 20
    counts[0,:] = 0
    rows, columns = np.nonzero(counts)
    mtx = '%%MatrixMarket matrix coordinate integer general\n40 60 ' + str(len(rows)) + '\n'
    mtx += ''.join(f'{j+1} {i+1} {counts[i,j]}\n' for i,j in zip(rows,columns))
    positions = ''.join(f'SYNTH_{i:03d}-1,{0 if i in (1,60,61,62,63) else 1},{i//8},{i%8},{10+i//8*20},{10+i%8*20}\n' for i in range(64))
    parts = {'matrix.mtx': mtx.encode(), 'features.tsv': ''.join(f'ENSG_SYNTH_{i:04d}\t'+('SAME' if i in (2,3) else f'GENE_{i}')+'\tGene Expression\n' for i in range(40)).encode(),
        'barcodes.tsv': ''.join(f'SYNTH_{i:03d}-1\n' for i in range(60)).encode(), 'tissue_positions_list.csv': positions.encode(),
        'scalefactors_json.json': json.dumps(dict(tissue_hires_scalef=1., tissue_lowres_scalef=.3, spot_diameter_fullres=12., fiducial_diameter_fullres=12.)).encode()}
    for name, side in [('hires',200), ('lowres',60)]:
        stream = io.BytesIO()
        Image.new('RGB', (side,side), '#f0eadf').save(stream, format='PNG')
        parts['tissue_'+name+'_image.png'] = stream.getvalue()
    return bundle_from_parts({'GSM9999001_'+name+'.gz': gzip.compress(value, mtime=0) for name,value in parts.items()})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', default=str(control.STATE))
    parser.add_argument('--gse', action='store_true')
    parser.add_argument('--fresh', action='store_true')
    parser.add_argument('--restart-at-qc', action='store_true')
    parser.add_argument('--analysis-attempt', help='Explicit new run identity after a diagnosed terminal failure; reuses the original recipe')
    args = parser.parse_args()
    if args.analysis_attempt and not re.fullmatch('[a-z][a-z0-9-]{0,63}', args.analysis_attempt):
        parser.error('analysis-attempt must be a bounded lowercase identifier')
    state = control.read_state(args.state)
    control.configure(state)
    if args.gse:
        desktop = Path.home() / 'Desktop'
        names = ['GSE262082_RAW.tar','GSE262082_family.soft','GSE262082_family.xml.tgz','GSE262082_series_matrix.txt','filelist.txt']
        contents = [(name, (desktop / name).read_bytes()) for name in names]
    else:
        contents = [('GSE9999000_RAW.tar', synthetic_bundle())]
    verification = Verification(state, 'gse' if args.gse else 'synthetic', fresh=args.fresh, restart_at_qc=args.restart_at_qc)
    try:
        print(json.dumps(verification.exercise(contents, analysis_attempt=args.analysis_attempt), ensure_ascii=False), flush=True)
    finally:
        verification.client.close()


if __name__ == '__main__':
    main()
