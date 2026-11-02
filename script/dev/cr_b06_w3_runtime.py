"""W3 acceptance: copy one fixed W2 project; retain originals and all attempts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / 'script/.runtime/client-requirements-b06-w3'
SOURCE = ROOT / 'script/.runtime/client-requirements-b06-w2'
STATE = RUNTIME / 'state.json'
DATA = Path('D:/PaperAssist-Runtime') / ('cr-b06-w3-' + hashlib.sha256(str(ROOT).casefold().encode()).hexdigest()[:12])
HOST, PORT = '127.0.0.92', 18092
WORKER_IMAGE = 'paperassist-client-b06-w1-worker:local'
BROKER_IMAGE = 'rabbitmq:4.3.6-alpine@sha256:2cb43283d8bbd3caa6c0f0dc00e96c8de772df33df7fd8af6aee4d605aeb8ada'
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'script/dev')]
import worker_stack


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    worker_stack.private_write(path, json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')


def state():
    value = read(STATE)
    from re import fullmatch
    assert fullmatch(r'pa_test_[a-f0-9]{32}', value['schema'])
    assert value['workspace'] == str(ROOT)
    assert Path(value['assets']) == DATA / 'acceptance' / value['schema'] / 'assets'
    assert value['schema'] != value['source_schema']
    return value


def configure(value):
    from cr_b03_runner import configure as common
    common(value)
    os.environ.update(PAPERASSIST_AUTH_TRUSTED_ORIGINS=f'{value["url"]},http://testserver',
        PAPERASSIST_BIO_STAGING_DIR=value['staging'], PAPERASSIST_BIO_INSIGHTS_STAGING_DIR=value['staging'],
        PAPERASSIST_BIO_RUNTIME_MANIFEST='', PAPERASSIST_BIO_INSIGHTS_RUNTIME_MANIFEST='',
        PAPERASSIST_SINGLE_CELL_RUNTIME_MANIFEST='', PAPERASSIST_PDF_RENDERER_URL='')


def port_free():
    with socket.socket() as sock:
        sock.settimeout(.2)
        return sock.connect_ex((HOST, PORT)) != 0


def prepare():
    if STATE.exists():
        value = state()
        if value['status'] == 'prepared':
            return {'status': 'prepared', 'schema': value['schema'], 'reused': True}
        raise RuntimeError('Incomplete preparation retained; inspect the same target before resuming')
    source = read(SOURCE / 'state.json')
    selection = read(RUNTIME / 'copy-selection.json')
    assert selection['source_schema'] == source['schema']
    assert read(SOURCE / 'user-acceptance.json')['status'] == 'accepted_with_documented_scope'
    assert port_free(), 'Selected W3 port occupied; no existing process changed'
    schema = 'pa_test_' + uuid4().hex
    directory = DATA / 'acceptance' / schema
    directory.mkdir(parents=True, exist_ok=False)
    worker_stack.protect_directory(directory)
    value = dict(schema=schema, source_schema=source['schema'], workspace=str(ROOT),
        assets=str(directory/'assets'), staging=str(directory/'staging'), url=f'http://{HOST}:{PORT}',
        bind_host=HOST, port=PORT, status='preparing', public_database_modified=False,
        real_model_calls=0, scientific_recompute=False, project_id=selection['project_id'])
    save(STATE, value)
    configure(value)
    Path(value['assets']).mkdir()
    Path(value['staging']).mkdir()
    from app.db.database import get_engine, get_migration_database_config, migrate_database, SCHEMA_HEAD
    assert SCHEMA_HEAD != '0069_manuscript_presentation', 'Wait for the W3 additive migration'
    config = get_migration_database_config()
    engine = get_engine(config)
    quote = engine.dialect.identifier_preparer.quote_identifier
    src, dst = quote(source['schema']), quote(schema)
    with engine.begin() as db:
        assert db.exec_driver_sql('SELECT current_database()').scalar_one() == 'paperassist_system_test'
        assert db.exec_driver_sql('SELECT version_num FROM '+src+'.alembic_version').scalar_one() == '0069_manuscript_presentation'
        db.exec_driver_sql('CREATE SCHEMA '+dst)
    migrate_database(config)
    catalog = read(RUNTIME / 'source-catalog.json')['columns']
    selections = {t: selection['selectors'][t] for t in selection['counts']}
    copied = {}
    with engine.begin() as db:
        db.exec_driver_sql("SELECT set_config('search_path',%s,true)", (schema,))
        files = db.exec_driver_sql('SELECT object_key,sha256,size_bytes FROM '+src+'.files WHERE project_id=%s', (value['project_id'],)).mappings().all()
        docx = db.exec_driver_sql('SELECT e.id,e.metadata_json FROM '+src+'.manuscript_exports e JOIN '+src+'.manuscript_versions v ON v.id=e.version_id WHERE v.project_id=%s', (value['project_id'],)).mappings().all()
        pdf = db.exec_driver_sql('SELECT metadata_json FROM '+src+'.pdf_exports WHERE project_id=%s', (value['project_id'],)).mappings().all()
        assets = [dict(row) for row in files]
        assets += [dict(object_key='manuscript_exports/'+row['id']+'.docx', **{k:row['metadata_json'][k] for k in ('sha256','size_bytes')}) for row in docx]
        assets += [dict(object_key='pdf_exports/'+row['metadata_json']['object_name'], **{k:row['metadata_json'][k] for k in ('sha256','size_bytes')}) for row in pdf]
        selections['storage_objects'] = ['object_key=ANY(%s)', [[a['object_key'] for a in assets]]]
        foreign = db.exec_driver_sql("SELECT c.conrelid::regclass::text,c.conname,pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname=%s AND c.contype='f' ORDER BY c.conname", (schema,)).all()
        # Exact new-target copy protocol used by previous CR batches. Sources are SELECT-only.
        for relation, name, _ in foreign:
            db.exec_driver_sql('ALTER TABLE '+relation+' DROP CONSTRAINT '+quote(name))
        for table, (condition, args) in selections.items():
            relation = dst+'.'+quote(table)
            assert db.exec_driver_sql('SELECT count(*) FROM '+relation).scalar_one() == 0
            columns = ','.join(quote(c['name']) for c in catalog[table])
            db.exec_driver_sql('ALTER TABLE '+relation+' DISABLE TRIGGER USER')
            inserted = db.exec_driver_sql('INSERT INTO '+relation+'('+columns+') OVERRIDING SYSTEM VALUE SELECT '+columns+' FROM '+src+'.'+quote(table)+' WHERE '+condition, tuple(args))
            db.exec_driver_sql('ALTER TABLE '+relation+' ENABLE TRIGGER USER')
            copied[table] = inserted.rowcount
            differences = db.exec_driver_sql('SELECT count(*) FROM ((SELECT '+columns+' FROM '+relation+') EXCEPT ALL (SELECT '+columns+' FROM '+src+'.'+quote(table)+' WHERE '+condition+')) d', tuple(args)).scalar_one()
            assert differences == 0, table
        for relation, name, definition in foreign:
            db.exec_driver_sql('ALTER TABLE '+relation+' ADD CONSTRAINT '+quote(name)+' '+definition)
        sequences = db.exec_driver_sql("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema=%s AND (is_identity='YES' OR column_default LIKE 'nextval%%')", (schema,)).all()
        for table, column in sequences:
            if table not in selections:
                continue
            relation = dst+'.'+quote(table)
            maximum = db.exec_driver_sql('SELECT max('+quote(column)+') FROM '+relation).scalar_one()
            if maximum is not None:
                sequence = db.exec_driver_sql('SELECT pg_get_serial_sequence(%s,%s)', (relation,column)).scalar_one()
                db.exec_driver_sql('SELECT setval(%s,%s,true)', (sequence,maximum))
        assert db.exec_driver_sql('SELECT count(*) FROM '+dst+'.task_outbox').scalar_one() == 0
    for item in assets:
        original, target = Path(source['assets'])/item['object_key'], Path(value['assets'])/item['object_key']
        assert original.resolve().is_relative_to(Path(source['assets']).resolve())
        assert target.resolve().is_relative_to(Path(value['assets']).resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
        raw = target.read_bytes()
        assert len(raw) == item['size_bytes'] and hashlib.sha256(raw).hexdigest() == item['sha256']
    save(directory/'credentials.json', read(Path(source['assets']).parent/'credentials.json'))
    value.update(status='prepared', migration_head=SCHEMA_HEAD, copied_rows=sum(copied.values()), copied_assets=len(assets))
    save(STATE,value)
    save(RUNTIME/'copy-verification.json',dict(source_schema=source['schema'],target_schema=schema,project_id=value['project_id'],
        selected_table_rows=copied,assets=assets,selected_rows_equal=True,source_writes=0,
        old_outbox_copied=False,old_auth_sessions_copied=False,old_pending_parse_dispatched=False,
        scope='one fixed W2 SCI engineering project; no B05 clone or new bottom-level outputs'))
    return {k:value[k] for k in ('status','schema','migration_head','copied_rows','copied_assets','url')}


def serve():
    value=state(); configure(value)
    import uvicorn
    from fastapi.staticfiles import StaticFiles
    from app.main import app
    app.mount('/', StaticFiles(directory=RUNTIME/'frontend-dist',html=True),name='cr-b06-w3')
    uvicorn.run(app,host=HOST,port=PORT,log_level='warning')


def start_api():
    value=state()
    assert port_free(), 'W3 port occupied; inspect saved process, no blind restart'
    assert (RUNTIME/'frontend-dist/index.html').exists()
    with (RUNTIME/'api.stdout.txt').open('ab') as out,(RUNTIME/'api.stderr.txt').open('ab') as err:
        child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'serve'],cwd=ROOT/'backend',stdin=subprocess.DEVNULL,
            stdout=out,stderr=err,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    receipt=dict(pid=child.pid,script=str(Path(__file__).resolve()),executable=sys.executable,url=value['url'])
    save(RUNTIME/'api-process.json',receipt)
    from urllib.request import build_opener,ProxyHandler
    opener=build_opener(ProxyHandler({}))
    for _ in range(80):
        try:
            with opener.open(value['url']+'/api/v1/health',timeout=.5) as response:
                if response.status==200:return receipt
        except OSError:
            pass
        assert child.poll() is None, 'API exited; retained logs'
        time.sleep(.25)
    raise RuntimeError('API observation timeout; retain and inspect the same process')


def workers():
    value=state();configure(value)
    from app.core.config import local_config
    stack=worker_stack.prepare(ROOT,local_config(),test_id=value['schema'][8:],assets=Path(value['assets']))
    image_id=worker_stack.docker(['image','inspect','--format','{{.Id}}',WORKER_IMAGE]).strip()
    worker_stack.docker(['image','inspect','--format','{{.Id}}',BROKER_IMAGE])
    environment=dict(PAPERASSIST_ENV='test',PAPERASSIST_DB_SCHEMA=value['schema'],PAPERASSIST_DATA_DIR='/data',
        PAPERASSIST_TEST_DATABASE_URL_FILE='/run/secrets/database-url',PAPERASSIST_BROKER_URL_FILE='/run/secrets/broker-url',
        PAPERASSIST_TASK_QUEUE='paperassist.test.'+value['schema'][8:],PAPERASSIST_QUEUE_TEST_ALLOWED='1',
        PAPERASSIST_RESEARCH_STAGING_DIR='/research-staging',PAPERASSIST_WRITING_LIVE_ENABLED='0',
        PAPERASSIST_PLOT_WORKER_ENABLED='0',PAPERASSIST_NCBI_ENABLED='0',OPENAI_API_KEY='',OPENAI_API_KEY_FILE='',
        PAPERASSIST_PDF_RENDERER_URL='',PAPERASSIST_WORKER_HEALTH_FILE='/tmp/dispatcher-health',
        PAPERASSIST_WORKER_CONCURRENCY_CEILING='1')
    shared=dict(image=image_id,init=True,pull_policy='never',environment=environment,
        volumes=[f'{value["assets"]}:/data',f'{value["staging"]}:/research-staging',f'{ROOT / "backend/app"}:/app/app:ro'],
        secrets=['database-url','broker-url'],labels={'io.paperassist.w3.schema':value['schema']},
        depends_on={'rabbitmq':{'condition':'service_healthy'}},stop_grace_period='45s')
    compose=dict(services={
        'rabbitmq':dict(image=BROKER_IMAGE,pull_policy='never',hostname='rabbitmq',
            secrets=[dict(source='rabbitmq-config',target='/etc/rabbitmq/rabbitmq.conf')],
            volumes=['broker-data:/var/lib/rabbitmq'],labels={'io.paperassist.w3.schema':value['schema']},
            healthcheck=dict(test=['CMD','rabbitmq-diagnostics','-q','ping'],interval='5s',timeout='5s',retries=12)),
        'worker':dict(shared,mem_limit='4g',cpus=1,command=['python','-m','app.workers','worker'],
            healthcheck=dict(test=['CMD','python','-m','app.workers','health','worker'],interval='10s',timeout='8s',retries=6,start_period='10s')),
        'dispatcher':dict(shared,mem_limit='512m',command=['python','-m','app.workers','dispatch'],
            healthcheck=dict(test=['CMD','python','-m','app.workers','health','dispatch'],interval='10s',timeout='5s',retries=6,start_period='10s'))},
        secrets={name:dict(file=str(stack.directory/file)) for name,file in [('database-url','database-url'),('broker-url','broker-url'),('rabbitmq-config','rabbitmq.conf')]},
        volumes={'broker-data':{}})
    file=RUNTIME/'compose.json';save(file,compose)
    args=['compose','--project-name',stack.project,'--file',str(file)]
    worker_stack.docker(args+['config','--quiet'],stack=stack)
    output=worker_stack.docker(args+['up','-d','--no-build','--wait','--wait-timeout','60'],stack=stack,timeout=85)
    receipt=dict(project=stack.project,schema=value['schema'],image_id=image_id,worker_memory='4GiB',concurrency=1,
        services=['rabbitmq','worker','dispatcher'],renderer_started=False,source_mount_readonly=True,new_downloads=0,
        status=worker_stack.docker(args+['ps','--format','json'],stack=stack),startup_output=output)
    save(RUNTIME/'worker-runtime.json',receipt)
    return {k:receipt[k] for k in ('project','schema','image_id','services','worker_memory','concurrency')}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','serve','start-api','workers'))
    args=parser.parse_args()
    result=globals()[args.action.replace('-','_')]()
    if result is not None:print(json.dumps(result,ensure_ascii=True,default=str))
