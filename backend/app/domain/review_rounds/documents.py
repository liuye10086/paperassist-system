"""Independent immutable document snapshots from published actual changes."""
from copy import deepcopy
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.adapters.task_store import TaskStore, source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key
from app.domain.literature.service import digest
from app.domain.manuscripts.service import now
from .planning import invalid
from .document_display import change_text


def build_snapshot(row, kind, language):
    result = row['result_json']; fixed = row['snapshot_json']; en = language == 'en'
    if kind == 'reply' and fixed['project_type'] != 'sci':
        raise invalid('毕业论文不生成 SCI 回复。')
    changes = result['actual_changes']; items = []; final_locations = None
    final = row.get('_output_snapshot')
    if final:
        from .grounded import locations_for
        from app.domain.manuscript_writing.context import normalize_sections
        final_locations = {loc['id']: {k:v for k,v in loc.items() if k!='text'} for loc in locations_for(final)}
        for section in normalize_sections(final):
            for number, paragraph in enumerate(section['paragraphs'],1):
                final_locations[paragraph['id']]['paragraph_number'] = number
        for group in final.get('results_groups',[]):
            for object_kind in ('figure','table'):
                for obj in group.get(object_kind+'s',[]):
                    if obj.get('number') is not None:final_locations[obj['id']][object_kind+'_number']=obj['number']
    sources = {s['id']: s for s in fixed.get('sources', [])}
    for original in result['items']:
        item = deepcopy(original); identity = item.get('id') or item.get('item_id')
        actual = [deepcopy(c) for c in changes if c['item_id'] == identity]
        if item['status'] == 'completed' and (not actual or any(c['before'] == c['after'] for c in actual)):
            raise source_conflict()
        reason = item.get('uncompleted_reason') or item.get('not_adopt_reason') or (item.get('decision') or {}).get('reason') or ''
        if item['status'] != 'completed' and not reason:
            reason = 'No verified change was completed.' if en else '尚无已核验的实际修改。'
        if item['status'] == 'completed':
            text = ('The manuscript was revised as follows: ' if en else '稿件已作以下实际修改：') + '\n'.join(change_text(c,'after',language) for c in actual)
        elif item['status'] == 'not_adopted':
            text = ('Not adopted. Reason: ' if en else '未采纳。原因：') + reason
        else:
            if actual:
                text=('Partial changes were made: ' if en else '已作部分实际修改：')+'\n'.join(change_text(c,'after',language) for c in actual)
                text+=('\nNot fully completed. Reason: ' if en else '\n本项尚未全部完成。原因：')+reason
            else:text = ('Not completed. Reason: ' if en else '未完成，仍待补充。原因：') + reason
        locations = []
        for change in actual:
            identity_location=change['location']['id']
            if final_locations is not None and identity_location not in final_locations:
                parent=row.get('_base_snapshot')
                previous=next((f for g in (parent or {}).get('results_groups',[]) for f in g.get('figures',[]) if f['id']==identity_location),None)
                if change['kind']!='remove_figure' or change['after'] is not None or previous is None or change['before']!=previous:raise source_conflict()
                location=next({k:v for k,v in loc.items() if k!='text'} for loc in locations_for(parent) if loc['id']==identity_location and loc['kind']=='figure')
                location.update(removed_from_output=True,parent_version_id=fixed['manuscript']['version_id'],figure_number=previous.get('number'))
            else:location=deepcopy(final_locations[identity_location] if final_locations is not None else change['location'])
            if location not in locations:locations.append(location)
        # Page and line references require a renderer's exact exported file map.
        for location in locations:
            for key in ('page', 'line', 'page_number', 'line_number'):
                location.pop(key, None)
        evidence = []
        for change in actual:
            for entry in change.get('evidence', []):
                if entry not in evidence: evidence.append(deepcopy(entry))
        for entry in row.get('_fixed_evidence',[]):
            if entry['id'] in item.get('evidence_ids',[]) and entry not in evidence:evidence.append(deepcopy(entry))
        source=sources.get(item.get('source_id'),{})
        items.append(dict(item_id=identity, source_id=item.get('source_id'), source_label=item.get('source_label') or source.get('label',''),source_role=source.get('role'),source_location=deepcopy(item.get('source_location')),
            number=item.get('number'), original_number=item.get('original_number'), original_text=item['original_text'], translation=deepcopy(item.get('translation')),
            status=item['status'], reason=reason, decision=deepcopy(item.get('decision')), actual_changes=actual, evidence=evidence, locations=locations, text=text))
    return dict(title=('Point-by-point response' if kind == 'reply' else 'Revision comparison') if en else ('逐条回复' if kind == 'reply' else '逐条修改对照'),
        project_type=fixed['project_type'], kind=kind, language=language, revision_id=row['id'], round_id=row['round_id'], result_sha256=row['result_sha256'],
        output=deepcopy(result['output']), synthetic=bool(result.get('synthetic')), items=items,
        location_notice='Stable section, paragraph and figure identifiers only; pagination differs between applications.' if en else '仅使用稳定章节、段落和图表编号定位；不同软件分页可能不同，未核验 PDF 页码或行号。')


class ReviewDocumentService:
    def __init__(self, assets):
        self.assets = assets; self.store = TaskStore(assets.owner_id, assets.db_config)

    def published_revision(self, db, project, identity):
        from .revisions import RevisionService
        service = RevisionService(self.assets); row = dict(service.revision_row(db, project, identity))
        task = self.store.require_task(db, row['task_id'])
        result = row['result_json']
        if task['status'] != 'succeeded' or not result:
            raise StorageError('review_revision_not_ready', '请等待实际修改成功。', 409)
        output = result['output']; producer = self.store.require_task(db, output['task_id'])
        version = db.execute('SELECT * FROM manuscript_versions WHERE id=%s AND manuscript_id=%s AND project_id=%s AND user_id=%s',
            (output['version_id'], output['manuscript_id'], project, self.store.user_id)).fetchone()
        if not version or version['task_id'] != producer['id'] or producer['status'] != 'succeeded':
            raise StorageError('review_revision_not_ready', '请等待公共新稿成功。', 409)
        if version['revision']!=output['revision'] or digest(version['snapshot_json'])!=version['snapshot_sha256']:
            raise source_conflict()
        row['_output_snapshot']=version['snapshot_json']
        from .grounded import evidence_for
        base=db.execute('SELECT snapshot_json,snapshot_sha256 FROM manuscript_versions WHERE id=%s AND manuscript_id=%s AND project_id=%s AND user_id=%s',
            (row['manuscript_version_id'],row['manuscript_id'],project,self.store.user_id)).fetchone()
        if not base or digest(base['snapshot_json'])!=base['snapshot_sha256']:raise source_conflict()
        row['_base_snapshot']=base['snapshot_json']
        row['_fixed_evidence']=evidence_for(base['snapshot_json'],row['snapshot_json'].get('plan_state',{}).get('materials',[]))
        return row

    def row(self, db, project, identity):
        self.store.require_project(db, project)
        row = db.execute('SELECT * FROM review_documents WHERE id=%s AND project_id=%s AND user_id=%s', (identity, project, self.store.user_id)).fetchone()
        if not row: raise StorageError('review_document_not_found', '独立文档不存在。', 404)
        if digest(row['snapshot_json']) != row['snapshot_sha256'] or digest(row['request_json']) != row['request_digest']:
            raise source_conflict()
        snapshot = row['snapshot_json']
        if any(snapshot[k] != row[k] for k in ('revision_id', 'round_id', 'kind', 'language')): raise source_conflict()
        revision = self.published_revision(db, project, row['revision_id'])
        if snapshot['result_sha256'] != revision['result_sha256'] or snapshot['output'] != revision['result_json']['output']:
            raise source_conflict()
        return row

    def latest(self, db, row):
        return db.execute('SELECT MAX(version) AS version FROM review_documents WHERE revision_id=%s AND kind=%s', (row['revision_id'], row['kind'])).fetchone()['version']

    def view(self, db, row):
        return dict(id=row['id'],project_id=row['project_id'],revision_id=row['revision_id'],round_id=row['round_id'],kind=row['kind'],version=row['version'],language=row['language'],
            confirmed_at=row['confirmed_at'].isoformat() if row['confirmed_at'] else None, created_at=row['created_at'].isoformat(),snapshot=row['snapshot_json'],latest_version=self.latest(db,row))

    def existing(self, db, project, key, body):
        old = db.execute('SELECT * FROM review_documents WHERE project_id=%s AND user_id=%s AND idempotency_key=%s',(project,self.store.user_id,key)).fetchone()
        if old and old['request_digest'] != digest(body):
            raise StorageError('task_idempotency_conflict','请求标识已用于不同输入。',409)
        return old

    def insert(self, db, project, revision, snapshot, body, key):
        version = db.execute('SELECT COALESCE(MAX(version),0)+1 AS n FROM review_documents WHERE revision_id=%s AND kind=%s',(revision['id'],snapshot['kind'])).fetchone()['n']
        identity = str(uuid4())
        db.execute('INSERT INTO review_documents(id,project_id,user_id,round_id,revision_id,kind,version,language,idempotency_key,request_json,request_digest,snapshot_json,snapshot_sha256,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (identity,project,self.store.user_id,revision['round_id'],revision['id'],snapshot['kind'],version,snapshot['language'],key,Jsonb(body),digest(body),Jsonb(snapshot),digest(snapshot),now()))
        return self.view(db,self.row(db,project,identity)),201

    def create(self, project, identity, request, key):
        require_key(key);body=dict(revision_id=identity,**request.model_dump())
        with self.store.connection(write=True) as db:
            self.store.require_project(db,project);db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(project,)).fetchone()
            old=self.existing(db,project,key,body)
            if old:return self.view(db,self.row(db,project,old['id'])),200
            revision=self.published_revision(db,project,identity)
            snapshot=build_snapshot(revision,request.kind,request.language)
            return self.insert(db,project,revision,snapshot,body,key)

    def version(self,project,identity,request,key):
        require_key(key);body=dict(document_id=identity,**request.model_dump())
        with self.store.connection(write=True) as db:
            self.store.require_project(db,project);db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(project,)).fetchone()
            old=self.existing(db,project,key,body)
            if old:return self.view(db,self.row(db,project,old['id'])),200
            row=self.row(db,project,identity)
            if request.expected_version!=row['version'] or self.latest(db,row)!=row['version']:raise invalid('文档已有新版本，请刷新后编辑。',409)
            snapshot=deepcopy(row['snapshot_json']);texts={edit.item_id:edit.text for edit in request.items}
            if len(texts)!=len(request.items) or set(texts)!={i['item_id'] for i in snapshot['items']}:raise invalid('请保留所有原意见，每项仅编辑说明或回复。')
            for item in snapshot['items']:item['text']=texts[item['item_id']]
            if request.language:
                snapshot['language']=request.language
                localized=build_snapshot(self.published_revision(db,project,row['revision_id']),snapshot['kind'],request.language)
                snapshot['title']=localized['title'];snapshot['location_notice']=localized['location_notice']
            return self.insert(db,project,self.published_revision(db,project,row['revision_id']),snapshot,body,key)

    def confirm(self,project,identity,request,key):
        require_key(key)
        with self.store.connection(write=True) as db:
            self.store.require_project(db,project);db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(project,)).fetchone()
            row=self.row(db,project,identity)
            if request.expected_version!=row['version']:raise invalid('文档版本不一致。',409)
            if row['confirmed_at'] and row['confirmation_key']==key:return self.view(db,row)
            if self.latest(db,row)!=row['version']:raise invalid('只能确认当前最新文档版本。',409)
            if not row['confirmed_at']:db.execute('UPDATE review_documents SET confirmed_at=%s,confirmation_key=%s WHERE id=%s AND confirmed_at IS NULL',(now(),key,identity))
            return self.view(db,self.row(db,project,identity))

    def get(self,project,identity):
        with self.store.connection() as db:return self.view(db,self.row(db,project,identity))

    def listing(self,project,identity):
        with self.store.connection() as db:
            self.published_revision(db,project,identity)
            rows=db.execute('SELECT id FROM review_documents WHERE revision_id=%s AND project_id=%s AND user_id=%s ORDER BY kind,version DESC',(identity,project,self.store.user_id)).fetchall()
            return dict(items=[self.view(db,self.row(db,project,r['id'])) for r in rows])
