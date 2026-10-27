"""Request-scoped task-list source reads without a database or file cache."""
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
from app.domain.manuscripts import sources
from app.domain.tasks.workspace import TaskWorkspaceService

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
