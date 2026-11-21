"""An idle dispatcher still checks late model receipts without scanning storage."""
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch

from app.adapters.task_execution_store import TaskExecutionStore
from app.domain.storage_governance import service as storage


class LeaseRecoveryStorageTests(TestCase):
    def setUp(self):
        self.store = Mock(spec=TaskExecutionStore)
        self.store.assets = Mock(directory=Path('test-storage'))
        self.db = MagicMock()
        transaction = MagicMock()
        transaction.__enter__.return_value = self.db
        self.store.connection.return_value = transaction
        self.leases = []
        self.steps = []

        def query(sql, args):
            result = Mock()
            if 'JOIN task_attempts' in sql:
                self.steps.append('read expired leases')
                result.fetchall.return_value = self.leases
            elif 'FROM storage_reservations' in sql:
                self.steps.append('check task reservation')
                result.fetchone.return_value = {'present': 1}
            else:
                self.fail(f'unexpected recovery query: {sql}')
            return result

        self.db.execute.side_effect = query
        self.scan = self.enterContext(patch.object(storage, 'reconcile_intents',
            side_effect=lambda *_: self.steps.append('reconcile storage')))
        self.store._recover_boxplot_receipts.return_value = 0
        self.store._recover_recommendation_receipts.return_value = 0

    def test_no_expired_leases_still_processes_late_receipts_without_scanning_storage(self):
        self.store._recover_boxplot_receipts.return_value = 1
        self.store._recover_recommendation_receipts.return_value = 2
        self.assertEqual(TaskExecutionStore.recover_expired(self.store, 5), 3)
        self.store._recover_boxplot_receipts.assert_called_once_with(self.db, 5)
        self.store._recover_recommendation_receipts.assert_called_once_with(self.db, 5)
        self.scan.assert_not_called()

    def test_expired_leases_share_one_scan_before_using_their_reservations(self):
        self.leases = [{'id': str(i), 'task_type': 'literature_search'} for i in (1, 2)]
        self.assertEqual(TaskExecutionStore.recover_expired(self.store), 2)
        self.assertEqual(self.steps, ['read expired leases', 'reconcile storage',
                                      'check task reservation', 'check task reservation'])
        self.scan.assert_called_once_with(self.db, self.store.assets.directory)
        self.store.connection.assert_called_once_with(write=True)
        self.assertEqual(self.store._finish.call_count, 2)
