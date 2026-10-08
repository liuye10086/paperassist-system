"""Read a task and its exact saved artifacts without advancing any execution."""
import json
from urllib.parse import quote

from app.adapters.task_store import TaskStore, source_conflict
from app.core.exceptions import StorageError
from app.domain.tasks.contracts import TaskCreateRequest


class TaskWorkspaceService:
    def __init__(self, user_id, config=None):
        self.store = TaskStore(user_id, config)

    def source(self, db, task):
        snapshot = task['input_snapshot']
        try:
            request = TaskCreateRequest(task_type=task['task_type'], file_id=snapshot['file']['id'],
                analysis_run_id=snapshot['result']['id'], expected_revision=snapshot['result']['setup_revision'],
                figure_id=snapshot['figure']['id'] if task['task_type'] in ('explanation', 'word_report') else None,
                explanation_id=snapshot['explanation']['id'] if task['task_type'] == 'word_report' else None)
            project = self.store.require_project(db, task['project_id'])
            try:
                current = self.store.source_snapshot(db, project, request)
                is_current = all(current[key] == snapshot[key]
                                 for key in ('file', 'result', 'figure', 'explanation', 'versions', 'output_language'))
            except StorageError as exc:
                if exc.code != 'task_source_conflict':
                    raise
                is_current = False
            return dict(file_id=request.file_id, filename=snapshot['file']['filename'],
                        analysis_run_id=request.analysis_run_id, is_current=is_current)
        except (KeyError, TypeError, ValueError) as exc:
            raise source_conflict() from exc

    def list(self, project_id, *, page=1, page_size=10, status=None, task_type=None):
        if (type(page) is not int or not 1 <= page <= 1_000_000
                or type(page_size) is not int or not 1 <= page_size <= 50
                or status not in (None, 'queued', 'running', 'waiting_input', 'waiting_confirmation', 'succeeded', 'failed')
                or task_type not in (None, 'boxplot', 'explanation', 'word_report')):
            raise StorageError('task_input_invalid', '任务列表查询参数无效。', 422)
        conditions = ['project_id=%s', 'user_id=%s']
        values = [project_id, self.store.user_id]
        for field, value in [('status', status), ('task_type', task_type)]:
            if value is not None:
                conditions.append(field + '=%s')
                values.append(value)
        where = ' AND '.join(conditions)
        with self.store.connection() as db:
            self.store.require_project(db, project_id)
            total = db.execute('SELECT count(*) AS n FROM tasks WHERE ' + where, tuple(values)).fetchone()['n']
            rows = db.execute('SELECT * FROM tasks WHERE ' + where
                + ' ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s',
                (*values, page_size, (page - 1) * page_size)).fetchall()
            items = [{'task': self.store.public_task(dict(row)), 'source': self.source(db, row)} for row in rows]
        return dict(project_id=project_id, items=items, total=total, page=page, page_size=page_size)

    @staticmethod
    def _saved_artifact(db, task, kind):
        tables = {'figure': ('figures', 'figure_json'), 'explanation': ('explanations', 'explanation_json'),
                  'report': ('reports', 'report_json')}
        reference = task.get('result_' + kind + '_id')
        if not reference:
            return None
        table, column = tables[kind]
        row = db.execute('SELECT a.*,r.file_id AS source_file_id FROM ' + table
                         + ' a JOIN analysis_runs r ON r.id=a.analysis_run_id WHERE a.id=%s AND a.analysis_run_id=%s',
                         (reference, task['input_snapshot']['result']['id'])).fetchone()
        if row is None:
            raise source_conflict()
        try:
            value = json.loads(row[column])
            snapshot = task['input_snapshot']
            if (value['id'] != reference or value['analysis_run_id'] != snapshot['result']['id']
                    or row['source_file_id'] != snapshot['file']['id']
                    or value['source_sha256'] != snapshot['file']['sha256']
                    or value['setup_revision'] != snapshot['result']['setup_revision']):
                raise source_conflict()
            if kind == 'figure' and value['file_id'] != snapshot['file']['id']:
                raise source_conflict()
            if kind == 'explanation' and (row['figure_id'] != snapshot['figure']['id']
                                          or value['figure_id'] != snapshot['figure']['id']
                                          or value['figure_sha256'] != snapshot['figure']['sha256']):
                raise source_conflict()
            if kind == 'report':
                saved_input = json.loads(row['input_json'])
                if (row['explanation_id'] != snapshot['explanation']['id']
                        or value['explanation_id'] != snapshot['explanation']['id']
                        or value['figure_id'] != snapshot['figure']['id']
                        or value['figure_sha256'] != snapshot['figure']['sha256']
                        or any(saved_input[key] != snapshot[key] for key in ('result', 'figure', 'explanation'))):
                    raise source_conflict()
            return value
        except (KeyError, TypeError, ValueError) as exc:
            raise source_conflict() from exc

    def artifacts(self, db, task):
        result = {'figure': None, 'explanation': None, 'report': None}
        snapshot = task['input_snapshot']
        prefix = '/api/v1/projects/{}/files/{}/analysis-runs/{}'.format(
            *[quote(value, safe='') for value in (task['project_id'], snapshot['file']['id'], snapshot['result']['id'])])
        try:
            figure = self._saved_artifact(db, task, 'figure')
            if figure:
                result['figure'] = {key: figure[key] for key in ('title', 'caption')}
                result['figure']['download_url'] = prefix + '/figures/' + quote(figure['id'], safe='') + '/download'
            explanation = self._saved_artifact(db, task, 'explanation')
            if explanation:
                result['explanation'] = {'sections': [{key: section[key] for key in ('key', 'title', 'text')}
                                                     for section in explanation['sections']],
                                         'limitations': explanation['limitations']}
            report = self._saved_artifact(db, task, 'report')
            if report:
                result['report'] = {'filename': report['filename'],
                                    'download_url': prefix + '/report/' + quote(report['id'], safe='') + '/download'}
            return result
        except (KeyError, TypeError, ValueError) as exc:
            raise source_conflict() from exc

    def get(self, task_id):
        from app.domain.tasks.waits import get_open_wait, allowed_recovery_actions

        with self.store.connection() as db:
            task = self.store.require_task(db, task_id)
            source = self.source(db, task)
            return {'task': self.store.public_task(task), 'source': source, 'wait': get_open_wait(db, task),
                    'allowed_actions': allowed_recovery_actions(db, task) if source['is_current'] else [],
                    'artifacts': self.artifacts(db, task)}
