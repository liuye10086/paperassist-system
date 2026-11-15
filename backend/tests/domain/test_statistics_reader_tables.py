import csv
import io
import json
from types import SimpleNamespace

import pytest

from app.domain.research_results.statistics_package import statistics_reproduction_files
from app.domain.statistics_reader_reports.tables import result_tables


LANGUAGES = ('zh-CN', 'en')


def reader_rows(content, language):
    source = SimpleNamespace(source_id='saved-run', content=content)
    tables = {}
    for metadata, raw in result_tables(source, 1, language):
        rows = csv.reader(io.StringIO(raw.decode('utf-8')), delimiter='\t')
        next(rows)
        tables[metadata['key']] = {measure: (value, unit, availability) for measure, value, unit, availability in rows}
    return tables


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize(('zh_label', 'en_label', 'value'), [
    ('残差标准差', 'Residual SD', '1.25'),
    ('模型诊断 · 残差 · 第 1 项', 'Model diagnostics · Residuals · Item 1', '0.0'),
    ('模型诊断 · 残差 · 第 2 项', 'Model diagnostics · Residuals · Item 2', '-1.25'),
    ('模型诊断 · 拟合值 · 第 1 项', 'Model diagnostics · Fitted values · Item 1', '0.0'),
    ('模型诊断 · 拟合值 · 第 2 项', 'Model diagnostics · Fitted values · Item 2', '12.5'),
])
def test_ols_outcome_units_in_reader_table(language, zh_label, en_label, value):
    en = language == 'en'
    result = {
        'selection': {'task_type': 'regression', 'method': 'ols', 'outcome_unit': 'mmHg'},
        'statistics': {'residual_sd': 1.25, 'diagnostics': {'residuals': [0.0, -1.25], 'fitted': [0.0, 12.5]}},
    }
    rows = reader_rows({'result': result}, language)['Run 01 Statistics' if en else '分析01 统计结果']
    assert rows[en_label if en else zh_label] == (value, 'mmHg', '')


@pytest.mark.parametrize('language', LANGUAGES)
def test_logistic_diagnostics_and_missing_residual_sd_stay_unitless(language):
    en = language == 'en'
    result = {
        'selection': {'task_type': 'regression', 'method': 'logistic', 'outcome_unit': 'mmHg'},
        'statistics': {'residual_sd': None, 'diagnostics': {'residuals': [-0.25], 'fitted': [0.25]}},
    }
    rows = reader_rows({'result': result}, language)['Run 01 Statistics' if en else '分析01 统计结果']
    assert rows['Residual SD' if en else '残差标准差'] == (
        'NA', '', 'Unavailable or not applicable' if en else '未提供或不适用',
    )
    assert rows['Model diagnostics · Residuals · Item 1' if en else '模型诊断 · 残差 · 第 1 项'] == ('-0.25', '', '')
    assert rows['Model diagnostics · Fitted values · Item 1' if en else '模型诊断 · 拟合值 · 第 1 项'] == ('0.25', '', '')


@pytest.mark.parametrize('language', LANGUAGES)
def test_frozen_role_audit_reads_as_plain_language_and_reproduction_retains_origin(language):
    en = language == 'en'
    origin = 'reconstructed_from_frozen_source_not_a_new_test'
    result = {'selection': {'task_type': 'descriptive_boxplot', 'data_roles': {'observation_unit': 'sample'}},
              'source': {'dataset_id': 'prepared-data'}}
    audit = {'origin': origin, 'included_rows': [2], 'excluded_rows': [{'row': 3, 'reason': 'selected_missing'}]}
    content = {'result': result, 'frozen_role_audit': audit}
    tables = reader_rows(content, language)
    rows = tables['Run 01 Role audit' if en else '分析01 角色纳入明细']
    assert origin not in json.dumps(tables)
    assert rows['Audit source' if en else '明细来源'] == (
        'Inclusion details were reconstructed from the frozen source. No new test was performed.' if en
        else '基于固定来源重建纳入明细，未执行新检验。', '', '',
    )
    assert rows['Included rows · Item 1' if en else '纳入行 · 第 1 项'] == ('2', '', '')
    assert rows['Excluded rows · Item 1 · Original row number' if en else '排除行 · 第 1 项 · 原表行号'] == ('3', '', '')
    files = statistics_reproduction_files([dict(source_kind='analysis_run', source_id='saved-run', content=content)])
    frozen_source = next(item['raw'] for item in files if item['name'].endswith('/frozen_source.json'))
    assert json.loads(frozen_source)['content']['frozen_role_audit']['origin'] == origin


@pytest.mark.parametrize('language', LANGUAGES)
def test_survival_probability_label_is_distinct_from_analysis_type(language):
    en = language == 'en'
    result = {
        'selection': {'task_type': 'survival', 'method': 'kaplan_meier', 'time_unit': 'months'},
        'statistics': {'groups': [{'label': 'A', 'points': [{'time': 6.0, 'survival': 0.0}]}]},
    }
    tables = reader_rows({'result': result}, language)
    settings = tables['Run 01 Analysis settings' if en else '分析01 分析选项']
    rows = tables['Run 01 Statistics' if en else '分析01 统计结果']
    assert settings['Analysis type' if en else '分析类型'] == ('Survival analysis' if en else '生存分析', '', '')
    assert rows['Group · A · Points · Item 1 · Survival probability' if en else '分组 · A · 数据点 · 第 1 项 · 生存概率'] == ('0.0', '', '')
    assert rows['Group · A · Points · Item 1 · Time' if en else '分组 · A · 数据点 · 第 1 项 · 时间'] == ('6.0', 'months', '')
