"""Link public work without claiming completion; adopt only verified CPU output."""
from copy import deepcopy
from contextlib import nullcontext
import json
from uuid import uuid4

from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key
from app.domain.literature.service import digest
from .service import ReviewRoundService
from .planning import invalid
from .figure_adoptions import FigureAdoptions


PURPOSE_TYPES = {
    'retrieval': {'literature_search', 'literature_assistance'},
    'statistics': {'statistics_compute'},
    'projection': {'figure_projection'},
    'plot': {'boxplot', 'figure_workbench'},
    'writing': {'manuscript_draft', 'manuscript_writing'},
    'revision': {'review_revision', 'journal_adaptation'},
}


class ScienceService(FigureAdoptions, ReviewRoundService):
    def validate_link_task(self, db, task):
        """Keep the public request digest separate from a full snapshot hash."""
        from app.domain.tasks.workspace import TaskWorkspaceService
        kind, snapshot = task['task_type'], task['input_snapshot']
        try:
            if kind in ('figure_projection', 'figure_workbench'):
                from app.adapters.figure_workbench_store import FigureWorkbenchStore, projection_request_digest, validate_projection_checkpoint
                from app.domain.figure_workbench.tasks import task_source
                task_source(self.store, db, task)
                workbench = FigureWorkbenchStore(self.assets)
                result = snapshot['result']
                row = workbench._version(db, task['project_id'], result['file_id'], result['id'], snapshot['figure_workbench']['version_id'])
                if snapshot['output_language'] != row['config_json']['language']:
                    raise source_conflict()
                if kind == 'figure_projection':
                    if task['workflow_version'] not in ('figure_projection_v1', 'figure_projection_v2'):
                        raise source_conflict()
                    checkpoint = db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1', (task['id'],)).fetchone()
                    validate_projection_checkpoint(task, checkpoint)
                    expected = (projection_request_digest(row) if task['workflow_version'] == 'figure_projection_v2'
                        else workbench.material(task['project_id'], result['file_id'], result['id'], row['id'])[2]['input_sha256'])
                else:
                    if task['workflow_version'] != 'figure_workbench_v1':
                        raise source_conflict()
                    external = snapshot['external_processing']
                    expected = digest(dict(version_id=row['id'], figure_id=None,
                        external={k: external[k] for k in ('confirmed', 'payload_sha256')}))
                if task['input_digest'] != expected:
                    raise source_conflict()
            elif kind == 'boxplot':
                from app.domain.tasks.contracts import TaskCreateRequest
                from app.domain.external_processing import request_digest, validate_frozen
                external = snapshot.get('external_processing')
                confirmation = None
                if external is not None:
                    validate_frozen(snapshot, kind, task['user_id'], external)
                    confirmation = dict(version=external['version'], confirmed=True,
                        source_digest=external['source_digest'], labels=external['labels'])
                request = TaskCreateRequest(task_type=kind, file_id=snapshot['file']['id'],
                    analysis_run_id=snapshot['result']['id'], expected_revision=snapshot['result']['setup_revision'],
                    external_processing=confirmation)
                if task['input_digest'] != request_digest(request):
                    raise source_conflict()
                TaskWorkspaceService(self.store.user_id, self.store.config).source(db, task)
            elif kind in set().union(*PURPOSE_TYPES.values()):
                if digest(snapshot) != task['input_digest']:
                    raise source_conflict()
            else:
                raise source_conflict()
        except (KeyError, TypeError, ValueError):
            raise source_conflict() from None

    def current_item(self, db, project, round_id, plan_revision, item_id, *, lock=False):
        row = self.round_row(db, project, round_id, lock)
        state, events = self.state(db, row)
        if not events or events[-1]['revision'] != plan_revision:
            raise StorageError('task_revision_conflict', '本轮计划或决定已变化，请刷新。', 409)
        item = next((i for i in state['items'] if i['id'] == item_id), None)
        if item is None:
            raise invalid('意见不属于本轮。')
        return row, state, item

    def science_row(self, db, project, identity, table):
        assert table in ('review_opinion_task_links', 'review_analysis_adoptions', 'review_figure_adoptions')
        self.project(db, project)
        row = db.execute('SELECT * FROM ' + table + ' WHERE id=%s AND project_id=%s AND user_id=%s',
                         (identity, project, self.store.user_id)).fetchone()
        if not row:
            raise StorageError('not_found', '意见关联或分析采用不存在。', 404)
        self.validate(row)
        snapshot=row['snapshot_json']
        if any(snapshot.get(k)!=row[k] for k in ('project_id','round_id','item_id','plan_revision')):
            raise source_conflict()
        return row

    def link_view(self, db, row):
        self.validate(row)
        task = self.store.require_task(db, row['task_id'])
        snap = row['snapshot_json']
        round=self.round_row(db,row['project_id'],row['round_id'])
        generation=next((e for e in self.events(db,round) if e['revision']==row['plan_revision']),None)
        item=next((i for i in generation['snapshot_json']['items'] if i['id']==row['item_id']),None) if generation else None
        if (not item or snap['item_revision']!=item['revision'] or snap['manuscript_version_id']!=round['snapshot_json']['manuscript']['version_id']
                or snap['task_id']!=row['task_id'] or task['task_type'] not in PURPOSE_TYPES.get(snap['purpose'],set())
                or task['project_id'] != row['project_id'] or task['input_digest'] != snap['task_input_digest']
                or ('task_snapshot_sha256' in snap and digest(task['input_snapshot']) != snap['task_snapshot_sha256'])):
            raise source_conflict()
        self.validate_link_task(db, task)
        public = self.store.public_task(task)
        if public['input_version']!=snap['input_version']:raise source_conflict()
        result = {k: deepcopy(public.get(k)) for k in ('result_analysis_run_id', 'result_figure_id', 'result_report_id', 'execution_receipt')}
        result['available'] = task['status'] == 'succeeded'
        result['workspace_url'] = '/api/v1/tasks/' + task['id'] + '/workspace'
        result['artifacts'] = {}
        result['public_result_url'] = None
        if task['status'] == 'succeeded':
            from app.domain.tasks.workspace import TaskWorkspaceService
            result['artifacts'] = TaskWorkspaceService(self.store.user_id, self.store.config).artifacts(db, task)
            prefix = '/api/v1/projects/' + row['project_id']
            if task['task_type'] == 'literature_search':
                result['public_result_url'] = prefix + '/literature/searches/' + task['id']
                result['artifacts']['literature']['references_url'] = prefix + '/literature/references?search_id=' + task['id']
                result['artifacts']['literature']['support_review_required'] = True
            elif task.get('result_analysis_run_id'):
                result['public_result_url'] = prefix + '/files/' + task['input_snapshot']['file']['id'] + '/analysis-runs/' + task['result_analysis_run_id']
            elif result['artifacts'].get('manuscript'):
                manuscript = result['artifacts']['manuscript']
                result['public_result_url'] = prefix + '/manuscripts/' + manuscript['id'] + '/versions/' + str(manuscript['revision'])
            elif task['task_type'] == 'manuscript_writing':
                from app.domain.manuscript_writing.service import WritingService
                manuscript_id = task['input_snapshot']['manuscript_id']
                writing = WritingService(self.assets).view(db, row['project_id'], manuscript_id, task['id'])
                result['artifacts']['writing'] = dict(request_id=task['id'], candidate_available=writing['candidate'] is not None,
                    published_revision=writing['published_revision'], model_calls=writing['model_calls'])
                result['public_result_url'] = prefix + '/manuscripts/' + manuscript_id + '/writing-requests/' + task['id']
            elif task['task_type'] == 'review_revision':
                result['public_result_url'] = prefix + '/reviews/revisions/' + task['input_snapshot']['id']
        return dict(id=row['id'], round_id=row['round_id'], item_id=row['item_id'], plan_revision=row['plan_revision'],
                    input_snapshot=deepcopy(snap), task=public, result=result, created_at=row['created_at'])

    def get_science(self, project, round_id):
        with self.store.connection() as db:
            row = self.round_row(db, project, round_id)
            _, events = self.state(db, row)
            links = db.execute('SELECT * FROM review_opinion_task_links WHERE round_id=%s ORDER BY created_at,id', (round_id,)).fetchall()
            adoptions = db.execute('SELECT * FROM review_analysis_adoptions WHERE round_id=%s ORDER BY created_at,id', (round_id,)).fetchall()
            return dict(round_id=round_id, plan_revision=events[-1]['revision'] if events else 1,
                        task_links=[self.link_view(db, r) for r in links],
                        analysis_adoptions=[self.adoption_view(self.validate_adoption(db, r)) for r in adoptions],
                        figure_adoptions=[self.figure_adoption_view(self.validate_figure_adoption(db,r)) for r in db.execute('SELECT * FROM review_figure_adoptions WHERE round_id=%s ORDER BY created_at,id',(round_id,)).fetchall()],
                        pending=['新增外部检索和模型绘图等待独立授权；任务关联不代表意见已完成。'])

    def create_link(self, project, round_id, request, key, *, request_body=None, creation_kind=None, db=None):
        require_key(key)
        body = request.model_dump(mode='json') if request_body is None else request_body
        with (nullcontext(db) if db is not None else self.store.connection(write=True)) as db:
            self.project(db, project, True)
            old = self.replay(db, 'review_opinion_task_links', project, key, body)
            if old:
                if old['round_id'] != round_id:
                    raise StorageError('task_idempotency_conflict', '标识已用于其他轮次。', 409)
                return self.link_view(db, old), 200
            row, _, item = self.current_item(db, project, round_id, request.plan_revision, request.item_id, lock=True)
            task = self.store.require_task(db, request.task_id)
            if task['project_id'] != project:
                raise StorageError('not_found', '任务不属于当前项目。', 404)
            if task['task_type'] not in PURPOSE_TYPES[request.purpose]:
                raise invalid('关联用途与公共任务类型不一致。')
            public = self.store.public_task(task)
            snap = dict(id=str(uuid4()), project_id=project, round_id=round_id, item_id=item['id'],
                        item_revision=item['revision'], plan_revision=request.plan_revision, purpose=request.purpose,
                        manuscript_version_id=row['snapshot_json']['manuscript']['version_id'], task_id=task['id'],
                        task_input_digest=task['input_digest'], task_snapshot_sha256=digest(task['input_snapshot']), input_version=public['input_version'],
                        synthetic=bool(row['snapshot_json']['synthetic']))
            if request_body is not None:
                if creation_kind is None:
                    snap['statistics_request'] = deepcopy(request_body)
                else:
                    snap.update(creation_kind=creation_kind, creation_request=deepcopy(request_body))
            self.insert(db, 'review_opinion_task_links', project, key, body, snap,
                        round_id=round_id, item_id=item['id'], plan_revision=request.plan_revision, task_id=task['id'])
            return self.link_view(db, self.science_row(db, project, snap['id'], 'review_opinion_task_links')), 201

    def adoption_view(self, row):
        self.validate(row)
        snap = row['snapshot_json']
        return dict(id=row['id'], round_id=row['round_id'], item_id=row['item_id'], plan_revision=row['plan_revision'],
                    input_snapshot=deepcopy(snap), source=deepcopy(snap['source']), impact=deepcopy(snap['impact']),
                    pending=deepcopy(snap['pending']), created_at=row['created_at'])

    def create_statistics(self, project, round_id, request, key):
        """Queue through the existing public statistics service, without computing."""
        from app.domain.descriptive import RunRequest
        from app.domain.statistics_execution.service import create, validate_setup
        from .science_contracts import TaskLinkRequest
        require_key(key)
        body = request.model_dump(mode='json')
        with self.store.connection(write=True) as db:
            self.project(db, project, True)
            self.round_row(db, project, round_id)
            old = self.replay(db, 'review_opinion_task_links', project, key, body)
            if old:
                if old['round_id'] != round_id or old['snapshot_json'].get('statistics_request') != body:
                    raise StorageError('task_idempotency_conflict', '标识已用于其他轮次或关联。', 409)
                return self.link_view(db, old), 200
            self.current_item(db, project, round_id, request.plan_revision, request.item_id, lock=True)
            self.assets.file(project, request.file_id)
            saved = db.execute('SELECT setup_json FROM analysis_setups WHERE file_id=%s', (request.file_id,)).fetchone()
            if not saved:
                raise invalid('请先确认数据与分析计划。', 409)
            setup = json.loads(saved['setup_json'])
            if setup['revision'] != request.expected_setup_revision:
                raise StorageError('setup_conflict', '分析配置已变化，请刷新。', 409)
            if not setup.get('source') or not setup.get('analysis_plan') or not validate_setup(self.assets, project, request.file_id, setup):
                raise invalid('仅能复用已确认整理数据及分析计划创建本地统计任务。', 409)
            # The public queue and full review request commit together.
            # An interrupted link rolls back the task and outbox as well.
            task = create(project, request.file_id, RunRequest(expected_revision=request.expected_setup_revision,
                idempotency_key='review-statistics:' + digest(dict(round_id=round_id, key=key))), self.assets, db=db)
            link_request = TaskLinkRequest(plan_revision=request.plan_revision, item_id=request.item_id, task_id=task['id'], purpose='statistics')
            result, status = self.create_link(project, round_id, link_request, key, request_body=body, db=db)
            return result, 202 if status == 201 else status

    def create_figure_task(self, project, round_id, request, key, *, plot=False):
        """Commit the full review request and public queue as one transaction."""
        from app.adapters.figure_workbench_store import FigureWorkbenchStore
        from .science_contracts import TaskLinkRequest
        require_key(key)
        body = request.model_dump(mode='json')
        kind = 'plot' if plot else 'projection'
        workbench = FigureWorkbenchStore(self.assets)
        with self.store.connection(write=True) as db:
            self.project(db, project, True)
            self.round_row(db, project, round_id)
            old = self.replay(db, 'review_opinion_task_links', project, key, body)
            if old:
                snap = old['snapshot_json']
                if old['round_id'] != round_id or snap.get('creation_kind') != kind or snap.get('creation_request') != body:
                    raise StorageError('task_idempotency_conflict', '标识已用于其他轮次或关联。', 409)
                return self.link_view(db, old), 200
            self.current_item(db, project, round_id, request.plan_revision, request.item_id, lock=True)
            row = workbench._version(db, project, request.file_id, request.analysis_run_id, request.figure_config_version_id)
            if plot:
                projection = workbench._projection(db, row)
                if (not projection or projection['id'] != request.projection_id
                        or projection['result']['input_sha256'] != request.projection_input_sha256):
                    raise source_conflict()
            args = (project, request.file_id, request.analysis_run_id, request.figure_config_version_id)
            if plot:
                from app.domain.figure_workbench.contracts import GenerateFigure
                from app.domain.figure_workbench.tasks import submit
                task = submit(workbench, *args, GenerateFigure(idempotency_key='review-plot:' + digest(dict(round_id=round_id, key=key)),
                    external_processing=request.external_processing), db=db)['task']
            else:
                checked = workbench.check(*args, db=db)
                task = checked.get('task')
                if task is None:
                    # A style-only version reuses the real parent projection task.
                    # The selected version remains fixed in creation_request.
                    row = workbench._version(db, *args)
                    projection = workbench._projection(db, row)
                    decision = db.execute('SELECT task_id FROM figure_projection_decisions WHERE id=%s', (projection['decision_id'],)).fetchone() if projection else None
                    if not decision:
                        raise source_conflict()
                    task = self.store.public_task(self.store.require_task(db, decision['task_id']))
            link = TaskLinkRequest(plan_revision=request.plan_revision, item_id=request.item_id, task_id=task['id'], purpose=kind)
            result, status = self.create_link(project, round_id, link, key, request_body=body, creation_kind=kind, db=db)
            return result, 202 if status == 201 else status

    def validated_analysis(self, db, project, task, *, require_current):
        from app.domain.statistics_execution.service import require_snapshot, validate_setup
        from app.domain.statistics_execution.verification import require_receipt, validate_statistics_receipt
        if task['project_id'] != project or task['task_type'] != 'statistics_compute' or task['status'] != 'succeeded' or not task.get('result_analysis_run_id'):
            raise invalid('必须先等待本地统计公共任务实际成功。', 409)
        frozen = require_snapshot(task)
        setup = frozen['setup']
        if not setup.get('source') or not setup.get('analysis_plan') or not frozen.get('plan'):
            raise invalid('统计结果缺少已确认数据和分析计划。', 409)
        if validate_setup(self.assets, project, frozen['file']['id'], setup) != frozen['plan']:
            raise source_conflict()
        if require_current:
            current = db.execute('SELECT setup_json FROM analysis_setups WHERE file_id=%s', (frozen['file']['id'],)).fetchone()
            if not current or json.loads(current['setup_json']) != setup:
                raise StorageError('setup_conflict', '分析配置或计划已经变化，请重新计算后采用。', 409)
        source = self.material(project, dict(kind='analysis_run', id=task['result_analysis_run_id'], file_id=frozen['file']['id'], role='computed_results'))
        receipt = validate_statistics_receipt(task.get('execution_receipt'))
        if receipt['status'] != 'succeeded' or receipt['result_sha256'] != digest(source['content']):
            raise source_conflict()
        require_receipt(self.assets, project, source['file_id'], source['content'], allow_legacy=False)
        return source

    def create_adoption(self, project, round_id, request, key):
        from .science_candidates import analysis_impact
        require_key(key)
        body = request.model_dump(mode='json')
        with self.store.connection(write=True) as db:
            self.project(db, project, True)
            old = self.replay(db, 'review_analysis_adoptions', project, key, body)
            if old:
                if old['round_id'] != round_id:
                    raise StorageError('task_idempotency_conflict', '标识已用于其他轮次。', 409)
                self.validate_adoption(db, old)
                return self.adoption_view(old), 200
            round, _, item = self.current_item(db, project, round_id, request.plan_revision, request.item_id, lock=True)
            base = self.fixed(db, round)
            link = self.science_row(db, project, request.task_link_id, 'review_opinion_task_links')
            if (link['round_id'] != round_id or link['item_id'] != item['id']
                    or link['snapshot_json']['item_revision'] != item['revision'] or link['snapshot_json']['purpose'] != 'statistics'):
                raise invalid('统计任务必须关联本轮当前意见和计划版本。', 409)
            self.link_view(db, link)
            task = self.store.require_task(db, link['task_id'])
            source = self.validated_analysis(db, project, task, require_current=True)
            prior = {s['id']: s for s in base['snapshot_json']['sources']}
            supersedes = request.supersedes_source_ids
            if len(set(supersedes)) != len(supersedes) or source['id'] in supersedes or any(s not in prior or prior[s]['kind'] != 'analysis_run' or prior[s]['role'] != 'computed_results' for s in supersedes):
                raise invalid('被替代来源必须是固定父稿的不同统计结果。')
            if db.execute('SELECT id FROM review_analysis_adoptions WHERE round_id=%s AND item_id=%s AND analysis_run_id=%s', (round_id, item['id'], source['id'])).fetchone():
                raise invalid('本轮该意见已经采用此统计结果，请复用已有采用记录。', 409)
            impact = analysis_impact(base['snapshot_json'], supersedes, body['affected_locations'])
            snap = dict(id=str(uuid4()), project_id=project, round_id=round_id, item_id=item['id'], item_revision=item['revision'],
                plan_revision=request.plan_revision, manuscript_version_id=base['id'], task_link_id=link['id'], task_id=task['id'],
                task_input_digest=task['input_digest'], execution_receipt=deepcopy(task['execution_receipt']), source=source,
                confirmed_plan=deepcopy(task['input_snapshot']['plan']), confirmed_data=deepcopy(task['input_snapshot']['setup']['source']),
                supersedes_source_ids=supersedes, affected_locations=body['affected_locations'], reason=request.reason,
                impact=impact, pending=['未生成新的数值图；需要新图的意见继续等待图件及授权。'], synthetic=bool(round['snapshot_json']['synthetic']))
            self.insert(db, 'review_analysis_adoptions', project, key, body, snap,
                round_id=round_id, item_id=item['id'], plan_revision=request.plan_revision, link_id=link['id'],
                analysis_run_id=source['id'], manuscript_version_id=base['id'])
            saved = self.science_row(db, project, snap['id'], 'review_analysis_adoptions')
            return self.adoption_view(saved), 201

    def validate_adoption(self, db, row, *, require_current=False):
        """Historical validation keeps the frozen plan, not today's setup revision."""
        self.validate(row)
        frozen = row['snapshot_json']
        round = self.round_row(db, row['project_id'], row['round_id'])
        if (frozen['round_id'] != row['round_id'] or frozen['item_id'] != row['item_id'] or frozen['plan_revision'] != row['plan_revision']
                or frozen['manuscript_version_id'] != row['manuscript_version_id']
                or round['snapshot_json']['manuscript']['version_id'] != row['manuscript_version_id']):
            raise source_conflict()
        link = self.science_row(db, row['project_id'], row['link_id'], 'review_opinion_task_links')
        self.link_view(db, link)
        if link['id'] != frozen['task_link_id'] or link['item_id'] != row['item_id'] or link['round_id'] != row['round_id']:
            raise source_conflict()
        task = self.store.require_task(db, link['task_id'])
        source = self.validated_analysis(db, row['project_id'], task, require_current=require_current)
        if (source != frozen['source'] or source['id'] != row['analysis_run_id'] or task['id'] != frozen['task_id']
                or task['input_digest'] != frozen['task_input_digest'] or task['execution_receipt'] != frozen['execution_receipt']
                or task['input_snapshot']['plan'] != frozen['confirmed_plan'] or task['input_snapshot']['setup']['source'] != frozen['confirmed_data']):
            raise source_conflict()
        return row

    def selected_adoptions(self, db, project, round_id, identities, plan_revision=None, *, require_current=False):
        if len(set(identities)) != len(identities):
            raise invalid('分析采用不能重复。')
        rows = []
        for identity in identities:
            row = self.science_row(db, project, identity, 'review_analysis_adoptions')
            if row['round_id'] != round_id:
                raise invalid('分析采用不属于当前轮次。')
            if plan_revision is not None:
                # Explicit selection under the current plan CAS reuses this
                # opinion's sealed analysis; it never rewrites the adoption.
                self.current_item(db, project, round_id, plan_revision, row['item_id'])
            self.validate_adoption(db, row, require_current=require_current)
            rows.append(row)
        superseded = [sid for row in rows for sid in row['snapshot_json']['supersedes_source_ids']]
        if len(set(superseded)) != len(superseded):
            raise invalid('同一旧结果不能在一个候选中被多个新结果替代。')
        return rows
