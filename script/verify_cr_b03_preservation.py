"""Read-only comparison of the accepted B02 source and original Git checkout."""
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'script/dev'),str(ROOT/'script'),str(ROOT/'backend')]
import cr_b03_runner as control
from cr_b03_preservation import asset_inventory,compare_assets,database_snapshot,compare_business


def git(*args,directory=ROOT):
    return subprocess.run(['git','-C',str(directory),*args],capture_output=True,text=True,encoding='utf-8',check=True).stdout.strip()


def main():
    state=control.read_state();control.configure(state)
    before=json.loads((control.RUNTIME/'b02-database-before.json').read_text(encoding='utf-8'))
    assets=json.loads((control.RUNTIME/'b02-assets-before.json').read_text(encoding='utf-8'))
    from app.db.database import get_migration_database_config,get_engine,database_connection
    engine=get_engine(get_migration_database_config())
    source=database_snapshot(engine,state['source_schema'],before)
    database_differences=compare_business(before,source)
    originals={name.replace('\\','/'):value for name,value in assets['files'].items()}
    original_assets=compare_assets(originals,asset_inventory(assets['source_assets']))
    cloned_assets=compare_assets(originals,asset_inventory(state['assets']))
    from app.maintenance.research_results_audit import audit_research_task_sources
    with database_connection() as db:checks=audit_research_task_sources(db,limit=1000)
    start=json.loads((control.RUNTIME/'implementation-start.json').read_text(encoding='utf-8'))
    missing=[p for p in start['tracked_file_sha256'] if not (ROOT/p).is_file()]
    changes=[]
    for name,sha in start['tracked_file_sha256'].items():
        if name.startswith(('backend/data/','data/','samples/','backups/','backup/','templates/')) and (ROOT/name).is_file():
            if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=sha:changes.append(name)
    main=Path('C:/Users/86182/Desktop/PaperAssist-System')
    handoff=json.loads((control.RUNTIME/'branch-handoff-20261030.json').read_text(encoding='utf-8'))
    with socket.socket() as connection:
        connection.settimeout(.2);b02_closed=connection.connect_ex(('127.0.0.82',18082))!=0
    stack=control.worker_stack.load(ROOT,test_id=state['source_schema'][8:])
    containers=control.worker_stack.owned_containers(stack)
    receipt=dict(source_database_differences=database_differences,source_assets=original_assets,cloned_original_assets=cloned_assets,
        research_task_audit=checks,tracked_files_missing=missing,protected_tracked_files_changed=changes,
        original_main_head=git('rev-parse','HEAD',directory=main),original_main_status=git('status','--porcelain',directory=main),
        branch=git('branch','--show-current'),head=git('rev-parse','HEAD'),index_empty=not git('diff','--cached','--name-only'),
        b02_api_closed=b02_closed,b02_containers=containers,next_batch_authorized=False,user_acceptance='pending')
    receipt['passed']=not(database_differences or original_assets['missing'] or original_assets['changed'] or cloned_assets['missing'] or cloned_assets['changed'] or missing or changes
        or any(c['invalid'] or c['truncated'] for c in checks) or receipt['original_main_status'] or receipt['original_main_head']!=handoff['main']
        or receipt['head']!=start['head'] or not receipt['index_empty'] or not b02_closed or len(containers)!=4 or any(c['status']!='exited' for c in containers))
    control.worker_stack.private_write(control.RUNTIME/'preservation-final.json',json.dumps(receipt,ensure_ascii=False,indent=2))
    print(json.dumps({k:receipt[k] for k in ('passed','branch','head','index_empty','source_database_differences','research_task_audit')},ensure_ascii=False))
    if not receipt['passed']:raise SystemExit(1)


if __name__=='__main__':main()
