"""Offline adapter checks; the SQL boundary is mocked, no database is started."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.adapters.research_intake_store import require_owner, version_view
from app.core.exceptions import StorageError
from app.domain.research_intake.contracts import RequirementContent


@pytest.fixture
def postgres_schema():
    yield None


def row():
    return {'id':'requirement-v1','project_id':'project1','operation':'save',
            'content_json':RequirementContent.model_validate({'schema_version':1}).model_dump(mode='json'),
            'content_sha256':'fixed-content-hash','request_digest':'private'}


def ref(version):
    return dict(delivery_id=None,file_id=None,bio_dataset_version_id=version,
                locator={},availability='available',purpose='analysis',note='')


def test_material_sources_join_uses_exact_linked_versions_and_project_not_current():
    original=row()
    before=deepcopy(original)
    refs=[ref('historical-v1'),ref('missing'),ref('other-project')]
    source={'bio_dataset_version_id':'historical-v1','dataset_id':'dataset1','dataset_name':'RNA data','version':1}
    db=Mock()
    db.execute.side_effect=[refs,[source]]
    value=version_view(db,original,'requirements')
    assert value['material_sources']==[source]
    assert value['material_refs']==refs
    assert original==before
    assert value['content_sha256']=='fixed-content-hash'
    assert 'request_digest' not in value
    assert db.execute.call_count==2
    sql,params=db.execute.call_args_list[1].args
    normalized=' '.join(sql.lower().split())
    assert 'join bio_dataset_versions v on v.id=r.bio_dataset_version_id' in normalized
    assert 'join bio_datasets d on d.id=v.dataset_id' in normalized
    assert 'r.requirement_version_id=%s' in normalized
    assert 'v.project_id=%s' in normalized
    assert 'd.project_id=v.project_id' in normalized
    assert params==('requirement-v1','project1')
    assert 'current_version_id' not in normalized
    assert all(item['bio_dataset_version_id'] not in ('missing','other-project') for item in value['material_sources'])


@pytest.mark.parametrize('refs',[[],[ref(None)]])
def test_no_bio_refs_returns_empty_sources_without_metadata_query(refs):
    db=Mock();db.execute.return_value=refs
    assert version_view(db,row(),'requirements')['material_sources']==[]
    assert db.execute.call_count==1


def test_unresolvable_refs_have_no_metadata():
    db=Mock();db.execute.side_effect=[[ref('deleted'),ref('other-project')],[]]
    assert version_view(db,row(),'requirements')['material_sources']==[]


def test_owner_boundary_still_rejects_other_owner():
    db=Mock();db.execute.return_value.fetchone.return_value=None
    with pytest.raises(StorageError):
        require_owner(db,SimpleNamespace(owner_id='owner1'),'project1')
    assert db.execute.call_args.args[1]==('project1','owner1')
