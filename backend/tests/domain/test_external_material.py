"""Confirmed labels replace all generated text without changing observations."""
import copy
import importlib.util
import json

import pytest

from app.core.exceptions import StorageError
from app.domain.external_processing import disclosure, freeze_confirmation
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud, prepared, generate  # noqa: F401


def sources(client):
    _, _, result, url = prepared(client)
    result = copy.deepcopy(result)
    result['numeric_name'] = 'PRIVATE_NUMERIC_SENTINEL'
    result['group_name'] = 'PRIVATE_GROUP_SENTINEL'
    result['selection']['sheet_name'] = 'PRIVATE_SHEET_SENTINEL'
    result['selection']['unit'] = 'PRIVATE_UNIT_SENTINEL'
    figure = generate(client, url)
    snapshot = {'result': result, 'file': {'id': 'private-file'}, 'figure': figure,
                'versions': {'figure': 'v1'}, 'output_language': 'zh-CN'}
    return result, figure, snapshot


def frozen(snapshot, task_type):
    preview = disclosure(snapshot, task_type, 'owner')
    labels = {item['key']: item['value'] for item in preview['labels']}
    labels.update(numeric_name='指标甲', unit='单位甲', group_name='组别甲')
    labels.update({key: f'匿名组{index}' for index, key in enumerate(labels) if key.startswith('group:')})
    if task_type == 'explanation':
        labels['figure_title'] = '匿名图标题'
    return freeze_confirmation(snapshot, task_type, 'owner',
        {'version': 1, 'confirmed': True, 'source_digest': preview['source_digest'], 'labels': labels})


def test_plot_material_preserves_exact_values_and_removes_private_text(client, cloud):
    assert importlib.util.find_spec('app.domain.external_material') is not None
    from app.domain.external_material import plot_material, plot_instructions
    result, figure, snapshot = sources(client)
    external = frozen(snapshot, 'boxplot')
    original = {'analysis_run_id': result['id'], 'source_sha256': result['source_sha256'],
                'values': [1, 2, 3], 'groups': [{'label': group['label'], 'values': [index + 1]}
                                              for index, group in enumerate(result['groups'])]}
    expected = {'analysis_run_id': result['id'], 'source_sha256': result['source_sha256'],
                **{key: figure[key] for key in ('title', 'x_label', 'y_label', 'caption', 'series')},
                'groups': result['groups'], 'overall': result['overall']}
    payload, remote_expected = plot_material(result, original, expected, external)
    assert set(payload) == {'labels', 'values', 'groups'}
    assert payload['values'] == original['values']
    assert [group['values'] for group in payload['groups']] == [group['values'] for group in original['groups']]
    assert 'PRIVATE_' not in json.dumps(payload, ensure_ascii=False)
    assert 'analysis_run_id' not in remote_expected and 'source_sha256' not in remote_expected
    assert 'analysis_run_id' not in plot_instructions(external)
    assert 'source_sha256' not in plot_instructions(external)
    assert plot_material(result, original, expected, None) == (original, expected)


def test_explanation_material_uses_aliases_for_facts_and_evidence(client, cloud):
    assert importlib.util.find_spec('app.domain.external_material') is not None
    from app.domain.external_material import explanation_material
    from app.domain.explanation_content import render_explanation
    from tests.domain.test_explanation_content import valid_draft
    result, figure, snapshot = sources(client)
    local, outbound = explanation_material(result, figure, frozen(snapshot, 'explanation'))
    assert 'sheet' not in local['facts']
    assert 'sheet' not in local['required_references']['data']
    assert 'PRIVATE_' not in json.dumps(outbound, ensure_ascii=False)
    assert not {'analysis_run_id', 'figure_id', 'source_sha256', 'figure_sha256'} & set(outbound)
    assert local['analysis_run_id'] == result['id']
    rendered = render_explanation(valid_draft(local), local)
    assert '指标甲' in rendered[0]['text']
    assert local['facts']['figure.title']['value'] == '匿名图标题'
    for index, group in enumerate(result['groups']):
        assert local['facts'][f'groups.{index}.n']['raw'] == group['statistics']['n']


def test_unknown_missing_duplicate_labels_and_client_time_are_rejected(client, cloud):
    _, _, snapshot = sources(client)
    preview = disclosure(snapshot, 'boxplot', 'owner')
    base = {'version': 1, 'confirmed': True, 'source_digest': preview['source_digest'],
            'labels': {item['key']: item['value'] for item in preview['labels']}}
    changes = [lambda c: c.update(confirmed_at='2000-01-01'),
               lambda c: c['labels'].update(unknown='x'),
               lambda c: c['labels'].pop('numeric_name'),
               lambda c: c['labels'].update({'group:0': 'same', 'group:1': 'same'})]
    for change in changes:
        candidate = copy.deepcopy(base)
        change(candidate)
        with pytest.raises(StorageError) as error:
            freeze_confirmation(snapshot, 'boxplot', 'owner', candidate)
        assert error.value.code == 'task_input_invalid'
