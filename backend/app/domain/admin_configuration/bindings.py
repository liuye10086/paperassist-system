"""Transaction-local reads and immutable associations; never modify task snapshots."""
from app.core.exceptions import StorageError

KINDS={'task','writing_bundle','review_round','school_confirmation','journal_confirmation'}


def read(db,version_id):
    row=db.execute('SELECT * FROM admin_configuration_versions WHERE id=%s',(version_id,)).fetchone()
    if not row:raise StorageError('configuration_not_found','配置版本不存在。',404)
    return dict(row)


def current(db):
    row=db.execute('SELECT version_id FROM admin_configuration_pointer WHERE id=1').fetchone()
    return read(db,row['version_id']) if row and row['version_id'] else None


def _kind(kind):
    if kind not in KINDS:raise StorageError('configuration_invalid','配置绑定类型不支持。',422)


def projection(db,kind,object_id):
    _kind(kind)
    row=db.execute('''SELECT b.version_id,v.sha256 FROM admin_configuration_bindings b
        JOIN admin_configuration_versions v ON v.id=b.version_id WHERE kind=%s AND object_id=%s''',(kind,object_id)).fetchone()
    return dict(status='bound',**dict(row)) if row else dict(status='legacy_unbound',version_id=None,sha256=None)


def resolve(db,*,kind=None,object_id=None,inherit_kind=None,inherit_id=None):
    if kind is not None:
        binding=projection(db,kind,object_id)
        return read(db,binding['version_id']) if binding['version_id'] else None
    if inherit_kind is not None:
        return resolve(db,kind=inherit_kind,object_id=inherit_id)
    return current(db)


def bind(db,*,kind,object_id,version,task_id=None):
    _kind(kind)
    if not isinstance(object_id,str) or not 1<=len(object_id)<=128:
        raise StorageError('configuration_invalid','配置绑定对象无效。',422)
    existing=projection(db,kind,object_id)
    if existing['status']=='bound':
        if not version or existing['version_id']!=version['id']:
            raise StorageError('configuration_binding_conflict','已有对象的配置绑定不可变更。',409)
        return existing
    if version is None:return existing
    actual=read(db,version['id'])
    if actual['sha256']!=version['sha256']:
        raise StorageError('configuration_binding_conflict','配置版本依据不一致。',409)
    db.execute('''INSERT INTO admin_configuration_bindings(kind,object_id,version_id,task_id)
        VALUES(%s,%s,%s,%s)''',(kind,object_id,actual['id'],object_id if kind=='task' else None))
    return projection(db,kind,object_id)
