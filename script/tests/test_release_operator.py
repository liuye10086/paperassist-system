import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / 'script/release/release.py'
        if path.exists():
            spec = importlib.util.spec_from_file_location('release_operator', path)
            cls.release = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = cls.release
            spec.loader.exec_module(cls.release)

    def test_operator_exists(self):
        self.assertTrue((ROOT / 'script/release/release.py').is_file(), 'approved operator is missing')

    def test_namespace_rejects_escape_and_existing_target(self):
        if not hasattr(self, 'release'): self.skipTest('operator missing')
        for name in ['../original', '', 'public/foo', 'A', 'a'*33]:
            with self.assertRaises(ValueError): self.release.validate_namespace(name)
        with tempfile.TemporaryDirectory() as d, patch.object(self.release, 'RELEASES', Path(d)):
            (Path(d)/'existing').mkdir()
            with self.assertRaises(ValueError): self.release.new_directory('existing')

    def test_manifest_excludes_secret_runtime_files(self):
        if not hasattr(self, 'release'): self.skipTest('operator missing')
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name in ['backend/app/ok.py','backend/app/.env','backend/app/__pycache__/x.pyc','backend/data/private.txt','frontend/dist/index.html','backend/requirements.txt','backend/alembic.ini']:
                p=root/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('x')
            paths=[p.as_posix() for p in self.release.source_files(root)]
            self.assertIn('backend/app/ok.py',paths)
            self.assertFalse(any('.env' in p or '__pycache__' in p or 'private' in p for p in paths))

    def test_maintenance_binding_and_atomic_replacement(self):
        if not hasattr(self, 'release'): self.skipTest('operator missing')
        with tempfile.TemporaryDirectory() as d:
            directory=Path(d); (directory/'control').mkdir()
            state={'namespace':'one','directory':str(directory)}
            self.release.maintenance(state,'maintenance')
            first=json.loads((directory/'control/maintenance.json').read_text())
            self.assertEqual(first['namespace'],'one')
            self.assertEqual(first['environment'],'production')
            first['namespace']='other'
            (directory/'control/maintenance.json').write_text(json.dumps(first))
            with self.assertRaises(ValueError): self.release.maintenance(state,'normal')

    def test_quiesce_orders_api_drain_workers_and_final_check(self):
        if not hasattr(self, 'release'): self.skipTest('operator missing')
        calls=[]
        state={}
        with patch.object(self.release,'maintenance',side_effect=lambda *a:calls.append('maintenance')), patch.object(self.release,'compose',side_effect=lambda s,a,**kw:calls.append(a) or ''), patch.object(self.release,'task_counts',side_effect=lambda s:calls.append('count') or {'queued':0,'running':0}), patch.object(self.release,'require_stopped',side_effect=lambda *a:calls.append('stopped')),patch.object(self.release,'stop_collector',side_effect=lambda *a:calls.append('collector-stopped')):
            self.release.quiesce(state)
        self.assertEqual(calls[0],'maintenance')
        self.assertEqual(calls[1],['stop','-t','120','api'])
        self.assertLess(calls.index('count'),calls.index(['stop','-t','120','dispatcher','worker']))
        self.assertEqual(calls[-2:],['count','collector-stopped'])

    def test_archive_manifest_rejects_traversal_and_changed_bytes(self):
        if not hasattr(self, 'release'): self.skipTest('operator missing')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'hidden').mkdir(); (root/'hidden/.intent').write_text('original')
            entries=self.release.file_manifest(root)
            self.release.validate_files(root,entries)
            (root/'hidden/.intent').write_text('changed')
            with self.assertRaises(ValueError): self.release.validate_files(root,entries)
            with self.assertRaises(ValueError): self.release.validate_files(root,[{'path':'../escape','bytes':0,'sha256':'0'*64}])

    def test_candidate_manifest_bound_to_actual_image_label(self):
        if not hasattr(self, 'release'): self.skipTest('operator missing')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'source-manifest.json').write_text('[]')
            value={'image':'sha256:'+'a'*64,'source_manifest_sha256':self.release.sha(root/'source-manifest.json')}
            (root/'candidate.json').write_text(json.dumps(value))
            with patch.object(self.release,'docker',return_value=json.dumps({'Id':value['image'],'Labels':{'io.paperassist.source-manifest':'wrong'}})):
                with self.assertRaisesRegex(ValueError,'manifest'): self.release.candidate(root/'candidate.json')

    def test_source_manifest_includes_operator_and_compose_contract(self):
        if not hasattr(self, 'release'): self.skipTest('operator missing')
        names=[p.as_posix() for p in self.release.source_files(ROOT)]
        self.assertIn('compose.release.yml',names)
        self.assertIn('script/release/release.py',names)

if __name__=='__main__': unittest.main()
