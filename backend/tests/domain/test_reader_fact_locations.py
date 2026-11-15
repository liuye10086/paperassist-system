"""Reader locations resolve frozen scientific rows without exposing row hashes."""
from copy import deepcopy
import io

from docx import Document
from openpyxl import load_workbook
import pytest

from tests.domain.test_research_reports import sample


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def snapshot_with_rows(language, *, nested=False, include_rows=True):
    snapshot = sample()
    snapshot['language'] = language
    finding = snapshot['finding']['content']
    source = dict(source_kind='bio_insight_result_member', source_id='selected-result', sha256='c'*64,
                  title='Measured protein comparison', provenance='system_computed', content={'table_key':'comparison_results'})
    rows = [dict(row_key='d'*64, feature_id='GENE_A', effect_value='0', contrast_id='B_A'),
            dict(row_key='e'*64, feature_id='GENE_B', effect_value='NA', contrast_id='B_A')]
    if include_rows:
        source['content']['rows'] = rows
    finding['sources'] = [dict(source_id='wrapper', title='Fixed report', provenance='research_derived',
        content=dict(finding=dict(content=dict(sources=[source]))))] if nested else [source]
    finding['facts'] = [dict(id='fact'+str(index), source_kind=source['source_kind'],source_sha256=source['sha256'],source_id=source['source_id'], raw_value=row['effect_value'],
        display_value=row['effect_value'], unit='log2', comparison='B / A', observation_level='sample',
        verification_status='verified', locator=dict(kind='row', table='comparison_results',
            row_key={'row_key': row['row_key']}, column='effect_value')) for index, row in enumerate(rows, 1)]
    finding['conflicts'] = [dict(fact_ids=['fact2','fact1'], decision='use_first', note='Check exact values', basis='')]
    return snapshot, rows


@pytest.mark.parametrize('language', ['en','zh-CN'])
@pytest.mark.parametrize('nested', [False, True])
def test_word_workbook_and_conflict_use_frozen_row_names_without_changing_identity(language, nested):
    from app.adapters.research_report_docx import build_report, conflict_text
    from app.adapters.research_results_xlsx import build_workbook
    snapshot, rows = snapshot_with_rows(language, nested=nested)
    before = deepcopy(snapshot)
    doc = Document(io.BytesIO(build_report(snapshot, [])))
    text = '\n'.join([p.text for p in doc.paragraphs] + [cell.text for table in doc.tables for row in table.rows for cell in row.cells])
    assert all(marker not in text for marker in ('d'*64, 'e'*64, 'comparison_results', 'effect_value'))
    assert 'GENE_A' in text and 'GENE_B' in text and 'B / A' in text
    finding = snapshot['finding']['content']
    conflict = conflict_text(finding['conflicts'][0], language == 'en', finding,reader=True)
    assert conflict.index('GENE_B') < conflict.index('GENE_A')
    assert 'NA' in conflict and '0 log2' in conflict
    raw, _ = build_workbook(snapshot, [dict(key='comparison_results', columns=['row_key','feature_id','effect_value'],
        rows=[[row[k] for k in ('row_key','feature_id','effect_value')] for row in rows], expected_rows=2)])
    book = load_workbook(io.BytesIO(raw), read_only=True, data_only=False)
    try:
        locations = [row[-1] for row in list(book['Facts'].values)[1:]]
        assert 'GENE_A' in locations[0] and 'GENE_B' in locations[1]
        assert all(marker not in str(locations) for marker in ('d'*64, 'e'*64, 'comparison_results', 'effect_value'))
        assert list(book['comparison_results'].values)[1:] == [('d'*64,'GENE_A','0'),('e'*64,'GENE_B','NA')]
    finally:
        book.close()
    assert snapshot == before


@pytest.mark.parametrize('language', ['en','zh-CN'])
def test_unavailable_row_names_use_distinct_selected_items_without_inventing_features(language):
    from app.adapters.research_report_docx import build_report
    snapshot, _ = snapshot_with_rows(language, include_rows=False)
    doc = Document(io.BytesIO(build_report(snapshot, [])))
    locations = [row.cells[0].text for row in doc.tables[0].rows[1:]]
    assert locations[0] != locations[1]
    assert ('Selected result 1' if language == 'en' else '选定结果第 1 项') in locations[0]
    assert ('Selected result 2' if language == 'en' else '选定结果第 2 项') in locations[1]
    assert all(value not in str(locations) for value in ('GENE_A','GENE_B','d'*64,'e'*64))


@pytest.mark.parametrize('language', ['en','zh-CN'])
def test_saved_table_title_and_comparison_direction_are_reader_facing(language):
    from app.adapters.research_report_docx import source_title
    from app.adapters.research_method_text import present_method
    title=source_title(dict(source_id='member',title='comparison_results'),language=='en')
    assert title==('Comparison results' if language=='en' else '比较结果')
    direction='groups[0] relative to groups[1]; omnibus has no single effect'
    method=dict(id='insight-method-location',executed=True,source=dict(source_kind='bio_insight_result_member',source_id='member',sha256='a'*64),
        parameters=dict(frozen_config=dict(kind='comparison',schema_version=2,mode='continuous',contrasts=[]),direction=direction))
    readable='\n'.join(present_method(method,language,reader=True)['paragraphs'])
    technical='\n'.join(present_method(method,language,reader=False)['paragraphs'])
    assert 'groups[' not in readable and direction in technical
    assert ('first selected group' if language=='en' else '首个选定组') in readable


@pytest.mark.parametrize('mismatch',['source_kind','sha256','table_key','missing_key'])
def test_row_name_never_comes_from_a_different_frozen_source_or_table(mismatch):
    from app.adapters.research_report_docx import build_report
    snapshot,_=snapshot_with_rows('en')
    source=snapshot['finding']['content']['sources'][0]
    source['title']='Wrong source'
    if mismatch=='table_key':source['content']['table_key']='other_results'
    elif mismatch=='missing_key':
        for row in source['content']['rows']:row.pop('row_key')
        for fact in snapshot['finding']['content']['facts']:fact['locator']['row_key']={'row_key':'None'}
    else:source[mismatch]='different'
    doc=Document(io.BytesIO(build_report(snapshot,[])))
    locations=[row.cells[0].text for row in doc.tables[0].rows[1:]]
    assert 'GENE_A' not in str(locations) and 'GENE_B' not in str(locations)
    conflict=next(p.text for p in doc.paragraphs if 'Check exact values' in p.text)
    assert 'Wrong source' not in conflict


def test_fact_titles_and_ordinals_follow_the_same_full_source_identity():
    from app.adapters.research_results_xlsx import build_workbook
    snapshot,_=snapshot_with_rows('en')
    finding=snapshot['finding']['content']
    second=deepcopy(finding['sources'][0]);second['sha256']='f'*64;second['title']='Second source'
    second['content']['rows'][0]['feature_id']='GENE_SECOND'
    finding['sources'].append(second)
    finding['facts'][1].update(source_sha256='f'*64,locator=deepcopy(finding['facts'][0]['locator']))
    raw,_=build_workbook(snapshot,[])
    book=load_workbook(io.BytesIO(raw),read_only=True)
    try:
        first,second=list(book['Facts'].values)[1:]
        assert first[-2]=='Measured protein comparison' and second[-2]=='Second source'
        assert 'Selected result 1' in first[-1] and 'GENE_A' in first[-1]
        assert 'Selected result 2' in second[-1] and 'GENE_SECOND' in second[-1]
    finally:book.close()


@pytest.mark.parametrize(('language','expected'),[
    ('en','d2c15559f392b8502e913ce610b9124bedad41682ebb9e54b9e35088ea9e8f3b'),
    ('zh-CN','0cfa968341980c1fbbc56aa4fc28b740de893de486289c77f242ace513f44ac1')])
def test_presentation_fix_preserves_existing_model_material_bytes(language,expected):
    import hashlib
    from app.domain.reader_reports.content import make_material,canonical
    # Recorded from the approved pre-presentation implementation. This is a
    # compatibility guarantee for existing paid interpretation cache bindings.
    material=make_material(snapshot_with_rows(language)[0],[])
    assert hashlib.sha256(canonical(material).encode()).hexdigest()==expected


@pytest.mark.parametrize('language',['en','zh-CN'])
def test_reader_scope_lists_translate_internal_enums_but_keep_gene_identifiers(language):
    from app.adapters.research_method_text import present_method
    method=dict(id='insight-method-figure',executed=True,source=dict(source_kind='bio_insight_result_member',source_id='member',sha256='a'*64),
        parameters=dict(source_inference_scopes=['sample_inference'],frozen_config=dict(kind='figure',figure_type='heatmap',
            sample_groups=[dict(label='A',sample_keys=[])],feature_ids=['HLA_DRA','GENE_A'])))
    reader='\n'.join(present_method(method,language,reader=True)['paragraphs'])
    technical='\n'.join(present_method(method,language,reader=False)['paragraphs'])
    assert 'sample_inference' not in reader and 'sample_inference' in technical
    from app.adapters.research_method_text import _details
    values=' '.join(_details(['sample_inference','HLA_DRA','GENE_A'],language=='en',reader=True))
    assert 'HLA_DRA' in values and 'GENE_A' in values and 'sample_inference' not in values
    ordinary=[None,True,False,'',0,1.5,'HLA_DRA']
    assert _details(ordinary,language=='en',reader=True)==_details(ordinary,language=='en',reader=False)


@pytest.mark.parametrize('language',['en','zh-CN'])
def test_hashed_summary_families_have_distinct_readable_locations_without_changing_evidence(language):
    from app.adapters.research_report_docx import build_report, fact_location
    from app.adapters.research_results_xlsx import build_workbook
    snapshot,_=snapshot_with_rows(language)
    finding=snapshot['finding']['content']
    finding['conflicts']=[]
    template=finding['facts'][0]
    paths=[f'summary.family.{"a"*64}.direction',f'summary.family.{"a"*64}.family_size',f'summary.family.{"b"*64}.direction']
    finding['facts']=[dict(template,id=f'family-{index}',raw_value=value,display_value=value,
        locator=dict(field_path=path)) for index,(path,value) in enumerate(zip(paths,['up','2','down']))]
    before=deepcopy(snapshot)
    doc=Document(io.BytesIO(build_report(snapshot,[])))
    locations=[row.cells[0].text for row in doc.tables[0].rows[1:]]
    first='Test family 1' if language=='en' else '检验族 1'
    second='Test family 2' if language=='en' else '检验族 2'
    assert first in locations[0] and first in locations[1] and second in locations[2]
    assert all(marker not in str(locations) for marker in ('a'*64,'b'*64,'family_size'))
    raw,_=build_workbook(snapshot,[])
    book=load_workbook(io.BytesIO(raw),read_only=True)
    try:assert [row[-1] for row in list(book['Facts'].values)[1:]]==locations
    finally:book.close()
    assert snapshot==before
    assert 'a'*64 in fact_location(dict(field_path=paths[0]),language=='en',reader=False)


def bulk_reader_snapshot(language):
    snapshot, rows = snapshot_with_rows(language)
    finding = snapshot['finding']['content']
    template = dict(finding['facts'][0], source_kind='bio_insight_result_version')
    additions = (
        ('comparison-index', 'summary.result_member_key', 'comparison_results'),
        ('enrichment-index', 'summary.result_member_key', 'enrichment_results'),
        ('ora-status', 'summary.enrichment_status', 'no_significant_terms'),
        ('retained', 'summary.other_scientific_value', 'HLA_DRA'),
        ('family-direction', f'summary.family.{"a"*64}.nested.{"a"*64}.direction', 'both'),
        ('family-size', f'summary.family.{"a"*64}.nested.{"a"*64}.family_size', 2),
    )
    finding['facts'].extend(dict(template, id=identifier, raw_value=value, display_value=str(value),
        locator=dict(kind='field', field_path=path), unit='') for identifier, path, value in additions)
    finding['conflicts'] = [dict(fact_ids=['enrichment-index', 'family-size'], decision='explained',
                                  note='Check exact values', basis='')]
    processed = dict(source_kind='bio_processed_dataset_version', source_id='fixed-counts', sha256='1'*64)
    finding['methods'] = [
        dict(id='quantitative', title='样本定量处理方法 / Sample quantitative processing',
             description='以样本为观测单位；输入尺度为 raw_counts，单位 counts。标准化 none。',
             parameters=dict(name='tabular_quantitative_v1', input_scale=dict(kind='raw_counts'),
                 description_en='Observations are samples; input scale raw counts (counts). Normalization none.',
                 description_zh='以样本为观测单位；输入尺度为 raw_counts，单位 counts。标准化 none。',
                 layers='raw, filtered, normalized and variance-stabilized layers retain explicit axes; analysis object is portable NPZ+JSON'),
             executed=True, source=processed),
        dict(id='clustering', title='sample_clustering', description='已执行 / Completed',
             parameters={}, executed=True, source=processed),
    ]
    return snapshot, rows


@pytest.mark.parametrize('language', ['en', 'zh-CN'])
def test_bulk_reader_hides_member_indexes_and_keeps_scientific_facts_and_raw_tables(language):
    from app.adapters.research_report_docx import build_report
    from app.adapters.research_results_xlsx import build_workbook

    snapshot, rows = bulk_reader_snapshot(language)
    before = deepcopy(snapshot)
    doc = Document(io.BytesIO(build_report(snapshot, [])))
    word = '\n'.join([p.text for p in doc.paragraphs] +
                     [c.text for t in doc.tables for r in t.rows for c in r.cells])
    columns = ['row_key', 'feature_id', 'effect_value']
    data = [tuple(row[key] for key in columns) for row in rows]
    xlsx, counts = build_workbook(snapshot, [dict(key='comparison_results', columns=columns,
                                                  rows=data, expected_rows=len(data))])
    book = load_workbook(io.BytesIO(xlsx), read_only=True, data_only=False)
    try:
        reader_sheets = ('Facts', 'Sources', 'Methods', 'Figures', 'Limitations')
        explanations = '\n'.join(str(cell) for name in reader_sheets for row in book[name].values for cell in row)
        for rendered in (word, explanations):
            for technical in ('comparison_results', 'enrichment_results', 'result member key', 'result_member_key',
                              'no_significant_terms', 'raw_counts', 'sample_clustering', 'NPZ+JSON',
                              'tabular quantitative v1'):
                assert technical not in rendered
            for scientific in ('HLA_DRA', 'No significant enrichment terms' if language=='en' else '未检出显著富集条目',
                               'Sample clustering' if language=='en' else '样本聚类',
                               'raw counts' if language=='en' else '原始计数'):
                assert scientific in rendered
        assert list(book['comparison_results'].values) == [tuple(columns), *data]
        assert counts['tables'][0]['key'] == 'comparison_results'
    finally:
        book.close()
    assert snapshot == before


@pytest.mark.parametrize('language', ['en', 'zh-CN'])
def test_repeated_hash_uses_position_specific_labels_in_both_exports(language):
    from app.adapters.research_report_docx import build_report, fact_location
    from app.adapters.research_results_xlsx import build_workbook

    snapshot, _ = bulk_reader_snapshot(language)
    doc = Document(io.BytesIO(build_report(snapshot, [])))
    xlsx, _ = build_workbook(snapshot, [])
    book = load_workbook(io.BytesIO(xlsx), read_only=True)
    expected = 'Test family 1 / nested / Selected item 2' if language=='en' else '检验族 1 / nested / 选定项目 2'
    try:
        word = [row.cells[0].text for row in doc.tables[0].rows[1:]]
        facts = [row[-1] for row in list(book['Facts'].values)[1:]]
        assert word == facts
        assert sum(location.startswith(expected) for location in word) == 2
    finally:
        book.close()
    locator = snapshot['finding']['content']['facts'][-1]['locator']
    assert fact_location(locator, language=='en', reader=False).count('a'*64) == 2


@pytest.mark.parametrize(('language','expected'), [
    ('en','575deb3ae4c3dec24fc5fa39111333e4a0efbc4abc57d9fbb2b7b93739160b99'),
    ('zh-CN','08de9fb2d59603260f15828cddd63a60fa78a64915b96e2bba1563207ffd050f'),
])
def test_bulk_indexes_and_repeated_hashes_keep_existing_model_material(language, expected):
    from hashlib import sha256
    from app.domain.reader_reports.content import canonical, make_material

    material = make_material(bulk_reader_snapshot(language)[0], [])
    assert sha256(canonical(material).encode()).hexdigest() == expected
