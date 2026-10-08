"""The launcher cannot route a test Worker to development data or leak secrets."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dev'))
import worker_stack


class WorkerStackTests(unittest.TestCase):
    def test_acl_identity_accepts_utf8_localized_account_name(self):
        whoami = subprocess.CompletedProcess([], 0, '"用户","S-1-5-21-123"\r\n'.encode('utf-8'), b'')
        with patch.object(worker_stack.os, 'name', 'nt'), patch.object(worker_stack.subprocess, 'run', return_value=whoami) as run:
            worker_stack.protect_directory(Path('.'))
        self.assertIn('*S-1-5-21-123:(OI)(CI)F', run.call_args.args[0])

    def values(self):
        return {'PAPERASSIST_DATABASE_URL': 'postgresql://paperassist_runtime:p%40ss@localhost:5432/paperassist_system',
                'PAPERASSIST_TEST_DATABASE_URL': 'postgresql://paperassist_test_runtime:test@localhost:5432/paperassist_system_test',
                'OPENAI_API_KEY': 'model-secret-marker',
                'PAPERASSIST_MIGRATION_DATABASE_URL': 'migration-secret-marker'}

    def test_model_key_is_private_and_migration_secret_never_enters_bundle(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(worker_stack, 'protect_directory'):
            root = Path(directory)
            config = worker_stack.prepare(root, self.values())
            contents = '\n'.join(path.read_text() for path in config.directory.iterdir() if path.is_file())
            self.assertEqual((config.directory / 'model-api-key').read_text(), 'model-secret-marker')
            self.assertNotIn('migration-secret-marker', contents)
            self.assertEqual(config.environment['PAPERASSIST_TASK_QUEUE'], 'paperassist.word')
            database = (config.directory / 'database-url').read_text()
            self.assertIn('host.docker.internal', database)
            self.assertIn('p%40ss', database)
            public = (config.directory / 'stack.json').read_text()
            self.assertNotIn('p%40ss', public)
            self.assertNotIn('amqp://', public)
            self.assertNotIn('model-secret-marker', public)
            self.assertNotIn('model-secret-marker', str(config.environment))

    def test_restart_reuses_broker_credentials_and_storage(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(worker_stack, 'protect_directory'):
            root = Path(directory)
            first = worker_stack.prepare(root, self.values())
            password = (first.directory / 'broker-url').read_bytes()
            second = worker_stack.prepare(root, self.values())
            self.assertEqual(first.project, second.project)
            self.assertEqual(password, (second.directory / 'broker-url').read_bytes())

    def test_test_stack_requires_matching_uuid_schema_and_separate_assets(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(worker_stack, 'protect_directory'):
            root = Path(directory)
            test_id = 'a' * 32
            values = {**self.values(), 'PAPERASSIST_ENV': 'test', 'PAPERASSIST_DB_SCHEMA': 'pa_test_' + test_id}
            with self.assertRaises(ValueError):
                worker_stack.prepare(root, values, test_id=test_id, assets=root / 'backend' / 'data')
            with self.assertRaises(ValueError):
                worker_stack.prepare(root, {**values, 'PAPERASSIST_DB_SCHEMA': 'public'}, test_id=test_id,
                                     assets=root / 'test-data')
            config = worker_stack.prepare(root, values, test_id=test_id, assets=root / 'test-data')
            self.assertEqual(config.environment['PAPERASSIST_TASK_QUEUE'], 'paperassist.test.' + test_id)
            self.assertEqual(config.environment['PAPERASSIST_QUEUE_TEST_ALLOWED'], '1')
            self.assertNotEqual(config.project, worker_stack.prepare(root, self.values()).project)
            self.assertIn('paperassist_system_test', (config.directory / 'database-url').read_text())
            self.assertEqual((config.directory / 'model-api-key').read_text(), '')

    def test_prepared_key_rotation_changes_worker_config_revision(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(worker_stack, 'protect_directory'):
            root = Path(directory)
            first = worker_stack.prepare(root, self.values())
            again = worker_stack.prepare(root, self.values())
            changed = worker_stack.prepare(root, {**self.values(), 'OPENAI_API_KEY': 'changed-test-key'})
            key = 'PAPERASSIST_WORKER_CONFIG_REVISION'
            self.assertEqual(first.environment[key], again.environment[key])
            self.assertNotEqual(first.environment[key], changed.environment[key])

    def test_model_key_file_enforces_raw_byte_limit_before_trimming(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(worker_stack, 'protect_directory'):
            root = Path(directory)
            secret = root / 'test-key'
            for content in (b'a' * 8192 + b' ' + b'x', ('密' * 3000).encode('utf-8')):
                secret.write_bytes(content)
                with self.subTest(size=len(content)), self.assertRaises(ValueError):
                    worker_stack.prepare(root, {**self.values(), 'OPENAI_API_KEY_FILE': str(secret)})

    def test_healthy_services_apply_changed_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            stack = worker_stack.Stack(Path(directory), Path(directory), 'project',
                                       {'PAPERASSIST_WORKER_CONFIG_REVISION': 'new'})
            (stack.directory / 'applied-config-revision').write_text('old')
            before = [{'id': name, 'service': name, 'status': 'running', 'health': 'healthy'}
                      for name in ('worker', 'dispatcher', 'rabbitmq')]
            with patch.object(worker_stack, 'ensure_docker'), patch.object(worker_stack, 'owned_containers', return_value=before), \
                    patch.object(worker_stack, 'compose') as compose:
                worker_stack.start(stack)
            self.assertTrue(any(call.args[1][0] == 'up' for call in compose.call_args_list))
            self.assertEqual((stack.directory / 'applied-config-revision').read_text(), 'new')

    def test_test_stack_does_not_mount_custom_development_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'backend').mkdir()
            (root / 'backend' / '.env').write_text('PAPERASSIST_DATA_DIR=research_data\n')
            test_id = 'b' * 32
            values = {**self.values(), 'PAPERASSIST_ENV': 'test', 'PAPERASSIST_DB_SCHEMA': 'pa_test_' + test_id,
                      'PAPERASSIST_DATA_DIR': str(root / 'temporary')}
            with self.assertRaises(ValueError):
                worker_stack.prepare(root, values, test_id=test_id, assets=root / 'backend' / 'research_data')

    def test_development_cannot_use_owner_or_remote_database(self):
        with tempfile.TemporaryDirectory() as directory:
            for url in ['postgresql://postgres:p@localhost/paperassist_system',
                        'postgresql://paperassist_runtime:p@elsewhere/paperassist_system',
                        'postgresql://paperassist_runtime:p@localhost/paperassist_system_test']:
                with self.subTest(url=url), self.assertRaises(ValueError):
                    worker_stack.prepare(Path(directory), {'PAPERASSIST_DATABASE_URL': url})

    def test_home_relative_assets_match_api_and_are_excluded_from_test_mounts(self):
        from app.core.config import get_data_dir
        # All real filesystem changes stay in this newly created temporary tree.
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory, patch.object(worker_stack, 'protect_directory'):
            root = Path(directory)
            value = '~/' + root.name + '/assets'
            values = {**self.values(), 'PAPERASSIST_DATA_DIR': value}
            with patch('app.core.config.local_config', return_value=values):
                api_assets = get_data_dir()
            stack = worker_stack.prepare(root, values)
            self.assertEqual(Path(stack.environment['PAPERASSIST_STACK_DATA']), api_assets)
            (root / 'backend').mkdir(exist_ok=True)
            (root / 'backend' / '.env').write_text('PAPERASSIST_DATA_DIR=' + value + '\n')
            test_id = 'c' * 32
            with self.assertRaises(ValueError):
                worker_stack.prepare(root, {**values, 'PAPERASSIST_ENV': 'test', 'PAPERASSIST_DB_SCHEMA': 'pa_test_' + test_id},
                                     test_id=test_id, assets=api_assets)

    def test_existing_stack_from_another_project_cannot_be_stopped(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(worker_stack, 'protect_directory'):
            root = Path(directory)
            config = worker_stack.prepare(root, self.values())
            data = json.loads((config.directory / 'stack.json').read_text())
            data['root'] = str(root / 'other')
            (config.directory / 'stack.json').write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                worker_stack.load(root)

    def test_failed_start_keeps_previously_running_container(self):
        stack = worker_stack.Stack(Path('.'), Path('.'), 'project', {})
        before = [{'id': 'existing', 'service': 'rabbitmq', 'status': 'running', 'health': 'healthy'}]
        after = before + [{'id': 'new-worker', 'service': 'worker', 'status': 'running', 'health': 'starting'}]
        def compose(_stack, args, **kwargs):
            if args[0] == 'up':
                raise RuntimeError('test startup failure')
        with patch.object(worker_stack, 'ensure_docker'), patch.object(worker_stack, 'owned_containers', side_effect=[before, after]), \
                patch.object(worker_stack, 'compose', side_effect=compose), patch.object(worker_stack, 'docker') as docker:
            with self.assertRaises(RuntimeError):
                worker_stack.start(stack)
        self.assertEqual(docker.call_count, 1)
        self.assertEqual(docker.call_args.args[0][-1], 'new-worker')


if __name__ == '__main__':
    unittest.main()
