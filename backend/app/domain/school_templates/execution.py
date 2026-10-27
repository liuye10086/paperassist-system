"""The API never parses DOCX; only the fenced worker invokes the bounded process."""
from threading import Event,Thread
from psycopg.types.json import Jsonb
from app.adapters.task_execution_store import TaskExecutionStore,LeaseLost
from app.adapters.task_store import TaskStore,source_conflict
from app.core.exceptions import StorageError
from app.domain.literature.service import digest
from app.domain.report_collections.service import scoped_store
from .service import SchoolTemplateService
from .contracts import PARSER_VERSION


def supplements(analysis,row,sources):
    """Compare supported requirements using the parser's deterministic text rules."""
    from app.adapters.school_template_parser import merge_template_notes
    notes=[]
    for source in sources:
        if source['role']!='supplement':continue
        for index,item in enumerate(source['evidence']):
            if item.get('text'):
                notes.append(dict(id=f"supplement:{source['file_id']}:{index}",text=item['text'],
                    source=dict(part=source['filename'],path=f"document-version:{source['document_version_id']}:{item['id']}",text=item['text']),
                    file_id=source['file_id'],document_version_id=source['document_version_id'],location=item.get('location')))
    text=row['request_json']['supplement_text']
    if text.strip():notes.append(dict(id='supplement:text',text=text,source=dict(part='supplement_text',path='supplement_text',text=text)))
    result=merge_template_notes(analysis,notes)
    for source in sources:
        if source['role']=='supplement' and not any(item.get('text','').strip() for item in source['evidence']):
            result['unsupported'].append(dict(id='supplement-no-text:'+source['file_id'],message='补充规范的已解析证据没有可用文字；原件及位置已保留，请先完成OCR或在补充规范文本框填写。'))
    return result


def run_school_template_task(task_id,task_revision,*,config=None,directory=None,parser=None):
    execution=TaskExecutionStore(config=config,directory=directory)
    lease=execution.claim(task_id,task_revision,task_type='school_template_parse')
    if lease is None:return None
    stop=Event()
    def heartbeat():
        while not stop.wait(10):
            try:
                if not execution.heartbeat(lease):return
            except StorageError:return
    thread=Thread(target=heartbeat,daemon=True);thread.start()
    try:
        with execution.connection() as db:
            task=execution.require_lease(db,lease);execution.require_owner(db,task)
            service=SchoolTemplateService(scoped_store(task['user_id'],execution.config,execution.assets.directory))
            row=service.row(db,task['project_id'],task['input_snapshot']['template_version_id'])
            sources,_=service.require_current(db,row)
            if row['analysis_json'] is not None:raise source_conflict()
            source=next(s for s in sources if s['role']=='template')
            raw=service.assets.original(source['file'])
            from app.domain.admin_configuration.rule_consumption import rules,task_version
            policy=rules(task_version(db,task),'schools')
        if parser is None:
            from app.adapters.school_template_process import inspect_school_template_isolated
            parser=inspect_school_template_isolated
        analysis=parser(raw,source['filename'],heading_aliases=policy['heading_aliases']) if policy['heading_aliases'] else parser(raw,source['filename'])
        keys=('raw_styles','sections','chapters','rules','notes','conflicts','missing','unsupported','identity_fields')
        if analysis.get('parser_version')!=PARSER_VERSION or not isinstance(analysis.get('defaults'),dict) or any(not isinstance(analysis.get(k),list) for k in keys):
            raise StorageError('parse_output_invalid','学校模板解析结果无效。',422)
        analysis=supplements(analysis,row,sources)
        for conflict in analysis['conflicts']:
            if sum(rule['id']==conflict['rule_id'] for rule in analysis['rules'])!=1:
                raise StorageError('parse_output_invalid','模板冲突未关联唯一规则。',422)
        with execution.connection(write=True) as db:
            task=execution.require_lease(db,lease);execution.require_owner(db,task)
            fresh=service.row(db,task['project_id'],row['id']);service.require_current(db,fresh)
            if fresh['analysis_json'] is not None:raise source_conflict()
            execution.require_lease(db,lease)
            db.execute('UPDATE school_template_versions SET analysis_json=%s,analysis_sha256=%s WHERE id=%s AND analysis_json IS NULL',(Jsonb(analysis),digest(analysis),row['id']))
            execution._finish(db,task,'succeeded',None)
            return TaskStore.public_task(task)
    except LeaseLost:return None
    except Exception as exc:
        code=exc.code if isinstance(exc,StorageError) else 'storage_unavailable' if isinstance(exc,OSError) else 'parse_output_invalid'
        try:return execution.fail(lease,code)
        except LeaseLost:return None
    finally:
        stop.set();thread.join(timeout=1)
