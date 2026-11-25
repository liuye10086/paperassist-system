from fastapi.testclient import TestClient

from app.adapters.research_figure_render import render_figure
from app.domain.research_results.execution import run_research_figure_task
from app.domain.school_templates.execution import run_school_template_task
from app.main import app
from tests.api.test_customer_sci_workflow import sci_project
from tests.api.test_customer_thesis_permissions import bind, template, thesis_project
from tests.api.test_customer_workspace import sign_in
from tests.api.test_school_templates import analysis, post
from tests.api.test_sci_resources import upload_png


def test_thesis_figure_resources_require_an_owned_thesis_project_and_bound_template():
    with TestClient(app) as customer, TestClient(app) as other, TestClient(app) as analyst:
        sign_in(customer, 'thesis-resources-owner@example.test', 'customer')
        sign_in(other, 'thesis-resources-other@example.test', 'customer')
        sign_in(analyst, 'thesis-resources-analyst@example.test', 'analyst')
        thesis = thesis_project(customer) + '/thesis-figure-resources'
        response = customer.get(thesis)
        assert response.status_code == 200, response.text
        assert response.json() == dict(revision=0, template_id=None, chapters=[], figures=[], placements=[])
        write = dict(expected_revision=0, placements=[])
        unbound = customer.put(thesis, json=write)
        assert unbound.status_code == 409, unbound.text
        assert unbound.json()['detail']['code'] == 'thesis_template_required'
        assert other.get(thesis).status_code == other.put(thesis, json=write).status_code == 404
        assert analyst.get(thesis).status_code == analyst.put(thesis, json=write).status_code == 403
        sci = sci_project(customer) + '/thesis-figure-resources'
        assert customer.get(sci).status_code == customer.put(sci, json=write).status_code == 403


def test_thesis_figure_placement_retries_and_template_rebinding(tmp_path):
    with TestClient(app) as customer:
        sign_in(customer, 'thesis-resources-rebinding@example.test', 'customer')
        project = thesis_project(customer)
        resource = project + '/thesis-figure-resources'
        file_id = upload_png(customer, project, 'panel.png', finish_parse=True)
        response = post(customer, project + '/thesis-figures', dict(title='Synthetic figure', file_ids=[file_id],
                                                                   columns=1), 'figure')
        assert response.status_code == 201, response.text
        figure = response.json()
        task = figure['task']
        result = run_research_figure_task(task['id'], task['revision'], engine=render_figure,
                                          staging_directory=tmp_path / 'staging')
        assert result['status'] == 'succeeded', result

        # Reuse the same actual chapter ID in two independently confirmed outlines.
        chapters = [dict(id='results-' + 'a' * 182, title='Results', level=1),
                    dict(id='references', title='References', level=1)]

        def confirm(name):
            version, _, _ = template(customer, project, name)
            task = run_school_template_task(version['task']['id'], 1, parser=analysis)
            assert task['status'] == 'succeeded', task
            url = f"{project}/school-templates/{version['id']}"
            listed = customer.get(project + '/school-templates')
            assert listed.status_code == 200, listed.text
            parsed = next(item for item in listed.json()['items'] if item['id'] == version['id'])
            response = post(customer, url + '/confirm', dict(analysis_sha256=parsed['analysis_sha256'],
                            decisions=[dict(conflict_id='conflict-1', option_id='text-2')], chapters=chapters), name)
            assert response.status_code == 201, response.text
            return response.json()

        original = confirm('original')
        profile = bind(customer, project, original, 0)
        state = customer.get(resource).json()
        assert state['template_id'] == original['id']
        assert [row['label'] for row in state['chapters']] == ['Results']
        assert [row['id'] for row in state['figures']] == [figure['id']]
        preview = customer.get(state['figures'][0]['preview_url'])
        assert preview.status_code == 200 and preview.headers['content-type'] == 'image/png', preview.status_code
        target = state['chapters'][0]['id']
        assert len(target) > 200
        placement = dict(figure_id=figure['id'], chapter_id=target, caption='Synthetic caption.')
        write = dict(expected_revision=profile['revision'], placements=[placement])
        saved = customer.put(resource, json=write)
        assert saved.status_code == 200, saved.text
        retry = customer.put(resource, json=write)
        assert retry.status_code == 200 and retry.json() == saved.json(), retry.text

        revision = saved.json()['revision']
        updated = customer.put(project + '/thesis-requirements', json=dict(
            expected_revision=revision, expected_language='zh-CN', language='zh-CN',
            basics=dict(title='Updated title', keywords=['cohort', 'comparison', 'expression', 'analysis'],
                        school='Synthetic university', education_level='硕士')))
        assert updated.status_code == 200, updated.text
        assert customer.get(resource).json()['placements'] == [placement]
        assert customer.put(resource, json=dict(write, expected_revision=revision)).status_code == 409

        replacement = confirm('replacement')
        profile = bind(customer, project, replacement, updated.json()['revision'])
        state = customer.get(resource).json()
        assert state['template_id'] == replacement['id']
        assert state['chapters'][0]['id'] != target
        assert state['placements'] == [placement]
        candidate_plan = customer.get(project + '/manuscripts/candidates').json()['paper_plan']
        assert candidate_plan['thesis_figures_need_configuration'] and candidate_plan['thesis_figures'] == []
        stale = customer.put(resource, json=dict(write, expected_revision=profile['revision']))
        assert stale.status_code == 422, stale.text
        assert stale.json()['detail']['code'] == 'thesis_figure_resources_invalid'
        cleared = customer.put(resource, json=dict(expected_revision=profile['revision'], placements=[]))
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()['placements'] == []
