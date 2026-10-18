"""Deep immutable-history loading, using real receipt verification.

Database/asset IO and relational approval auditing are explicit memory doubles;
the real load_version/load_quality_version/read_candidate/base_object call path
and verify_frozen_receipt run. API/DB tests cover the substituted trust boundary.
"""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


@pytest.fixture
def history(monkeypatch):
    import app.domain.dataset_preparation.service as service
    import app.domain.dataset_preparation.quality_service as quality
    from app.domain.analysis_sources import prepared_dataset_source
    from app.domain.dataset_preparation.quality_contracts import QualityRecipe
    from app.domain.dataset_preparation.quality_transform import prepare_quality, build_quality_object
    from tests.domain.test_batch07_quality_transform import base

    anchor, _ = base([[1, 2, 'A']])
    root = anchor.parent_source.model_dump()
    recipe = QualityRecipe(fields=[dict(column=c) for c in (1, 2, 3)])
    rows, tasks, checkpoints, objects, relations, manifests = {}, {}, {}, {}, {}, {}
    counts = dict(reads=0, audited_nodes=0)
    ids = []
    for index in range(351):
        task_id = f'deep-history-task-{index}'
        identity = service.candidate_id(task_id)
        ids.append(identity)
        digest = str(index).zfill(64)
        row = dict(id=identity, file_id='file', parent_dataset_id='raw', task_id=task_id,
            decision_id=f'decision-{index}', version=index+1, created_by='user',
            object_key=f'prepared-datasets/{identity}/{digest}.json', sha256=digest, size_bytes=10)
        if index:
            sheet, summary, manifest = prepare_quality(previous_object, previous_source, recipe)
            reference = dict(object_key=f'quality-manifests/{identity}/{digest}.json',
                sha256=digest, size_bytes=10, entry_count=0)
            obj = build_quality_object(previous_object, previous_source, recipe, sheet, summary, reference)
            relations[identity] = {f'manifest_{key}':value for key, value in reference.items()}
            relations[identity]['base_prepared_dataset_id'] = previous_source['dataset_id']
            manifests[reference['object_key']] = manifest
            snapshot = dict(source=previous_source, root_source=root)
        else:
            # The v1 anchor's own publication/IO checks are substituted, while
            # its original prepared values and source remain the chain origin.
            obj = SimpleNamespace(parent_source=anchor.parent_source, sheet=anchor.sheet,
                recipe=recipe, summary=SimpleNamespace(model_dump=lambda **kwargs:{'record_count':1}), schema_version=1)
            snapshot = dict(source=root)
        row.update(recipe_json=obj.recipe.model_dump(), summary_json=obj.summary.model_dump())
        state = dict(candidate={key:row[key] for key in service.CandidateReference.model_fields},
            recipe=row['recipe_json'], decision_id=row['decision_id'], result_id=row['id'])
        checkpoints[task_id] = dict(id=f'checkpoint-{index}', node='done', next_node='done', state_json=state)
        tasks[task_id] = dict(id=task_id, workflow_version='dataset_preparation_v2' if index else 'dataset_preparation_v1',
            status='succeeded', user_id='user', project_id='project', input_snapshot=snapshot)
        rows[identity] = row
        objects[identity] = obj
        previous_object = obj
        previous_source = prepared_dataset_source(row, root, schema_version=2 if index else 1)

    class Database:
        def execute(self, sql, args=()):
            counts['reads'] += 1
            if 'FROM prepared_dataset_versions' in sql:
                result = rows[args[0]]
            elif 'FROM prepared_dataset_derivations' in sql:
                result = relations[args[0]]
            elif 'FROM tasks' in sql:
                result = tasks[args[0]]
            else:
                raise AssertionError(sql)
            return SimpleNamespace(fetchone=lambda:result)

    class Store:
        user_id = 'user'

        @contextmanager
        def connection(self, *args, **kwargs):
            yield Database()

        def require_task(self, db, identity):
            return tasks[identity]

    class ObjectStore:
        def read(self, reference):
            return b'', objects[reference['id']]

    class ManifestStore:
        def read(self, reference):
            return b'', manifests[reference['object_key']]

    def init(self, assets):
        self.assets = assets
        self.store = Store()
        self.datasets = SimpleNamespace(require_file=lambda *args:None)
        self.objects = ObjectStore()
        self.manifests = ManifestStore()

    def audited_node(db, task, row):
        counts['audited_nodes'] += 1
        source = prepared_dataset_source(row, root, schema_version=2)
        return source, rows[task['input_snapshot']['source']['dataset_id']]

    def audited_chain(db, task, row):
        while task['workflow_version'] == 'dataset_preparation_v2':
            _, row = audited_node(db, task, row)
            task = tasks[row['task_id']]

    monkeypatch.setattr(service.DatasetPreparationService, '__init__', init)
    monkeypatch.setattr(quality.QualityPreparationService, '__init__', init)
    monkeypatch.setattr(service.DatasetPreparationService, 'require_raw', lambda *args:None)
    for module in (service, quality):
        monkeypatch.setattr(module, 'validate_snapshot', lambda task:task['input_snapshot'])
        monkeypatch.setattr(module, 'latest_checkpoint', lambda db, task:checkpoints[task['id']])
    monkeypatch.setattr(service, 'require_approval', lambda *args:None)
    monkeypatch.setattr(quality, 'audit_published', audited_chain)
    monkeypatch.setattr(quality, '_audit_published_node', audited_node)
    return SimpleNamespace(service=service.DatasetPreparationService(None), counts=counts,
        ids=ids, objects=objects, manifests=manifests)


@pytest.mark.parametrize('depth', [300, 350])
def test_deep_history_loads_without_recursion_or_reauditing_ancestors(history, depth):
    row, _, obj = history.service.load_version('project', 'file', history.ids[depth])
    assert row['version'] == depth+1
    assert obj.sheet.active_source_rows == [2]
    assert [(cell.column, cell.value) for cell in obj.sheet.cells] == [(1, '1'), (2, '2'), (3, 'A')]
    assert history.counts['audited_nodes'] == depth
    assert history.counts['reads'] <= 2*depth+5


def test_deep_history_rejects_a_changed_ancestor_manifest(history):
    from app.core.exceptions import StorageError
    ancestor = history.objects[history.ids[150]]
    key = ancestor.manifest.object_key
    frozen = history.manifests[key]
    history.manifests[key] = frozen.model_copy(update={
        'summary': frozen.summary.model_copy(update={'root_record_count':999})})
    with pytest.raises(StorageError) as caught:
        history.service.load_version('project', 'file', history.ids[350])
    assert caught.value.code == 'task_source_conflict'
