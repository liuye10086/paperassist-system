"""Durable explanation jobs and drafts, using the project's existing transactions."""

from datetime import datetime, timezone
import json
from uuid import uuid4

from app.domain.explanation_content import VERSION
from app.core.exceptions import StorageError


class ExplanationStore:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def latest_job(db, figure_id):
        row = db.execute('SELECT job_json FROM explanation_jobs WHERE figure_id = %s AND engine_version = %s '
                         'ORDER BY created_at DESC, seq DESC LIMIT 1', (figure_id, VERSION)).fetchone()
        return json.loads(row['job_json']) if row else None

    def job(self, figure_id):
        with self.store.connection() as db:
            return self.latest_job(db, figure_id)

    def saved(self, figure_id):
        with self.store.connection() as db:
            row = db.execute('SELECT explanation_json FROM explanations WHERE figure_id = %s AND engine_version = %s',
                             (figure_id, VERSION)).fetchone()
        return json.loads(row['explanation_json']) if row else None

    def require_source(self, db, file_id, explanation):
        self.store.require_analysis_revision(db, file_id, explanation['setup_revision'])
        row = db.execute('''SELECT f.figure_json FROM figures f JOIN analysis_runs r ON r.id = f.analysis_run_id
            WHERE f.id = %s AND r.id = %s AND r.file_id = %s''',
            (explanation['figure_id'], explanation['analysis_run_id'], file_id)).fetchone()
        figure = json.loads(row['figure_json']) if row else None
        if not figure or figure['sha256'] != explanation['figure_sha256'] or figure['source_sha256'] != explanation['source_sha256']:
            raise StorageError('figure_conflict', '图表或数据版本已变化，请重新读取当前结果。', 409)
        self.store.figure_png(figure)

    def begin(self, result, figure, payload, model, retry):
        with self.store.connection(write=True) as db:
            self.require_source(db, result['file_id'], {**payload, 'setup_revision': result['setup_revision']})
            existing = self.latest_job(db, figure['id'])
            if existing and (existing['status'] not in ('failed', 'uncertain') or not retry):
                return existing, False
            # A completed draft wins even if a concurrent retrieval has not updated its job yet.
            saved = db.execute('SELECT id FROM explanations WHERE figure_id = %s AND engine_version = %s',
                               (figure['id'], VERSION)).fetchone()
            if saved and existing:
                return existing, False
            job = {'id': str(uuid4()), 'analysis_run_id': result['id'], 'figure_id': figure['id'],
                   'status': 'submitting', 'message': '正在向 OpenAI 提交统计汇总，请勿重复生成。',
                   'message_code': 'task_submitting', 'message_params': {},
                   'response_id': None, 'created_at': datetime.now(timezone.utc).isoformat(),
                   'model': model, 'payload': payload}
            db.execute('INSERT INTO explanation_jobs (id, analysis_run_id, figure_id, engine_version, created_at, job_json) VALUES (%s, %s, %s, %s, %s, %s)',
                       (job['id'], result['id'], figure['id'], VERSION, job['created_at'],
                        json.dumps(job, ensure_ascii=False, allow_nan=False)))
        return job, True

    def update_job(self, job_id, **changes):
        with self.store.connection(write=True) as db:
            row = db.execute('SELECT job_json FROM explanation_jobs WHERE id = %s', (job_id,)).fetchone()
            job = json.loads(row['job_json'])
            if job['status'] == 'completed':
                return job
            job.update(changes)
            db.execute('UPDATE explanation_jobs SET job_json = %s WHERE id = %s',
                       (json.dumps(job, ensure_ascii=False, allow_nan=False), job_id))
        return job

    def save(self, project_id, file_id, explanation):
        self.store.file(project_id, file_id)
        with self.store.connection(write=True) as db:
            self.require_source(db, file_id, explanation)
            row = db.execute('SELECT explanation_json FROM explanations WHERE figure_id = %s AND engine_version = %s',
                             (explanation['figure_id'], VERSION)).fetchone()
            if row:
                return json.loads(row['explanation_json'])
            saved = {**explanation, 'id': str(uuid4())}
            db.execute('INSERT INTO explanations VALUES (%s, %s, %s, %s, %s)',
                       (saved['id'], saved['analysis_run_id'], saved['figure_id'], VERSION,
                        json.dumps(saved, ensure_ascii=False, allow_nan=False)))
            db.execute('UPDATE projects SET updated_at = GREATEST(updated_at, %s) WHERE id = %s',
                       (saved['created_at'], project_id))
        return saved

    def pending(self):
        with self.store.connection() as db:
            return [dict(row) for row in db.execute('''
                SELECT j.id AS job_id, j.analysis_run_id AS run_id, r.file_id, f.project_id
                FROM explanation_jobs j JOIN analysis_runs r ON r.id = j.analysis_run_id JOIN files f ON f.id = r.file_id
                WHERE j.engine_version = %s AND (j.job_json::jsonb ->> 'status') IN ('running', 'submitting')
                ORDER BY j.created_at
            ''', (VERSION,))]
