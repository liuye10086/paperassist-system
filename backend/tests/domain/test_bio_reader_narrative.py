import json

import pytest


FIELDS = (
    "abstract",
    "design_and_data",
    "quality_control",
    "methods_summary",
    "key_findings",
    "limitations",
    "reader_cautions",
)


def narrative(text="自然语言段落"):
    return {field: text for field in FIELDS}


def test_reader_contract_rejects_hashes_and_json():
    from app.adapters.bio_reader_narrative import validate_reader_narrative

    value = narrative("自然语言段落")
    value["key_findings"] = "result_id abc123"
    with pytest.raises(ValueError):
        validate_reader_narrative(value, "zh-CN")
    value = narrative('{"key":"value"}')
    with pytest.raises(ValueError):
        validate_reader_narrative(value, "zh-CN")


def test_reader_contract_accepts_bilingual_natural_language():
    from app.adapters.bio_reader_narrative import validate_reader_narrative

    value = narrative("This is a reader-facing paragraph.")
    assert validate_reader_narrative(value, "en")["abstract"] == value["abstract"]


def test_payload_removes_identity_fields_and_limits_rows():
    from app.adapters.bio_reader_narrative import build_reader_payload

    manifest = {
        "summary": {"row_count": 2, "result_id": "hidden"},
        "methods": {"name": "cellchat", "source_sha256": "a" * 64},
        "warnings": ["labels are not validated"],
    }
    tables = {"communication_results": {"total": 25, "rows": [{"sender": "T", "source_id": "x"}] * 25}}
    payload = build_reader_payload("result-id", {"kind": "integration", "method": "cellchat"}, manifest, tables)
    text = json.dumps(payload, ensure_ascii=False)
    assert "hidden" not in text and "source_id" not in text and "sha256" not in text.lower()
    assert payload["result_tables"]["communication_results"]["total"] == 25
    assert len(payload["result_tables"]["communication_results"]["rows"]) == 20


def test_generation_uses_curated_payload_and_returns_digest():
    from app.adapters.bio_reader_narrative import generate_reader_narrative

    seen = {}

    def fake_provider(**kwargs):
        seen.update(kwargs)
        return narrative("English reader text.")

    payload = {"report_kind": "cellchat", "result_tables": {"rows": []}}
    record = generate_reader_narrative(payload, "en", provider=fake_provider, model="fake-model")
    assert seen["payload"] == payload
    assert record["model"] == "fake-model"
    assert len(record["input_sha256"]) == 64
    assert record["narrative"]["abstract"] == "English reader text."


def test_cache_round_trip(tmp_path):
    from app.adapters.bio_reader_narrative import load_cached_narrative, save_cached_narrative

    from app.adapters.bio_reader_narrative import _digest

    record = dict(input_sha256="a" * 64, model="fake-model", narrative=narrative())
    path = save_cached_narrative(tmp_path, "project-1", "result-1", "zh-CN", record)
    assert path.is_file()
    loaded = load_cached_narrative(tmp_path, "project-1", "result-1", "zh-CN")
    assert loaded["narrative_sha256"] == _digest(record["narrative"])
def test_bulk_cached_narrative_matches_exact_facts_and_language(tmp_path):
    from app.adapters.bio_reader_narrative import (
        BULK_PROMPT_VERSION, NARRATIVE_FIELDS, load_bulk_cached_narrative, save_cached_narrative,
    )

    facts_sha = 'e' * 64
    cache_id = 'bulk-' + facts_sha
    narrative = {field: 'The interpretation describes the reviewed evidence.' for field in NARRATIVE_FIELDS}
    record = dict(narrative=narrative, input_sha256=facts_sha, prompt_version=BULK_PROMPT_VERSION)
    save_cached_narrative(tmp_path, 'project', cache_id, 'en', record)
    assert load_bulk_cached_narrative(tmp_path, 'project', facts_sha, 'en')['narrative'] == narrative
    assert load_bulk_cached_narrative(tmp_path, 'project', 'a' * 64, 'en') is None
    assert load_bulk_cached_narrative(tmp_path, 'project', facts_sha, 'zh-CN') is None
    save_cached_narrative(tmp_path, 'project', cache_id, 'en', {**record, 'input_sha256': 'b' * 64})
    assert load_bulk_cached_narrative(tmp_path, 'project', facts_sha, 'en') is None
