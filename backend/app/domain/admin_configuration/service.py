"""Admin-only lifecycle. Every mutation rechecks identity in its own transaction."""
from uuid import uuid4
from pydantic import Field, ValidationError
from psycopg.types.json import Jsonb

from app.core.exceptions import StorageError
from app.db.database import database_connection, ensure_schema_current
from app.domain.admin_operations import require_identity
from app.domain.admin_configuration import bindings, catalog, legacy, validation
from app.domain.admin_configuration.contracts import Strict, Token, parse_bundle, safe_text


class Switch(Strict):
    expected_revision:int=Field(ge=0,le=2147483646)
    reason:str=Field(min_length=5,max_length=500)
    request_key:Token


def _error(code,message):return StorageError(code,message,409)


def _insert(db,user,bundle,sources,parent=None):
    value=parse_bundle(bundle);identity=str(uuid4());sha=catalog.digest(value)
    db.execute('''INSERT INTO admin_configuration_versions(id,parent_id,sha256,bundle,sources,created_by)
        VALUES(%s,%s,%s,%s,%s,%s)''',(identity,parent,sha,Jsonb(value),Jsonb(sources),user))
    return bindings.read(db,identity)


class Configurations:
    def __init__(self,user_id):self.user_id=user_id

    def _identity(self,db):
        ensure_schema_current(db)
        require_identity(db,self.user_id)

    def catalog(self):
        with database_connection() as db:self._identity(db)
        return catalog.metadata()

    def current(self):
        with database_connection() as db:
            self._identity(db)
            pointer=db.execute('SELECT revision,version_id FROM admin_configuration_pointer WHERE id=1').fetchone()
            return dict(revision=pointer['revision'],version=bindings.read(db,pointer['version_id']) if pointer['version_id'] else None)

    def list(self):
        with database_connection() as db:
            self._identity(db)
            rows=db.execute('''SELECT id,parent_id,sha256,sources,created_by,created_at FROM admin_configuration_versions
                ORDER BY created_at DESC,id DESC LIMIT 100''').fetchall()
            return dict(items=[dict(row) for row in rows])

    def detail(self,version_id):
        with database_connection() as db:
            self._identity(db);result=bindings.read(db,version_id)
            result['validations']=[row['result'] for row in db.execute('''SELECT result FROM admin_configuration_validations
                WHERE version_id=%s ORDER BY created_at DESC,id DESC LIMIT 20''',(version_id,)).fetchall()]
            return result

    def baseline(self):
        with database_connection(write=True) as db:
            self._identity(db);bundle,sources=catalog.defaults()
            return _insert(db,self.user_id,bundle,sources)

    def copy(self,version_id):
        with database_connection(write=True) as db:
            self._identity(db);parent=bindings.read(db,version_id)
            return _insert(db,self.user_id,parent['bundle'],parent['sources'],version_id)

    def save(self,version_id,bundle):
        with database_connection(write=True) as db:
            self._identity(db);parent=bindings.read(db,version_id)
            value=parse_bundle(bundle)
            sources={name:('administrator_revision' if value[name]!=parent['bundle'][name] else parent['sources'][name]) for name in catalog.DOMAINS}
            return _insert(db,self.user_id,value,sources,version_id)

    def diff(self,version_id,against=None):
        with database_connection() as db:
            self._identity(db);target=bindings.read(db,version_id)
            other=bindings.read(db,against or target['parent_id']) if against or target['parent_id'] else bindings.current(db)
            before=other['bundle'] if other else catalog.defaults()[0]
            def get(value,path):
                for key in path.split('.'):
                    if not isinstance(value,dict):return None
                    value=value.get(key)
                return value
            return dict(version_id=version_id,against=other['id'] if other else None,
                changes=[dict(path=path,before=get(before,path),after=get(target['bundle'],path))
                         for path in legacy.changed_paths(before,target['bundle'])])

    def validate(self,version_id):
        with database_connection(write=True) as db:
            self._identity(db)
            return validation.validate(db,bindings.read(db,version_id),self.user_id)

    def switch(self,version_id,*,expected_revision,reason,request_key,operation='activate'):
        try:
            data=Switch(expected_revision=expected_revision,reason=reason,request_key=request_key)
            safe_text(reason)
            safe_text(request_key)
            if not reason.strip() or any(ord(char)<32 for char in reason) or operation not in ('activate','rollback'):raise ValueError()
        except (ValidationError,ValueError,TypeError):
            raise StorageError('configuration_invalid','请提供有效版本、请求标识和不少于5字的安全理由。',422) from None
        request_sha=catalog.digest(dict(version_id=version_id,operation=operation,**data.model_dump()))
        with database_connection(write=True) as db:
            self._identity(db)
            previous=db.execute('SELECT request_sha256,response FROM admin_configuration_events WHERE actor_user_id=%s AND request_key=%s',
                (self.user_id,request_key)).fetchone()
            if previous:
                if previous['request_sha256']!=request_sha:raise _error('configuration_idempotency_conflict','请求标识已用于不同配置操作。')
                return previous['response']
            pointer=db.execute('SELECT * FROM admin_configuration_pointer WHERE id=1 FOR UPDATE').fetchone()
            if pointer['revision']!=expected_revision:raise _error('configuration_revision_conflict','有效配置已变化，请刷新后重试。')
            target=bindings.read(db,version_id)
            current=bindings.read(db,pointer['version_id']) if pointer['version_id'] else None
            if current and current['sha256']==target['sha256']:raise _error('configuration_no_change','配置内容与当前有效版本相同。')
            if operation=='rollback' and not db.execute('SELECT 1 FROM admin_configuration_events WHERE after_version_id=%s LIMIT 1',(version_id,)).fetchone():
                raise _error('configuration_rollback_invalid','只能回退到曾有效的版本。')
            evidence=db.execute('''SELECT id FROM admin_configuration_validations WHERE version_id=%s AND sha256=%s
                AND validator_version=%s AND capability_version=%s AND status='passed' ORDER BY created_at DESC,id DESC LIMIT 1''',
                (version_id,target['sha256'],catalog.VALIDATOR_VERSION,catalog.capability_version())).fetchone()
            if not evidence:raise _error('configuration_validation_required','此修订缺少当前能力版本对应的成功离线验证。')
            legacy.check(db,legacy.changed_paths(current['bundle'] if current else catalog.defaults()[0],target['bundle']))
            revision=expected_revision+1
            changed=db.execute('UPDATE admin_configuration_pointer SET version_id=%s,revision=%s WHERE id=1 AND revision=%s',
                (version_id,revision,expected_revision))
            if changed.rowcount!=1:raise _error('configuration_revision_conflict','有效配置已变化，请刷新后重试。')
            response=dict(revision=revision,version_id=version_id,sha256=target['sha256'],operation=operation)
            db.execute('''INSERT INTO admin_configuration_events
                (id,actor_user_id,operation,reason,request_key,request_sha256,before_version_id,after_version_id,validation_id,revision,response)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (str(uuid4()),self.user_id,operation,reason,request_key,request_sha,pointer['version_id'],version_id,evidence['id'],revision,Jsonb(response)))
            return response

    def events(self):
        with database_connection() as db:
            self._identity(db)
            return dict(items=[dict(row) for row in db.execute('''SELECT id,actor_user_id,operation,reason,
                before_version_id,after_version_id,validation_id,revision,created_at FROM admin_configuration_events
                ORDER BY revision DESC LIMIT 100''').fetchall()])

    def binding(self,kind,object_id):
        with database_connection() as db:
            self._identity(db)
            return bindings.projection(db,kind,object_id)
