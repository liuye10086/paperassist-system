"""The customer's project summary names the next page to open, per project type."""

from fastapi.testclient import TestClient

from app.domain.delivery_packages.contracts import SnapshotWrite
from app.main import app
from tests.api.test_analyst_workspace import assign, upload_material
from tests.api.test_customer_material_submissions import code, submit
from tests.api.test_customer_project_types import SCI_SETTINGS, create, project_body, project_path
from tests.api.test_customer_workspace import create_customer_project, freeze_delivery, publish_delivery, sign_in, write_requirements


TARGET = dict.fromkeys(('delivery_id', 'snapshot_id', 'manuscript_id', 'revision', 'round_id', 'item_id',
                        'template_version_id', 'view', 'mode'))


def summary(client, project):
    response = client.get(project + '/customer-workspace/summary')
    assert response.status_code == 200, response.text
    return response.json()


def landing(client, project):
    value = summary(client, project)
    assert set(value) == {'project_id', 'project_type', 'kind', 'actor', 'step', 'target', 'message_key',
                          'message_params', 'updated_at'}
    assert value['project_id'] == project.rsplit('/', 1)[-1] and value['message_key'] == 'summary.' + value['kind']
    assert set(value['target']) == set(TARGET)
    return value['kind'], value['actor'], value['step']


def test_research_summary_follows_rules_in_order():
    with TestClient(app) as customer, TestClient(app) as analyst, TestClient(app) as admin:
        owner_id = sign_in(customer, 'rules-customer@summary.test', 'customer')
        analyst_id = sign_in(analyst, 'rules-analyst@summary.test', 'analyst')
        sign_in(admin, 'rules-admin@summary.test', 'admin')
        project = create_customer_project(customer)
        first = summary(customer, project)
        assert (first['project_type'], first['target'], first['message_params']) == ('research', TARGET, {})
        assert landing(customer, project) == ('upload_needed', 'customer', 'upload')
        write_requirements(customer, project, 1, 'save')
        assert landing(customer, project) == ('upload_needed', 'customer', 'upload')
        file_id, _ = upload_material(customer, project)
        assert landing(customer, project) == ('requirements_needed', 'customer', 'requirements')
        requirement = write_requirements(customer, project, 2, 'confirm')
        assert landing(customer, project) == ('waiting_assignment', 'admin', 'progress')
        revision = assign(admin, project, analyst_id)
        assert landing(customer, project) == ('in_analysis', 'analyst', 'progress')

        progress = {'assignment_revision': revision, 'requirement_version_id': requirement['id'],
                    'status': 'needs_materials', 'note': 'Please attach sample groups.'}
        assert analyst.patch(project + '/analyst-workspace/progress', json=progress).status_code == 200
        needed = summary(customer, project)
        assert landing(customer, project) == ('supplement_needed', 'customer', 'upload')
        assert needed['target'] == {**TARGET, 'mode': 'supplement'}
        assert submit(customer, project, 'summary-submit', requirement['version'], [file_id]).status_code == 201
        submitted = summary(customer, project)
        assert landing(customer, project) == ('supplement_submitted', 'analyst', 'progress')
        assert submitted['message_params'] == {'count': 1} and submitted['target'] == TARGET
        assert analyst.patch(project + '/analyst-workspace/progress',
                             json={**progress, 'status': 'analyzing'}).status_code == 200
        assert landing(customer, project) == ('in_analysis', 'analyst', 'progress')

        service, older, _, _ = freeze_delivery(customer, project, owner_id, requirement['id'])
        newer, status = service.freeze(older['project_id'], older['delivery_id'], SnapshotWrite(
            stage='revision', parent_snapshot_id=older['id'], expected_revision=1, requirement_version_id=requirement['id'],
            change_note='Second fixture note', opinion_round='synthetic', members=[{'kind': 'file', 'file_id': file_id}],
        ), 'freeze-newer')
        assert status == 201
        publish_delivery(older)
        publish_delivery(newer)
        ready = summary(customer, project)
        assert landing(customer, project) == ('delivery_ready', 'none', 'deliveries')
        assert ready['target'] == {**TARGET, 'delivery_id': newer['delivery_id'], 'snapshot_id': newer['id']}
        latest = customer.get(project + '/customer-workspace/deliveries').json()['items'][0]
        assert latest['id'] == newer['id'] and ready['updated_at'] == latest['published_at']

        write_requirements(customer, project, 3, 'confirm')
        assert landing(customer, project) == ('in_analysis', 'analyst', 'progress')
        assign(admin, project, None, revision)
        assert landing(customer, project) == ('waiting_assignment', 'admin', 'progress')


def test_thesis_without_requirements_opens_details_and_new_sci_starts_with_materials():
    with TestClient(app) as customer:
        sign_in(customer, 'paper-customer@summary.test', 'customer')
        sci = project_path(create(customer, 'sci', **project_body('sci', sci_settings=SCI_SETTINGS)))
        thesis = project_path(create(customer, 'thesis', **project_body('thesis')))
        value = summary(customer, thesis)
        assert (value['project_type'], value['target']) == ('thesis', TARGET)
        assert landing(customer, thesis) == ('requirements_needed', 'customer', 'details')
        value = summary(customer, sci)
        assert (value['project_type'], value['target'], value['message_params']) == ('sci', TARGET, {})
        assert landing(customer, sci) == ('materials_needed', 'customer', 'materials')


def test_summary_is_customer_only_and_owner_scoped():
    with TestClient(app) as customer, TestClient(app) as other, TestClient(app) as analyst, TestClient(app) as admin:
        sign_in(customer, 'scope-customer@summary.test', 'customer')
        sign_in(other, 'scope-other@summary.test', 'customer')
        project = create_customer_project(customer)
        foreign = other.get(project + '/customer-workspace/summary')
        assert (foreign.status_code, code(foreign)) == (404, 'project_not_found')
        for client, role in ((analyst, 'analyst'), (admin, 'admin')):
            sign_in(client, f'scope-{role}@summary.test', role)
            own = create_customer_project(client, key=role + '-project')
            denied = client.get(own + '/customer-workspace/summary')
            assert (denied.status_code, code(denied)) == (403, 'permission_denied')


# ---- SCI rules (B03). The rule order is B01 interface design, section 1.4. ----

def manuscript_target(manuscript, revision, view):
    return {**TARGET, 'manuscript_id': manuscript, 'revision': revision, 'view': view}


def set_task(task_id, status, reason=None, error=None):
    from app.db.database import database_connection
    with database_connection(write=True) as db:
        db.execute('UPDATE tasks SET status=%s,reason_code=%s,error_code=%s,revision=revision+1 WHERE id=%s',
                   (status, reason, error, task_id))


def sci_with_material(customer, key):
    from app.adapters.docx_parser import parse_docx
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    from tests.api.test_customer_sci_workflow import sci_project, upload_docx
    project = sci_project(customer, key=key)
    result = 'The synthetic cohort included 4 observations.'
    material = upload_docx(customer, project, key + '.docx', result)
    assert run_parse_file_task(material['task']['id'], material['task']['revision'], parser=parse_docx)['status'] == 'succeeded'
    source = dict(kind='original', id=material['id'], file_id=material['id'], role='user_results')
    return project, material['id'], dict(sources=[source], reported_result=dict(text=result, source_ids=[material['id']]))


def test_sci_settings_missing_opens_details():
    from app.adapters.storage import ProjectStore
    from app.core.config import get_data_dir
    with TestClient(app) as customer:
        owner = sign_in(customer, 'settings-customer@summary.test', 'customer')
        legacy = ProjectStore(get_data_dir(), owner_id=owner).create_project('Legacy SCI', 'Synthetic study', 'sci')
        project = '/api/v1/projects/' + legacy['id']
        assert landing(customer, project) == ('settings_needed', 'customer', 'details')
        assert summary(customer, project)['target'] == TARGET


def test_sci_summary_follows_manuscript_writing_and_word_rules():
    from app.domain.manuscript_writing.execution import run_manuscript_writing_task
    from app.domain.tasks.execution import run_task
    from tests.api.test_customer_sci_workflow import article_request
    from tests.api.test_literature_evidence import post
    from tests.api.test_manuscript_writing_live import LiveFixture, owner_budgets
    from tests.api.test_manuscripts import body
    from tests.integration.test_customer_sci_to_word import SciFixtureProvider
    with TestClient(app) as customer:
        sign_in(customer, 'sci-rules@summary.test', 'customer')
        project, file_id, materials = sci_with_material(customer, 'sci-rules')
        assert landing(customer, project) == ('materials_needed', 'customer', 'materials')

        created = post(customer, project + '/manuscripts', body(**materials), 'summary-fact')
        assert created.status_code == 201, created.text
        manuscript = created.json()['id']
        first = created.json()['versions'][0]
        value = summary(customer, project)
        assert landing(customer, project) == ('writing_needed', 'customer', 'manuscripts')
        assert value['target'] == manuscript_target(manuscript, 1, 'writing') and value['message_params'] == {'revision': 1}
        root = project + '/manuscripts/' + manuscript
        preview = article_request('research', selected_source_ids=[file_id])
        premature = post(customer, root + '/writing-previews', preview, 'before-ready')
        assert premature.status_code == 409, premature.text
        assert run_task(first['task_id'], 1)['status'] == 'succeeded'
        value = summary(customer, project)
        assert landing(customer, project) == ('writing_needed', 'customer', 'manuscripts')
        assert value['target'] == manuscript_target(manuscript, 1, 'writing')

        word = post(customer, root + '/versions/1/exports', {}, 'summary-word-1')
        assert word.status_code == 201, word.text
        assert landing(customer, project) == ('writing_needed', 'customer', 'manuscripts')
        assert run_task(word.json()['task_id'], 1)['status'] == 'succeeded'
        value = summary(customer, project)
        assert landing(customer, project) == ('word_ready', 'none', 'word')
        assert value['target'] == manuscript_target(manuscript, 1, 'exports')

        # D2 overwrite: version 2 replaces the materials, version 1's Word no longer counts.
        second = post(customer, root + '/versions', body(expected_revision=1, **materials), 'summary-overwrite')
        assert second.status_code == 201, second.text
        assert run_task(second.json()['versions'][0]['task_id'], 1)['status'] == 'succeeded'
        value = summary(customer, project)
        assert landing(customer, project) == ('writing_needed', 'customer', 'manuscripts')
        assert value['target'] == manuscript_target(manuscript, 2, 'writing') and value['message_params'] == {'revision': 2}

        bundle = post(customer, root + '/writing-previews', article_request(
            'research', base_revision=2, selected_source_ids=[file_id]), 'summary-preview')
        assert bundle.status_code == 201, bundle.text
        bundle = bundle.json()
        ref = dict(bundle_id=bundle['id'], bundle_sha256=bundle['bundle_sha256'])
        auth = post(customer, project + '/writing-authorizations', dict(schema_version=2, confirmed=True,
            tasks=[dict(logical_task_id=key, bundles=[ref]) for key in ('article', 'candidate', 'new-draft')]), 'summary-auth')
        assert auth.status_code == 201, auth.text
        requested = post(customer, root + '/writing-requests', dict(
            schema_version=2, authorization_id=auth.json()['id'], logical_task_id='article', **ref), 'summary-write')
        assert requested.status_code == 202, requested.text
        task = requested.json()['task']
        writing = manuscript_target(manuscript, 2, 'writing')
        value = summary(customer, project)
        assert landing(customer, project) == ('writing_running', 'none', 'manuscripts')
        assert value['target'] == writing and value['message_params'] == {'revision': 2}

        # Only the automatic task budget exists: user and project budgets are support's to open.
        waited = run_manuscript_writing_task(task['id'], task['revision'], provider=LiveFixture())
        assert waited['status'] == 'waiting_confirmation', waited
        value = summary(customer, project)
        assert landing(customer, project) == ('writing_waiting', 'admin', 'manuscripts')
        assert value['target'] == writing
        assert value['message_params'] == {'revision': 2, 'reason': 'model_budget_missing'}

        set_task(task['id'], 'waiting_confirmation', 'submission_unknown', 'model_submission_unknown')
        assert landing(customer, project) == ('submission_unknown', 'admin', 'manuscripts')
        assert summary(customer, project)['target'] == writing

        set_task(task['id'], 'failed', error='task_execution_failed')
        assert landing(customer, project) == ('writing_needed', 'customer', 'manuscripts')

        def start(logical_task_id):
            response = post(customer, root + '/writing-requests', dict(schema_version=2, authorization_id=auth.json()['id'],
                            logical_task_id=logical_task_id, **ref), logical_task_id)
            assert response.status_code == 202, response.text
            return response.json()['task']

        candidate = start('candidate')
        owner_budgets(customer, candidate, ('user', 'project'))
        sections = bundle['local_manifest']['writing_scope']['target_section_ids']
        provider = SciFixtureProvider({section: dict(text='Synthetic text for review.') for section in sections})
        assert run_manuscript_writing_task(candidate['id'], candidate['revision'], provider=provider)['status'] == 'succeeded'
        assert landing(customer, project) == ('review_needed', 'customer', 'manuscripts')
        assert summary(customer, project)['target'] == writing

        newer = start('new-draft')
        assert landing(customer, project) == ('writing_running', 'none', 'manuscripts')
        failed = run_manuscript_writing_task(newer['id'], newer['revision'], provider=LiveFixture(model='different-model'))
        assert failed['status'] == 'failed'
        assert landing(customer, project) == ('review_needed', 'customer', 'manuscripts')
        assert summary(customer, project)['target'] == writing


def test_material_preparation_and_retry_reopen_the_same_writing_version():
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.domain.tasks.execution import run_task
    from tests.api.test_customer_sci_workflow import sci_project
    from tests.api.test_literature_evidence import post
    from tests.api.test_manuscripts import body

    with TestClient(app) as customer:
        sign_in(customer, 'prepare-version@summary.test', 'customer')
        project = sci_project(customer, key='prepare-version')
        created = post(customer, project + '/manuscripts', body(), 'fact')
        assert created.status_code == 201, created.text
        manuscript = created.json()['id']
        version = created.json()['versions'][0]
        task_url = '/api/v1/tasks/' + version['task_id']

        def check_landing(version_status):
            result = summary(customer, project)
            assert (result['kind'], result['actor'], result['step']) == ('writing_needed', 'customer', 'manuscripts')
            assert result['target'] == manuscript_target(manuscript, 1, 'writing')
            assert result['message_params'] == {'revision': 1}
            current = customer.get(project + '/manuscripts/' + manuscript).json()['versions'][0]
            assert (current['id'], current['status']) == (version['id'], version_status)

        check_landing('pending')
        execution = TaskExecutionStore()
        lease = execution.claim(version['task_id'], 1, task_type='manuscript_draft')
        assert lease
        check_landing('pending')
        assert execution.fail(lease, 'storage_unavailable')['status'] == 'failed'
        check_landing('failed')
        workspace = customer.get(task_url + '/workspace').json()
        assert 'retry' in workspace['allowed_actions']
        task = workspace['task']
        assert task['input_version']['manuscript_version_id'] == version['id']
        resumed = post(customer, task_url + '/resume', dict(operation='retry', wait_id=None,
                       expected_task_revision=task['revision'], input_version=task['input_version']), 'retry-fact')
        assert resumed.status_code == 202, resumed.text
        assert (resumed.json()['id'], resumed.json()['status']) == (version['task_id'], 'queued')
        check_landing('pending')
        assert run_task(version['task_id'], resumed.json()['revision'])['status'] == 'succeeded'
        check_landing('published')


def test_adopted_version_without_word_needs_word(monkeypatch):
    from app.domain import customer_summary_paper
    from app.domain.tasks.execution import run_task
    from tests.api.test_customer_sci_workflow import sci_project
    from tests.api.test_literature_evidence import post
    from tests.api.test_manuscripts import body
    with TestClient(app) as customer:
        sign_in(customer, 'sci-adopted@summary.test', 'customer')
        project = sci_project(customer, key='sci-adopted')
        created = post(customer, project + '/manuscripts', body(), 'adopted-fact').json()
        assert run_task(created['versions'][0]['task_id'], 1)['status'] == 'succeeded'
        monkeypatch.setattr(customer_summary_paper, 'is_adopted', lambda row: True)
        value = summary(customer, project)
        assert landing(customer, project) == ('word_needed', 'customer', 'word')
        assert value['target'] == manuscript_target(created['id'], 1, 'exports')
        assert value['message_params'] == {'revision': 1}


def test_adoption_means_a_version_with_written_or_derived_text():
    from app.domain.customer_summary_paper import is_adopted
    assert not is_adopted(dict(parent_version_id=None, snapshot_json={'title': 'Fact'}))
    written = dict(parent_version_id='base', snapshot_json={'writing_provenance': {'base_version_id': 'base'}})
    assert is_adopted(written)
    assert not is_adopted(dict(written, parent_version_id='other'))
    for key in ('review_provenance', 'review_revision_provenance', 'user_return_provenance',
                'journal_adaptation_provenance', 'school_change_provenance'):
        assert is_adopted(dict(parent_version_id='base', snapshot_json={key: {'any': 'value'}}))


def test_word_ready_uses_successful_non_blind_exports():
    from app.domain.customer_summary_paper import word_ready

    blind = dict(id='archived', status='succeeded', presentation={'binding': {'review_mode': 'blind'}})
    signed = dict(id='signed', status='succeeded', presentation={'binding': {'review_mode': 'identified'}})
    plain = dict(id='plain', status='succeeded')
    assert word_ready([blind, signed | {'status': 'failed'}]) is None
    assert word_ready([blind, signed, plain]) == signed
    assert word_ready([blind, plain, signed]) == plain


def test_open_review_round_comes_first_until_it_continues(monkeypatch):
    from app.domain.review_rounds.service import ReviewRoundService
    from app.domain.tasks.execution import run_task
    from tests.api.test_customer_sci_workflow import sci_project
    from tests.api.test_literature_evidence import post
    from tests.api.test_manuscripts import body
    with TestClient(app) as customer:
        sign_in(customer, 'sci-review@summary.test', 'customer')
        project = sci_project(customer, key='sci-review')
        created = post(customer, project + '/manuscripts', body(), 'review-fact').json()
        version = created['versions'][0]
        assert run_task(version['task_id'], 1)['status'] == 'succeeded'
        started = post(customer, project + '/reviews/rounds', dict(
            title='Synthetic review', project_type='sci', synthetic=False, materials=[],
            manuscript=dict(id=created['id'], revision=1, version_id=version['id']),
            sources=[dict(role='reviewer', label='Reviewer 1', format='text',
                          text='1. Clarify the method.\n2. Add experiment to confirm conclusion.')]), 'review-round')
        assert started.status_code == 202, started.text
        run_task(started.json()['task']['id'], 1)
        saved = customer.get(project + '/reviews/rounds/' + started.json()['id']).json()
        open_items = [item for item in saved['items'] if item['status'] in ('pending', 'waiting_confirmation', 'waiting_material')]
        assert open_items
        value = summary(customer, project)
        assert landing(customer, project) == ('review_open', 'customer', 'reviews')
        assert value['target'] == {**TARGET, 'round_id': saved['id'], 'item_id': open_items[0]['id']}
        assert value['message_params'] == {'round': saved['round_number'], 'count': len(open_items)}

        view = ReviewRoundService.view
        monkeypatch.setattr(ReviewRoundService, 'view', lambda self, db, row: view(self, db, row) | {'next_round_ids': ['later']})
        assert landing(customer, project) == ('writing_needed', 'customer', 'manuscripts')


# ---- Thesis rules (B04). B01 interface design, section 1.5. ----

THESIS_BASICS = dict(education_level='硕士', school='Synthetic university', title='Synthetic thesis',
                     keywords=['cohort', 'sampling', 'observations', 'comparison'])


def thesis_requirements(customer, project, basics=None):
    revision = customer.get(project + '/thesis-requirements').json()['revision']
    saved = customer.put(project + '/thesis-requirements', json=dict(
        expected_revision=revision, expected_language='zh-CN', language='zh-CN', basics=basics or THESIS_BASICS))
    assert saved.status_code == 200, saved.text
    return saved.json()


def parsed_template(customer, project, name, parser=None):
    from app.domain.school_templates.execution import run_school_template_task
    from tests.api.test_customer_thesis_permissions import template
    from tests.api.test_school_templates import analysis
    item, file_id, _ = template(customer, project, name)
    assert run_school_template_task(item['task']['id'], 1, parser=parser or analysis)['status'] == 'succeeded'
    return item, file_id


def bound_thesis(customer, key):
    from tests.api.test_customer_thesis_permissions import bind, confirm_template
    project = project_path(create(customer, key, **project_body('thesis')))
    thesis_requirements(customer, project)
    item, file_id = parsed_template(customer, project, key + '-template')
    confirmation, _, _ = confirm_template(customer, project, item, key + '-rules')
    profile = bind(customer, project, confirmation, customer.get(project + '/thesis-profile').json()['revision'])
    return project, confirmation, profile, file_id


def test_thesis_requirements_then_template_rules_come_first():
    from app.domain.school_templates.execution import run_school_template_task
    from tests.api.test_customer_thesis_permissions import hide, template
    from tests.api.test_school_templates import analysis
    with TestClient(app) as customer, TestClient(app) as other:
        sign_in(customer, 'thesis-rules@summary.test', 'customer')
        actor = sign_in(other, 'thesis-rules-other@summary.test', 'customer')
        project = project_path(create(customer, 'thesis-rules', **project_body('thesis')))
        assert landing(customer, project) == ('requirements_needed', 'customer', 'details')
        assert summary(customer, project)['target'] == TARGET
        thesis_requirements(customer, project)
        assert landing(customer, project) == ('template_needed', 'customer', 'school')
        assert summary(customer, project)['target'] == TARGET

        pending, _, _ = template(customer, project, 'thesis-pending')
        assert landing(customer, project) == ('template_needed', 'customer', 'school')
        assert run_school_template_task(pending['task']['id'], 1, parser=analysis)['status'] == 'succeeded'
        value = summary(customer, project)
        assert landing(customer, project) == ('template_conflicts', 'customer', 'school')
        assert value['target'] == {**TARGET, 'template_version_id': pending['id'], 'view': 'confirm'}
        assert value['message_params'] == {'count': 1}

        def two_conflicts(*args):
            # 12 pt disagrees with the fixture note's 四号, so the parse adds a second conflict.
            result = analysis(*args)
            result['rules'].append(dict(id='body.font_size_pt', category='body', label='字号', value=12,
                                        source=result['rules'][0]['source']))
            return result
        newer, newer_file = parsed_template(customer, project, 'thesis-newer', parser=two_conflicts)
        value = summary(customer, project)
        assert value['target']['template_version_id'] == newer['id'] and value['message_params'] == {'count': 2}

        hide(newer_file, actor)   # the newest version's source is no longer current or visible
        assert landing(customer, project) == ('template_needed', 'customer', 'school')


def test_template_summary_counts_text_decisions_with_and_without_rule_conflicts():
    from tests.api.test_school_template_updates import text_analysis
    from tests.api.test_school_templates import analysis

    def mixed_rules(*args):
        result = text_analysis(*args)
        result['notes'].extend(analysis()['notes'])
        return result

    with TestClient(app) as customer:
        sign_in(customer, 'thesis-text-rules@summary.test', 'customer')
        project = project_path(create(customer, 'thesis-text-rules', **project_body('thesis')))
        thesis_requirements(customer, project)
        for parser, key, count in ((text_analysis, 'text-only', 2), (mixed_rules, 'mixed-rules', 3)):
            item, _ = parsed_template(customer, project, key, parser=parser)
            value = summary(customer, project)
            assert value['kind'] == 'template_conflicts'
            assert value['target'] == {**TARGET, 'template_version_id': item['id'], 'view': 'confirm'}
            assert value['message_params'] == {'count': count}


def test_bound_thesis_follows_sci_manuscript_rules(monkeypatch):
    from app.domain import customer_summary_paper
    from app.domain.tasks.execution import run_task
    from tests.api.test_literature_evidence import post
    with TestClient(app) as customer:
        sign_in(customer, 'thesis-bound@summary.test', 'customer')
        project, confirmation, profile, _ = bound_thesis(customer, 'thesis-bound')
        assert landing(customer, project) == ('materials_needed', 'customer', 'materials')
        # A newer, unconfirmed template after binding is D6 territory and does not take over.
        parsed_template(customer, project, 'thesis-bound-newer')
        assert landing(customer, project) == ('materials_needed', 'customer', 'materials')

        request = dict(title='Synthetic thesis', output_language='zh-CN', sources=[], thesis=dict(
            confirmation_id=confirmation['id'], profile_revision=profile['revision'], chapter_mappings=[dict(
                chapter_id='results', purpose='results', output_language='project', result_group_ids=[])]))
        created = post(customer, project + '/manuscripts', request, 'thesis-fact')
        assert created.status_code == 201, created.text
        manuscript = created.json()['id']
        value = summary(customer, project)
        assert landing(customer, project) == ('writing_needed', 'customer', 'manuscripts')
        assert value['target'] == manuscript_target(manuscript, 1, 'writing')
        assert run_task(created.json()['versions'][0]['task_id'], 1)['status'] == 'succeeded'
        assert landing(customer, project) == ('writing_needed', 'customer', 'manuscripts')
        assert summary(customer, project)['target'] == manuscript_target(manuscript, 1, 'writing')

        writing = dict(task_id='synthetic', has_candidate=False, published_revision=None, status='running',
                       reason_code=None, error_code=None, updated_at=None)
        monkeypatch.setattr(customer_summary_paper, 'latest_writing_task', lambda db, version: writing)
        assert landing(customer, project) == ('writing_running', 'none', 'manuscripts')
        writing.update(status='succeeded', has_candidate=True)
        assert landing(customer, project) == ('review_needed', 'customer', 'manuscripts')
        monkeypatch.setattr(customer_summary_paper, 'latest_writing_task', lambda db, version: None)
        monkeypatch.setattr(customer_summary_paper, 'is_adopted', lambda row: True)
        assert landing(customer, project) == ('word_needed', 'customer', 'word')
        monkeypatch.setattr(customer_summary_paper, 'word_ready', lambda exports: dict(created_at=None))
        value = summary(customer, project)
        assert landing(customer, project) == ('word_ready', 'none', 'word')
        assert value['target'] == manuscript_target(manuscript, 1, 'exports')


def test_thesis_summary_is_owner_scoped():
    with TestClient(app) as customer, TestClient(app) as other:
        sign_in(customer, 'thesis-scope@summary.test', 'customer')
        sign_in(other, 'thesis-scope-other@summary.test', 'customer')
        project = project_path(create(customer, 'thesis-scope', **project_body('thesis')))
        foreign = other.get(project + '/customer-workspace/summary')
        assert (foreign.status_code, code(foreign)) == (404, 'project_not_found')
