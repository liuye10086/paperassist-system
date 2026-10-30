"""Request-scoped task-list source reads without a database or file cache."""
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
from hashlib import sha256
from tempfile import TemporaryDirectory
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
from app.domain.manuscripts import sources
from app.domain.tasks.workspace import TaskWorkspaceService
from app.adapters.document_objects import DocumentObjects
from app.adapters.file_objects import FileObjects, LocalFileObjects
from app.adapters.task_store import DatasetTaskAssets, TaskStore
from app.core.exceptions import StorageError
from app.domain.documents.service import document_snapshot
from app.domain.external_evidence.service import ExternalEvidenceService
from app.domain.parsed_evidence.documents import docx_items
from app.adapters.docx_parser import parse_docx, DOCX_SETTINGS
from tests.helpers.document_samples import document_bytes


class PersistedDocument:
 """Real files and validators; only SQL transport is replaced by fixed rows."""
 def __init__(self, root):
  self.project='project';self.owner='owner';self.active=True;self.newer=False
  original=document_bytes();file_id=str(uuid4());parse_id=str(uuid4());task_id=str(uuid4())
  self.file=dict(id=file_id,filename='paper.docx',file_type='docx',storage_backend='local',
   object_key=f'files/{file_id}.docx',sha256=sha256(original).hexdigest(),size_bytes=len(original))
  LocalFileObjects(root).port.put_immutable(self.file['object_key'],original)
  result=parse_docx(original,self.file['filename'],DOCX_SETTINGS)
  self.manifest=DocumentObjects(root).save(parse_id,result)
  snapshot=document_snapshot(self.project,self.file,parse_id,1)
  self.row=dict(id=parse_id,file_id=file_id,task_id=task_id,version=1,source_sha256=self.file['sha256'],
   parser_version=snapshot['parser_version'],settings_json=snapshot['settings'],result_json=self.manifest,
   status='succeeded',input_snapshot=snapshot,workflow_version='docx_document_v1',project_id=self.project,
   user_id=self.owner,task_type='parse_file')
  self.assets=DatasetTaskAssets(self.owner,object(),root)
  self.service=types.SimpleNamespace(store=TaskStore(self.owner,self.assets.db_config),assets=self.assets)
  self.selection=dict(kind='document_version',id=parse_id,file_id=file_id,role='image_observation')
  base=f'/api/v1/projects/{self.project}/files/{file_id}/document-versions/{parse_id}'
  items=[i.model_dump(mode='json') for i in docx_items(result.document,base+'/images')]
  source=dict(kind='document_version',file_id=file_id,filename=self.file['filename'],file_type='docx',
   source_sha256=self.file['sha256'],size_bytes=len(original),
   original_download_url=f'/api/v1/projects/{self.project}/files/{file_id}/download',
   version_id=parse_id,version=1,sha256=self.manifest['object']['sha256'],
   object_download_url=base+'/download',review_status='not_reviewed')
  images=[]
  for image in result.document.images:
   associations=[a for item in items if item.get('image_id')==image.id for a in item.get('associations',[])]
   images.append(dict(id=image.id,sha256=image.sha256,caption_candidates=[a['caption_text'] for a in associations],
    preview_url=base+'/images/'+image.id))
  self.expected=dict(**self.selection,label=self.file['filename'],sha256=source['sha256'],
   download_url=base+'/download',content=dict(source=source,items=items,images=images))

 def execute(self, sql, params):
  if 'JOIN users u' in sql:
   value={'owner_id':self.owner} if params==(self.project,self.owner) and self.active else None
  elif sql.startswith('SELECT * FROM files WHERE id='):
   value=self.file if params==(self.file['id'],self.project) else None
  elif sql.startswith('SELECT * FROM files WHERE project_id='):
   value=self.file if params==(self.project,self.file['id']) else None
  elif 'JOIN tasks t' in sql:
   value=self.row if params==(self.file['id'],self.row['id']) else None
  elif sql.startswith('SELECT * FROM file_parse_results'):
   value=self.row if params==(self.row['id'],self.row['task_id']) else None
  elif sql.startswith('SELECT 1 FROM file_parse_results'):
   value={'exists':1} if self.newer else None
  else:raise AssertionError('Unexpected SQL: '+sql)
  return types.SimpleNamespace(fetchone=lambda:deepcopy(value))

 def read(self):return sources.read_source(self.service,self.project,self.selection)


class SourceMaterialReadTests(unittest.TestCase):
 def setUp(self):
  self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.fixture=PersistedDocument(Path(self.temp.name))
  self.connection=patch.object(TaskStore,'connection',lambda store,write=False:nullcontext(self.fixture))
  self.connection.start();self.addCleanup(self.connection.stop)

 def test_document_source_reads_original_json_and_each_image_once_with_equal_response(self):
  counts={'original':0,'json':0,'image':0};original=FileObjects.original;read=DocumentObjects._read
  def read_original(store,record):counts['original']+=1;return original(store,record)
  def read_object(store,record,limit):
   counts['json' if record['object_key'].endswith('.json') else 'image']+=1
   return read(store,record,limit)
  with patch.object(FileObjects,'original',read_original),patch.object(DocumentObjects,'_read',read_object):
   self.assertEqual(self.fixture.read(),self.fixture.expected)
  self.assertEqual(counts,{'original':1,'json':1,'image':2})

 def test_public_evidence_source_contract_is_unchanged(self):
  f=self.fixture;value=ExternalEvidenceService(f.assets).source(f.project,f.file['id'],'document_version',f.row['id'])
  self.assertEqual(value,(f.expected['content']['source'],f.expected['content']['items']))

 def test_changes_compares_each_snapshot_and_reads_bytes_again_on_next_request(self):
  f=self.fixture;cache={};snapshot={'sources':[deepcopy(f.expected)]}
  self.assertEqual(sources.changes(f.service,f.project,snapshot,current_sources=cache),[])
  changed=deepcopy(snapshot);changed['sources'][0]['label']='different frozen label'
  self.assertEqual(sources.changes(f.service,f.project,changed,current_sources=cache)[0]['reasons'],['source_changed'])
  f.newer=True
  self.assertEqual(sources.changes(f.service,f.project,snapshot,current_sources=cache)[0]['reasons'],['newer_source_version'])
  image=Path(self.temp.name)/f.manifest['images'][0]['object_key'];image.write_bytes(b'bad')
  self.assertIn('source_unavailable_or_changed',sources.changes(f.service,f.project,snapshot,current_sources={})[0]['reasons'])
  with self.assertRaises(StorageError):f.read()

 def test_identity_summary_and_object_corruption_are_still_rejected(self):
  for mutation in ('producer','parse_id','parser_version','counts','warnings','image_sha','image_size','image_mime','document_bytes','image_bytes','original_bytes'):
   with self.subTest(mutation=mutation),TemporaryDirectory() as root:
    f=PersistedDocument(Path(root))
    if mutation=='producer':f.row['user_id']='foreign'
    elif mutation=='parse_id':f.row['input_snapshot']['parse_id']=str(uuid4())
    elif mutation=='parser_version':f.row['parser_version']='wrong'
    elif mutation=='counts':f.manifest['summary']['counts']['paragraphs']+=1
    elif mutation=='warnings':f.manifest['summary']['warnings'].append(dict(code='invented',message='wrong',count=1))
    elif mutation=='image_sha':f.manifest['images'][0]['sha256']='a'*64
    elif mutation=='image_size':f.manifest['images'][0]['size_bytes']+=1
    elif mutation=='image_mime':f.manifest['images'][0]['mime']='image/jpeg'
    elif mutation=='document_bytes':(Path(root)/f.manifest['object']['object_key']).write_bytes(b'bad')
    elif mutation=='image_bytes':(Path(root)/f.manifest['images'][0]['object_key']).write_bytes(b'bad')
    elif mutation=='original_bytes':(Path(root)/f.file['object_key']).write_bytes(b'bad')
    with patch.object(TaskStore,'connection',lambda store,write=False:nullcontext(f)):
     with self.assertRaises(StorageError):f.read()

 def test_foreign_project_and_disabled_owner_cannot_read(self):
  f=self.fixture
  with self.assertRaises(StorageError) as foreign:sources.read_source(f.service,'foreign',f.selection)
  self.assertEqual(foreign.exception.status,404)
  f.active=False
  with self.assertRaises(StorageError) as disabled:f.read()
  self.assertEqual(disabled.exception.status,404)

class SourceReadTests(unittest.TestCase):
 def test_reuses_verified_read_but_compares_every_snapshot_and_rechecks_next_request(self):
  source=dict(kind='analysis_run',id='run',file_id='file',role='result',content={'setup_revision':1})
  db=types.SimpleNamespace(execute=lambda *a:types.SimpleNamespace(fetchone=lambda:{'revision':1}))
  service=types.SimpleNamespace(store=types.SimpleNamespace(connection=lambda:nullcontext(db)))
  cache={};snapshot={'sources':[source]}
  with patch.object(sources,'read_source',return_value=deepcopy(source)) as read:
   self.assertEqual(sources.changes(service,'project',snapshot,current_sources=cache),[])
   altered=deepcopy(snapshot);altered['sources'][0]['content']['setup_revision']=2
   self.assertIn('source_changed',sources.changes(service,'project',altered,current_sources=cache)[0]['reasons'])
   self.assertEqual(read.call_count,1)
   read.return_value={**source,'sha256':'changed'}
   self.assertIn('source_changed',sources.changes(service,'project',snapshot,current_sources={})[0]['reasons'])
   self.assertEqual(read.call_count,2)
   sources.changes(service,'another-project',snapshot,current_sources=cache)
   self.assertEqual(read.call_count,3)
 def test_list_reuse_is_local_and_ownership_task_checks_still_run(self):
  service=TaskWorkspaceService.__new__(TaskWorkspaceService)
  task={'id':'one','input_snapshot':{},'task_type':'manuscript_draft'}
  store=types.SimpleNamespace(user_id='user',connection=lambda:nullcontext(object()),require_project=lambda *a:None,require_task=lambda *a:task,public_task=lambda row:row)
  service.store=store;caches=[]
  def source(db,row,*,manuscript_sources=None):caches.append(manuscript_sources);return {}
  service.source=source
  with patch('app.adapters.legacy_task_query.mixed_task_page',return_value=(2,[{'origin':'unified','id':'one'}]*2)),patch.object(store,'require_task',wraps=store.require_task) as require_task:
   service.list('project');service.list('project')
   self.assertEqual(require_task.call_count,4)
  self.assertIsNotNone(caches[0]);self.assertIs(caches[0],caches[1]);self.assertIs(caches[2],caches[3]);self.assertIsNot(caches[0],caches[2])

if __name__=='__main__':unittest.main()
