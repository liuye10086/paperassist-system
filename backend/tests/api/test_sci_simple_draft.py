import json
from io import BytesIO

import pytest

from docx import Document
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
from tests.integration.test_customer_sci_to_word import SciFixtureProvider, create_fact, selected_pubmed_reference, submit_candidate


def test_sci_template_confirmation_freezes_edited_chapter_names_and_order_in_new_draft():
    with TestClient(app) as owner:
        sign_in(owner, 'template-writer@example.test', 'customer')
        paper = sci_project(owner)
        path = paper + '/sci-template'
        before = owner.get(paper + '/manuscripts/candidates').json()['paper_plan']
        response = owner.get(path)
        assert response.status_code == 200, response.text
        catalog = response.json()
        assert catalog['selected_template_id'] is None
        assert all(row['article_type'] == 'research' for row in catalog['templates'])
        template = next(row for row in catalog['templates'] if row['id'] == 'frontiers-genetics-research-v1')
        assert template['source_url'].startswith('https://www.frontiersin.org/')
        selected = dict(expected_revision=catalog['revision'], template_id=template['id'])
        wrong = owner.put(path, json={**selected, 'template_id': 'frontiers-genetics-review-v1'})
        assert wrong.status_code == 422, wrong.text
        saved = owner.put(path, json=selected)
        assert saved.status_code == 200, saved.text
        assert saved.json()['selected_template_id'] == template['id']
        assert owner.put(path, json=selected).json() == saved.json()
        assert owner.get(path).json() == saved.json()

        sections = [dict(section) for section in template['sections']]
        sections[0]['level'] = 1
        sections[-1].update(en='Works cited', level=2)
        sections[4].update(zh='主要发现', en='Principal findings', level=2)
        sections[3], sections[4] = sections[4], sections[3]
        custom_id = 'sci-section-0123456789abcdef0123456789abcdef'
        sections.insert(-1, dict(id=custom_id, en='Data availability', zh='数据可用性', level=3))
        adjusted = dict(selected, expected_revision=saved.json()['revision'], sections=sections)
        saved = owner.put(path, json=adjusted)
        assert saved.status_code == 200, saved.text
        assert saved.json()['selected_sections'] == sections
        assert owner.put(path, json=adjusted).json() == saved.json()
        assert owner.get(path).json() == saved.json()
        assert owner.put(path, json=dict(selected, expected_revision=saved.json()['revision'])).json() == saved.json()
        invalid = owner.put(path, json=dict(adjusted, expected_revision=saved.json()['revision'], sections=sections[1:] + sections[:1]))
        assert invalid.status_code == 422, invalid.text
        invalid = owner.put(path, json=dict(adjusted, expected_revision=saved.json()['revision'],
                            sections=[*sections[:-2], dict(sections[-2], id='unknown'), sections[-1]]))
        assert invalid.status_code == 422, invalid.text

        plan = owner.get(paper + '/manuscripts/candidates').json()['paper_plan']
        assert plan['token'] != before['token']
        assert plan['sci_template'] == dict(template, sections=sections)
        created = post(owner, paper + '/manuscripts', body(title=plan['title'], paper_plan_token=plan['token']), 'template-draft')
        assert created.status_code == 201, created.text
        root = created.json()
        assert run_task(root['versions'][0]['task_id'], 1)['status'] == 'succeeded'
        preview_url = paper + '/manuscripts/' + root['id'] + '/writing-previews'
        preview = post(owner, preview_url, article_request('research'), 'template-preview')
        assert preview.status_code == 201, preview.text
        payload = json.loads(json.loads(preview.json()['wire_json'])['input'])
        headings = [section['heading'] for section in payload['article_structure']]
        assert headings.index('Principal findings') < headings.index('Materials and Methods')
        assert payload['article_structure'][-2] == dict(id=custom_id, heading='Data availability', level=3)

        provider = SciFixtureProvider({sid: dict(text='Synthetic template test prose.')
                                       for sid in payload['writing_scope']['output_section_ids']})
        reader, candidate = submit_candidate(owner, paper, paper + '/manuscripts/' + root['id'], preview.json(), provider)
        assert [section['id'] for section in candidate['sections']] == [section['id'] for section in sections]
        assert next(section for section in candidate['sections'] if section['id'] == custom_id)['level'] == 3
        assert owner.get(reader, params={'revision': 1}).json()['draft']['reference_heading'] == dict(heading='Works cited', level=2)
        word = owner.get(reader + '/word', params={'revision': 1})
        assert word.status_code == 200, word.text
        document = Document(BytesIO(word.content))
        paragraphs = [paragraph.text for paragraph in document.paragraphs]
        assert paragraphs.index('Principal findings') < paragraphs.index('Materials and Methods')
        assert document.paragraphs[0].style.name == 'Heading 1'
        assert document.paragraphs[paragraphs.index('Principal findings')].style.name == 'Heading 2'
        assert document.paragraphs[paragraphs.index('Data availability')].style.name == 'Heading 3'

        settings = owner.get(paper + '/sci-settings').json()
        edit = owner.put(paper + '/sci-settings', json=dict(expected_revision=settings['revision'],
                         settings={**settings['settings'], 'proposed_title': 'A revised title'}))
        assert edit.status_code == 200, edit.text
        assert owner.get(path).json()['selected_template_id'] == template['id']
        assert owner.get(path).json()['selected_sections'] == sections

        changed = owner.put(path, json=dict(expected_revision=edit.json()['revision'], template_id='scientific-reports-article-v1'))
        assert changed.status_code == 200, changed.text
        latest = owner.get(paper + '/manuscripts/candidates').json()['paper_plan']
        assert latest['sci_template']['id'] == 'scientific-reports-article-v1'
        assert latest['token'] != plan['token']
        old_draft = owner.get(reader, params={'revision': 1})
        assert old_draft.status_code == 200, old_draft.text
        assert old_draft.json()['draft']['sci_template_name'] == template['name']
        old_word = owner.get(reader + '/word', params={'revision': 1})
        assert old_word.status_code == 200, old_word.text
        assert [p.text for p in Document(BytesIO(old_word.content)).paragraphs] == paragraphs


def test_cell_press_research_template_preserves_manuscript_format_and_optional_sections(monkeypatch):
    monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', '')
    with TestClient(app) as owner:
        sign_in(owner, 'cell-press-template@example.test', 'customer')
        paper = sci_project(owner)
        template_url = paper + '/sci-template'
        catalog = owner.get(template_url).json()
        template = next(row for row in catalog['templates'] if row['id'] == 'cell-press-research-v1')
        assert template['article_type'] == 'research'
        guide = template['format_guide']
        author_fields = ['Author list', 'Author affiliations and footnotes', 'Contact information']
        assert [field['en'] for field in guide['title_fields']] == author_fields
        assert guide['keywords']['en'] == 'Keywords'
        assert 'notes' not in guide
        assert all('note' not in item for item in [*guide['title_fields'], guide['keywords'], *guide['optional_sections']])
        design, supplemental = guide['optional_sections']
        assert design['section']['en'] == 'Design' and design['after'] == 'introduction'
        assert supplemental['section']['en'] == 'Supplemental information'
        headings = ['Title', 'Summary', 'Introduction', 'Results', 'Discussion', 'Materials and Methods', 'References']
        assert [section['en'] for section in template['sections']] == headings
        saved = owner.put(template_url, json=dict(expected_revision=catalog['revision'], template_id=template['id']))
        assert saved.status_code == 200, saved.text
        assert owner.get(template_url).json()['selected_sections'] == template['sections']

        sections = [*template['sections'][:-1], supplemental['section'], template['sections'][-1]]
        saved = owner.put(template_url, json=dict(expected_revision=saved.json()['revision'],
                                                  template_id=template['id'], sections=sections))
        assert saved.status_code == 200, saved.text
        assert owner.get(template_url).json()['selected_sections'] == sections

        plan = owner.get(paper + '/manuscripts/candidates').json()['paper_plan']
        assert plan['sci_template']['id'] == template['id']
        assert 'format_guide' not in plan['sci_template']
        root, _ = create_fact(owner, paper, body(title=plan['title'], paper_plan_token=plan['token']))
        preview = post(owner, root + '/writing-previews', article_request('research'), 'cell-press-preview')
        assert preview.status_code == 201, preview.text
        bundle = preview.json()
        assert bundle['execution_contract'].get('skills_snapshot') is None
        payload = json.loads(json.loads(bundle['wire_json'])['input'])
        assert [section['heading'] for section in payload['article_structure']] == [section['en'] for section in sections]
        provider = SciFixtureProvider({sid: dict(text='Synthetic template test prose.')
                                       for sid in payload['writing_scope']['output_section_ids']})
        reader, _ = submit_candidate(owner, paper, root, bundle, provider)
        detail = owner.get(reader, params={'revision': 1})
        assert detail.status_code == 200, detail.text
        rendered = detail.json()['draft']
        assert rendered['sci_template_name'] == template['name']
        assert rendered['title_fields'] == author_fields
        assert [section['heading'] for section in rendered['sections']] == [section['en'] for section in sections[:-1]]
        word = owner.get(reader + '/word', params={'revision': 1})
        assert word.status_code == 200, word.text
        lines = [p.text for p in Document(BytesIO(word.content)).paragraphs]
        assert [line.rstrip(': ') for line in lines[1:4]] == author_fields
        assert lines[4] == 'Summary'
        [keywords] = [line for line in lines if line.startswith('Keywords')]
        assert keywords == 'Keywords: ' + ', '.join(SCI_SETTINGS['keywords'])
        assert lines.index('Summary') < lines.index(keywords) < lines.index('Introduction')
        assert lines.index('Results') < lines.index('Discussion') < lines.index('Materials and Methods')
        assert lines.index('Materials and Methods') < lines.index('Supplemental information')


def test_sci_template_review_reorders_themes_without_replacing_their_notes():
    from app.domain.manuscript_writing.article_contract import labels, theme_sections

    with TestClient(app) as owner:
        sign_in(owner, 'template-review@example.test', 'customer')
        settings = {key: value for key, value in SCI_SETTINGS.items() if key != 'figure_findings'}
        settings.update(article_type='narrative_review', review_sections=[
            dict(id='first', heading='Previous first heading', content='First saved material'),
            dict(id='second', heading='Previous second heading', content='Second saved material'),
        ])
        paper = project_path(create(owner, 'review-outline', **project_body('sci', sci_settings=settings)))
        path = paper + '/sci-template'
        before = owner.get(paper + '/manuscripts/candidates').json()['paper_plan']
        state = owner.get(path).json()
        headings = [dict(id='second', heading='Revised second heading'),
                    dict(id='first', heading='Previous first heading')]
        data = dict(expected_revision=state['revision'], template_id='frontiers-genetics-review-v1', review_headings=headings)
        assert owner.put(path, json={**data, 'review_headings': [headings[0]] * 2}).status_code == 422
        saved = owner.put(path, json=data)
        assert saved.status_code == 200, saved.text
        assert saved.json()['review_headings'] == owner.get(path).json()['review_headings'] == headings
        plan = owner.get(paper + '/manuscripts/candidates').json()['paper_plan']
        assert plan['sections'] == [dict(before['sections'][1], label=headings[0]['heading']), before['sections'][0]]
        assert [section['level'] for section in theme_sections(dict(paper_plan=plan))] == [2, 2]
        outgoing = [heading for _, heading, _ in labels('narrative_review', dict(paper_plan=plan))]
        assert outgoing.index(headings[0]['heading']) < outgoing.index(headings[1]['heading'])
        state = owner.get(paper + '/sci-settings').json()
        edited = owner.put(paper + '/sci-settings', json=dict(
            expected_revision=state['revision'], settings=dict(state['settings'], proposed_title='Updated review title')))
        assert edited.status_code == 200, edited.text
        assert owner.get(path).json()['review_headings'] == headings


def test_sci_template_combines_review_topics_in_the_confirmed_chapter():
    from app.domain.manuscript_writing.article_contract import theme_sections

    with TestClient(app) as owner:
        sign_in(owner, 'combined-review@example.test', 'customer')
        paper = sci_project(owner, 'narrative_review')
        path = paper + '/sci-template'
        state = owner.get(path).json()
        template = next(row for row in state['templates'] if row['id'] == 'standard-sci-review-v1')
        saved = owner.put(path, json=dict(expected_revision=state['revision'], template_id=template['id'],
                                        combine_review_topics=True))
        assert saved.status_code == 200, saved.text
        assert saved.json()['combine_review_topics'] is True
        assert owner.get(paper + '/sci-settings').json()['settings']['review_sections'][0]['content'] == 'Synthetic scope'

        plan = owner.get(paper + '/manuscripts/candidates').json()['paper_plan']
        assert plan['sections'][0]['text'] == 'Synthetic scope'
        assert not theme_sections(dict(paper_plan=plan))
        bibliography, _, _, _, quote = selected_pubmed_reference(owner, paper, 'en')
        root_path, base = create_fact(owner, paper, body(title=plan['title'], methods={}, paper_plan_token=plan['token'],
                                                        citation_draft=bibliography))
        evidence = base['citation_snapshot']['paragraphs'][0]['fragments'][0]['bindings'][0]['evidence'][0]
        preview = post(owner, root_path + '/writing-previews',
                       article_request('narrative_review', selected_evidence_ids=[evidence['id']]), 'combined-preview')
        assert preview.status_code == 201, preview.text
        payload = json.loads(json.loads(preview.json()['wire_json'])['input'])
        assert payload['paper_notes'] == [dict(section_id='themes', text='Synthetic scope', topic='Research themes', source_aliases=[])]
        output = {sid: dict(text='Synthetic review prose.') for sid in payload['writing_scope']['output_section_ids']}
        output['themes'] = dict(text=quote, evidence_aliases=['e1'])
        provider = SciFixtureProvider(output)
        reader, candidate = submit_candidate(owner, paper, root_path, preview.json(), provider)
        assert [section['id'] for section in candidate['sections']] == [section['id'] for section in template['sections']]
        word = owner.get(reader + '/word', params={'revision': 1})
        assert word.status_code == 200, word.text
        headings = [p.text for p in Document(BytesIO(word.content)).paragraphs if p.style.name.startswith('Heading')]
        assert 'Thematic synthesis' in headings and 'Research themes' not in headings


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
