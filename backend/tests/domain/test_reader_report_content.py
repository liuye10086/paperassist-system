import base64
import copy
import io

import pytest
from PIL import Image

from app.adapters.bio_reader_narrative import NARRATIVE_FIELDS


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def png(color='red'):
    out = io.BytesIO()
    Image.new('RGB', (20, 12), color).save(out, 'PNG')
    return out.getvalue()


def snapshot():
    return {'title': '空间转录组分析', 'language': 'zh-CN', 'finding': {'id': 'local-result', 'content': {
        'facts': [{'id': 'f1', 'source_id': 's1', 'location': 'summary.retained_observations',
                   'raw_value': 1162, 'unit': 'spots', 'verification': 'verified'}],
        'sources': [{'source_id': 's1', 'title': '空间表达矩阵', 'content': {
            'summary': {'statistical_unit': 'spot_exploratory', 'candidate_count': 0,
                        'confirmed': False, 'missing': None, 'uuid': '00000000-0000-4000-8000-000000000000'},
            'params': {'n_neighbors': 15}}}],
        'methods': [], 'claims': [], 'gaps': [], 'limitations': ['供者设计尚未确认'], 'conflicts': []}},
        'figures': [{'id': 'figure-one', 'manifest_sha256': 'a' * 64}], 'tables': []}


def output(count=1):
    return {'narrative': {key: '本段说明已保存结果与解释条件，无法据此判断供者之间的差异。' for key in NARRATIVE_FIELDS},
            'figures': [{'number': i + 1, 'title': f'质量分布图', 'reading': '横轴显示质量指标，纵轴表示空间点分布。',
                         'observations': '图中分布用于检查当前数据，精确数值应依据保存结果。',
                         'interpretation': '该分布提供样本质量线索，需要结合数据处理条件解释。',
                         'limitations': '图中空间点不等于独立供者，无法从图中确认组间差异。'} for i in range(count)]}


def test_payload_is_bound_but_only_curated_science_is_transmitted():
    from app.domain.reader_reports.content import make_material, binding_digest
    source = snapshot(); old = copy.deepcopy(source)
    material = make_material(source, [{'content': png(), 'config': {'title': '质量分布'}}])
    assert source == old
    assert material['figures'][0]['image_url'] == 'data:image/png;base64,' + base64.b64encode(png()).decode()
    assert material['facts']['facts'][0]['value'] == 1162
    summary = material['facts']['sources'][0]['content']['summary']
    assert summary['candidate_count'] == 0 and summary['confirmed'] is False and summary['missing'] is None
    assert 'uuid' not in summary
    assert 'local-result' not in str(material) and 'manifest_sha256' not in str(material)
    changed = copy.deepcopy(source); changed['figures'][0]['manifest_sha256'] = 'b' * 64
    assert binding_digest(changed) != binding_digest(source)


def test_figure_order_and_bytes_are_exact_model_inputs():
    from app.domain.reader_reports.content import make_material
    a, b = {'content': png('red'), 'title': 'A'}, {'content': png('blue'), 'title': 'B'}
    source = snapshot()
    first = make_material(source, [a, b]); second = make_material(source, [b, a])
    assert first['figures'][0]['image_url'] != second['figures'][0]['image_url']
    assert [f['number'] for f in first['figures']] == [1, 2]


def test_material_retains_frozen_fact_context_and_public_accession():
    from app.domain.reader_reports.content import make_material

    source = snapshot()
    source['finding']['content']['facts'][0].update(
        comparison='Spatial region A versus region B', origin='public_reanalysis',
        limitations=['Neither region is an independent biological replicate'],
    )
    source['finding']['content']['sources'][0]['content']['source_accessions'] = {
        'gse': None, 'gsm': 'GSM8157269',
    }
    material = make_material(source, [])
    record = material['facts']['facts'][0]
    assert record['comparison'] == 'Spatial region A versus region B'
    assert record['origin'] == 'public_reanalysis'
    assert record['limitations'] == ['Neither region is an independent biological replicate']
    assert material['facts']['sources'][0]['content']['source_accessions'] == {'gse': None, 'gsm': 'GSM8157269'}


def test_research_field_locators_survive_without_leaking_file_paths():
    from app.domain.reader_reports.content import make_material

    source = snapshot()
    content = source['finding']['content']
    content['facts'][0].pop('location')
    content['facts'][0]['locator'] = {'kind': 'field', 'field_path': 'summary.retained_features'}
    content['facts'][0]['raw_value'] = 0
    content['sources'][0]['content']['summary'].update(
        filename='patient-data.xlsx', cache_path=r'C:\private\analysis-inputs',
    )
    caption_fact = {'locator': {'kind': 'field', 'field_path': 'steps[0].retained'}, 'raw_value': 0,
                    'file_path': '/private/results.xlsx', 'filename': 'private-output.csv'}
    material = make_material(source, [{'content': png(), 'caption_facts': [caption_fact]}])

    assert material['facts']['facts'][0]['measure']['field_path'] == 'summary.retained_features'
    assert material['facts']['facts'][0]['value'] == 0
    figure_fact = material['figures'][0]['caption_facts'][0]
    assert figure_fact['locator']['field_path'] == 'steps[0].retained'
    assert figure_fact['raw_value'] == 0
    assert all(text not in str(material) for text in (
        'filename', 'cache_path', 'file_path', 'patient-data.xlsx', 'analysis-inputs', 'results.xlsx', 'private-output.csv',
    ))


def test_only_exact_frozen_source_rows_supply_extra_feature_names():
    from app.domain.reader_reports.content import make_material

    source = snapshot()
    finding = source['finding']['content']
    artifact = {'source_kind': 'bio_analysis_artifact', 'source_id': 'markers', 'sha256': 'a' * 64,
                'title': 'Marker table', 'content': {'table_key': 'markers', 'rows': [
                    {'cluster': '1', 'feature_id': 'ENSG1', 'symbol': 'HOPX', 'logfc': 1.4},
                    {'cluster': '2', 'feature_id': 'ENSG1', 'symbol': 'UnselectedName', 'logfc': 9.2},
                ]}}
    finding['sources'].append(artifact)
    exact = {'source_kind': 'bio_analysis_artifact', 'source_id': 'markers', 'source_sha256': 'a' * 64,
             'locator': {'kind': 'row', 'table': 'markers', 'row_key': {'cluster': '1', 'feature_id': 'ENSG1'}},
             'raw_value': 1.4}
    finding['facts'].extend([exact, {**exact, 'source_sha256': 'b' * 64}])

    material = make_material(source, [])
    assert material['facts']['facts'][1]['feature_names'] == {'symbol': 'HOPX'}
    assert 'feature_names' not in material['facts']['facts'][2]
    assert 'UnselectedName' not in str(material)
    assert '9.2' not in str(material)


def test_reader_explains_bulk_prefilter_from_the_bound_comparison_and_counts():
    from app.domain.reader_reports.content import make_material

    source = snapshot()
    source['finding']['content']['sources'] = [{
        'source_kind': 'bio_report_context', 'title': 'Fixed count report',
        'content': {'assay': 'bulk_rna_counts', 'summary': {'contrasts': [{'contrast_id': 'B_A'}]}},
    }]
    source['tables'] = [
        {'key': key, 'format': 'tsv', 'expected_rows': count,
         'source': {'source_kind': 'bio_insight_result_member', 'result_version_id': 'fixed'}}
        for key, count in [('comparison_results', 2), ('model_counts', 1)]
    ]
    raws = [
        b'contrast_id\tfeature_id\ttest_status\treason\nB_A\tf3\texcluded\tminimum_total_counts\nC_A\tf4\texcluded\tminimum_total_counts\n',
        b'model_id\tfeature_id\tprivate_sample_one\tprivate_sample_two\nbulk_model_1\tf3\t1\t5\n',
    ]

    material = make_material(source, [], table_raws=raws)

    assert material['facts']['table_evidence']['bulk_testing_limits'] == [{
        'contrast': 'B_A', 'feature': 'f3', 'status': 'excluded', 'reason': 'minimum_total_counts',
        'model_input_total_count': 6, 'model_input_count_scope': 'model_cohort',
    }]
    assert 'f4' not in str(material['facts']['table_evidence'])
    assert 'private_sample' not in str(material)


def test_reader_keeps_trajectory_evidence_without_cell_or_sample_identifiers():
    from app.domain.reader_reports.content import make_material

    source = snapshot()
    source['finding']['content']['sources'] = [{
        'source_kind': 'bio_report_context', 'title': 'Fixed trajectory', 'content': {'assay': 'slingshot'},
    }]
    source['tables'] = [
        {'key': 'trajectory_results', 'format': 'tsv', 'expected_rows': 2,
         'source': {'source_kind': 'bio_insight_result_member'}},
        {'key': 'topic_units', 'format': 'tsv', 'expected_rows': 1,
         'source': {'source_kind': 'bio_insight_result_member'}},
    ]
    raws = [
        b'barcode\tcluster\tlineage_id\tpseudotime\tweight\tcovered\nprivate-barcode\t0\tL1\t0.0\t1.0\tTrue\nother-cell\t1\tL1\t\t0.0\tFalse\n',
        b'unit_id\tsamples\nprivate-unit\t"[""private-sample""]"\n',
    ]

    material = make_material(source, [], table_raws=raws)

    evidence = material['facts']['table_evidence']['trajectory']
    assert evidence['known_selected_sample_count'] == 1
    assert evidence['rows'] == [
        {'cluster': '0', 'lineage': 'L1', 'pseudotime': '0.0', 'weight': '1.0', 'covered': True},
        {'cluster': '1', 'lineage': 'L1', 'pseudotime': None, 'weight': '0.0', 'covered': False},
    ]
    assert 'private-' not in str(material)


@pytest.mark.parametrize('field', ['caption_facts', 'source_caption'])
def test_cumulative_text_cap_includes_figure_metadata(monkeypatch, field):
    from app.domain.reader_reports import content

    monkeypatch.setattr(content, 'MAX_FACT_BYTES', 5000)
    description = '有值' * 1000
    figure = {'content': png(), 'config': {}}
    if field == 'caption_facts':
        figure['caption_facts'] = [{'limitations': [description]}]
    else:
        figure['config']['caption'] = description
    with pytest.raises(ValueError, match='reader input limit'):
        content.make_material(snapshot(), [figure])


@pytest.mark.parametrize('mutation', ['missing', 'reversed', 'extra', 'hash', 'code', 'version', 'empty', 'path', 'filename'])
def test_output_rejects_incomplete_or_technical_interpretations(mutation):
    from app.domain.reader_reports.content import validate_output
    raw = output(2)
    if mutation == 'missing': raw['figures'].pop()
    if mutation == 'reversed': raw['figures'].reverse()
    if mutation == 'extra': raw['narrative']['unexpected'] = 'x'
    if mutation == 'hash': raw['figures'][0]['observations'] = 'SHA256 ' + 'a' * 64
    if mutation == 'code': raw['narrative']['methods_summary'] = '```python\nprint(1)\n```'
    if mutation == 'version': raw['figures'][0]['reading'] = '软件 version 1.2.3'
    if mutation == 'empty': raw['figures'][0]['limitations'] = ' '
    if mutation == 'path': raw['figures'][0]['limitations'] = r'See C:\research\private\results'
    if mutation == 'filename': raw['figures'][0]['limitations'] = 'See patient-results.xlsx for details.'
    with pytest.raises(ValueError):
        validate_output(raw, {'language': 'zh-CN', 'figures': [{'number': 1}, {'number': 2}]})


def test_zero_figures_and_bilingual_output_are_supported():
    from app.domain.reader_reports.content import validate_output
    assert validate_output(output(0), {'language': 'zh-CN', 'figures': []})['figures'] == []
    raw = output()
    raw['narrative'] = {key: 'This section describes recorded evidence and its limitations.' for key in NARRATIVE_FIELDS}
    for key in ('title', 'reading', 'observations', 'interpretation', 'limitations'):
        raw['figures'][0][key] = 'Recorded observations require independent validation.'
    result = validate_output(raw, {'language': 'en', 'figures': [{'number': 1}]})
    assert 'How to read' in result['figures'][0]['caption']


def test_invalid_image_is_rejected_before_any_provider_submission():
    from app.domain.reader_reports.content import make_material
    with pytest.raises(ValueError):
        make_material(snapshot(), [{'content': b'not a PNG'}])


def test_outbound_strings_remove_internal_identity_without_changing_raw_snapshot():
    from app.domain.reader_reports.content import make_material
    source = snapshot()
    source['finding']['content']['sources'][0]['title'] = 'patient-results.xlsx'
    source['finding']['content']['facts'][0]['raw_value'] = 'task_id 00000000-0000-4000-8000-000000000000 at C:\\research\\private\\data.tsv'
    old = copy.deepcopy(source)
    figure_fact = {'id': 'local-fact', 'raw_value': 8, 'unit': 'mg/mL', 'locator': {'field_path': 'n'}}
    material = make_material(source, [{'content': png(), 'caption_facts': [figure_fact], 'config': {'caption': '原始读图说明'}}])
    assert source == old
    assert 'patient-results.xlsx' not in str(material) and 'task_id' not in str(material) and 'research\\private' not in str(material)
    assert material['figures'][0]['caption_facts'][0]['raw_value'] == 8
    assert material['figures'][0]['caption_facts'][0]['unit'] == 'mg/mL'
    assert material['figures'][0]['source_caption'] == '原始读图说明'
