"""Exercise manifest admission with a fresh directory and an empty ledger stub."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from app.core.exceptions import StorageError
from app.domain.storage_governance import deterministic, service


class ManifestAdmissionTests(TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.db = MagicMock()
        self.db.config.schema = 'test'
        self.db.config.url.database = 'test'
        self.db.execute.return_value.fetchone.return_value = None
        self.db.execute.return_value.fetchall.return_value = []
        self.task = dict(id='task', revision=1, project_id='project', user_id='owner')
        self.entries = [
            ('document', name, dict(object_key=name, size_bytes=1, sha256='a' * 64))
            for name in ('text.json', 'one.png', 'two.png')
        ]
        self.enterContext(patch.object(service, '_project', return_value=dict(id='project', owner_id='owner')))
        self.disk = self.enterContext(patch.object(service, '_disk_guard'))
        self.scan = self.enterContext(patch.object(service, 'reconcile_intents', wraps=service.reconcile_intents))

    def test_batch_scans_once_and_reserves_every_member(self):
        rows = deterministic.admit_manifest(self.db, self.root, self.task, self.entries)
        self.scan.assert_called_once_with(self.db, self.root)
        self.assertEqual([row['object_key'] for row in rows], ['text.json', 'one.png', 'two.png'])
        self.assertEqual([call.kwargs.get('key') for call in self.disk.call_args_list],
                         [None, 'text.json', 'one.png', 'two.png'])
        self.assertEqual(len(list((self.root / '.storage-intents').glob('*.json'))), 3)

    def test_late_invalid_member_prevents_all_journals(self):
        self.entries[-1][2]['size_bytes'] = -1
        with self.assertRaises(StorageError):
            deterministic.admit_manifest(self.db, self.root, self.task, self.entries)
        self.assertFalse((self.root / '.storage-intents').exists())

    def test_unresolved_journal_blocks_independent_reservation_and_batch(self):
        self.scan.return_value = 1
        with self.assertRaises(StorageError):
            service.reserve(self.db, self.root, 'project', 'one', self.root / 'one.png', 1)
        with self.assertRaises(StorageError):
            deterministic.admit_manifest(self.db, self.root, self.task, self.entries)
        self.assertEqual(self.scan.call_count, 2)
        self.db.execute.assert_not_called()
        self.disk.assert_not_called()
