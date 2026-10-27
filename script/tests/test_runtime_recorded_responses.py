"""Read-only PostgreSQL aggregate tests using synthetic CTE rows, never provider calls."""
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent.parent/'backend'))
import unittest
from unittest.mock import patch
from psycopg.types.json import Jsonb
from app.db.database import database_connection
from app.domain import runtime_status as runtime

class RecordedResponseSqlTests(unittest.TestCase):
 now=datetime(2026,10,27,4,0,tzinfo=timezone.utc)
 def doi(self,status,**extra):
  result=dict(execution_kind='doi_org',network_attempted=True,http_status=status)
  result.update(extra.pop('result',{}))
  return dict(kind='doi_resolution',source_kind='pubmed',snapshot_json=dict(result=result),created_at=self.now.isoformat(),**extra)
 def pmc(self,statuses,kind='pmc_oai'):
  return dict(source_kind=kind,snapshot_json=dict(responses=[dict(http_status=s) for s in statuses]),created_at=self.now.isoformat())
 def collected(self,checks=(),pmc=()):
  prefix='''WITH literature_check_receipts AS (SELECT * FROM jsonb_to_recordset(%s::jsonb)
   AS t(kind text,source_kind text,snapshot_json jsonb,created_at timestamptz)),
   literature_pmc_receipts AS (SELECT * FROM jsonb_to_recordset(%s::jsonb)
   AS t(source_kind text,snapshot_json jsonb,created_at timestamptz)) '''
  @contextmanager
  def connection(**kw):
   self.assertEqual(kw,{'capture':True})
   with database_connection(capture=True) as db:
    class FixtureDB:
     def execute(inner,sql,args=()):
      if 'FROM literature_check_receipts' in sql:
       self.assertNotIn('SELECT *',sql);self.assertNotIn('model_calls',sql)
       return db.execute(prefix+sql,(Jsonb(list(checks)),Jsonb(list(pmc)),*args))
      return db.execute(sql,args)
    yield FixtureDB()
  binding=runtime.binding()
  observation=dict(binding,observed_at=self.now.isoformat(),services={name:dict(status='unknown',observed_at=None) for name in ('worker','dispatcher','broker')},worker_startup_id=None,external_limits=None)
  with patch.object(runtime,'database_connection',connection),patch.object(runtime,'read_file',return_value=None):
   receipt=runtime.collect(observation,now=self.now)
  self.assertEqual(receipt['database']['status'],'healthy')
  return receipt['external_limits']
 def test_recorded_doi_and_pmc_statuses_are_counted_without_loading_bodies(self):
  limits=self.collected([self.doi(429),self.doi(200)],[self.pmc([429,503])])
  self.assertIsNotNone(limits)
  self.assertEqual(limits['observed_calls'],4);self.assertEqual(limits['observed_429'],2)
  self.assertEqual(limits['window_seconds'],3600);self.assertEqual(limits['coverage'],'recorded_provider_responses')
 def test_synthetic_invalid_unattempted_and_outside_window_are_excluded(self):
  synthetic=self.doi(429);synthetic['source_kind']='synthetic_fixture'
  old=self.doi(429);old['created_at']=(self.now-timedelta(seconds=3601)).isoformat()
  future=self.doi(429);future['created_at']=(self.now+timedelta(seconds=1)).isoformat()
  other=self.doi(429);other['kind']='saved_record'
  malformed_pmc=self.pmc([]);malformed_pmc['snapshot_json']['responses']={}
  checks=[synthetic,old,future,other,self.doi(429,result={'network_attempted':False}),self.doi(429,result={'execution_kind':'local'})]+[self.doi(s) for s in [None,'429',True,99,600,429.5,1e100]]
  limits=self.collected(checks,[self.pmc([429],'synthetic_fixture'),self.pmc([None,'429',True,99,600,429.5,1e100]),malformed_pmc])
  self.assertIsNone(limits)
 def test_no_recorded_responses_remains_unknown(self):
  self.assertIsNone(self.collected())

if __name__=='__main__':unittest.main()
