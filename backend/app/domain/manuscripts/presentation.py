"""Fixed bilingual associations and append-only user presentation metadata."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import re
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key
from app.domain.literature.service import digest
from app.domain.manuscript_review.facts import displayed_paragraphs
from app.domain.manuscript_writing.numeric_review import numbers
from .illustrations import BODY_REFERENCE
from .presentation_contracts import PresentationRequest, PresentationConfig, STATEMENT_KINDS

def invalid(message):return StorageError('task_input_invalid',message,422)
def missing():return StorageError('manuscript_not_found','输出配置或固定稿件不存在。',404)

def validate_language_confirmation(items,review):
    from app.domain.manuscript_writing.school_language import validate_decisions
    validate_decisions(items,dict(inventory_sha256=digest(items),decisions=[d.model_dump() for d in review.decisions]))
    return dict(status='confirmed',source_export_id=review.source_export_id,source_sha256=review.source_sha256,inventory_sha256=digest(items),decision_count=len(review.decisions))

def _config_payload(config):
    payload=config.model_dump()
    if payload.get('language_review') is None:payload.pop('language_review',None)
    return payload

def _paragraphs(snapshot):
    return {p['id']:dict(deepcopy(p),section_id=role) for role,p in displayed_paragraphs(snapshot)}

def _citation_ids(paragraphs,snapshot):
    refs={r.get('id'):r for r in snapshot.get('references',[])}
    result=set()
    for p in paragraphs:
        for citation in p.get('citations',[]):
            row=refs.get(citation) if isinstance(citation,str) else citation
            if not row:result.add('unresolved:'+str(citation));continue
            identity=row.get('project_reference_id') or row.get('metadata_version_id') or row.get('citation_version_id') or row.get('id')
            if identity:result.add(identity)
            else:result.add('unresolved:'+digest(row))
    return result

def _source_ids(paragraphs,snapshot):
    sources={s['id']:s for s in snapshot.get('sources',[])}
    result=set()
    for identity in {s for p in paragraphs for s in p.get('source_ids',[])}:
        source=sources.get(identity)
        if source is None:result.add(identity);continue
        if source['kind']=='figure_language_version':
            original=source.get('content',{}).get('original',{})
            result.add((original.get('kind'),original.get('id'),original.get('sha256')))
        else:result.add((source['kind'],identity,source.get('sha256')))
    return result

def _text_without_citation_numbers(paragraphs,snapshot):
    from app.domain.manuscript_writing.context import citation_prose
    return '\n'.join(citation_prose(snapshot,p) if p.get('citations') else p['text'] for p in paragraphs)

def _markers(text):
    clean=BODY_REFERENCE.sub('',text)
    units=set(re.findall(r'(?<![A-Za-z])(?:mg|μg|µg|ug|ng|kg|g|mL|ml|µL|μL|L|mmol|µmol|μmol|mol|mm|cm|nm|h|min|s|%)(?![A-Za-z])',clean))
    na=bool(re.search(r'\b(?:NA|N/A|NaN)\b|缺失|不可用|未检出',clean,re.I))
    directions=set()
    for key,pattern in [('up',r'上升|升高|增加|高于|\b(?:increase\w*|higher|upregulated)\b'),('down',r'下降|降低|减少|低于|\b(?:decrease\w*|lower|downregulated)\b')]:
        if re.search(pattern,clean,re.I):directions.add(key)
    return set(numbers(clean)),units,na,directions

def build_preview(request,base,peer,base_sha,peer_sha):
    """Bounded observations, never semantic approval or translated text."""
    request=PresentationRequest.model_validate(request) if isinstance(request,dict) else request
    config=_config_payload(request.config);checks=[];groups=[]
    def add(code,status,message,**extra):checks.append(dict(code=code,status=status,message=message,**extra))
    snaps={s['output_language']:s for s in (base,peer) if s is not None}
    if peer and len(snaps)!=2:raise ValueError('Bilingual peer must have a different output language')
    lookup={lang:_paragraphs(s) for lang,s in snaps.items()}
    for group in request.config.paragraph_groups:
        sides={}
        for lang,key in [('zh-CN','zh_ids'),('en','en_ids')]:
            ids=getattr(group,key)
            if any(i not in lookup.get(lang,{}) for i in ids):raise ValueError('Unknown fixed paragraph identity for '+lang)
            sides[lang]=[lookup[lang][i] for i in ids]
        zh,en=sides['zh-CN'],sides['en'];groups.append(dict(id=group.id,zh=zh,en=en,status=group.status))
        if not zh or not en or group.status!='paired':
            add('group:'+group.id+':pairing','pending','缺译或未确认对应。',group_id=group.id);continue
        ztext='\n'.join(p['text'] for p in zh);etext='\n'.join(p['text'] for p in en)
        try:
            ztext=_text_without_citation_numbers(zh,snaps['zh-CN']);etext=_text_without_citation_numbers(en,snaps['en'])
            zm,em=_markers(ztext),_markers(etext)
            for i,key in enumerate(('numbers','units','na','direction')):
                add('group:'+group.id+':'+key,'passed' if zm[i]==em[i] else 'conflict','固定文本有限'+key+'核对；不替代科学语义审查。',group_id=group.id)
        except ValueError:
            add('group:'+group.id+':numbers','pending','缺精确引用片段或存在需人工解释的数值表达，未猜测移除括号数字。',group_id=group.id)
        def facts(paragraphs):
            # Occurrence order and local model aliases may change across languages;
            # source identity is checked separately against frozen catalog hashes.
            return {digest({k:b[k] for k in ('kind','source_id','fact_id','fact_path','value','evidence_id') if k in b}) for p in paragraphs for b in p.get('numeric_bindings',[])}
        zfacts,efacts=facts(zh),facts(en)
        add('group:'+group.id+':fact_identity','passed' if zfacts and zfacts==efacts else 'conflict' if zfacts!=efacts else 'pending','比较已审核事实路径/数值；缺结构化绑定不提升为事实验证。',group_id=group.id)
        for key,z,e in [('source_identity',_source_ids(zh,snaps['zh-CN']),_source_ids(en,snaps['en'])),('citation_identity',_citation_ids(zh,snaps['zh-CN']),_citation_ids(en,snaps['en']))]:
            unresolved=any(str(i).startswith('unresolved:') for i in z|e)
            add('group:'+group.id+':'+key,'pending' if unresolved else 'passed' if z==e else 'conflict','比较稳定来源身份，允许引用显示编号变化。',group_id=group.id)
        for term in request.config.terminology:
            if term.zh in ztext:
                matched=any(value.casefold() in etext.casefold() for value in [term.en,*term.variants])
                add('group:'+group.id+':term:'+term.zh,'conflict' if not matched else 'passed' if term.state=='known' else 'pending','术语仅按明确词表匹配，未全局替换。',group_id=group.id)
    for lang,items in lookup.items():
        used={i for g in request.config.paragraph_groups for i in (g.zh_ids if lang=='zh-CN' else g.en_ids)}
        unpaired=sorted(set(items)-used)
        if peer and unpaired:add('unpaired:'+lang,'pending','存在未关联段落。',paragraph_ids=unpaired)
    # Frozen paragraph locations feed the existing actual-export language inventory.
    # Actual OOXML inventory still runs at export; preview never renders a DOCX.
    inventories=[]
    for lang,snapshot in snaps.items():
        for role,p in displayed_paragraphs(snapshot):
            inventories.append(dict(location=lang+':'+p['id'],kind='export_text',text=p['text'],content_sha256=digest(p['text']),expected_language=lang,section_id=role))
        add('language:'+lang,'pending','逐位置预期语言已固定；原语言审核继续适用，配置保存不构成新语言审核。')
    figures={lang:{f['id']:f for g in snap.get('results_groups',[]) for f in g.get('figures',[])} for lang,snap in snaps.items()}
    for pair in request.config.figure_pairs:
        z=figures.get('zh-CN',{}).get(pair.zh_figure_id);e=figures.get('en',{}).get(pair.en_figure_id)
        if not z or not e:raise ValueError('Unknown fixed figure identity')
        same=_source_ids([z],snaps['zh-CN'])==_source_ids([e],snaps['en'])
        add('figure:'+pair.figure_id+':identity','passed' if same else 'conflict','图来源身份核对。')
        add('figure:'+pair.figure_id+':caption','pending','题注身份 '+pair.caption_identity+' 由用户关联，语义仍待人工核对。')
        add('figure:'+pair.figure_id+':language','pending' if pair.language_status!='known' or not pair.source else 'passed','只记录有来源的图语言确认，图内科学含义仍需人工。')
    school=request.config.school
    if school:
        context=base.get('thesis_context')
        if not context:raise ValueError('School presentation requires a frozen school manuscript')
        chapters={c['id']:c for c in context['chapters']};included=set(school.include_chapter_ids);excluded=set(school.exclude_chapter_ids)
        if not (included|excluded)<=set(chapters) or included&excluded:raise ValueError('Unknown or contradictory school chapter selection')
        if any(c['purpose']=='abstract' and (c['id'] in excluded or included and c['id'] not in included) for c in chapters.values()):raise ValueError('Mandatory bilingual abstracts cannot be excluded')
        manual={c.chapter_id:c.text for c in school.options.manual_chapters}
        if any(i not in chapters or chapters[i]['purpose']!='manual' for i in manual):raise ValueError('Manual text must bind existing manual chapter identity')
        for supplement in school.supplements:
            chapter=chapters.get(supplement.chapter_id)
            if not chapter or chapter['purpose'] not in ('manual','acknowledgements'):raise ValueError('Supplement requires existing manual/acknowledgements chapter')
            existing=next((s for s in base.get('sections',[]) if s['id']==supplement.chapter_id),{})
            supplied=manual.get(supplement.chapter_id,'').strip() or any(p.get('text','').strip() and not p.get('id','').endswith(':pending') for p in existing.get('paragraphs',[]))
            ready=bool(supplied and supplement.source.strip())
            add('school:supplement:'+supplement.chapter_id,'passed' if ready else 'pending','真实提供补充内容与来源；缺失保持待补。')
        limits=school.length_requirements
        from app.domain.journals.format_rules import count_text
        for i,limit in enumerate(limits):
            parts=[];selected_chapters=[];manual_chapters=[];pending_chapters=[]
            for section in base.get('sections',[]):
                chapter_id=section['id'];chapter=chapters[chapter_id]
                if chapter_id in excluded or included and chapter_id not in included:continue
                role=section.get('purpose',chapter['purpose'])
                language=section.get('output_language',chapter.get('output_language',base['output_language']))
                if language!=limit.language:continue
                if limit.scope=='abstract' and role!='abstract':continue
                if limit.scope=='body' and role in ('abstract','references','title','manual','acknowledgements'):continue
                selected_chapters.append(chapter_id)
                if chapter_id in manual and manual[chapter_id].strip():
                    parts.append(manual[chapter_id]);manual_chapters.append(chapter_id)
                else:
                    paragraphs=section.get('paragraphs',[])
                    parts.extend(p['text'] for p in paragraphs if not p.get('id','').endswith(':pending'))
                    if any(p.get('id','').endswith(':pending') for p in paragraphs):pending_chapters.append(chapter_id)
            text='\n'.join(parts);counts=count_text(text,limit.language)
            actual=len(re.sub(r'\s','',text)) if limit.unit=='characters' else counts['hanzi']+counts['latin_words'] if limit.language=='zh-CN' else counts['whitespace_words']
            passed=actual>=limit.value if limit.kind=='minimum' else actual<=limit.value
            projection=dict(chapter_ids=selected_chapters,manual_chapter_ids=manual_chapters,pending_chapter_ids=pending_chapters,
                language=limit.language,scope=limit.scope,count_method='non_whitespace_characters' if limit.unit=='characters' else 'zh_hanzi_latin_words' if limit.language=='zh-CN' else 'en_whitespace_words',
                excluded_components=['headings','cover','captions','tables','reference_list','authors','affiliations','statements','toc','headers_footers','image_text'])
            pending=limit.scope=='whole' or not selected_chapters or bool(pending_chapters)
            message=('按固定章节语言及本次纳入/排除、人工替换观察；whole仅为章节文本观察，作者/声明等不在本投影中，须按实际导出核定。' if limit.scope=='whole' else '按固定章节语言及本次纳入/排除、人工替换计数；待补占位不当真实正文，不等同Word字数。')
            message+=' 口径：'+('非空白字符数。' if limit.unit=='characters' else '汉字数加拉丁词数。' if limit.language=='zh-CN' else '英文按空白分词。')
            add('school:length:'+str(i),'pending' if pending else 'passed' if passed else 'conflict',message,actual=actual,observed_count=actual,count_projection=projection,requirement=limit.model_dump())
        for a in limits:
            for b in limits:
                if a.kind=='minimum' and b.kind=='maximum' and (a.scope,a.language,a.unit)==(b.scope,b.language,b.unit) and a.value>b.value:
                    add('school:length_conflict','conflict','同一语言、范围和单位的学校最低篇幅超过上限。')
        if school.guide_version_id:add('journal:guide','pending','固定指南另由现有期刊规则检查，不将字段保存视为合规。')
    chapters={s['id'] for snap in snaps.values() for s in snap.get('sections',[])}
    if not set(request.config.blind.hidden_chapter_ids)<=chapters:raise ValueError('Unknown blind hidden chapter identity')
    for kind in STATEMENT_KINDS:
        statement=next((s for s in request.config.statements if s.kind==kind),None)
        add('statement:'+kind,'pending' if not statement or statement.state=='pending' else 'passed','仅记录用户声明、依据和状态；不自动推定合规。')
    add('authors','passed' if request.config.authors else 'pending','作者顺序及单位由用户提供；缺失不猜填。')
    add('blind:images','passed' if request.config.blind.manual_image_review else 'pending','图片、扫描签名及嵌入对象须人工检查。')
    add('blind:rules','passed' if request.config.blind.identity_terms else 'pending','盲审须明确身份词和例外；自动扫描不能保证匿名。')
    return dict(schema_version=1,base_version_id=request.base_version_id,peer_version_id=request.peer_version_id,base_sha256=base_sha,peer_sha256=peer_sha,config=config,checks=checks,paragraph_groups=groups,language_inventory=inventories,quality=dict(scientific_semantic='pending',word_wps='pending',real_compliance='pending'),can_export=not any(c['status']=='conflict' for c in checks))

class PresentationService:
    def __init__(self,manuscripts):self.manuscripts=manuscripts;self.store=manuscripts.store

    def _version(self,db,project,identity,provided=None):
        if provided is not None and provided['id']==identity:
            if provided['project_id']!=project or provided['user_id']!=self.store.user_id:raise missing()
            return provided
        row=db.execute('SELECT * FROM manuscript_versions WHERE id=%s AND project_id=%s AND user_id=%s',(identity,project,self.store.user_id)).fetchone()
        if not row:raise missing()
        self.manuscripts.validate_version(db,row)
        if self.store.require_task(db,row['task_id'])['status']!='succeeded':raise source_conflict()
        return row

    def _prepare(self,db,project,identity,request,base_version=None):
        root=self.manuscripts.root(db,project,identity)
        base=self._version(db,project,request.base_version_id,base_version)
        if base['manuscript_id']!=identity:raise invalid('基础版本须属于当前稿件。')
        peer=self._version(db,project,request.peer_version_id) if request.peer_version_id else None
        if peer:
            other=self.manuscripts.root(db,project,peer['manuscript_id'])
            if root.get('document_kind')!=other.get('document_kind') or bool(base['snapshot_json'].get('thesis_context'))!=bool(peer['snapshot_json'].get('thesis_context')):raise invalid('两侧稿件类型必须兼容。')
        try:preview=build_preview(request,base['snapshot_json'],peer['snapshot_json'] if peer else None,base['snapshot_sha256'],peer['snapshot_sha256'] if peer else None)
        except ValueError as exc:raise invalid(str(exc)) from exc
        guide_id=request.config.guide_version_id or (request.config.school.guide_version_id if request.config.school else None)
        if guide_id:
            guide=db.execute('SELECT * FROM journal_guides WHERE id=%s AND project_id=%s AND user_id=%s',(guide_id,project,self.store.user_id)).fetchone()
            if not guide:raise missing()
            if digest(guide['snapshot_json'])!=guide['snapshot_sha256'] or digest(guide['request_json'])!=guide['request_digest']:raise source_conflict()
            from app.domain.journals.guide_rules import select_requirements
            from app.domain.journals.format_rules import check_format
            selected,conflicts,_=select_requirements(guide['snapshot_json']['requirements'],base['snapshot_json'].get('article_type'),[])
            warnings=[]
            if guide['snapshot_json'].get('permission_status')!='allowed' or guide['snapshot_json'].get('source_status')!='available':warnings.append(dict(message='指南权限或资料状态待核实。',blocks_rules=True))
            result=check_format(base['snapshot_json'],selected,conflicts,warnings=warnings)
            preview['journal_check']=dict(result,guide_id=guide['id'],guide_sha256=guide['snapshot_sha256'],requirements_version=guide['snapshot_json']['requirements_version'])
            preview['checks']=[c for c in preview['checks'] if c['code']!='journal:guide']
            for item in result['items']:
                preview['checks'].append(dict(code='journal:'+item['id'],status='passed' if item['status']=='pass' else 'conflict' if item['status']=='mismatch' else 'pending',message=item['reason']))
            preview['can_export']=not any(c['status']=='conflict' for c in preview['checks'])
        if request.config.language_review:
            proof=self._language_review(db,project,identity,request,base,peer)
            preview['language_review']=proof
            preview['checks'].append(dict(code='language:actual_export',status='passed',message='已逐项确认固定实际导出清单；只对相同字节、输出语言和审稿方式有效，不替代语义审核。'))
        return base,peer,preview

    def _language_review(self,db,project,identity,request,base,peer):
        review=request.config.language_review
        export=db.execute('SELECT e.* FROM manuscript_exports e JOIN manuscript_versions v ON v.id=e.version_id WHERE e.id=%s AND v.manuscript_id=%s AND v.project_id=%s AND v.user_id=%s',(review.source_export_id,identity,project,self.store.user_id)).fetchone()
        if not export or export['version_id']!=base['id']:raise source_conflict()
        task=self.store.require_task(db,export['task_id']);metadata=export['metadata_json'] or {};presentation=metadata.get('presentation') or {};binding=presentation.get('binding') or {}
        if (task['status']!='succeeded' or task['task_type']!='manuscript_docx' or task['project_id']!=project or task['user_id']!=self.store.user_id
            or digest(task['input_snapshot'])!=task['input_digest'] or task['input_snapshot'].get('export_id')!=export['id']
            or task['input_snapshot'].get('manuscript_version_id')!=base['id'] or task['input_snapshot'].get('manuscript_id')!=identity
            or metadata.get('sha256')!=review.source_sha256 or metadata.get('input_sha256')!=base['snapshot_sha256']
            or (task['input_snapshot'].get('presentation') or {}).get('binding')!=binding
            or binding.get('base_version_id')!=base['id'] or binding.get('base_sha256')!=base['snapshot_sha256']
            or binding.get('language_view')!=review.language_view or binding.get('review_mode')!=review.review_mode):raise source_conflict()
        source_id=binding.get('presentation_version_id')
        if not source_id:raise source_conflict()
        source,_,_,old=self.fixed(db,project,identity,source_id,base_version=base,peer_version=peer)
        if (binding.get('presentation_sha256')!=source['snapshot_sha256'] or binding.get('config_sha256')!=digest(old['config'])
            or binding.get('peer_version_id')!=(peer['id'] if peer else None) or binding.get('peer_sha256')!=(peer['snapshot_sha256'] if peer else None)
            or PresentationConfig.model_validate(old['config']).model_dump(exclude={'language_review'})!=request.config.model_dump(exclude={'language_review'})):raise source_conflict()
        try:raw=(self.manuscripts.directory/(export['id']+'.docx')).read_bytes()
        except OSError as exc:raise source_conflict() from exc
        if len(raw)!=metadata.get('size_bytes') or sha256(raw).hexdigest()!=review.source_sha256:raise source_conflict()
        items=presentation.get('language_inventory')
        if not isinstance(items,list) or not items:raise invalid('来源实际导出缺少逐项语言清单。')
        try:return validate_language_confirmation(items,review)
        except ValueError as exc:raise invalid(str(exc)) from exc

    def preview(self,project,identity,request):
        with self.store.connection() as db:return self._prepare(db,project,identity,request)[2]

    def fixed(self,db,project,identity,presentation_id,base_version=None,peer_version=None):
        self.manuscripts.root(db,project,identity)
        row=db.execute('SELECT * FROM manuscript_presentation_versions WHERE id=%s AND manuscript_id=%s AND project_id=%s AND user_id=%s',(presentation_id,identity,project,self.store.user_id)).fetchone()
        if not row:raise missing()
        if digest(row['request_json'])!=row['request_digest'] or digest(row['snapshot_json'])!=row['snapshot_sha256']:raise source_conflict()
        request=PresentationRequest.model_validate(row['request_json'])
        base=self._version(db,project,request.base_version_id,base_version)
        peer=self._version(db,project,request.peer_version_id,peer_version) if request.peer_version_id else None
        preview=row['snapshot_json']
        if (base['manuscript_id']!=identity or base['id']!=row['base_version_id'] or preview['base_sha256']!=base['snapshot_sha256'] or preview.get('peer_sha256')!=(peer['snapshot_sha256'] if peer else None) or row['peer_version_id']!=request.peer_version_id or preview['config']!=row['request_json'].get('config',{})):raise source_conflict()
        return row,base,peer,deepcopy(preview)

    def _view(self,db,row,base,peer,preview):
        stale=[]
        for version in (base,peer):
            if version is None:continue
            head=db.execute('SELECT current_revision FROM manuscripts WHERE id=%s',(version['manuscript_id'],)).fetchone()
            if head['current_revision']!=version['revision']:stale.append(version['id'])
        return dict(preview,id=row['id'],manuscript_id=row['manuscript_id'],revision=row['revision'],created_at=row['created_at'],stale=bool(stale),stale_version_ids=stale,config_sha256=digest(preview['config']))

    def get(self,project,identity,presentation_id):
        with self.store.connection() as db:return self._view(db,*self.fixed(db,project,identity,presentation_id))

    def list(self,project,identity):
        with self.store.connection() as db:
            self.manuscripts.root(db,project,identity)
            rows=db.execute('SELECT id,base_version_id,peer_version_id FROM manuscript_presentation_versions WHERE manuscript_id=%s AND project_id=%s AND user_id=%s ORDER BY revision DESC',(identity,project,self.store.user_id)).fetchall()
            versions={version_id:self._version(db,project,version_id) for version_id in {v for r in rows for v in (r['base_version_id'],r['peer_version_id']) if v}}
            return dict(items=[self._view(db,*self.fixed(db,project,identity,r['id'],versions[r['base_version_id']],versions.get(r['peer_version_id']))) for r in rows])

    def save(self,project,identity,request,key):
        require_key(key)
        payload=request.model_dump();payload['config']=_config_payload(request.config);request_digest=digest(payload)
        with self.store.connection(write=True) as db:
            self.manuscripts.root(db,project,identity)
            db.execute('SELECT id FROM manuscripts WHERE id=%s FOR UPDATE',(identity,)).fetchone()
            prior=db.execute('SELECT id,request_digest FROM manuscript_presentation_versions WHERE manuscript_id=%s AND idempotency_key=%s',(identity,key)).fetchone()
            if prior:
                if prior['request_digest']!=request_digest:raise StorageError('task_idempotency_conflict','请求键已用于不同输出配置。',409)
                return self._view(db,*self.fixed(db,project,identity,prior['id'])),200
            latest=db.execute('SELECT coalesce(max(revision),0) AS revision FROM manuscript_presentation_versions WHERE manuscript_id=%s',(identity,)).fetchone()['revision']
            if request.expected_revision!=latest:raise StorageError('manuscript_revision_conflict','输出配置已更新，请刷新后重试。',409)
            base,peer,preview=self._prepare(db,project,identity,request)
            identity_id=str(uuid4());created=datetime.now(timezone.utc)
            row=db.execute('INSERT INTO manuscript_presentation_versions(id,manuscript_id,project_id,user_id,revision,base_version_id,peer_version_id,idempotency_key,request_json,request_digest,snapshot_json,snapshot_sha256,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *',(identity_id,identity,project,self.store.user_id,latest+1,base['id'],peer['id'] if peer else None,key,Jsonb(payload),request_digest,Jsonb(preview),digest(preview),created)).fetchone()
            return self._view(db,row,base,peer,preview),201
