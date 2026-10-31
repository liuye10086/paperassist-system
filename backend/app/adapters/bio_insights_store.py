"""Owner-scoped B04 persistence and content-addressed storage helpers."""
from datetime import datetime,timezone
from uuid import UUID,uuid5

from psycopg.types.json import Jsonb

from app.adapters.task_store import TaskStore
from app.adapters.bio_objects import BioObjects
from app.core.exceptions import StorageError
from app.db.bio_insights_schema import TABLE_NAMES,SOURCE_TARGETS


def now():return datetime.now(timezone.utc)


def identity(project,kind,key):
    return str(uuid5(UUID('e94af56e-505b-46ef-b30a-dd2b30b115d6'),project+':'+kind+':'+key))


def invalid(code='bio_insight_source_conflict',status=409):
    return StorageError(code,'分析来源、设计或版本需要重新核对；原有成果仍保留。',status)


def base(identifier,project,owner):
    return dict(id=identifier,project_id=project,user_id=owner,created_at=now(),schema_version=1)


def insert(db,table,row):
    if table not in TABLE_NAMES:raise ValueError('Unregistered bio insight table')
    from app.db.schema import metadata
    if not set(row)<=set(metadata.tables[table].c.keys()):raise ValueError('Unknown bio insight column')
    for value in row.values():
        if isinstance(value,(dict,list)):
            if db.execute('SELECT octet_length(%s::jsonb::text) AS n',(Jsonb(value),)).fetchone()['n']>4194304:
                raise invalid('bio_insight_limit_exceeded',422)
    db.execute('INSERT INTO '+table+'('+','.join(row)+') VALUES('+','.join(['%s']*len(row))+')',
               tuple(Jsonb(v) if isinstance(v,(dict,list)) else v for v in row.values()))


class BioInsightsObjects(BioObjects):
    prefix='bio-insights'


class BioInsightsStore:
    def __init__(self,assets):
        self.assets=assets
        self.store=TaskStore(assets.owner_id,assets.db_config)
        self.objects=BioInsightsObjects(assets.directory)

    def require(self,db,table,project,identifier):
        self.store.require_project(db,project)
        if table not in TABLE_NAMES:raise ValueError('Unregistered bio insight table')
        row=db.execute('SELECT * FROM '+table+' WHERE id=%s AND project_id=%s AND user_id=%s',
                       (identifier,project,self.store.user_id)).fetchone()
        if not row:raise invalid('bio_insight_not_found',404)
        return dict(row)

    def lock(self,db,project,key):
        self.store.require_project(db,project)
        db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('bio-insight:'+project+':'+key,))

    def bind(self,db,project,version_id,source,ordinal):
        value=source.model_dump(mode='json') if hasattr(source,'model_dump') else source
        column,_=SOURCE_TARGETS[value['source_kind']]
        insert(db,'bio_insight_plan_sources',{**base(identity(project,'binding',version_id+':'+str(ordinal)),project,self.store.user_id),
            'plan_version_id':version_id,'source_kind':value['source_kind'],'source_id':value['source_id'],column:value['source_id'],
            'role':value['role'],'ordinal':ordinal,'source_sha256':value['sha256'],'locator_json':value['locator'],
            'parse_version_id':value['locator'].get('parse_version_id') if value['source_kind']=='original_file' else None})

    def write_document(self,db,project,identifier,name,value):
        from app.domain.bioinformatics.contracts import canonical
        from app.domain.storage_governance import service as ledger
        content=canonical(value)
        if len(content)>4194304:raise invalid('bio_insight_limit_exceeded',422)
        record=self.objects.describe(identifier,content,json=False)
        from app.adapters.bio_analysis_store import object_by_key
        with ledger.publication(db,self.assets.directory,project,'bio-insight:'+identifier+':'+name,
                                self.objects.path(record['object_key']),content,kind='bio_insight_snapshot'):
            self.objects.write(record,content)
        return object_by_key(db,project,self.store.user_id,record)
