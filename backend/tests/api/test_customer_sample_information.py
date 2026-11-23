"""Customer sample declarations and the assigned analyst's design share a submitted version."""
from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.api.test_customer_workspace import create_customer_project, sign_in
from tests.api.test_excel import workbook_bytes
from tests.api.test_project_assignments import assign


@pytest.fixture
def assignment():
    customer, analyst, admin = [TestClient(app) for _ in range(3)]
    sign_in(customer, 'sample-customer@example.test', 'customer')
    analyst_id = sign_in(analyst, 'sample-analyst@example.test', 'analyst')
    sign_in(admin, 'sample-admin@example.test', 'admin')
    project = create_customer_project(customer)
    assert assign(admin, project, analyst_id, 0).status_code == 200
    return customer, analyst, project


def write(client, project, kind, body, key):
    return client.post(project + '/' + kind, json=body, headers={'Idempotency-Key': key})


def test_customer_maps_only_visible_files_and_submits_scoped_sample_references(assignment):
    customer, analyst, project = assignment
    book = workbook_bytes()
    visible, private = [client.post(project + '/files', files={'file': (name, book)}).json()['file']['id']
                        for client, name in ((customer, 'sample.xlsx'), (analyst, 'internal.xlsx'))]
    mapping = {'sheet': '研究数据', 'mapping': {'id': '编号', 'group_id': '值'},
               'experiment_id': 'e', 'group_ids': ['0']}
    preview = customer.post(project + '/design-table-previews', json={**mapping, 'file_id': visible})
    assert preview.status_code == 200, preview.text
    [sample] = preview.json()['samples']
    assert sample['file_id'] == visible
    hidden = customer.post(project + '/design-table-previews', json={**mapping, 'file_id': private})
    assert hidden.status_code == 422 and hidden.json()['detail']['code'] == 'research_material_invalid'
    groups = [{'id': '0', 'experiment_id': 'e', 'name': 'Control'}]
    body = {'operation': 'confirm', 'expected_revision': 1, 'content': {'schema_version': 1,
            'services': ['analysis'], 'study_species': ['人类', '小鼠'], 'sample_information': {'groups': groups, 'samples': [sample]}}}
    assert write(customer, project, 'requirements', body, 'missing-ref').status_code == 422
    body['material_refs'] = [{'availability': 'provided', 'purpose': 'sample_sheet', 'file_id': visible}]
    for change in ('private', 'group', 'duplicate'):
        invalid = deepcopy(body)
        data = invalid['content']['sample_information']
        if change == 'private':
            data['samples'][0]['file_id'] = invalid['material_refs'][0]['file_id'] = private
        elif change == 'group':
            data['samples'][0]['experiment_id'] = 'other-experiment'
        else:
            data['groups'].append(data['groups'][0])
        assert write(customer, project, 'requirements', invalid, change).status_code == 422
    confirmed = write(customer, project, 'requirements', body, 'confirmed')
    assert confirmed.status_code == 201, confirmed.text
    intake = analyst.get(project + '/research-intake').json()
    assert intake['current_requirement']['id'] == confirmed.json()['version']['id']
    assert intake['current_requirement']['content']['sample_information']['samples'] == [sample]
    assert intake['current_requirement']['content']['study_species'] == ['人类', '小鼠']
    assert customer.get(project + '/research-intake').json()['current_design'] is None
    assert customer.get(project + '/research-designs').status_code == 403


def test_analyst_can_change_design_but_only_copy_submitted_sample_information(assignment):
    customer, analyst, project = assignment
    info = {'groups': [{'id': 'g', 'experiment_id': 'e', 'name': 'Control'}],
            'samples': [{'id': 's', 'experiment_id': 'e', 'group_id': 'g'}]}
    design = {'expected_revision': 1, 'operation': 'save', 'content': {'schema_version': 1,
              'experiments': [{'id': 'e', 'data_type': 'Table'}], **info}}
    denied = write(analyst, project, 'research-designs', design, 'forbidden')
    assert denied.status_code == 403, denied.text
    assert denied.json()['detail']['code'] == 'customer_sample_information_read_only'
    requirement = {'expected_revision': 1, 'operation': 'save', 'content': {'schema_version': 1,
                   'services': ['analysis'], 'sample_information': info}}
    draft = write(customer, project, 'requirements', requirement, 'draft')
    assert draft.status_code == 201
    design['expected_revision'] = 2
    assert write(analyst, project, 'research-designs', design, 'draft-is-private').status_code == 403
    assert analyst.get(project + '/research-intake').json()['current_requirement'] is None
    requirement.update(expected_revision=2, operation='confirm')
    assert write(customer, project, 'requirements', requirement, 'submitted').status_code == 201
    design['expected_revision'] = 3
    design['content']['observation'] = {'structure': 'paired'}
    adopted = write(analyst, project, 'research-designs', design, 'use-submission')
    assert adopted.status_code == 201, adopted.text
    requirement = deepcopy(requirement)
    requirement['expected_revision'] = 4
    requirement['content']['sample_information']['groups'][0]['name'] = 'New control'
    assert write(customer, project, 'requirements', requirement, 'corrected').status_code == 201
    assert write(analyst, project, 'research-designs', design, 'use-submission').json() == adopted.json()
    design['expected_revision'] = 5
    denied = write(analyst, project, 'research-designs', design, 'old-samples')
    assert denied.status_code == 403 and denied.json()['detail']['code'] == 'customer_sample_information_read_only'
    assert customer.get(project + '/research-intake').json()['current_design'] is None


def test_legacy_design_samples_are_preserved_without_disclosing_internal_design(assignment):
    from app.adapters.storage import ProjectStore
    from app.core.config import get_data_dir
    from app.domain.research_intake.contracts import DesignWrite
    from app.domain.research_intake.service import write_version

    customer, analyst, project = assignment
    owner_id = customer.get('/api/v1/auth/me').json()['user']['id']
    design = {'expected_revision': 1, 'operation': 'save', 'content': {'schema_version': 1,
              'experiments': [{'id': 'e', 'data_type': 'Table'}],
              'groups': [{'id': 'g', 'name': 'Legacy group', 'experiment_id': 'e'}],
              'samples': [{'id': 'existing-private-id', 'experiment_id': 'e', 'group_id': 'g'}]}}
    write_version(ProjectStore(get_data_dir(), owner_id=owner_id), project.rsplit('/', 1)[-1], 'research-designs',
                  DesignWrite.model_validate(design), 'legacy')
    legacy_body = {'expected_revision': 2, 'operation': 'confirm', 'content': {
        'schema_version': 1, 'services': ['analysis']}}
    submitted = write(customer, project, 'requirements', legacy_body, 'legacy-format')
    assert submitted.status_code == 201, submitted.text
    assert 'sample_information' not in submitted.json()['version']['content']
    assert submitted.json()['version']['sha256'] == 'eab6d9abe8ec3232ee02a46071b695cad1145ea4e830e889e8dcc0eb28989484'
    from app.db.database import database_connection
    with database_connection() as db:
        receipt = db.execute('SELECT request_digest FROM research_requirement_versions WHERE id=%s',
                             (submitted.json()['version']['id'],)).fetchone()
        assert receipt['request_digest'] == 'ece50ebbb85d216973a0b5f4ef3f829d30a08f8708a7ac2d0dea5381e11c0b08'
    assert 'existing-private-id' not in customer.get(project + '/research-intake').text
    design['expected_revision'] = 3
    design['content']['observation'] = {'structure': 'independent'}
    assert write(analyst, project, 'research-designs', design, 'preserve-existing').status_code == 201
    design['expected_revision'] = 4
    design['content']['samples'] = []
    rejected = write(analyst, project, 'research-designs', design, 'delete-existing')
    assert rejected.status_code == 403 and rejected.json()['detail']['code'] == 'customer_sample_information_read_only'


def test_sample_dataset_references_require_customer_visible_source_files(assignment):
    from tests.helpers.bio_fixtures import visium_bundle_bytes
    from tests.integration.test_bio_import_publication import confirm, read, run

    customer, analyst, project = assignment
    archive = visium_bundle_bytes()
    for uploader, expected in ((analyst, 422), (customer, 201)):
        key = str(uuid4())
        filename = 'GSE9999999_RAW.tar'
        batch = uploader.post(project + '/bio-upload-batches', headers={'Idempotency-Key': key}, json={
            'items': [{'client_id': key, 'filename': filename, 'size_bytes': len(archive)}]})
        assert batch.status_code == 201, batch.text
        file = uploader.post(project + f"/bio-upload-batches/{batch.json()['id']}/items/{key}",
                             files={'file': (filename, archive)})
        assert file.status_code == 202, file.text
        created = analyst.post(project + '/bio-imports', headers={'Idempotency-Key': key}, json={
            'file_ids': [file.json()['file_id']], 'assay': 'visium', 'name': 'Imported table', 'expected_dataset_revision': 0})
        assert created.status_code == 202, created.text
        imported = created.json()
        assert run(imported['task'])['status'] == 'waiting_confirmation'
        accepted = confirm(analyst, project, imported, read(analyst, project, imported))
        assert run(accepted.json())['status'] == 'succeeded'
        dataset_id = read(analyst, project, imported)['result_source']['dataset_version_id']
        declaration = {'groups': [{'id': 'g', 'experiment_id': 'e', 'name': 'Group'}],
                       'samples': [{'id': 's', 'experiment_id': 'e', 'group_id': 'g', 'bio_dataset_version_id': dataset_id}]}
        body = {'expected_revision': 1, 'operation': 'save', 'content': {
            'schema_version': 1, 'services': ['analysis'], 'sample_information': declaration},
            'material_refs': [{'availability': 'provided', 'purpose': 'raw_data', 'bio_dataset_version_id': dataset_id}]}
        saved = write(customer, project, 'requirements', body, key)
        assert saved.status_code == expected, saved.text
        if expected == 422:
            assert saved.json()['detail']['code'] == 'research_material_invalid'
