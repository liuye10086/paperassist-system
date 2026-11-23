import json
import pytest

from fastapi.testclient import TestClient

from app.adapters.docx_parser import parse_docx
from app.adapters.ncbi import parse_fetch
from app.domain.literature.execution import run_literature_task
from app.domain.tasks.execution import run_task
from app.domain.tasks.file_parse_execution import run_parse_file_task
from app.main import app
from tests.api.test_customer_project_types import SCI_SETTINGS, create, project_body, project_path
from tests.api.test_customer_sci_workflow import article_request, sci_project, upload_docx
from tests.api.test_customer_workspace import sign_in
from tests.api.test_literature import create as create_search, request as search_input
from tests.api.test_literature_citations import CitationNcbi
from tests.api.test_literature_evidence import post
from tests.api.test_manuscripts import body


def test_project_finding_and_unlinked_description_have_distinct_roles():
    with TestClient(app) as owner:
        sign_in(owner, 'simple-writer@example.test', 'customer')
        paper = sci_project(owner)
        file = upload_docx(owner, paper, 'methods.docx', 'Study methods.')
        task = file['task']
        assert run_parse_file_task(task['id'], task['revision'], parser=parse_docx)['status'] == 'succeeded'
        note = owner.put(paper + '/paper-materials/' + file['id'], json=dict(
            expected_revision=0, file_id=file['id'], result='Sampling procedure only.'))
        assert note.status_code in (200, 201), note.text
        plan = owner.get(paper + '/manuscripts/candidates').json()['paper_plan']
        request = body(title=plan['title'], paper_plan_token=plan['token'],
                       sources=[dict(kind='original', id=file['id'], file_id=file['id'], role='methods')])
        prepared = post(owner, paper + '/manuscripts', request, 'materials')
        assert prepared.status_code == 201, prepared.text
        root = prepared.json()
        assert run_task(root['versions'][0]['task_id'], 1)['status'] == 'succeeded'
        path = paper + '/manuscripts/' + root['id'] + '/writing-previews'
        response = post(owner, path, article_request('research', selected_source_ids=[file['id']]), 'preview')
        assert response.status_code == 201, response.text
        payload = json.loads(json.loads(response.json()['wire_json'])['input'])
        assert any(note['text'] == SCI_SETTINGS['figure_findings'][0]['finding'] for note in payload['paper_notes'])
        assert payload['sources'][0]['file_description'] == 'Sampling procedure only.'
        assert payload['sources'][0]['facts'] == []
        # The text entered as a result remains usable even without sending any upload.
        no_files = post(owner, path, article_request('research'), 'without-file')
        assert no_files.status_code == 201, no_files.text
        without_file = json.loads(json.loads(no_files.json()['wire_json'])['input'])
        assert without_file['sources'] == [] and without_file['paper_notes'][0]['source_aliases'] == []

        # Keeping the same file and description while clearing the author's result must block writing.
        settings = owner.get(paper + '/sci-settings').json()
        changed = owner.put(paper + '/sci-settings', json=dict(expected_revision=settings['revision'],
                            settings={**settings['settings'], 'figure_findings': []}))
        assert changed.status_code == 200, changed.text
        new_plan = owner.get(paper + '/manuscripts/candidates').json()['paper_plan']
        updated = post(owner, paper + '/manuscripts/' + root['id'] + '/versions',
                       {**request, 'expected_revision': 1, 'paper_plan_token': new_plan['token']}, 'without-result')
        assert updated.status_code == 201, updated.text
        second = next(row for row in updated.json()['versions'] if row['revision'] == 2)
        assert run_task(second['task_id'], 1)['status'] == 'succeeded'
        denied = post(owner, path, article_request('research', base_revision=2, selected_source_ids=[file['id']]), 'description-only')
        assert denied.status_code == 422 and denied.json()['detail']['code'] == 'manuscript_writing_evidence_required'


def test_topic_supplies_a_localized_default_section_only_for_empty_reviews():
    with TestClient(app) as owner:
        sign_in(owner, 'brief-review@example.test', 'customer')
        paper = project_path(create(owner, 'review', **project_body('sci', sci_settings={
            **{key: value for key, value in SCI_SETTINGS.items() if key != 'figure_findings'},
            'article_type': 'narrative_review', 'review_sections': [],
        })))
        plan = owner.get(paper + '/manuscripts/candidates').json()['paper_plan']
        assert len(plan['sections']) == 1
        assert plan['sections'][0]['text'] == 'Synthetic topic'


def test_shortlisted_paper_freezes_all_abstract_sections_without_manual_quotes():
    class TwoSections(CitationNcbi):
        def fetch(self, pmids):
            raw = super().fetch(pmids).raw.replace(b'</Abstract>', b'<AbstractText Label="RESULTS">Saved result. '
                b'See https://example.org/code. Further findings. Stable result.</AbstractText>'
                b'<AbstractText Label="CONCLUSIONS">Saved result.</AbstractText></Abstract>')
            # A personal name may be recorded in PubMed as a single LastName, with no initials.
            raw = raw.replace(b'<CollectiveName>Synthetic testing group</CollectiveName>', b'<LastName>Sagar</LastName>')
            return parse_fetch(raw, pmids)

    with TestClient(app) as owner:
        sign_in(owner, 'selected-abstract@example.test', 'customer')
        paper = sci_project(owner)
        task = create_search(owner, paper.rsplit('/', 1)[-1]).json()
        assert run_literature_task(task['id'], task['revision'], client=TwoSections(2))['status'] == 'succeeded'
        lit = paper + '/literature'
        ref = next(r for r in owner.get(lit + '/references').json()['items'] if r['record']['abstract'])
        endpoint = paper + '/manuscripts/selected-references'
        selection = dict(references=[dict(project_reference_id=ref['id'], search_id=task['id'])], output_language='en')
        assert post(owner, endpoint, selection, 'not-selected').status_code == 409
        assert owner.patch(lit + '/references/' + ref['id'], json=dict(expected_revision=1, status='shortlisted')).status_code == 200
        result = post(owner, endpoint, selection, 'selected')
        assert result.status_code == 201, result.text
        frozen = post(owner, paper + '/manuscripts/preview', body(citation_draft=result.json()), 'checked')
        assert frozen.status_code == 200, frozen.text
        draft = frozen.json()['citation_snapshot']
        binding = draft['paragraphs'][0]['fragments'][0]['bindings'][0]
        quotes = binding['evidence']
        assert [row['quote'] for row in quotes] == [
            ref['record']['abstract'][0]['text'], 'Saved result.', 'Further findings. Stable result.', 'Saved result.']
        assert [row['location']['abstract_index'] for row in quotes] == [0, 1, 1, 2]
        for row in quotes:
            location = row['location']
            section = ref['record']['abstract'][location['abstract_index']]
            assert section['text'][location['start']:location['end']] == row['quote']
            assert location['label'] == section['label']
        replay = post(owner, endpoint, selection, 'selected')
        assert replay.status_code == 200 and replay.json() == result.json()
        assert all(row['reading_scope'] == 'abstract' for row in binding['evidence'])
        assert binding['metadata']['authors'] == [dict(family='Sagar', given='', initials='', collective='')]
        assert draft['output']['references'][0]['text'].startswith('Sagar. ')
        plan = owner.get(paper + '/manuscripts/candidates').json()['paper_plan']
        second = create_search(owner, paper.rsplit('/',1)[-1], dict(search_input(), query='second query'), 'second').json()
        created = post(owner, paper + '/manuscripts', body(title=plan['title'], paper_plan_token=plan['token'],
                       citation_draft=result.json()), 'generate')
        assert created.status_code == 201, created.text
        root = created.json()
        # A later retrieval may put the identical record in a new EFetch batch.
        assert run_literature_task(second['id'], second['revision'], client=TwoSections(3))['status'] == 'succeeded'
        latest = owner.get(lit + '/references/' + ref['id']).json()
        assert latest['record'] == ref['record'] and latest['source']['receipt_id'] != ref['source']['receipt_id']
        assert run_task(root['versions'][0]['task_id'], 1)['status'] == 'succeeded'
        path = paper + '/manuscripts/' + root['id'] + '/writing-previews'
        preview = post(owner, path, article_request('research', selected_evidence_ids=[row['id'] for row in quotes]), 'write')
        assert preview.status_code == 201, preview.text
        wire = json.loads(json.loads(preview.json()['wire_json'])['input'])
        assert [item['quote'] for item in wire['evidence']] == [row['quote'] for row in quotes]
        assert 'example.org/code' not in preview.json()['wire_json']
        changed = create_search(owner, paper.rsplit('/',1)[-1], dict(search_input(), query='changed query'), 'changed').json()
        assert run_literature_task(changed['id'], changed['revision'], client=TwoSections(4, suffix='updated'))['status'] == 'succeeded'
        latest_version = owner.get(paper + '/manuscripts/' + root['id']).json()['versions'][0]
        assert any('citation_current_changed' in entry['reasons'] for entry in latest_version['current_changes'])


def test_automatic_excerpt_reports_the_pmid_for_absent_or_oversized_usable_text():
    from app.core.exceptions import StorageError
    from app.domain.manuscripts.selected_references import abstract_excerpts
    for text, expected in [
        ('', 'selected_reference_abstract_unusable'),
        ('Download https://example.org/private. Use Bearer opaque. Open C:\\stored\\data.', 'selected_reference_abstract_unusable'),
        ('a' * 12001, 'selected_reference_abstract_limit'),
    ]:
        with pytest.raises(StorageError) as error:
            abstract_excerpts(dict(pmid='990000002', abstract=[dict(text=text)]), 2, 20)
        assert error.value.code == expected
        assert error.value.params == dict(position=2, pmid=990000002)
