"""Role-scoped reading of a synthetic published Propeller member."""

from hashlib import sha256
from uuid import uuid4

from fastapi.testclient import TestClient

from app.adapters.bio_insights_store import BioInsightsObjects
from app.adapters.task_store import TaskStore
from app.core.config import get_data_dir
from app.db.database import database_connection
from app.domain.bio_insights import results
from app.domain.bio_insights.service import BioInsightsService
from app.main import app
from tests.api.test_customer_workspace import create_customer_project, sign_in
from tests.api.test_project_assignments import assign


TABLE = (
    'category\tlabel_id\tnumerator\tdenominator\tmean_proportion_denominator\tmean_proportion_numerator\t'
    'proportion_difference\tp_adjust\tinference_status\treason\n'
    'label\tT\tstim\tctrl\t0.3300\t0.5875\t0.2575\t0.00048353808306252034\ttested\t\n'
    'label\tB\tstim\tctrl\t0.4825\t0.2650\t-0.2175\t0.001906752541801201\ttested\t\n'
    'unknown\t\tstim\tctrl\t0.1875\t0.1475\t-0.0400\t0.11249980986901548\ttested\t\n'
).encode()


def test_assigned_analyst_reads_fixed_propeller_table_and_rollback_keeps_original(monkeypatch, tmp_path):
    with TestClient(app) as owner, TestClient(app) as staff, TestClient(app) as analyst, TestClient(app) as unassigned:
        sign_in(owner, 'propeller-owner@skills.test', 'customer')
        sign_in(staff, 'propeller-admin@skills.test', 'admin')
        analyst_id = sign_in(analyst, 'propeller-analyst@skills.test', 'analyst')
        sign_in(unassigned, 'propeller-unassigned@skills.test', 'analyst')
        base = create_customer_project(owner)
        project = base.rsplit('/', 1)[-1]
        assert assign(staff, base, analyst_id, 0).status_code == 200
        result_id = str(uuid4())
        objects = BioInsightsObjects(get_data_dir())
        member = {**objects.describe(result_id, TABLE), 'id': str(uuid4()), 'key': 'composition_results',
                  'role': 'table', 'format': 'tsv', 'shape_json': {}}
        objects.write(member, TABLE)
        manifest = {'members': [{key: member[key] for key in ('key', 'role', 'format', 'sha256', 'size_bytes')}]}
        row = dict(id=result_id, run_id='fixture-run', plan_version_id='fixture-plan', kind='comparison',
                   inference_scope='donor_inference', provenance='synthetic_fixture',
                   summary_json={'total_cells': 800, 'unit_count': 8},
                   methods_json={'name': 'speckle_propeller', 'denominator': 'all_retained_cells_in_selected_conditions',
                                 'actual_units': [{'numerator': 'stim', 'denominator': 'ctrl', 'observation_level': 'donor',
                                                   'n_numerator': 4, 'n_denominator': 4}],
                                 'versions': {'R': '4.4.3', 'speckle': '1.6.0'},
                                 'config': {'schema_version': 5, 'method': 'single_cell_composition',
                                            'mode': 'donor_unpaired', 'transform': 'asin', 'labels_confirmed': True,
                                            'batch_adjustment': False, 'numerator': 'stim', 'denominator': 'ctrl'}},
                   task_id='fixture-task', manifest_sha256='a' * 64)
        original_require = results.BioInsightResultService.require
        original_task = TaskStore.require_task

        def frozen_result(self, db, table, project_id, identifier):
            if table == 'bio_insight_result_versions' and project_id == project and identifier == result_id:
                self.store.require_project(db, project_id)
                return row
            return original_require(self, db, table, project_id, identifier)

        def frozen_task(self, db, task_id):
            if task_id == 'fixture-task':
                return {'id': task_id, 'status': 'succeeded'}
            return original_task(self, db, task_id)

        def frozen_members(service, db, project_id, selected, *, resource=False):
            assert not resource
            assert (project_id, selected['id']) == (project, result_id)
            assert service.objects.read(member) == TABLE
            return manifest, [member]

        def require_frozen_source(self, db, task, *, runtime=True):
            assert (task['id'], runtime) == ('fixture-task', False)

        monkeypatch.setattr(results.BioInsightResultService, 'require', frozen_result)
        monkeypatch.setattr(TaskStore, 'require_task', frozen_task)
        monkeypatch.setattr(TaskStore, 'public_task', staticmethod(lambda task: task))
        monkeypatch.setattr(results, 'checked_members', frozen_members)
        monkeypatch.setattr(BioInsightsService, 'require_sources', require_frozen_source)
        path = f'{base}/bio-insight-results/{result_id}'
        endpoint = path + '/composition-preview'
        original = analyst.get(path)
        assert original.status_code == 200
        assert 'composition_preview' not in original.json()
        assert analyst.get(endpoint).status_code == 404

        monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', 'single_cell_composition_preview')
        advertised = analyst.get(path).json()
        assert advertised.pop('composition_preview') is True
        assert advertised == original.json()
        assert owner.get(endpoint).status_code == 403
        assert unassigned.get(endpoint).status_code == 404
        assert analyst.get(f'{base}/bio-insight-results/{uuid4()}/composition-preview').status_code == 404

        with database_connection() as db:
            before = db.execute('SELECT count(*) AS n FROM tasks WHERE project_id=%s', (project,)).fetchone()['n']
        response = analyst.get(endpoint, params={'page': 2, 'page_size': 2})
        assert response.status_code == 200, response.text
        assert response.headers['Cache-Control'] == 'no-store'
        preview = response.json()
        assert (preview['project_id'], preview['result_version_id']) == (project, result_id)
        assert preview['manifest_sha256'] == row['manifest_sha256']
        assert preview['table_sha256'] == sha256(TABLE).hexdigest()
        assert preview['trace']['workflow'] == 'single_cell_composition_preview'
        assert preview['trace']['tool']['id'] == 'fixed_propeller_table'
        assert preview['design'] == {'denominator': 'ctrl', 'numerator': 'stim', 'n_denominator': 4, 'n_numerator': 4}
        assert preview['total'] == 3 and preview['page'] == 2
        assert preview['rows'][0]['category'] == 'unknown'
        assert preview['rows'][0]['proportion_difference'] == '-0.0400'
        assert preview['rows'][0]['p_adjust'] == '0.11249980986901548'
        original_url = original.json()['members'][0]['download_url']
        assert analyst.get(original_url).content == TABLE

        with monkeypatch.context() as missing:
            missing.setenv('PAPERASSIST_SKILLS_DIR', str(tmp_path / 'missing'))
            assert analyst.get(endpoint).status_code == 503
            assert analyst.get(original_url).content == TABLE
        assert assign(staff, base, None, 1).status_code == 200
        assert analyst.get(endpoint).status_code == 404
        assert assign(staff, base, analyst_id, 2).status_code == 200
        monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', '')
        assert analyst.get(endpoint).status_code == 404
        assert analyst.get(path).json() == original.json()
        assert analyst.get(original_url).content == TABLE
        with database_connection() as db:
            assert db.execute('SELECT count(*) AS n FROM tasks WHERE project_id=%s', (project,)).fetchone()['n'] == before
            assert db.execute('SELECT count(*) AS n FROM model_calls WHERE project_id=%s', (project,)).fetchone()['n'] == 0
