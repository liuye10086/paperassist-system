"""Focused reproductions for the deployment review; no Docker mutations."""
import ast
import asyncio
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch, AsyncMock

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('review_release',ROOT/'script/release/release.py')
release=importlib.util.module_from_spec(spec); spec.loader.exec_module(release)


class ReviewTests(unittest.TestCase):
    def test_exact_unlabelled_resource_collision_rejected(self):
        for kind,name in [('volume','pa-release-fresh_database'),('volume','pa-release-fresh_broker'),('network','pa-release-fresh_private')]:
            def docker(args,**kwargs):
                return name if args[:2]==[kind,'ls'] and '--filter' not in args else ''
            with self.subTest(kind=kind,name=name),patch.object(release,'docker',side_effect=docker),patch.object(release,'candidate',return_value={}),patch.object(release,'new_directory',side_effect=AssertionError('fresh directory must not be touched')):
                with self.assertRaisesRegex(ValueError,'target'): release.create('fresh','unused',18443,Path('.'))

    def test_existing_database_mount_and_network_binding_rejected(self):
        state={'project':'pa-release-one','namespace':'one'}
        resources={'volume': [{'Name':'pa-release-one_database','Labels':{'com.docker.compose.project':'pa-release-one','com.docker.compose.volume':'database'}}],
                   'network':[{'Name':'pa-release-one_private','Id':'network-id','Internal':True,'Labels':{'com.docker.compose.project':'pa-release-one','com.docker.compose.network':'private'}}]}
        for bad in ['mount','network']:
            container={'Id':'container-id','Config':{'Labels':{'com.docker.compose.project':state['project'],'com.docker.compose.service':'db','io.paperassist.release':'one','io.paperassist.workspace':str(ROOT)}},'State':{'Running':True},'Mounts':[{'Type':'volume','Name':'foreign' if bad=='mount' else 'pa-release-one_database','Destination':'/var/lib/postgresql'}],'NetworkSettings':{'Networks':{'pa-release-one_private':{'NetworkID':'foreign' if bad=='network' else 'network-id'}}}}
            def docker(args,**kwargs):
                if args[0]=='ps': return 'container-id'
                if args[0]=='inspect':
                    if '--format' in args: return '|'.join(json.dumps(v) for v in [container['Id'],container['Config']['Labels'],container['State']])
                    return json.dumps([container])
                if args[1]=='ls': return '\n'.join(x['Name'] for x in resources[args[0]])
                return json.dumps(resources[args[0]])
            with self.subTest(bad=bad),patch.object(release,'docker',side_effect=docker):
                with self.assertRaisesRegex(ValueError,'volume binding' if bad=='mount' else 'network binding'): release.owned(state)

    def test_compose_uses_verified_candidate_snapshot_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'context').mkdir(); frozen=root/'context/compose.release.yml'; frozen.write_text('services: {}')
            entries=[{'path':'compose.release.yml','bytes':frozen.stat().st_size,'sha256':release.sha(frozen)}]
            (root/'source-manifest.json').write_text(json.dumps(entries))
            state={'candidate':{'receipt':str(root/'candidate.json'),'source_manifest_sha256':release.sha(root/'source-manifest.json')},'project':'test'}
            with patch.object(release,'environment',return_value={}),patch.object(release,'docker',return_value='') as docker:
                release.compose(state,['config','--quiet'])
                self.assertIn(str(frozen),docker.call_args.args[0])
                frozen.write_text('services: {changed: {}}')
                with self.assertRaisesRegex(ValueError,'Compose'): release.compose(state,['up','-d'])
                self.assertEqual(docker.call_count,1)

    def test_collector_sampling_reuses_container(self):
        state={'project':'pa-release-one','candidate':{'image':'sha256:'+'a'*64}}
        container={'id':'collector-id','service':'collector','state':{'Running':True},'image':state['candidate']['image']}
        with patch.object(release,'candidate_compose'),patch.object(release,'owned',return_value=[container]),patch.object(release,'compose') as compose,patch.object(release,'docker',return_value='{}') as docker:
            release.operator(state,'collect'); release.operator(state,'collect')
            compose.assert_not_called()
            self.assertEqual(docker.call_count,2)
            self.assertEqual(docker.call_args.args[0],['exec','collector-id','python','release_entry.py','collect'])

    def test_resume_updates_state_only_after_explicit_migration_without_bootstrap(self):
        with tempfile.TemporaryDirectory() as d:
            directory=Path(d); (directory/'control').mkdir(); (directory/'control/maintenance.json').write_text('{"mode":"maintenance"}')
            state={'directory':d,'initialized':True,'schema_ready':False,'candidate':{'image':'old'}}
            with patch.object(release,'candidate',return_value={'image':'new'}),patch.object(release,'require_stopped'),patch.object(release,'bootstrap') as bootstrap,patch.object(release,'operator',side_effect=RuntimeError('migration failed')):
                with self.assertRaises(RuntimeError): release.resume_migration(state,'candidate','0052_admin_configurations')
                bootstrap.assert_not_called(); self.assertFalse(state['schema_ready']); self.assertNotIn('revision',state)
            with patch.object(release,'candidate',return_value={'image':'new'}),patch.object(release,'require_stopped'),patch.object(release,'operator') as operator:
                release.resume_migration(state,'candidate','0052_admin_configurations')
                operator.assert_called_once_with(state,'migrate',migration=True,extra=['--revision','0052_admin_configurations'],timeout=300)
                self.assertFalse(state['schema_ready']); self.assertEqual(state['revision'],'0052_admin_configurations')

    def test_hard_deadline_rejects_snapshot_before_database_or_assets(self):
        with patch.object(release,'maintenance'),patch.object(release,'compose'),patch.object(release,'owned',return_value=[{'service':'api','state':{'Running':False,'ExitCode':137}}]),patch.object(release,'task_counts') as counts:
            with self.assertRaisesRegex(ValueError,'gracefully'): release.backup({})
            counts.assert_not_called()

    def test_backup_includes_prepared_research_bytes_without_changing_originals(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'backups').mkdir()
            (root/'assets').mkdir()
            (root/'assets'/'saved').write_bytes(b'published')
            (root/'source-manifest.json').write_text('[]', encoding='utf-8')
            state={'directory':str(root),'namespace':'source','candidate':{'receipt':str(root/'candidate.json'),
                'source_manifest_sha256':release.sha(root/'source-manifest.json')}}

            def dump(_state,args,**kwargs):
                (root/args[-1].lstrip('/')).write_bytes(b'database')

            def capture(_state,asset_copy):
                (asset_copy/'prepared').write_bytes(b'staged')
                return [entry for entry in release.file_manifest(asset_copy) if entry['path']=='prepared']

            with patch.object(release,'quiesce'),patch.object(release,'operator',return_value='{}'), \
                    patch.object(release,'stop_collector'),patch.object(release,'compose',side_effect=dump), \
                    patch.object(release,'prepared_research_assets',side_effect=capture,create=True):
                snapshot=Path(release.backup(state))
            self.assertEqual((snapshot/'assets'/'prepared').read_bytes(),b'staged')
            self.assertEqual({item['path'] for item in release.read(snapshot/'backup.json')['assets']},{'saved','prepared'})
            self.assertEqual(list((root/'assets').iterdir()),[root/'assets'/'saved'])

    def test_restore_rejects_missing_prepared_research_bytes_before_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            source=root/'source'
            (source/'assets').mkdir(parents=True)
            target=root/'target'
            (target/'backups').mkdir(parents=True)
            state={'directory':str(target)}
            selected={'image':'candidate-image'}
            receipt={'namespace':'source','fingerprint':{},'assets':[]}
            def create_target(*args,restore_pending=False):
                if restore_pending: state['restore_pending']=True
                release.save(state)
                return state

            with patch.object(release,'candidate',return_value=selected), \
                    patch.object(release,'validate_backup',return_value=receipt), \
                    patch.object(release,'create',side_effect=create_target),patch.object(release,'bootstrap'), \
                    patch.object(release,'compose',return_value=''),patch.object(release,'operator',return_value='{}'), \
                    patch.object(release,'prepared_research_assets',side_effect=ValueError('missing prepared leaf'),create=True):
                with self.assertRaisesRegex(ValueError,'missing prepared leaf'):
                    release.restore('target',source,'candidate',18443,Path('.'))
            self.assertNotIn('schema_ready',state)
            self.assertTrue(release.read(target/'state.json')['restore_pending'])
            self.assertFalse((target/'restore-receipt.json').exists())

    def test_unverified_restore_cannot_be_marked_ready_via_migration_or_switch(self):
        state={'restore_pending':True,'initialized':True,'schema_ready':False}
        actions=[(release.initialize,()),(release.resume_migration,('candidate','head')),
                 (release.switch,('candidate',)),(release.up,()),(release.backup,())]
        for action,args in actions:
            with self.subTest(action=action.__name__),self.assertRaisesRegex(ValueError,'Incomplete restore'):
                action(state,*args)

    def test_compose_tmpfs_single_complete_mount(self):
        import yaml
        config=yaml.safe_load((ROOT/'compose.release.yml').read_text())
        for service,size in [('api','256m'),('migration','256m'),('collector','256m'),('renderer','512m')]:
            self.assertEqual(config['services'][service]['tmpfs'],[f'/tmp:size={size},mode=1777'])


class ShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_admitted_request_is_not_cancelled_by_inner_shutdown_deadline(self):
        import uvicorn
        tree=ast.parse((ROOT/'infra/api/release_web.py').read_text())
        entry=tree.body[-1]
        captured={}
        with patch.object(uvicorn,'run',side_effect=lambda *args,**kwargs:captured.update(kwargs)):
            exec(compile(ast.Module(body=entry.body,type_ignores=[]),'entry','exec'),{'app':object()})
        self.assertIsNone(captured.get('timeout_graceful_shutdown'))
        config=uvicorn.Config(lambda *a:None,timeout_graceful_shutdown=captured.get('timeout_graceful_shutdown'))
        server=uvicorn.Server(config); server.servers=[]; server.lifespan=types.SimpleNamespace(shutdown=AsyncMock())
        done=asyncio.Event(); request=asyncio.create_task(done.wait()); server.server_state.tasks.add(request)
        request.add_done_callback(server.server_state.tasks.discard)
        shutdown=asyncio.create_task(server.shutdown())
        await asyncio.sleep(0.25)
        self.assertFalse(shutdown.done()); self.assertFalse(request.cancelled())
        done.set(); await asyncio.wait_for(shutdown,1)
        self.assertTrue(request.result())


if __name__=='__main__': unittest.main()
