"""Immutable local author-guide versions and ordinary target confirmation."""
import re
import hashlib
from contextlib import nullcontext
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.literature.service import digest
from app.domain.dataset_preparation.service import require_key
from .service import JournalService,invalid,now
from .format_contracts import GuideRequest,TargetRequest
from .guide_rules import extract_requirements,select_requirements

TABLES=('journal_guides','journal_targets','journal_format_checks','journal_adaptations','journal_submission_events')

class GuideService(JournalService):
    def row(self,db,project,identity,table='journal_guides'):
        if table not in TABLES:return super().row(db,project,identity,table)
        self.project(db,project)
        row=db.execute('SELECT * FROM '+table+' WHERE id=%s AND project_id=%s AND user_id=%s',(identity,project,self.store.user_id)).fetchone()
        if not row:raise StorageError('not_found','指南、目标或格式检查批次不存在。',404)
        self.validate(row)
        if row['snapshot_json']['project_id']!=project:raise source_conflict()
        return row

    def insert(self,db,table,project,key,body,snapshot,**columns):
        names=['id','project_id','user_id','idempotency_key','request_json','request_digest','snapshot_json','snapshot_sha256','created_at',*columns]
        values=[snapshot['id'],project,self.store.user_id,key,Jsonb(body),digest(body),Jsonb(snapshot),digest(snapshot),now(),*columns.values()]
        db.execute('INSERT INTO '+table+'('+','.join(names)+') VALUES ('+','.join(['%s']*len(names))+')',tuple(values))

    def guides(self,project):return self.snapshots(project,'journal_guides')
    def targets(self,project):return self.snapshots(project,'journal_targets')
    def snapshots(self,project,table):
        assert table in TABLES
        with self.store.connection() as db:
            self.project(db,project);rows=db.execute('SELECT * FROM '+table+' WHERE project_id=%s AND user_id=%s ORDER BY created_at DESC,id',(project,self.store.user_id)).fetchall()
            for row in rows:self.validate(row)
            return dict(items=[r['snapshot_json'] for r in rows])
    def get_guide(self,project,identity):
        with self.store.connection() as db:return self.row(db,project,identity)['snapshot_json']
    def get_target(self,project,identity):
        with self.store.connection() as db:return self.target_row(db,project,identity)['snapshot_json']

    def fetch_guide(self,project,identity,key):
        """Acquire only a saved, owned and explicitly permitted guide source."""
        from .configuration import configured_web_adapter
        from .web import guide_text
        require_key(key);replay_body=dict(fetch_guide_id=identity)
        with self.store.connection(write=True) as db:
            self.project(db,project,True)
            old=self.replay(db,'journal_guides',project,key,replay_body)
            if old:return old['snapshot_json'],200
            parent=self.row(db,project,identity)['snapshot_json']
            if parent['synthetic'] or parent['permission_status']!='allowed' or parent['source_status']!='available' or not parent['source_url']:
                raise invalid('仅允许读取本项目已登记且许可允许、状态可用的非合成指南来源。',422)
            if db.execute('SELECT id FROM journal_guides WHERE previous_version_id=%s',(identity,)).fetchone():
                raise invalid('指南已有后续版本，请从后续版本继续更新。')
            try:
                result=configured_web_adapter().fetch_result(parent['source_url'])
                text=guide_text(result['body'],result['content_type'])
            except (ValueError,UnicodeError,OSError) as exc:
                raise invalid('受控指南获取失败：'+str(exc),409 if 'disabled' in str(exc) else 422) from exc
            checksum=hashlib.sha256(result['body']).hexdigest()
            data={field:parent[field] for field in GuideRequest.model_fields}
            data.update(previous_version_id=identity,source_text=text,source_url=result['final_url'],
                source_version='web-sha256:'+checksum,acquired_on=now().date(),requirements=[],material=None)
            request=GuideRequest.model_validate(data)
            retrieval={key:result[key] for key in ('final_url','content_type','etag','last_modified')}
            retrieval.update(requested_url=parent['source_url'],body_sha256=checksum,bytes=len(result['body']),
                fetched_at=now().isoformat(),official_verification='not_established')
            return self.create_guide(project,request,key,_db=db,_replay_body=replay_body,_retrieval=retrieval)

    def create_guide(self,project,request,key,*,_db=None,_replay_body=None,_retrieval=None):
        require_key(key);body=request.model_dump(mode='json')
        replay_body=body if _replay_body is None else _replay_body
        with (nullcontext(_db) if _db is not None else self.store.connection(write=True)) as db:
            self.project(db,project,True);old=self.replay(db,'journal_guides',project,key,replay_body)
            if old:return old['snapshot_json'],200
            profile=self.row(db,project,request.profile_id,'journal_profiles')['snapshot_json']
            parent=self.row(db,project,request.previous_version_id)['snapshot_json'] if request.previous_version_id else None
            if (profile['synthetic'] or parent and parent['synthetic']) and request.source_type!='synthetic':raise invalid('合成档案/指南来源链不能升级为真实材料。',422)
            if parent and parent['profile_id']!=request.profile_id:raise invalid('指南后续版本必须保留同一固定档案版本。',422)
            if parent and db.execute('SELECT id FROM journal_guides WHERE previous_version_id=%s',(parent['id'],)).fetchone():raise invalid('指南已有后续版本，请从后续版本继续更新。')
            material=self.material(project,request.material) if request.material else None
            items=(material or {}).get('content',{}).get('items',[])
            if request.material and not items and not request.source_text.strip():
                raise invalid('所选公共材料版本没有可定位原文；请先解析/OCR核对或选择可读版本。',422)
            extracted=extract_requirements(request.source_text) if request.extract else []
            if request.extract:
                for item in items:
                    extracted.extend(extract_requirements(item.get('text',''),location_prefix='material:'+str(item.get('id',item.get('location')))))
            for i,rule in enumerate(extracted):rule['id']='extracted:'+str(i+1)
            manual=body['requirements']
            for rule in manual:
                line=re.fullmatch(r'line:([1-9]\d*)',rule['location'])
                text_lines=request.source_text.splitlines()
                text_match=False
                if line and int(line[1])<=len(text_lines):
                    start=int(line[1])-1;first=rule['quote'].splitlines()[0]
                    offset=text_lines[start].find(first)
                    text_match=offset>=0 and '\n'.join(text_lines[start:])[offset:].startswith(rule['quote'])
                matched_item=next((i for i in items if rule['quote'] in i.get('text','') and rule['location'] in (i.get('id'),str(i.get('location')))),None)
                if not text_match and matched_item is None:raise invalid('要求引文未在登记原文或材料的对应位置找到；粘贴原文请使用准确line:N。',422)
                # Validate against the complete located source lines. Quoting a
                # substring must not discard an article qualifier/count scope.
                source_lines=text_lines[start:start+len(rule['quote'].splitlines())] if text_match else []
                if matched_item is not None and not text_match:
                    text=matched_item['text'];position=text.index(rule['quote'])
                    begin=text.rfind('\n',0,position)+1;end=text.find('\n',position+len(rule['quote']))
                    source_lines=text[begin:None if end<0 else end].splitlines()
                explicit=[r for r in extract_requirements('\n'.join(source_lines)) if r['key']==rule['key']]
                from .display import STYLE_KEYS
                if rule['status']=='known' and rule['key'] in (*STYLE_KEYS,'section_display_names') and not explicit:raise invalid('显示规则必须使用明确对象、数值及单位的完整有限原句；不能更换标题/正文适用对象。',422)
                if any(r.get('count_method')!=rule.get('count_method') or r.get('article_type')!=rule.get('article_type') for r in explicit):raise invalid('人工纠正须保留原句明确文章类型及计数口径；未知口径不能仅靠选择升级。',422)
                if rule['status']=='known':
                    values=rule['value'].values() if isinstance(rule['value'],dict) else rule['value'] if isinstance(rule['value'],list) else [rule['value']]
                    for value in values:
                        if type(value) is int:
                            if not re.search(r'(?<!\d)'+str(value)+r'(?!\d)',rule['quote']):raise invalid('数值要求必须逐项有原句数字依据。',422)
                        elif isinstance(value,str) and value.casefold() not in rule['quote'].casefold():raise invalid('标题/样式要求必须逐项有原句依据。',422)
                    if explicit and any(r['value']!=rule['value'] for r in explicit):raise invalid('人工纠正不能反转原句明确数字、列表或布尔要求。',422)
                replacements=[r for r in extracted if (r['key'],r.get('article_type'),r.get('origin'))==(rule['key'],rule.get('article_type'),rule.get('origin'))]
                if replacements and not rule['note'].strip():raise invalid('人工纠正已提取要求时请填写解释；原提取条款会保留。',422)
            replaced={(r['key'],r.get('article_type'),r.get('origin')) for r in manual}
            requirements=[r for r in extracted if (r['key'],r.get('article_type'),r.get('origin')) not in replaced]+manual
            if len({r['id'] for r in requirements})!=len(requirements):raise invalid('人工和提取要求ID重复。',422)
            identity=str(uuid4());synthetic=request.source_type=='synthetic'
            version=digest(dict(requirements=requirements,source_version=request.source_version,article_types=request.article_types))
            snapshot=body|dict(id=identity,project_id=project,material=material,requirements=requirements,extracted_requirements=extracted,requirements_version=version,synthetic=synthetic,verification_level='synthetic_material_only' if synthetic else 'user_material_only',created_at=now().isoformat())
            if _retrieval is not None:snapshot.update(retrieval=_retrieval,verification_level='web_fetch_unverified')
            self.insert(db,'journal_guides',project,key,replay_body,snapshot,profile_id=request.profile_id,previous_version_id=request.previous_version_id,requirements_version=version)
            if material:
                columns={k:None for k in ('document_version_id','ocr_review_version_id','external_evidence_version_id')}
                if material['kind']!='original':columns[material['kind']+'_id']=material['id']
                db.execute('INSERT INTO journal_material_refs(id,project_id,user_id,guide_id,file_id,document_version_id,ocr_review_version_id,external_evidence_version_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',(str(uuid4()),project,self.store.user_id,identity,material['file_id'],*columns.values()))
            return snapshot,201

    def target_row(self,db,project,identity):
        row=self.row(db,project,identity,'journal_targets');snap=row['snapshot_json']
        recommendation=super().row(db,project,row['recommendation_id']);JournalService.view(self,db,recommendation)
        if snap['guide']!=self.row(db,project,row['guide_id'])['snapshot_json'] or snap['recommendation_id']!=row['recommendation_id'] or snap['profile_id']!=row['profile_id']:raise source_conflict()
        for guide in snap.get('additional_guides',[]):
            if self.row(db,project,guide['id'])['snapshot_json']!=guide:raise source_conflict()
        return row

    def create_target(self,project,request,key):
        require_key(key);body=request.model_dump(mode='json')
        with self.store.connection(write=True) as db:
            self.project(db,project,True);old=self.replay(db,'journal_targets',project,key,body)
            if old:return self.target_row(db,project,old['id'])['snapshot_json'],200
            recommendation=super().row(db,project,request.recommendation_id);view=JournalService.view(self,db,recommendation)
            if view['task']['status']!='succeeded' or not view['result']:raise invalid('只能从已完成的固定建议批次确认目标。')
            candidates=view['result']['candidates']+view['result']['pending_verification']
            candidate=next((c for c in candidates if c['profile']['id']==request.profile_id),None)
            if candidate is None:raise invalid('目标必须来自该固定批次候选/待核实列表，不能选择排除项或其他档案。',422)
            guide=self.row(db,project,request.guide_id)['snapshot_json']
            if guide['profile_id']!=request.profile_id or guide['requirements_version']!=request.requirements_version:raise invalid('目标档案或指南要求版本不匹配。',422)
            if request.article_type not in guide['article_types']:raise invalid('指南未明确适用于所选文章类型，请登记适用指南版本。',422)
            extras=[self.row(db,project,i)['snapshot_json'] for i in request.additional_guide_ids]
            if any(g['profile_id']!=request.profile_id or request.article_type not in g['article_types'] for g in extras):raise invalid('补充来源需属于同一固定期刊档案且明确适用文章类型。',422)
            rules=[];warnings=[]
            for source in [guide,*extras]:
                rules.extend(dict(r,id=source['id']+':'+r['id'],source_id=source['id'],source_version=source['source_version']) for r in source['requirements'])
                for flag,condition,message in [('source_status',source['source_status']!='available','指南来源不可用或已失效，保留旧证据但不能确认规则可用。'),('permission_status',source['permission_status']!='allowed','指南许可/使用条件尚未允许或待核实，不能默认可用。')]:
                    if condition:warnings.append(dict(key=flag,source_id=source['id'],message=message,blocks_rules=True))
            unit=candidate['profile']['fields'].get('unit_requirements')
            requested_units=view['input_snapshot']['research'].get('unit_requirements',[])
            if unit or requested_units:
                warnings.append(dict(key='unit_requirements',source_id=None,actual=dict(requested=requested_units,profile=unit.get('value') if unit else None),evidence=[unit] if unit else [],message='单位标签只保留原始条件，未结构化的单位要求仍需人工核对，不能默认为满足；涉及SCI/指标的事实仍关闭。',blocks_rules=False))
            try:selected,conflicts,decisions=select_requirements(rules,request.article_type,body['resolutions'])
            except ValueError as exc:raise invalid(str(exc),422) from exc
            identity=str(uuid4());timestamp=now().isoformat()
            snapshot=body|dict(id=identity,project_id=project,candidate=candidate,guide=guide,additional_guides=extras,selected_requirements=selected,conflicts=conflicts,decisions=decisions,warnings=warnings,synthetic=bool(candidate['profile']['synthetic'] or any(g['synthetic'] for g in [guide,*extras])),confirmed_by=self.store.user_id,confirmed_at=timestamp)
            self.insert(db,'journal_targets',project,key,body,snapshot,recommendation_id=request.recommendation_id,profile_id=request.profile_id,guide_id=request.guide_id)
            from app.domain.admin_configuration.bindings import bind,resolve
            bind(db,kind='journal_confirmation',object_id=identity,version=resolve(db,kind='task',object_id=recommendation['task_id']))
            return snapshot,201
