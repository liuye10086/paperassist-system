"""Reader-facing narrative contracts for saved single-cell results.

The narrative is a presentation layer over frozen facts. It never replaces
the source manifest, result tables, figures, or their traceability records.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


NARRATIVE_FIELDS = (
    "abstract",
    "design_and_data",
    "quality_control",
    "methods_summary",
    "key_findings",
    "limitations",
    "reader_cautions",
)
PROMPT_VERSION = "single-cell-reader-report-v1"
_LANGUAGES = {"zh-CN", "en"}
_SHA = re.compile(r"(?i)(?:sha(?:256)?\s*[:=]?\s*)?[0-9a-f]{64}")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.I)
_FORBIDDEN = re.compile(r"(?i)(?:```|\b(?:result_id|source_id|task_id|manifest_sha256|content_sha256|input_sha256)\b)")
_TEXT_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.I)
_TEXT_HASH = re.compile(r"\b[0-9a-f]{64}\b", re.I)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _safe_scalar(value):
    if isinstance(value, str):
        return _TEXT_HASH.sub("[redacted hash]", _TEXT_UUID.sub("[redacted identifier]", value))
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return None


def _strip_identity(value, depth=0):
    if depth > 3:
        return None
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(token in key_text for token in ("id", "sha", "digest", "hash", "path", "object_key", "filename")):
                continue
            cleaned = _strip_identity(item, depth + 1)
            if cleaned is not None:
                result[key] = cleaned
        return result
    if isinstance(value, list):
        return [_strip_identity(item, depth + 1) for item in value[:20]]
    return _safe_scalar(value)


def build_reader_payload(identifier, config, manifest, tables):
    """Build a bounded, identity-free fact payload for the language model."""
    summary = _strip_identity(manifest.get("summary", {})) or {}
    methods = _strip_identity(manifest.get("methods", {})) or {}
    method_config = _strip_identity(config) or {}
    rows = {}
    for key, raw in (tables or {}).items():
        items = raw.get("rows", []) if isinstance(raw, dict) else raw
        rows[key] = {
            "total": raw.get("total", len(items)) if isinstance(raw, dict) else len(items),
            "rows": _strip_identity(items) or [],
        }
    return {
        "report_kind": config.get("method") or config.get("kind") or "single_cell",
        "language": config.get("output_language", "zh-CN"),
        "study_design": _strip_identity({
            key: config.get(key)
            for key in ("purpose", "mode", "inference_scope", "independence_basis", "label_basis", "contrasts")
            if config.get(key) is not None
        }) or {},
        "summary": summary,
        "methods": methods,
        "method_configuration": method_config,
        "warnings": _strip_identity(manifest.get("warnings", [])) or [],
        "limitations": _strip_identity(manifest.get("limitations", [])) or [],
        "result_tables": rows,
        "fact_scope": "Values and statuses are frozen observations; unsupported interpretation is prohibited.",
    }


def validate_reader_narrative(value, language):
    if language not in _LANGUAGES or not isinstance(value, dict):
        raise ValueError("Invalid reader narrative language or shape")
    if set(value) != set(NARRATIVE_FIELDS):
        raise ValueError("Reader narrative fields are incomplete")
    checked = {}
    for field in NARRATIVE_FIELDS:
        text = value[field]
        if not isinstance(text, str) or not text.strip() or len(text) > 12000:
            raise ValueError("Reader narrative text is invalid")
        if _SHA.search(text) or _UUID.search(text) or _FORBIDDEN.search(text):
            raise ValueError("Reader narrative contains traceability or code content")
        if text.lstrip().startswith(("{", "[")):
            raise ValueError("Reader narrative contains JSON")
        checked[field] = text.strip()
    return checked


def narrative_cache_path(root, project_id, result_id, language):
    if language not in _LANGUAGES:
        raise ValueError("Unsupported narrative language")
    for value in (project_id, result_id):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
            raise ValueError("Unsafe narrative identity")
    return Path(root).resolve() / "bio-reader-narratives" / project_id / result_id / f"{language}.json"


def load_cached_narrative(root, project_id, result_id, language):
    path = narrative_cache_path(root, project_id, result_id, language)
    if not path.is_file():
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    record["narrative"] = validate_reader_narrative(record.get("narrative"), language)
    if record.get("narrative_sha256") != _digest(record["narrative"]):
        raise ValueError("Reader narrative digest mismatch")
    return record


def save_cached_narrative(root, project_id, result_id, language, record):
    narrative = validate_reader_narrative(record.get("narrative"), language)
    value = {
        "schema_version": 1,
        "language": language,
        "result_id": result_id,
        "input_sha256": record["input_sha256"],
        "model": record.get("model", "unknown"),
        "prompt_version": record.get("prompt_version", PROMPT_VERSION),
        "generated_at": record.get("generated_at") or datetime.now(timezone.utc).isoformat(),
        "narrative": narrative,
        "narrative_sha256": _digest(narrative),
        "provider_response_id": record.get("provider_response_id"),
    }
    path = narrative_cache_path(root, project_id, result_id, language)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".writing")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def _instructions(language):
    if language == "zh-CN":
        return (
            "你是科研报告编辑。只根据输入的冻结事实生成面向读者的中文科研报告段落。"
            "不得改变或补造任何数字、P值、供者数、样本数、方法状态或限制；不得声称因果、临床意义或生物学验证。"
            "证据不足、未计算或标签未验证必须明确写出。只返回一个 JSON 对象，字段必须正好是："
            + ",".join(NARRATIVE_FIELDS)
            + "。每个字段是自然语言段落或短句，不要 Markdown、代码、ID、哈希或 JSON 字符串。"
        )
    return (
        "You are a scientific report editor. Write reader-facing English paragraphs using only the frozen facts in the input. "
        "Do not change or invent numbers, p-values, donor/sample counts, method status, or limitations; do not claim causality, clinical meaning, or biological validation. "
        "State insufficient evidence, non-computable results, and unvalidated labels explicitly. Return one JSON object with exactly these fields: "
        + ",".join(NARRATIVE_FIELDS)
        + ". Each field must be natural-language prose or short sentences; no Markdown, code, IDs, hashes, or JSON strings."
    )


def generate_reader_narrative(payload, language, *, provider, model=None):
    if not callable(provider):
        raise ValueError("A model provider callable is required")
    input_sha256 = _digest(payload)
    raw = provider(instructions=_instructions(language), payload=payload, language=language, model=model)
    if isinstance(raw, str):
        raw = json.loads(raw)
    narrative = validate_reader_narrative(raw, language)
    return {
        "input_sha256": input_sha256,
        "model": model or "unknown",
        "prompt_version": PROMPT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "narrative": narrative,
        "narrative_sha256": _digest(narrative),
    }
