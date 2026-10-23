"""Read a task and its exact saved artifacts without advancing any execution."""
import json
from urllib.parse import quote

from app.adapters.task_store import DatasetTaskAssets, TaskStore, source_conflict, snapshots_match
from app.core.exceptions import StorageError
from app.domain.tasks.contracts import TaskCreateRequest


class TaskWorkspaceService:
    def __init__(self, user_id, config=None):
        self.store = TaskStore(user_id, config)

    def source(self, db, task):
        snapshot = task['input_snapshot']
        if task['task_type']=='journal_adaptation':
            from app.domain.journals.adaptation_service import AdaptationService
            from app.domain.report_collections.service import scoped_store
            service=AdaptationService(scoped_store(task['user_id'],self.store.config))
            row=service.adaptation_row(db,task['project_id'],snapshot['id'])
            return dict(file_id=None,filename='期刊显示适配',analysis_run_id=None,is_current=True)
        if task['task_type']=='journal_format_check':
            from app.domain.journals.format_service import FormatService
            from app.domain.report_collections.service import scoped_store
            service=FormatService(scoped_store(task['user_id'],self.store.config))
            row=service.check_row(db,task['project_id'],snapshot['id'])
            return dict(file_id=None,filename=row['snapshot_json']['manuscript']['snapshot']['title'],analysis_run_id=None,is_current=True)
        if task['task_type']=='journal_recommendation':
            from app.domain.journals.service import input_version
            input_version(task)
            return dict(file_id=None,filename=snapshot['research']['title'],analysis_run_id=None,is_current=True)
        if task['task_type']=='school_template_parse':
            from app.domain.school_templates.service import SchoolTemplateService
            from app.domain.report_collections.service import scoped_store
            service=SchoolTemplateService(scoped_store(task['user_id'],self.store.config))
            row=service.row(db,task['project_id'],snapshot['template_version_id'])
            sources,_=service.validate(db,row)
            source=next(s for s in sources if s['role']=='template')
            return dict(file_id=source['file_id'],filename=source['filename'],analysis_run_id=None,is_current=not bool(service.current_changes(db,row,sources)))
        if task['task_type']=='manuscript_writing':
            from app.domain.manuscript_writing.service import require_snapshot
            snap=require_snapshot(task)
            return dict(file_id=None,filename=snap['base_snapshot']['title'],analysis_run_id=None,is_current=True)
        if task['task_type'] in ('pdf_export','layout_docx'):
            if task['task_type']=='layout_docx':
                from app.domain.layout_exports.service import LayoutExportService as PdfExportService
            else:
                from app.domain.pdf_exports.service import PdfExportService
            from app.domain.report_collections.service import scoped_store
            service=PdfExportService(scoped_store(task['user_id'],self.store.config))
            row=service.row(db,task['project_id'],snapshot['export_id']);service.verify(db,row)
            return dict(file_id=None,filename=row['input_json']['source']['metadata']['filename'],analysis_run_id=None,is_current=True)
        if task['task_type'] in ('manuscript_draft','manuscript_docx'):
            from app.domain.manuscripts.service import ManuscriptService
            from app.domain.manuscripts.sources import changes
            from app.domain.report_collections.service import scoped_store
            service=ManuscriptService(scoped_store(task['user_id'],self.store.config))
            version=service.verify_task(db,task)
            return dict(file_id=None,filename=version['snapshot_json']['title'],analysis_run_id=None,is_current=not bool(changes(service,task['project_id'],version['snapshot_json'])))
        if task['task_type'] == 'literature_assistance':
            from app.domain.literature_assistance.service import require_snapshot
            snapshot = require_snapshot(task)
            current = True
            if snapshot['input']['kind'] in ('evidence_review','evidence_comparison'):
                from app.domain.literature_assistance.service import LiteratureAssistanceService
                try:
                    LiteratureAssistanceService(self.store).assert_current(task)
                except StorageError as exc:
                    if exc.status not in (404,409): raise
                    current = False
            return dict(file_id=None,filename=snapshot['input'].get('research_topic') or snapshot['material']['claim']['content'],analysis_run_id=None,is_current=current)
        if task['task_type'] == 'literature_search':
            from app.domain.literature.service import require_snapshot
            snapshot = require_snapshot(task)
            return dict(file_id=None, filename=snapshot['input']['research_topic'], analysis_run_id=None, is_current=True)
        if task['task_type'] == 'statistics_compute':
            from app.domain.statistics_execution.service import require_snapshot
            snapshot = require_snapshot(task)
            current = db.execute('SELECT setup_json FROM analysis_setups WHERE file_id=%s',(snapshot['file']['id'],)).fetchone()
            return dict(file_id=snapshot['file']['id'],filename=snapshot['file']['filename'],analysis_run_id=None,
                is_current=bool(current and json.loads(current['setup_json'])==snapshot['setup']),
                **({'dataset_source':snapshot['setup']['source']} if snapshot['setup'].get('source') else {}))
        if task['task_type'] in ('figure_projection','figure_workbench','figure_explanation'):
            from app.domain.figure_workbench.tasks import task_source
            return task_source(self.store, db, task)
        if task['task_type'] == 'collection_word_report':
            from app.domain.report_collections.service import collection_task_source
            return collection_task_source(self.store, db, task)
        if task['task_type'] == 'analysis_recommendation':
            from app.domain.analysis_recommendation.service import RecommendationService
            snapshot=RecommendationService(DatasetTaskAssets(self.store.user_id,self.store.config)).require_material(task)
            return dict(file_id=snapshot['source']['file_id'],filename=snapshot['filename'],analysis_run_id=None,is_current=True,dataset_source=snapshot['source'])
        if task['task_type'] == 'analysis_plan':
            from app.domain.analysis_plan.service import validate_snapshot, AnalysisPlanService
            snapshot = validate_snapshot(task)
            assets = DatasetTaskAssets(self.store.user_id, self.store.config)
            if task['workflow_version'] in ('analysis_plan_v4','analysis_plan_v5'):
                view=AnalysisPlanService(assets).get_task(task['id'])
                source=view['source']
                return dict(file_id=source['file_id'] if source else None,filename=snapshot.get('filename') or '',
                            analysis_run_id=None,is_current=True,**({'dataset_source':source} if source else {}),
                            material_versions=view['evidence_versions'],
                            **({'continuation_task_id':view['continuation']['task']['id']} if view.get('continuation') else {}))
            AnalysisPlanService(assets).require_source(snapshot['source'], task['project_id'])
            return dict(file_id=snapshot['source']['file_id'], filename=snapshot['filename'],
                        analysis_run_id=None, is_current=True, dataset_source=snapshot['source'])
        if task['task_type'] == 'review_ocr':
            from app.domain.ocr_review.service import validate_snapshot, OcrReviewService
            snapshot = validate_snapshot(task)
            assets = DatasetTaskAssets(self.store.user_id,self.store.config)
            OcrReviewService(assets).require_raw(snapshot['source'],task['project_id'])
            return dict(file_id=snapshot['source']['file_id'],filename=snapshot['filename'],
                        analysis_run_id=None,is_current=True)
        if task['task_type'] == 'prepare_dataset':
            from app.domain.dataset_preparation.service import validate_snapshot, DatasetPreparationService
            snapshot = validate_snapshot(task)
            assets = DatasetTaskAssets(self.store.user_id, self.store.config)
            service = DatasetPreparationService
            if task['workflow_version'] == 'dataset_preparation_v2':
                from app.domain.dataset_preparation.quality_service import QualityPreparationService
                service = QualityPreparationService
            elif task['workflow_version']=='dataset_preparation_v3':
                from app.domain.dataset_preparation.derivation_service import DerivationPreparationService
                service=DerivationPreparationService
            service(assets).require_raw(snapshot['source'], task['project_id'])
            return dict(file_id=snapshot['source']['file_id'], filename=snapshot['filename'],
                        analysis_run_id=None, is_current=True, dataset_source=snapshot['source'])
        if task['task_type'] in ('parse_file','extract_dataset'):
            if task['task_type'] == 'extract_dataset':
                from app.domain.datasets.snapshots import require_structure_source as require_parse_source, validate_snapshot
            else:
                from app.domain.file_parsing import require_parse_source, validate_snapshot
            snapshot = validate_snapshot(task)
            self.store.require_project(db, task['project_id'])
            try:
                require_parse_source(db, task)
                is_current = True
            except StorageError:
                is_current = False
            return dict(file_id=snapshot['file']['id'], filename=snapshot['file']['filename'],
                        analysis_run_id=None, is_current=is_current)
        try:
            request = TaskCreateRequest(task_type=task['task_type'], file_id=snapshot['file']['id'],
                analysis_run_id=snapshot['result']['id'], expected_revision=snapshot['result']['setup_revision'],
                figure_id=snapshot['figure']['id'] if task['task_type'] in ('explanation', 'word_report') else None,
                explanation_id=snapshot['explanation']['id'] if task['task_type'] == 'word_report' else None)
            project = self.store.require_project(db, task['project_id'])
            # Historical configuration changes do not invalidate an intact
            # frozen source, but must never hide corruption of that source.
            if ('source' in snapshot or 'source' in snapshot['result']
                    or task['workflow_version'].endswith('_v2')):
                from app.domain.analysis_sources import source_dict
                from app.domain.dataset_analysis import load_dataset
                frozen = source_dict(snapshot['source'])
                if (snapshot['schema_version'] != 2 or type(snapshot['schema_version']) is not int
                        or snapshot['result'].get('source') != frozen
                        or frozen['file_id'] != request.file_id
                        or frozen['source_sha256'] != snapshot['file']['sha256']
                        or task['workflow_version'] != task['task_type'] + '_v2'):
                    raise source_conflict()
                try:
                    load_dataset(DatasetTaskAssets(self.store.user_id, self.store.config), project['id'],
                                 request.file_id, frozen['dataset_id'], expected_source=frozen)
                except StorageError as exc:
                    raise source_conflict() from exc
            from app.domain.analysis_plan.service import validate_plan_reference
            validate_plan_reference(DatasetTaskAssets(self.store.user_id, self.store.config),
                                    project['id'], request.file_id, snapshot['result'])
            try:
                current = self.store.source_snapshot(db, project, request)
                is_current = snapshots_match(current, snapshot)
            except StorageError as exc:
                if exc.code != 'task_source_conflict':
                    raise
                is_current = False
            return dict(file_id=request.file_id, filename=snapshot['file']['filename'],
                        analysis_run_id=request.analysis_run_id, is_current=is_current,
                        **({'dataset_source': snapshot['source']} if 'source' in snapshot else {}))
        except (KeyError, TypeError, ValueError) as exc:
            raise source_conflict() from exc

    def list(self, project_id, *, page=1, page_size=10, status=None, task_type=None):
        if (type(page) is not int or not 1 <= page <= 1_000_000
                or type(page_size) is not int or not 1 <= page_size <= 50
                or status not in (None, 'queued', 'running', 'waiting_input', 'waiting_confirmation', 'succeeded', 'failed')
                or task_type not in (None, 'boxplot', 'explanation', 'word_report', 'parse_file', 'extract_dataset', 'prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'figure_projection', 'figure_workbench', 'figure_explanation', 'collection_word_report', 'statistics_compute', 'literature_search', 'literature_assistance', 'manuscript_draft', 'manuscript_docx', 'pdf_export', 'layout_docx', 'manuscript_writing', 'school_template_parse', 'journal_recommendation', 'journal_format_check', 'journal_adaptation')):
            raise StorageError('task_input_invalid', '任务列表查询参数无效。', 422)
        from app.adapters.legacy_task_query import mixed_task_page, require_legacy_task
        from app.domain.tasks.legacy import public_legacy_task, legacy_source
        from app.domain.tasks.legacy_artifacts import exact_legacy_artifact
        with self.store.connection() as db:
            self.store.require_project(db, project_id)
            total, rows = mixed_task_page(db, self.store.user_id, project_id, page=page, page_size=page_size,
                                         status=status, task_type=task_type)
            items = []
            for candidate in rows:
                if candidate['origin'] == 'legacy':
                    row = require_legacy_task(db, self.store.user_id, candidate['id'])
                    items.append({'task': public_legacy_task(row, exact_legacy_artifact(db, row)),
                                  'source': legacy_source(row)})
                else:
                    row = self.store.require_task(db, candidate['id'])
                    items.append({'task': self.store.public_task(row), 'source': self.source(db, row)})
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
            if (value.get('source') != snapshot['result'].get('source')
                    or snapshot.get('source') != snapshot['result'].get('source')
                    or value['id'] != reference or value['analysis_run_id'] != snapshot['result']['id']
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
                from app.adapters.report_store import digest
                if (saved_input.get('source') != snapshot.get('source')
                        or value['input_sha256'] != digest(saved_input)
                        or row['explanation_id'] != snapshot['explanation']['id']
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
        if task['task_type'] in ('school_template_parse','journal_recommendation', 'journal_format_check', 'journal_adaptation'): return result
        if task['task_type']=='manuscript_writing':
            from app.domain.manuscript_writing.service import require_snapshot
            require_snapshot(task)
            return result
        if task['task_type'] in ('pdf_export','layout_docx'):
            if task['task_type']=='layout_docx':
                from app.domain.layout_exports.service import LayoutExportService as PdfExportService
            else:
                from app.domain.pdf_exports.service import PdfExportService
            from app.domain.report_collections.service import scoped_store
            service=PdfExportService(scoped_store(task['user_id'],self.store.config))
            row=service.row(db,task['project_id'],task['input_snapshot']['export_id']);view=service.view(db,row)
            if view['download_url']: result['report']=dict(filename=view['filename'],download_url=view['download_url'])
            return result
        if task['task_type'] in ('manuscript_draft','manuscript_docx'):
            from app.domain.manuscripts.service import ManuscriptService
            from app.domain.report_collections.service import scoped_store
            service=ManuscriptService(scoped_store(task['user_id'],self.store.config))
            version=service.verify_task(db,task)
            result['manuscript']=dict(id=version['manuscript_id'],version_id=version['id'],revision=version['revision'],download_url=None)
            if task['task_type']=='manuscript_docx':
                view=service.export_view(db,version,task['input_snapshot']['export_id'])
                if view['download_url']: result['report']=dict(filename=view['filename'],download_url=view['download_url'])
            return result
        if task['task_type'] == 'literature_assistance':
            from app.domain.literature_assistance.service import LiteratureAssistanceService
            view = LiteratureAssistanceService(self.store).view(db,task['project_id'],task['id'])
            result['literature_assistance'] = dict(kind=view['kind'],result=view['result'],real_calls_enabled=False)
            return result
        if task['task_type'] == 'literature_search':
            from app.domain.literature.service import require_snapshot
            require_snapshot(task)
            row = db.execute('SELECT retrieved_count,matched_count FROM literature_searches WHERE task_id=%s', (task['id'],)).fetchone()
            if not row: raise source_conflict()
            result['literature'] = dict(search_id=task['id'], **dict(row))
            return result
        if task['task_type'] in ('figure_projection','figure_workbench','figure_explanation'):
            from app.domain.figure_workbench.tasks import task_artifacts
            return task_artifacts(self.store, db, task)
        if task['task_type'] == 'collection_word_report':
            from app.domain.report_collections.service import collection_task_artifact
            result['report'] = collection_task_artifact(self.store, db, task)
            return result
        if task['task_type'] == 'statistics_compute':
            if task.get('result_analysis_run_id'):
                from app.domain.statistics_execution.execution import assets_for
                from app.adapters.task_execution_store import TaskExecutionStore
                assets = assets_for(TaskExecutionStore(config=self.store.config), task)
                value = assets.analysis_result_by_id(task['project_id'],task['input_snapshot']['file']['id'],task['result_analysis_run_id'])
                result['analysis'] = value
            return result
        if task['task_type'] in ('analysis_plan','analysis_recommendation'):
            return result
        if task['task_type'] == 'review_ocr':
            row = db.execute('SELECT id,version FROM ocr_review_versions WHERE task_id=%s',(task['id'],)).fetchone()
            if row:
                from app.domain.ocr_review.service import OcrReviewService
                summary = OcrReviewService(DatasetTaskAssets(self.store.user_id,self.store.config)).get_version(
                    task['project_id'],task['input_snapshot']['source']['file_id'],row['id'])
                result['ocr_review'] = dict(filename=f"ocr-review-v{row['version']}.json",download_url=summary['download_url'])
            return result
        if task['task_type'] == 'prepare_dataset':
            row = db.execute('SELECT id,version FROM prepared_dataset_versions WHERE task_id=%s',(task['id'],)).fetchone()
            if row:
                from app.domain.dataset_preparation.service import DatasetPreparationService
                assets = DatasetTaskAssets(self.store.user_id, self.store.config)
                summary = DatasetPreparationService(assets).get_version(task['project_id'], task['input_snapshot']['source']['file_id'], row['id'])
                result['dataset'] = dict(filename=f"prepared-data-v{row['version']}.json",download_url=summary['download_url'])
            return result
        if task['task_type'] in ('parse_file','extract_dataset'):
            return result
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
            from app.domain.tasks.legacy import is_legacy_id, public_legacy_task, legacy_source
            if is_legacy_id(task_id):
                from app.adapters.legacy_task_query import require_legacy_task
                from app.domain.tasks.legacy_artifacts import exact_legacy_artifact, legacy_artifacts
                row = require_legacy_task(db, self.store.user_id, task_id)
                artifact = exact_legacy_artifact(db, row)
                return {'task': public_legacy_task(row, artifact), 'source': legacy_source(row),
                        'wait': None, 'allowed_actions': [], 'artifacts': legacy_artifacts(row, artifact)}
            task = self.store.require_task(db, task_id)
            source = self.source(db, task)
            return {'task': self.store.public_task(task), 'source': source, 'wait': get_open_wait(db, task),
                    'allowed_actions': allowed_recovery_actions(db, task) if source['is_current'] else [],
                    'artifacts': self.artifacts(db, task),
                    **({'verification_failure':task['verification_failure']} if task.get('verification_failure') else {})}
