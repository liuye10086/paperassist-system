"""Pure contract regressions: no database, numerical worker, or provider calls."""
from copy import deepcopy
from hashlib import sha256
import pytest

from app.domain.external_processing import digest
from app.domain.figure_workbench import material, presentation, prompts, tasks
from app.adapters.figure_description import description_lines
from tests.domain.test_batch06_presentation import materials


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def test_v2_material_expected_and_prompt_bytes_remain_frozen():
    payload, expected, kwargs = materials()
    payload, expected = presentation.enrich_material(payload, expected, **kwargs)
    assert digest(payload) == '0de27dbf184bd07dc553c04004f99fd898b5f9fd0f36cd9117298851453847d4'
    assert digest(expected) == '650bcef5e2151c986a670868584d312d569666ac5a5f3efc1d586b5b800aa342'
    assert sha256(prompts.instructions_for(payload).encode()).hexdigest() == 'b3e9d93ec9fb6cab1bc3615da64641cffdaf211a78ca6208dbda085928061894'
    assert tasks.prompt_version(payload) == 'openai_figure_workbench_v2'


def test_v3_legend_has_reserved_space_outside_data_axes_without_shrinking_text():
    payload, expected, kwargs = materials()
    old, _ = presentation.enrich_material(payload, expected, **kwargs)
    new, _ = presentation.enrich_material(payload, expected, contract=3, **kwargs)
    instruction = prompts.instructions_for(new)
    for required in ('Reserve dedicated canvas space outside the data axes for the legend before plotting',
                     'Never overlay the legend on any box, whisker, error bar, point, confidence interval or risk table',
                     'Do not rely only on loc=best',
                     'do not shrink labels, the full caption or abbreviations to unreadable sizes',
                     'preserve the exact supplied labels and legend label-to-color mapping'):
        assert required in instruction
        assert required not in prompts.instructions_for(old)
        assert required not in prompts.instructions_for(payload)
    assert 'Render labels.caption exactly once' in instruction


def test_v3_layout_separates_axis_labels_and_caption_and_checks_final_text_bounds():
    payload, expected, kwargs = materials()
    new, _ = presentation.enrich_material(payload, expected, contract=3, **kwargs)
    instruction = prompts.instructions_for(new)
    for required in ('Keep the exact requested style.width/style.height pixels and supplied font_size',
                     'title, tick labels, axis labels, legend, full caption and abbreviations must occupy separate non-overlapping regions',
                     'Reduce the data-axes area when needed',
                     'draw the final canvas and use the renderer to inspect text bounding boxes',
                     'Reposition and rewrap until every required text bounding box is inside the canvas and does not overlap other text',
                     'In particular, separate the x-axis label from the first caption line'):
        assert required in instruction
        assert required not in prompts.instructions_for(payload)


@pytest.mark.parametrize('language,author', [('zh-CN', '人工合成材料，仅作软件验证。'), ('en', 'Synthetic data for software verification only.')])
def test_v3_full_caption_owns_author_and_system_notes_once(language, author):
    payload, expected, kwargs = materials(language=language)
    kwargs['config']['style']['caption'] = author
    payload['labels']['caption'] += ' ' + author
    payload, expected = presentation.enrich_material(payload, expected, contract=3, **kwargs)
    assert payload['presentation']['schema_version'] == 2
    assert payload['labels']['caption'].count(author) == 1
    for note in payload['presentation']['statistical_notes']:
        assert payload['labels']['caption'].count(note) == 1
        assert note not in '\n'.join(description_lines(payload['presentation'], language == 'en'))
    assert payload['presentation'] == expected['presentation']
    assert 'Render labels.caption exactly once' in prompts.instructions_for(payload)
    assert 'never render statistical_notes or the author caption separately' in prompts.instructions_for(payload)
    assert 'Render abbreviations and statistical_notes' not in prompts.instructions_for(payload)
    assert tasks.prompt_version(payload) == 'openai_figure_workbench_v3'
    assert presentation.renderer_for({'figure_contract': 3}) == 'openai_figure_workbench_v3'


def test_column_letter_aliases_fix_descriptive_only_in_v3():
    result = {'numeric_name': 'Measurement', 'group_name': 'Group',
              'selection': {'numeric_column': 'E', 'group_column': 'I', 'unit': 'mm'},
              'groups': [{'label': 'Group 0'}, {'label': 'Group 1'}]}
    aliases = {'E': '测量指标', 'I': '研究分组'}
    snapshot = {'result': result}
    for version in (1, 2):
        old = material.display_labels(snapshot, aliases, figure_contract=version)
        assert old['numeric_name'] == 'Measurement' and old['group_name'] == 'Group'
    new = material.display_labels(snapshot, aliases, figure_contract=3)
    assert new['numeric_name'] == '测量指标' and new['group_name'] == '研究分组'
    assert new['unit'] == 'mm' and new['group:0'] == 'Group 0'


@pytest.mark.parametrize('language,base,extra', [
    ('zh-CN', '箱体为 Q1–Q3，中线为中位数；须端为 1.5×IQR 范围内最远观测。', '箱体和须不是置信区间。'),
    ('en', 'Boxes show Q1-Q3 and median; whiskers reach extreme observations within 1.5*IQR.', 'Boxes and whiskers are not confidence intervals.'),
])
def test_v3_boxplot_keeps_detailed_base_caption_without_repeating_whisker_definition(language, base, extra):
    payload = {'figure_kind': 'boxplot', 'legacy_contract': 1, 'language': language,
               'labels': {'title': 'Title', 'x_label': 'Value (mm)', 'y_label': 'Arm', 'caption': base + ' Author caption.'}}
    actual, _ = presentation.enrich_material(payload, {}, config={'style': {'caption': 'Author caption.'}}, result={}, projection=None, fields={}, contract=3)
    assert actual['labels']['caption'] == base + ' Author caption. ' + extra
    assert actual['presentation']['statistical_notes'] == [extra]


@pytest.mark.parametrize('kind', ['correlation', 'group_comparison', 'regression', 'roc', 'survival'])
def test_modern_family_column_aliases_preserve_units_and_categories(kind):
    result = {'result_type': kind, 'selection': {'group_column': 'I'},
              'variables': [{'column': 'E', 'name': 'Measurement', 'unit': 'mm'}, {'column': 'I', 'name': 'Group', 'unit': ''}],
              'groups': [{'label': 'Group 0'}], 'statistics': {'groups': [{'label': 'Group 0'}],
              'coefficients': [{'column': 'E', 'level': None, 'reference': None},
                               {'column': 'I', 'level': {'value': 'Group 1'}, 'reference': {'value': 'Group 0'}}]}}
    actual = material.display_labels({'result': result}, {'E': '测量指标', 'I': '研究分组'}, figure_contract=3)
    assert actual['field:E'] == '测量指标' and actual['field:I'] == '研究分组'
    assert actual['unit:E'] == 'mm'
    if kind in ('group_comparison', 'survival'):
        assert actual['group:0'] == 'Group 0'
    if kind == 'regression':
        assert actual['effect:0'] == '测量指标'
        assert actual['effect:1'] == '研究分组: Group 1 / reference Group 0'


@pytest.mark.parametrize('kind', ['line', 'bar', 'violin'])
def test_projection_family_axes_and_legend_use_column_aliases(kind):
    config = {'figure_kind': kind, 'language': 'en', 'style': {'aliases': {'E': 'Value alias', 'I': 'Arm alias'}},
              'projection': {'x_column': 'I', 'category_column': 'I', 'group_column': 'I', 'y_column': 'E', 'bar_stat': 'mean'}}
    payload = {'figure_kind': kind, 'language': 'en', 'labels': {'title': 'Title', 'x_label': '', 'y_label': '', 'caption': ''}}
    actual, _ = presentation.enrich_material(payload, {}, config=config, result={}, projection={'series': [{'group': 'Group 0'}]},
                                             fields={'E': {'name': 'Measurement', 'unit': 'mm'}, 'I': {'name': 'Group'}}, contract=3)
    assert actual['presentation']['axes']['x']['label'] == 'Arm alias'
    assert actual['presentation']['axes']['y']['label'] == 'Value alias (mm)'
    assert actual['presentation']['legend']['title'] == 'Arm alias'
    assert actual['presentation']['legend']['entries'][0]['label'] == 'Group 0'


def test_explanation_version_upgrade_keeps_historical_v2_binding():
    from app.domain.figure_workbench.explanations import version_for
    assert version_for({'engine': {'id': 'openai_figure_workbench_v2'}, 'presentation': {'schema_version': 1}}) == 'figure_explanation_v2'
    assert version_for({'engine': {'id': 'openai_figure_workbench_v3'}, 'presentation': {'schema_version': 2}}) == 'figure_explanation_v5'


def test_prompt_rejects_noninteger_or_unknown_presentation_version():
    from app.core.exceptions import StorageError
    for version in (True, 1.0, '2', 4):
        with pytest.raises(StorageError):
            tasks.prompt_version({'presentation': {'schema_version': version}})


@pytest.mark.parametrize('version', [2, 3])
def test_projection_source_audit_binds_actual_version_and_all_frozen_sources(version):
    from app.adapters.figure_workbench_store import projection_request_digest
    from app.maintenance.dataset_source_audit import validate_projection_v2_source
    from types import SimpleNamespace
    result = {'id': 'run', 'source': {'id': 'data'}, 'analysis_plan': {'sha256': 'plan'}, 'check': {'valid_count': 2}}
    source = {'source': result['source'], 'analysis_plan': result['analysis_plan'], 'result_sha256': digest(result), 'figure_contract': version}
    config = {'id': 'config', 'config_json': {'language': 'en'}, 'source_json': source, 'created_by': 'owner', 'project_id': 'project', 'analysis_run_id': 'run'}
    config['sha256'] = digest({'config': config['config_json'], 'source': source})
    snapshot = {'projection_execution': 2, 'result': result, 'output_language': 'en', 'figure_workbench': {'version_id': 'config', 'configuration_sha256': config['sha256']}}
    task = {'id': 'task', 'project_id': 'project', 'user_id': 'owner', 'input_digest': projection_request_digest(config), 'input_snapshot': snapshot, 'workflow_version': 'figure_projection_v2'}
    checkpoint = {'next_node': 'check', 'state_json': {'version_id': 'config', 'request_sha256': task['input_digest'], 'check': None, 'payload': None, 'expected': None, 'material_sha256': None}}
    def database(row):
        return SimpleNamespace(execute=lambda sql, _: SimpleNamespace(fetchone=lambda: row if 'figure_config_versions' in sql else checkpoint))
    validate_projection_v2_source(database(config), task, snapshot, result)
    for key, value in [('sha256', 'wrong'), ('project_id', 'other'), ('analysis_run_id', 'other'), ('created_by', 'other')]:
        with pytest.raises(ValueError):
            validate_projection_v2_source(database({**config, key: value}), task, snapshot, result)
    for value in (True, '3', 4):
        changed = deepcopy(config); changed['source_json']['figure_contract'] = value
        with pytest.raises(ValueError):
            validate_projection_v2_source(database(changed), task, snapshot, result)
    changed = deepcopy(config); changed['source_json']['result_sha256'] = 'wrong'
    changed['sha256'] = digest({'config': changed['config_json'], 'source': changed['source_json']})
    with pytest.raises(ValueError):
        validate_projection_v2_source(database(changed), task, snapshot, result)
