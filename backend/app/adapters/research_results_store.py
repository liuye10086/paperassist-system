"""Small owner-scoped persistence helpers for research results."""
from datetime import datetime,timezone
from uuid import UUID,uuid5,uuid4
from psycopg.types.json import Jsonb

from app.adapters.task_store import TaskStore
from app.core.exceptions import StorageError
from app.db.research_results_schema import TABLE_NAMES,SOURCE_TARGETS
from app.domain.bioinformatics.contracts import digest


def now():return datetime.now(timezone.utc)


def identity(project,kind,key):
    return str(uuid5(UUID('48dab26a-134f-491b-8b6b-27f3a757f4ac'),project+':'+kind+':'+key))


def invalid(code='research_source_conflict',status=409):
    return StorageError(code,'研究来源、数值或版本需要重新核对；原有成果仍保留。',status)


def base(identifier,project,owner):
    return dict(id=identifier,project_id=project,user_id=owner,created_at=now(),schema_version=1)


def insert(db,table,row):
    if table not in TABLE_NAMES:raise ValueError('Unregistered research table')
    from app.db.schema import metadata
    if not set(row)<=set(metadata.tables[table].c.keys()):raise ValueError('Unknown research column')
    # PostgreSQL jsonb includes whitespace in its size constraint; validate the
    # exact database representation before a constraint error aborts the write.
    for value in row.values():
        if isinstance(value,(dict,list)):
            size=db.execute('SELECT octet_length(%s::jsonb::text) AS bytes',(Jsonb(value),)).fetchone()['bytes']
            if size>4*1024*1024:raise invalid('research_source_limit_exceeded',422)
    db.execute('INSERT INTO '+table+'('+','.join(row)+') VALUES ('+','.join(['%s']*len(row))+')',
        tuple(Jsonb(v) if isinstance(v,(dict,list)) else v for v in row.values()))


class ResearchResultsStore:
    def __init__(self,assets):
        self.assets=assets;self.store=TaskStore(assets.owner_id,assets.db_config)

    def require(self,db,table,project,identifier):
        self.store.require_project(db,project)
        if table not in TABLE_NAMES:raise ValueError('Unregistered research table')
        row=db.execute('SELECT * FROM '+table+' WHERE id=%s AND project_id=%s AND user_id=%s',
            (identifier,project,self.store.user_id)).fetchone()
        if not row:raise invalid('research_source_not_found',404)
        return dict(row)

    def lock(self,db,project,key):
        self.store.require_project(db,project)
        db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('research:'+project+':'+key,))

    def bind(self,db,project,parent_kind,parent_id,source,role='supporting'):
        if parent_kind not in ('finding','figure','report'):raise ValueError('Invalid research parent')
        value=source.model_dump(mode='json') if hasattr(source,'model_dump') else source
        col,_=SOURCE_TARGETS[value['source_kind']]
        insert(db,'research_source_bindings',{**base(str(uuid4()),project,self.store.user_id),
            'parent_kind':parent_kind,parent_kind+'_version_id':parent_id,'source_kind':value['source_kind'],
            'source_id':value['source_id'],col:value['source_id'],'locator_json':value['locator'],
            'source_sha256':value['sha256'],'role':role})

    @staticmethod
    def verify_content(row):
        if digest(row['content_json'])!=row['content_sha256']:raise invalid()
        return row['content_json']
