"""Read-only retention evidence. Never migrates, removes, or starts anything."""
from pathlib import Path
import hashlib
import re


def _linked(path):
    return path.is_symlink() or getattr(path,'is_junction',lambda:False)()


def asset_inventory(directory):
    root=Path(directory).absolute()
    if any(_linked(p) for p in (root,*root.parents)):
        raise ValueError('Asset inventory refuses linked roots')
    if not root.is_dir():raise ValueError('Asset inventory root is missing')
    result={}
    for path in sorted(root.rglob('*')):
        if _linked(path):raise ValueError('Asset inventory refuses linked entries')
        if not path.is_file():continue
        before=path.stat();digest=hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
        after=path.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
            raise ValueError('Asset changed during read-only snapshot')
        result[path.relative_to(root).as_posix()]={'size':after.st_size,'sha256':digest.hexdigest()}
    return result


def compare_assets(before,after):
    missing=sorted(set(before)-set(after));added=sorted(set(after)-set(before))
    changed=sorted(k for k in set(before)&set(after) if before[k]!=after[k])
    return dict(missing=missing,changed=changed,added=added,preserved=not missing and not changed)


def compare_business(before,after):
    failures=[]
    for table,old in sorted(before.items()):
        new=after.get(table)
        if new is None:failures.append('table:'+table);continue
        if old['columns']!=new['columns']:failures.append('columns:'+table)
        if (old['count'],old['sha256'])!=(new['count'],new['sha256']):failures.append('rows:'+table)
    return failures


def database_snapshot(engine,schema,original=None):
    """Hash old column projections under one consistent read-only transaction."""
    if not re.fullmatch(r'pa_test_[a-f0-9]{32}',schema):
        raise ValueError('Only an explicitly named isolated test schema may be inspected')
    quote=engine.dialect.identifier_preparer.quote
    result={}
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as db:
        with db.begin():
            db.exec_driver_sql('SET TRANSACTION READ ONLY')
            if db.exec_driver_sql('SELECT current_database()').scalar_one()!='paperassist_system_test':
                raise ValueError('Expected test database')
            tables=db.exec_driver_sql('SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname=%s ORDER BY tablename',(schema,)).scalars().all()
            for name in tables:
                columns=db.exec_driver_sql('SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position',(schema,name)).scalars().all()
                selected=original[name]['columns'] if original and name in original else columns
                if not set(selected)<=set(columns):
                    result[name]=dict(columns=columns,count=-1,sha256='missing_column');continue
                sql='SELECT row_to_json(r)::text FROM (SELECT '+','.join(map(quote,selected))+' FROM '+quote(schema)+'.'+quote(name)+') r ORDER BY row_to_json(r)::text'
                digest=hashlib.sha256();count=0
                for row in db.exec_driver_sql(sql):
                    raw=row[0].encode('utf-8');digest.update(len(raw).to_bytes(8,'big'));digest.update(raw);count+=1
                result[name]=dict(columns=selected,count=count,sha256=digest.hexdigest())
    return result
