from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.literature.service import digest
from app.domain.manuscripts.service import ManuscriptService
from app.domain.review_rounds.service import ReviewRoundService


class WrittenReviewInput(TestCase):
    def setUp(self):
        self.assets = SimpleNamespace(customer=True, owner_id='owner', db_config=Mock(), directory=Path('.'))
        self.rounds = ReviewRoundService(self.assets)
        self.returned = {'return_id':'return-5'}
        self.base = self.version('v4', 4, None)
        self.parent = self.version('v5', 5, 'v4', user_return_provenance=self.returned)
        self.child = self.version('v6', 6, 'v5', user_return_provenance=self.returned,
                                  writing_provenance={'request_id':'writing-6','base_version_id':'v5'})
        self.db = Mock()
        self.db.execute.side_effect = self.read

    def version(self, identity, revision, parent, **provenance):
        snapshot = dict(project_id='project', **provenance)
        return dict(id=identity, revision=revision, parent_version_id=parent, manuscript_id='manuscript',
                    project_id='project', user_id='owner', snapshot_json=snapshot, snapshot_sha256=digest(snapshot))

    def read(self, sql, args):
        row = None
        if 'FROM review_round_user_returns' in sql and args[-1] == 'v5':
            proof = {'return_file':'visible only to its owner'}
            row = dict(snapshot_json=proof, snapshot_sha256=digest(proof), parent_id='v4', round_id='previous')
        elif 'FROM manuscript_versions' in sql:
            assert args[1:4] == ('manuscript','project','owner')
            row = {'v4':self.base,'v5':self.parent}[args[0]]
            assert row['revision'] < args[4]
        elif 'FROM review_rounds' in sql:
            row = {'snapshot_json':{'review_source':'fixed previous opinion'}}
        return Mock(fetchone=lambda:row)

    def test_validates_written_output_then_follows_the_returned_parent(self):
        with patch.object(ManuscriptService,'validate_version',autospec=True) as validate_writing, \
                patch.object(self.rounds,'validate'), \
                patch('app.domain.review_rounds.service.require_visible_snapshot') as visible:
            self.rounds.visible_manuscript(self.db,self.child)
        assert validate_writing.call_args.args[1:] == (self.db,self.child)
        assert self.parent['snapshot_json'] in [c.args[-1] for c in visible.call_args_list]
        assert {'return_file':'visible only to its owner'} in [c.args[-1] for c in visible.call_args_list]

    def test_rejects_invalid_writing_and_hidden_parent_review_material(self):
        with patch.object(ManuscriptService,'validate_version',side_effect=source_conflict()) as validate_writing:
            with self.assertRaises(StorageError) as failed:
                self.rounds.visible_manuscript(self.db,self.child)
            self.assertEqual(failed.exception.status,409)
            validate_writing.assert_called_once()
        def visible(assets,db,project,snapshot):
            if 'return_file' in snapshot:
                raise StorageError('manuscript_source_not_visible','关联材料不可访问。',404)
        with patch.object(ManuscriptService,'validate_version'), patch('app.domain.review_rounds.service.require_visible_snapshot',side_effect=visible):
            with self.assertRaises(StorageError) as hidden:
                self.rounds.visible_manuscript(self.db,self.child)
            self.assertEqual(hidden.exception.status,404)
