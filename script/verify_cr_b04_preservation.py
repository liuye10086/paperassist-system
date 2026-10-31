"""Verify accepted originals and copied historical assets; never repair data."""
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'script/dev'),str(ROOT/'script'),str(ROOT/'backend')]
import cr_b04_runner as control
from cr_b03_preservation import asset_inventory,compare_assets,database_snapshot,compare_business


def git(*args,directory=ROOT):
    return subprocess.run(['git','-C',str(directory),*args],capture_output=True,text=True,encoding='utf-8',check=True).stdout.strip()


def main():
    state=control.read_state();control.configure(state)
    from app.db.database import get_migration_database_config,get_engine,database_connection
    engine=get_engine(get_migration_database_config());sources=[]
    for batch,baseline in [('b03',control.RUNTIME),('b02',ROOT/'script/.runtime/client-requirements-b03')]:
        original=json.loads((ROOT/f'script/.runtime/client-requirements-{batch}/state.json').read_text(encoding='utf-8-sig'))
        before=json.loads((baseline/(batch+'-database-before.json')).read_text(encoding='utf-8'))
        inventory=json.loads((baseline/(batch+'-assets-before.json')).read_text(encoding='utf-8'))
        current=database_snapshot(engine,original['schema'],before)
        changes=compare_business(before,current)
        assets=compare_assets({k.replace('\\','/'):v for k,v in inventory['files'].items()},asset_inventory(inventory['source_assets']))
        stack=control.worker_stack.load(ROOT,test_id=original['schema'][8:]);containers=control.worker_stack.owned_containers(stack)
        with socket.socket() as connection:
            connection.settimeout(.2);closed=connection.connect_ex((original['bind_host'],original['port']))!=0
        sources.append(dict(batch=batch,database_differences=changes,assets=assets,api_closed=closed,containers=containers,
            passed=not changes and assets['preserved'] and closed and len(containers)==4 and all(c['status']=='exited' for c in containers)))
    before_assets=json.loads((control.RUNTIME/'b03-assets-before.json').read_text(encoding='utf-8'))
    copied=compare_assets({k.replace('\\','/'):v for k,v in before_assets['files'].items()},asset_inventory(state['assets']))
    start=json.loads((control.RUNTIME/'implementation-start.json').read_text(encoding='utf-8'))
    protected=[];missing=[]
    for name,record in start['files'].items():
        path=ROOT/name
        if not path.is_file():missing.append(name)
        elif name.startswith(('backend/data/','data/','samples/','backups/','backup/','templates/')):
            if hashlib.sha256(path.read_bytes()).hexdigest()!=record['sha256']:protected.append(name)
    from app.maintenance.research_results_audit import audit_research_task_sources
    with database_connection() as db:audit=audit_research_task_sources(db,limit=1000)
    main=Path('C:/Users/86182/Desktop/PaperAssist-System')
    handoff=json.loads((ROOT/'script/.runtime/client-requirements-b03/branch-handoff-20261030.json').read_text(encoding='utf-8'))
    receipt=dict(sources=sources,copied_historical_assets=copied,protected_files_changed=protected,baseline_files_missing=missing,
        branch=git('branch','--show-current'),head=git('rev-parse','HEAD'),index_empty=not git('diff','--cached','--name-only'),
        original_main_head=git('rev-parse','HEAD',directory=main),original_main_status=git('status','--porcelain',directory=main),
        research_task_audit=audit,user_acceptance='pending',next_batch_authorized=False)
    receipt['passed']=all(s['passed'] for s in sources) and copied['preserved'] and not(protected or missing) and receipt['branch']==start['branch'] and receipt['head']==start['head'] and receipt['index_empty'] and receipt['original_main_head']==handoff['main'] and not receipt['original_main_status'] and not any(c['invalid'] or c['truncated'] for c in audit)
    control.worker_stack.private_write(control.RUNTIME/'preservation-final.json',json.dumps(receipt,ensure_ascii=False,indent=2))
    print(json.dumps(dict(passed=receipt['passed'],branch=receipt['branch'],head=receipt['head'],index_empty=receipt['index_empty'],source_preservation=[dict(batch=s['batch'],passed=s['passed']) for s in sources],audit=audit)))
    if not receipt['passed']:raise SystemExit(1)


if __name__=='__main__':main()
