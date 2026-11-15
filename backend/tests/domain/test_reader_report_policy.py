import json

import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def settings(tmp_path, monkeypatch, allowance=50000, cap=1000000):
    value = {'policy': {'model': 'synthetic-model', 'prompt_version': 'old', 'output_format': 'text',
        'max_output_tokens': 10000, 'timeout_seconds': 45, 'tools': [], 'price': {
        'version': 'test-only', 'model': 'synthetic-model', 'input_micro_usd_per_million': 2000000,
        'cached_input_micro_usd_per_million': 100000, 'output_micro_usd_per_million': 10000000}},
        'input_token_allowance': allowance, 'task_limit_micro_usd': cap}
    path = tmp_path / 'reader-policy.json'; path.write_text(json.dumps(value), encoding='utf-8')
    monkeypatch.setenv('PAPERASSIST_READER_REPORT_POLICY_FILE', str(path))


def test_runtime_enable_gate_does_not_invalidate_paid_response_reuse(tmp_path, monkeypatch):
    from app.domain.reader_reports.policy import bundle
    settings(tmp_path, monkeypatch)
    material = {'language': 'en', 'facts': {'n': 20}, 'figures': []}
    monkeypatch.setenv('PAPERASSIST_READER_REPORT_MODEL_ENABLED', '0'); disabled = bundle(material)
    monkeypatch.setenv('PAPERASSIST_READER_REPORT_MODEL_ENABLED', '1'); enabled = bundle(material)
    assert disabled['bundle_sha256'] == enabled['bundle_sha256']
    assert disabled['input_digest'] == enabled['input_digest']
    assert disabled['real_calls_enabled'] is False and enabled['real_calls_enabled'] is True
    assert enabled['policy']['output_format'] == 'reader_report_v1'
    assert enabled['reserved_micro_usd'] == 200000


@pytest.mark.parametrize('allowance,cap,code', [(1,1000000,'reader_report_input_limit'), (50000,1,'reader_report_budget_limit')])
def test_input_and_task_cap_checked_before_queueing(tmp_path, monkeypatch, allowance, cap, code):
    from app.domain.reader_reports.policy import bundle
    from app.core.exceptions import StorageError
    settings(tmp_path, monkeypatch, allowance, cap)
    with pytest.raises(StorageError) as caught:
        bundle({'language': 'en', 'facts': {'n': 20}, 'figures': []})
    assert caught.value.code == code


@pytest.mark.parametrize('field', ['caption_facts', 'source_caption'])
def test_figure_text_counts_against_policy_while_image_url_is_excluded(tmp_path, monkeypatch, field):
    from app.core.exceptions import StorageError
    from app.domain.reader_reports.policy import bundle

    settings(tmp_path, monkeypatch, allowance=20000)
    figure = {'number': 1, 'title': 'QC', 'image_url': 'data:image/png;base64,' + 'A' * 30000}
    material = {'language': 'en', 'facts': {'n': 20}, 'figures': [figure]}
    assert bundle(material)['input_token_allowance'] == 20000
    text = '每个图件均有实际观察。' * 1000
    figure[field] = [{'limitations': [text]}] if field == 'caption_facts' else text
    with pytest.raises(StorageError) as caught:
        bundle(material)
    assert caught.value.code == 'reader_report_input_limit'
