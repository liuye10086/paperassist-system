"""Generate reader-facing narratives for a retained single-cell result.

The script reads the frozen local manifest and result tables, sends only a bounded
identity-free fact payload to the configured OpenAI Responses endpoint, validates
the structured prose, and writes language-specific narrative caches next to the
acceptance assets. It never changes the database or the original result members.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.adapters.bio_reader_narrative import (  # noqa: E402
    NARRATIVE_FIELDS,
    _instructions,
    build_reader_payload,
    generate_reader_narrative,
    save_cached_narrative,
)
from app.core.config import local_config  # noqa: E402


ALLOWED_TABLES = {
    "trajectory_results",
    "regulation_results",
    "communication_units",
    "communication_results",
    "communication_comparisons",
    "composition_units",
    "composition_counts",
    "composition_results",
    "aggregation_units",
    "comparison_results",
    "enrichment_results",
}


def _member_path(result_dir: Path, member: dict) -> Path:
    matches = list(result_dir.glob(str(member["sha256"]) + ".*"))
    if len(matches) != 1:
        raise RuntimeError(f"member file is not uniquely available: {member.get('key')}")
    return matches[0]


def _load_tables(result_dir: Path, manifest: dict) -> dict:
    tables: dict[str, dict] = {}
    for member in manifest.get("members", []):
        key = member.get("key")
        fmt = member.get("format")
        if key == "ora_sets" and fmt == "json":
            data = json.loads(_member_path(result_dir, member).read_text(encoding="utf-8"))
            families = data.get("families", [])
            tables["ora_background"] = {
                "rows": [{name: family.get(name) for name in ("contrast_id", "N", "n", "resource_id")} for family in families],
                "total": len(families),
            }
            continue
        if key not in ALLOWED_TABLES or fmt not in ("tsv", "csv"):
            continue
        rows: list[dict] = []
        total = 0
        with _member_path(result_dir, member).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t" if fmt == "tsv" else ",")
            for row in reader:
                total += 1
                if len(rows) < 200:
                    rows.append(dict(row))
        tables[key] = {"rows": rows, "total": total}
    return tables


def _api_key(values: dict) -> str:
    key_file = str(values.get("OPENAI_API_KEY_FILE") or "").strip()
    if key_file:
        candidate = (BACKEND / Path(key_file).expanduser()).resolve()
        if not candidate.is_file() or BACKEND not in candidate.parents:
            raise RuntimeError("configured OpenAI key file is unavailable")
        key = candidate.read_text(encoding="utf-8-sig").strip()
    else:
        key = str(values.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("OpenAI is not configured in backend/.env")
    return key


def _provider(api_key: str, response_ids: list[str]):
    client = OpenAI(api_key=api_key, base_url="https://api.openai.com/v1", max_retries=0, timeout=90)
    schema = {
        "type": "object",
        "properties": {field: {"type": "string"} for field in NARRATIVE_FIELDS},
        "required": list(NARRATIVE_FIELDS),
        "additionalProperties": False,
    }

    def call(*, instructions: str, payload: dict, language: str, model: str):
        response = client.responses.create(
            model=model,
            background=False,
            store=True,
            instructions=instructions,
            input=json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False),
            text={"format": {"type": "json_schema", "name": "single_cell_reader_narrative", "strict": True, "schema": schema}},
            max_output_tokens=8000,
        )
        response_ids.append(str(response.id))
        output = response.output_text
        if not output:
            raise RuntimeError("model returned no structured narrative")
        return json.loads(output)

    call.close = client.close  # type: ignore[attr-defined]
    return call


def generate(args) -> dict:
    result_dir = Path(args.data_root).resolve() / "bio-insights" / args.result_id
    manifest_files = list(result_dir.glob("*.json"))
    if len(manifest_files) != 1:
        raise RuntimeError("expected exactly one local result manifest")
    manifest = json.loads(manifest_files[0].read_text(encoding="utf-8"))
    config = dict(manifest.get("methods", {}).get("config", {}))
    tables = _load_tables(result_dir, manifest)
    values = local_config()
    model = str(values.get("OPENAI_MODEL") or "gpt-6.1-sol").strip()
    key = _api_key(values)
    response_ids: list[str] = []
    provider = _provider(key, response_ids)
    records = []
    try:
        for language in args.languages:
            language_config = {**config, "output_language": language}
            payload = build_reader_payload(args.result_id, language_config, manifest, tables)
            record = generate_reader_narrative(payload, language, provider=provider, model=model)
            if response_ids:
                record["provider_response_id"] = response_ids[-1]
            save_cached_narrative(args.output_root, args.project_id, args.result_id, language, record)
            records.append({
                "language": language,
                "input_sha256": record["input_sha256"],
                "narrative_sha256": record.get("narrative_sha256"),
                "provider_response_id": record.get("provider_response_id"),
                "model": model,
                "status": "saved",
            })
    finally:
        provider.close()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_id": args.project_id,
        "result_id": args.result_id,
        "languages": records,
        "fact_tables": sorted(tables),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--result-id", required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--languages", nargs="+", choices=("zh-CN", "en"), default=("zh-CN", "en"))
    parser.add_argument("--receipt", type=Path, default=ROOT / "script/.runtime/local-engineering-closeout/reader-narrative-generation.json")
    args = parser.parse_args()
    receipt = generate(args)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
