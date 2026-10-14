"""Immutable report files with input snapshots and transactional version checks."""

from datetime import datetime, timezone
import hashlib
import json
import os
from uuid import uuid4

import docx

from app.adapters.report_docx import VERSION
from app.core.exceptions import StorageError


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, allow_nan=False,
                                     sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


class ReportStore:
    def __init__(self, store):
        self.store = store
        self.directory = store.directory / 'reports'

    @staticmethod
    def cached(db, explanation_id):
        row = db.execute('SELECT report_json FROM reports WHERE explanation_id=%s AND renderer_version=%s',
                         (explanation_id, VERSION)).fetchone()
        return json.loads(row['report_json']) if row else None

    def saved(self, explanation_id):
        with self.store.connection() as db:
            return self.cached(db, explanation_id)

    def by_id(self, project_id, file_id, run_id, report_id):
        result = self.store.analysis_result_by_id(project_id, file_id, run_id)
        with self.store.connection() as db:
            row = db.execute('SELECT * FROM reports WHERE id=%s AND analysis_run_id=%s', (report_id, run_id)).fetchone()
            if row and 'source' in result:
                self.validate_dataset_report(db, result, row)
        if row is None:
            raise StorageError('report_not_found', '当前统计结果中没有此报告，请重新读取报告。', 404)
        if 'source' in result:
            from app.domain.dataset_analysis import load_dataset
            load_dataset(self.store, project_id, file_id, result['source']['dataset_id'], expected_source=result['source'])
        return json.loads(row['report_json'])

    @staticmethod
    def validate_dataset_report(db, result, row):
        """Read historical dataset reports against their own immutable inputs."""
        from app.domain.reports import validate_sources
        try:
            report, snapshot = json.loads(row['report_json']), json.loads(row['input_json'])
            figure, explanation = snapshot['figure'], snapshot['explanation']
            validate_sources(result, figure, explanation)
            if (snapshot['result'] != result or snapshot.get('source') != result['source']
                    or report.get('source') != result['source']
                    or report['id'] != row['id'] or report['analysis_run_id'] != result['id']
                    or report['setup_revision'] != result['setup_revision']
                    or report['source_sha256'] != result['source_sha256']
                    or report['figure_id'] != figure['id'] or report['figure_sha256'] != figure['sha256']
                    or report['explanation_id'] != explanation['id']
                    or row['explanation_id'] != explanation['id']
                    or report['input_sha256'] != digest(snapshot)):
                raise ValueError('Report lineage mismatch')
            for table, column, value in (('figures', 'figure_json', figure),
                                         ('explanations', 'explanation_json', explanation)):
                saved = db.execute('SELECT ' + column + ' FROM ' + table + ' WHERE id=%s AND analysis_run_id=%s',
                                   (value['id'], result['id'])).fetchone()
                if saved is None or json.loads(saved[column]) != value:
                    raise ValueError('Report predecessor mismatch')
        except (KeyError, TypeError, ValueError, StorageError) as exc:
            raise StorageError('report_source_changed', '报告与保存的统计、图表或解释来源不一致。', 409) from exc

    def content(self, report):
        try:
            with (self.directory / (report['id'] + '.docx')).open('rb') as stream:
                content = stream.read(report['size_bytes'] + 1)
        except FileNotFoundError as exc:
            raise StorageError('report_missing', '报告文件缺失，请恢复完整数据目录，或另存配置并完成分析后导出新报告。', 410) from exc
        except OSError as exc:
            raise StorageError('storage_unavailable', '无法读取报告，请检查目录权限。') from exc
        if len(content) != report['size_bytes'] or hashlib.sha256(content).hexdigest() != report['sha256']:
            raise StorageError('report_changed', '报告文件内容发生变化，请恢复原报告或另存配置生成新报告。', 409)
        return content

    @staticmethod
    def metadata(snapshot):
        result, figure, explanation = (snapshot[key] for key in ('result', 'figure', 'explanation'))
        report_id = str(uuid4())
        return {'id': report_id, 'analysis_run_id': result['id'], 'figure_id': figure['id'], 'explanation_id': explanation['id'],
                'setup_revision': result['setup_revision'], 'source_sha256': result['source_sha256'], 'figure_sha256': figure['sha256'],
                'created_at': datetime.now(timezone.utc).isoformat(), 'filename': f'分析报告-v{result["setup_revision"]}-{report_id[:8]}.docx',
                'language': 'zh-CN', 'engine': {'id': VERSION, 'python_docx': docx.__version__}, 'input_sha256': digest(snapshot),
                **({'source': result['source']} if 'source' in result else {})}

    def save(self, snapshot, report, content):
        result, figure, explanation = (snapshot[key] for key in ('result', 'figure', 'explanation'))
        temporary = self.directory / (report['id'] + '.part')
        target = self.directory / (report['id'] + '.docx')
        owned_paths = []
        try:
            with self.store.connection(write=True) as db:
                self.store.require_analysis_revision(db, result['file_id'], result['setup_revision'])
                # All three immutable source records must still equal the rendering snapshot.
                for table, column, value in [('analysis_runs', 'result_json', result), ('figures', 'figure_json', figure),
                                              ('explanations', 'explanation_json', explanation)]:
                    row = db.execute(f'SELECT {column} FROM {table} WHERE id=%s', (value['id'],)).fetchone()
                    if not row or json.loads(row[column]) != value:
                        raise StorageError('report_source_changed', '导出期间统计、图表或解释发生变化，请重新读取当前结果。', 409)
                record = db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s',
                                    (result['file_id'], snapshot['project']['id'])).fetchone()
                if not record or record['sha256'] != result['source_sha256']:
                    raise StorageError('report_source_changed', '报告数据来源已变化，请重新读取结果。', 409)
                if 'source' in result:
                    from app.domain.dataset_analysis import load_dataset
                    load_dataset(self.store, snapshot['project']['id'], result['file_id'],
                                 result['source']['dataset_id'], expected_source=result['source'])
                else:
                    self.store.original(dict(record))
                self.store.figure_png(figure)
                existing = self.cached(db, explanation['id'])
                if existing:
                    self.content(existing)
                    return existing, False
                self.directory.mkdir(parents=True, exist_ok=True)
                with temporary.open('xb') as stream:
                    owned_paths.append(temporary)
                    stream.write(content); stream.flush(); os.fsync(stream.fileno())
                temporary.rename(target)
                owned_paths.append(target)
                saved = {**report, 'size_bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
                db.execute('INSERT INTO reports (id, analysis_run_id, explanation_id, renderer_version, report_json, input_json) VALUES (%s, %s, %s, %s, %s, %s)',
                           (report['id'], result['id'], explanation['id'], VERSION,
                            json.dumps(saved, ensure_ascii=False, allow_nan=False), json.dumps(snapshot, ensure_ascii=False, allow_nan=False)))
                db.execute('UPDATE projects SET updated_at=GREATEST(updated_at, %s) WHERE id=%s', (saved['created_at'], snapshot['project']['id']))
            return saved, True
        except (OSError, StorageError) as exc:
            # Only this attempt's UUID files can be removed; existing reports stay intact.
            for path in owned_paths:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            if isinstance(exc, StorageError):
                raise
            raise StorageError('storage_unavailable', '报告保存失败，请检查数据目录权限和磁盘空间后重试。') from exc
