"""Receipt-backed adoption uses only the server's successful public task result."""
from copy import deepcopy
from uuid import uuid4
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key
from app.domain.literature.service import digest
from .planning import invalid

TABLE='review_figure_adoptions'


class FigureAdoptions:
    def validated_figure(self,db,project,task,*,require_current=False):
        if task.get('task_type')=='boxplot':
            raise invalid('新图采用需要外置编号和固定配置/投影；请使用图表工作台的新图，旧箱线图仍可关联及历史读取。',409)
        if (task['project_id']!=project or task['task_type'] not in ('figure_workbench','boxplot')
            or task['status']!='succeeded' or not task.get('result_figure_id')):
            raise invalid('必须先等待公共绘图任务实际成功并保存PNG。',409)
        self.validate_link_task(db,task)
        frozen=task['input_snapshot'];result=frozen['result']
        source=self.material(project,dict(kind='figure',id=task['result_figure_id'],file_id=result['file_id'],role='image_observation'))
        figure=source['content'];raw=self.assets.figure_png(figure)
        from hashlib import sha256
        if (figure['analysis_run_id']!=result['id'] or figure['sha256']!=sha256(raw).hexdigest()
            or figure['size_bytes']!=len(raw) or figure.get('language',figure.get('output_language','zh-CN'))!=frozen['output_language']):raise source_conflict()
        if task['task_type']=='figure_workbench':
            from app.adapters.figure_workbench_store import read_bundle,FigureWorkbenchStore
            bundle=read_bundle(self.assets,project,figure['id'])
            if bundle['result']!=result or figure['figure_config_version_id']!=frozen['figure_workbench']['version_id'] or figure['projection_id']!=frozen['figure_workbench']['projection_id']:raise source_conflict()
            if require_current:
                row=FigureWorkbenchStore(self.assets)._version(db,project,result['file_id'],result['id'],figure['figure_config_version_id'])
                if row['revision']!=row['current_revision']:raise invalid('图表配置已变化，请核对后重新采用。',409)
        elif figure.get('source')!=result.get('source'):
            raise source_conflict()
        analysis=self.material(project,dict(kind='analysis_run',id=result['id'],file_id=result['file_id'],role='computed_results'))
        if analysis['content']!=result:raise source_conflict()
        if require_current:
            current=db.execute('SELECT revision FROM analysis_setups WHERE file_id=%s',(result['file_id'],)).fetchone()
            if not current or current['revision']!=result['setup_revision']:raise invalid('分析配置已变化，请重新计算后采用。',409)
        provenance=figure.get('provenance') or {}
        call=db.execute('SELECT * FROM model_calls WHERE id=%s AND task_id=%s AND project_id=%s AND user_id=%s',
            (provenance.get('model_call_id'),task['id'],project,task['user_id'])).fetchone()
        if (not call or call['provider_status']!='completed' or call['status']!='completed'
            or call['provider_response_id']!=provenance.get('response_id') or call['input_digest']!=provenance.get('model_input_digest')
            or call['model']!=provenance.get('model') or (call['provider_state'] or {}).get('container_id')!=provenance.get('container_id')):raise source_conflict()
        receipt={k:deepcopy(call[k]) for k in ('id','task_id','call_key','provider','model','input_digest','provider_status','provider_response_id','provider_request_id','provider_state')}
        return source,analysis,receipt

    def figure_adoption_view(self,row):
        self.validate(row);snap=row['snapshot_json']
        return dict(id=row['id'],round_id=row['round_id'],item_id=row['item_id'],plan_revision=row['plan_revision'],
            input_snapshot=deepcopy(snap),source=deepcopy(snap['source']),supersedes_figure_id=snap['supersedes_figure_id'],
            affected_locations=deepcopy(snap['affected_locations']),created_at=row['created_at'])

    def create_figure_adoption(self,project,round_id,request,key):
        from app.domain.manuscripts.service import ManuscriptService
        from .science_candidates import analysis_impact
        require_key(key);body=request.model_dump(mode='json')
        with self.store.connection(write=True) as db:
            self.project(db,project,True)
            old=self.replay(db,TABLE,project,key,body)
            if old:
                if old['round_id']!=round_id:raise StorageError('task_idempotency_conflict','标识已用于其他轮次。',409)
                return self.figure_adoption_view(self.validate_figure_adoption(db,old)),200
            round,_,item=self.current_item(db,project,round_id,request.plan_revision,request.item_id,lock=True)
            base=self.fixed(db,round)
            current=ManuscriptService(self.assets).root(db,project,base['manuscript_id'])['current_revision']
            if current!=request.expected_current_revision:raise StorageError('manuscript_revision_conflict','当前稿件版本已变化，请刷新。',409)
            link=self.science_row(db,project,request.task_link_id,'review_opinion_task_links')
            if (link['round_id']!=round_id or link['item_id']!=item['id'] or link['snapshot_json']['item_revision']!=item['revision']
                or link['snapshot_json']['purpose']!='plot'):raise invalid('绘图任务必须关联本轮当前意见。',409)
            self.link_view(db,link);task=self.store.require_task(db,link['task_id'])
            source,analysis,receipt=self.validated_figure(db,project,task,require_current=True)
            old_figure=next((f for g in base['snapshot_json']['results_groups'] for f in g.get('figures',[]) if f['id']==request.supersedes_figure_id),None)
            if not old_figure or source['id']==old_figure['id'] or any(f['id']==source['id'] for g in base['snapshot_json']['results_groups'] for f in g.get('figures',[])):
                raise invalid('必须明确替代固定父稿中的不同旧图。')
            if source['content'].get('language',source['content'].get('output_language','zh-CN'))!=base['snapshot_json']['output_language']:raise source_conflict()
            analysis_impact(base['snapshot_json'],[],body['affected_locations'])
            if db.execute('SELECT id FROM review_figure_adoptions WHERE round_id=%s AND item_id=%s AND figure_id=%s',(round_id,item['id'],source['id'])).fetchone():raise invalid('本意见已经保存此图采用，请复用已有记录。',409)
            snap=dict(id=str(uuid4()),project_id=project,round_id=round_id,item_id=item['id'],item_revision=item['revision'],
                plan_revision=request.plan_revision,manuscript_version_id=base['id'],task_link_id=link['id'],task_id=task['id'],
                task_input_digest=task['input_digest'],task_snapshot_sha256=digest(task['input_snapshot']),
                source=source,analysis_source=analysis,execution_receipt=receipt,png_sha256=source['sha256'],
                png_size_bytes=source['content']['size_bytes'],facts_sha256=source['content'].get('facts_sha256'),
                renderer=deepcopy(source['content']['engine']),supersedes_figure_id=old_figure['id'],
                affected_locations=body['affected_locations'],reason=request.reason,synthetic=bool(round['snapshot_json']['synthetic']))
            self.insert(db,TABLE,project,key,body,snap,round_id=round_id,item_id=item['id'],plan_revision=request.plan_revision,
                link_id=link['id'],task_id=task['id'],file_id=source['file_id'],analysis_run_id=analysis['id'],figure_id=source['id'],
                manuscript_id=base['manuscript_id'],manuscript_version_id=base['id'])
            return self.figure_adoption_view(self.science_row(db,project,snap['id'],TABLE)),201

    def validate_figure_adoption(self,db,row,*,require_current=False):
        self.validate(row);snap=row['snapshot_json'];round=self.round_row(db,row['project_id'],row['round_id'])
        if any(snap.get(k)!=row[k] for k in ('project_id','round_id','item_id','plan_revision','task_id','manuscript_version_id')) or round['snapshot_json']['manuscript']['version_id']!=row['manuscript_version_id']:raise source_conflict()
        link=self.science_row(db,row['project_id'],row['link_id'],'review_opinion_task_links');self.link_view(db,link)
        if (link['id']!=snap['task_link_id'] or link['round_id']!=row['round_id'] or link['item_id']!=row['item_id']
            or link['task_id']!=row['task_id'] or link['snapshot_json']['item_revision']!=snap['item_revision'] or link['snapshot_json']['purpose']!='plot'):raise source_conflict()
        task=self.store.require_task(db,row['task_id']);source,analysis,receipt=self.validated_figure(db,row['project_id'],task,require_current=require_current)
        if (source!=snap['source'] or analysis!=snap['analysis_source'] or receipt!=snap['execution_receipt']
            or source['id']!=row['figure_id'] or source['file_id']!=row['file_id'] or analysis['id']!=row['analysis_run_id']
            or task['input_digest']!=snap['task_input_digest'] or digest(task['input_snapshot'])!=snap['task_snapshot_sha256']):raise source_conflict()
        return row

    def selected_figure_adoptions(self,db,project,round_id,identities,plan_revision=None,*,require_current=False):
        if len(set(identities))!=len(identities):raise invalid('图采用不能重复。')
        rows=[]
        for identity in identities:
            row=self.science_row(db,project,identity,TABLE)
            if row['round_id']!=round_id:raise invalid('图采用不属于当前轮次。')
            if plan_revision is not None:
                _,_,item=self.current_item(db,project,round_id,plan_revision,row['item_id'])
                if item['revision']!=row['snapshot_json']['item_revision']:raise invalid('意见已变化，请重新核对图采用。',409)
            rows.append(self.validate_figure_adoption(db,row,require_current=require_current))
        old=[r['snapshot_json']['supersedes_figure_id'] for r in rows]
        if len(set(old))!=len(old):raise invalid('同一旧图不能在一个候选中被多个新图替代。')
        return rows
