"""Actual runtime regressions; no deployment mutations."""
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import yaml
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('runtime_release',ROOT/'script/release/release.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

class RuntimeTests(unittest.TestCase):
 def test_renderer_address_matches_existing_transport_allowlist(self):
  c=yaml.safe_load((ROOT/'compose.release.yml').read_text())
  self.assertEqual(c['services']['worker']['environment']['PAPERASSIST_PDF_RENDERER_URL'],'http://pdf-renderer:8080')
  self.assertIn('pdf-renderer',c['services']['renderer']['networks']['private']['aliases'])
 def test_api_front_network_and_verified_https_health(self):
  c=yaml.safe_load((ROOT/'compose.release.yml').read_text())
  self.assertFalse(c['networks'].get('front',{}).get('internal',True))
  self.assertTrue(c['networks']['private']['internal'])
  self.assertEqual(set(c['services']['api']['networks']),{'private','front'})
  health=' '.join(c['services']['api']['healthcheck']['test'])
  self.assertIn('ssl.create_default_context',health);self.assertIn('/run/tls/ca.pem',health)
  self.assertIn('https://127.0.0.1:8443/api/v1/health',health)
  self.assertNotIn('CERT_NONE',health)
  for name,service in c['services'].items():
   if name!='api':
    self.assertEqual(set(service['networks']),{'private'});self.assertNotIn('ports',service)
 def test_fresh_front_name_collision_is_rejected(self):
  def docker(args,**kw):return 'pa-release-fresh_front' if args[:2]==['network','ls'] else ''
  with patch.object(r,'docker',side_effect=docker):
   with self.assertRaisesRegex(ValueError,'target'):r.named_resources('pa-release-fresh',fresh=True)
 def test_network_internal_flag_is_checked(self):
  for suffix,internal in [('private',False),('front',True)]:
   name='pa-release-one_'+suffix
   row={'Name':name,'Internal':internal,'Labels':{'com.docker.compose.project':'pa-release-one','com.docker.compose.network':suffix}}
   def docker(args,**kw):
    if args[:2]==['network','ls']:return name
    if args[:2]==['network','inspect']:return json.dumps([row])
    return ''
   with self.subTest(suffix=suffix),patch.object(r,'docker',side_effect=docker):
    with self.assertRaisesRegex(ValueError,'isolation'):r.named_resources('pa-release-one')
 def test_front_network_is_api_only_and_private_is_internal(self):
  state={'project':'pa-release-one','namespace':'one'}
  network=lambda suffix,internal:{'Id':suffix,'Internal':internal,'Labels':{'com.docker.compose.project':state['project'],'com.docker.compose.network':suffix}}
  resources={state['project']+'_private':network('private',True),state['project']+'_front':network('front',False)}
  row={'Id':'api-id','Image':'image','Config':{'Labels':{'io.paperassist.release':'one','io.paperassist.workspace':str(ROOT),'com.docker.compose.service':'api'}},'State':{'Running':True},'NetworkSettings':{'Networks':{key:{'NetworkID':value['Id']} for key,value in resources.items()}}}
  with patch.object(r,'named_resources',return_value=resources),patch.object(r,'docker',side_effect=lambda args,**kw:'api-id' if args[0]=='ps' else json.dumps([row])):
   self.assertEqual(r.owned(state)[0]['service'],'api')
   row['Config']['Labels']['com.docker.compose.service']='worker'
   with self.assertRaisesRegex(ValueError,'network'):r.owned(state)
 def test_parallel_exact_probes_and_single_owned_observation(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'control').mkdir();start={'startup_id':'startup','observed_at':'2026-10-27T01:00:01+00:00'}
   (p/'control/worker-startup.json').write_text(json.dumps(start));(p/'control/status.json').write_text('{}')
   state={'namespace':'one','directory':d,'project':'pa-release-one','candidate':{'image':'image'}}
   rows=[{'id':key+'-id','service':key,'image':'image','state':{'Running':True,'StartedAt':'2026-10-27T01:00:00Z'}} for key in ['worker','dispatcher','broker','collector']]
   barrier=threading.Barrier(3);calls=[]
   def docker(args,**kw):
    calls.append(args)
    if args[0]=='exec':barrier.wait(timeout=2);return ''
    if args[0]=='ps':return 'worker-id'
    if args[0]=='inspect':return json.dumps([{'Id':'worker-id','Image':'image','State':rows[0]['state']}])
    raise AssertionError(args)
   with patch.object(r,'owned',return_value=rows) as owned,patch.object(r,'docker',side_effect=docker),patch.object(r,'compose',side_effect=AssertionError('probe must use inspected identity')),patch.object(r,'operator',return_value='{}') as operator:
    r.sample(state)
   self.assertEqual(owned.call_count,1)
   self.assertTrue(all(v['status']=='healthy' for v in r.read(p/'control/observations.json')['services'].values()))
   self.assertEqual(r.read(p/'control/observations.json')['worker_startup_id'],'startup')
   self.assertEqual(operator.call_args.kwargs['containers'],rows)
   self.assertEqual({c[1] for c in calls if c[0]=='exec'},{'worker-id','dispatcher-id','broker-id'})

if __name__=='__main__':unittest.main()
