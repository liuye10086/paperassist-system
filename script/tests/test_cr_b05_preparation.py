"""Preparation reuses a verified isolated schema and requires accepted source."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'dev'))


def source(tmp_path, accepted):
    directory = tmp_path / 'script/.runtime/client-requirements-b05-sub2'
    directory.mkdir(parents=True)
    (directory / 'user-acceptance.json').write_text(json.dumps({
        'user_acceptance': accepted, 'scope': 'CR-B05 subpackage 2 only'}))
    (directory / 'state.json').write_text(json.dumps({'schema': 'accepted_source'}))


def test_unaccepted_source_cannot_start_preparation(tmp_path):
    from cr_b05_prepare import prepare
    source(tmp_path, 'pending')
    with pytest.raises(ValueError, match='accepted'):
        prepare(SimpleNamespace(ROOT=tmp_path), 'client-requirements-b05-sub2', 'CR-B05 subpackage 2 only', '0063_qpcr_statistics_bridge')


def test_verified_existing_preparation_returns_without_mutation(tmp_path):
    from cr_b05_prepare import prepare
    source(tmp_path, 'accepted')
    state_file = tmp_path / 'target.json'
    state_file.write_text('existing')
    state = {'preparation_kind': 'fresh_schema', 'source_schema': 'accepted_source', 'clone_status': 'verified'}
    control = SimpleNamespace(ROOT=tmp_path, STATE=state_file, read_state=lambda: state)
    assert prepare(control, 'client-requirements-b05-sub2', 'CR-B05 subpackage 2 only', '0063_qpcr_statistics_bridge') is state
    assert state_file.read_text() == 'existing'
