"""Retired presentation options stay invalid when a manuscript already has saved settings."""
from unittest import TestCase
from unittest.mock import MagicMock

from app.core.exceptions import StorageError
from app.domain.literature.service import digest
from app.domain.manuscripts.presentation import PresentationService
from app.domain.manuscripts.presentation_contracts import PresentationRequest


class BlindPresentationWriteTest(TestCase):
    def test_removed_option_is_identified_even_with_a_stale_configuration_revision(self):
        service = PresentationService(MagicMock())
        db = service.store.connection.return_value.__enter__.return_value
        # A permitted manuscript with four saved configuration versions and a new request key.
        options = [
            {'blind': {'manual_image_review': True}},
            {'language_review': {
                'source_export_id': 'source1', 'source_sha256': 'a' * 64,
                'language_view': 'zh-CN', 'review_mode': 'blind',
                'decisions': [{'location': 'paragraph:0', 'content_sha256': 'b' * 64,
                               'decision': 'target_language', 'reason': '合成核对'}],
            }},
        ]
        for config in options:
            with self.subTest(config=next(iter(config))):
                db.execute.return_value.fetchone.side_effect = [None, None, {'revision': 4}]
                request = PresentationRequest(base_version_id='base1', config=config)
                with self.assertRaises(StorageError) as raised:
                    service.save('project1', 'manuscript1', request, 'new-key')
                self.assertEqual((raised.exception.status, raised.exception.code),
                                 (422, 'blind_review_removed'))

    def test_stale_identified_settings_still_report_a_version_conflict(self):
        service = PresentationService(MagicMock())
        db = service.store.connection.return_value.__enter__.return_value
        db.execute.return_value.fetchone.side_effect = [None, None, {'revision': 4}]
        request = PresentationRequest(base_version_id='base1')
        with self.assertRaises(StorageError) as raised:
            service.save('project1', 'manuscript1', request, 'new-key')
        self.assertEqual((raised.exception.status, raised.exception.code),
                         (409, 'manuscript_revision_conflict'))

    def test_valid_saved_configuration_still_replays(self):
        service = PresentationService(MagicMock())
        request = PresentationRequest(base_version_id='base1')
        payload = request.model_dump()
        payload['config'].pop('blind', None)
        payload['config'].pop('language_review', None)
        db = service.store.connection.return_value.__enter__.return_value
        db.execute.return_value.fetchone.side_effect = [None, {'id': 'saved', 'request_digest': digest(payload)}]
        service.fixed = MagicMock(return_value=('saved-row', 'base', None))
        service._view = MagicMock(return_value={'id': 'saved'})
        self.assertEqual(service.save('project1', 'manuscript1', request, 'original-key'),
                         ({'id': 'saved'}, 200))
