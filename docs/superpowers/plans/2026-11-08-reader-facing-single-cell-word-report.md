# 面向读者的单细胞 Word 报告实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or superpowers:subagent-driven-development) to implement this plan task-by-task.

**Goal:** 为单细胞结果生成中英文读者版 DOCX，正文使用受事实约束的自然语言；追溯字段保留在叙述缓存和工程回执中，不写入 Word；并用本机真实模型生成当前固定结果的叙述缓存。

**Architecture:** 新增独立的读者叙述模块，接收裁剪后的结构化事实并通过 OpenAI Responses 生成严格 JSON；叙述按结果版本和语言缓存到验收资产目录。现有单细胞 Word 适配器读取缓存，将正文、关键结果和图件组合成 DOCX；下载接口不发起模型请求。

**Tech Stack:** Python 3.11、OpenAI Responses SDK、python-docx、PostgreSQL 现有只读结果存储、pytest、LibreOffice/render_docx.py。

## Global Constraints

- 中英文同时生成；真实模型只使用 `backend/.env` 的本机配置。
- 不上传 FASTQ，不调用阿里云/EasyGene，不修改原始结果、manifest、图件或数据库结果版本。
- 模型不得改变任何数值或事实；模型失败时不发布新读者版缓存。
- DOCX-only；不生成 PDF。
- 继续保留现有工作树改动；不提交、不推送、不部署。
- 验收服务只在生成和验证完成后启动，并保持运行等待用户检查。

---

### Task 1: 建立读者叙述合同与缓存模块

**Files:**
- Create: `backend/app/adapters/bio_reader_narrative.py`
- Test: `backend/tests/domain/test_bio_reader_narrative.py`

**Interfaces:**
- `build_reader_payload(identifier, config, manifest, tables) -> dict`
- `validate_reader_narrative(value, language) -> dict`
- `narrative_cache_path(root, project_id, result_id, language) -> Path`
- `load_cached_narrative(root, project_id, result_id, language) -> dict | None`
- `save_cached_narrative(root, project_id, result_id, language, record) -> Path`

- [ ] **Step 1: Write failing tests**

```python
from app.adapters.bio_reader_narrative import validate_reader_narrative


def test_reader_contract_rejects_hashes_and_json():
    value = {key: "自然语言段落" for key in (
        "abstract", "design_and_data", "quality_control", "methods_summary",
        "key_findings", "limitations", "reader_cautions")}
    value["key_findings"] = "result_id abc123"
    with pytest.raises(ValueError):
        validate_reader_narrative(value, "zh-CN")


def test_reader_contract_accepts_bilingual_natural_language():
    value = {key: "This is a reader-facing paragraph." for key in (
        "abstract", "design_and_data", "quality_control", "methods_summary",
        "key_findings", "limitations", "reader_cautions")}
    assert validate_reader_narrative(value, "en")["abstract"] == value["abstract"]
```

- [ ] **Step 2: Run tests and verify the contract is missing**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/domain/test_bio_reader_narrative.py -q`
Expected: FAIL because the module and validator do not exist.

- [ ] **Step 3: Implement the minimal contract and cache helpers**

Use a fixed field tuple, require non-empty strings, reject code fences, JSON-looking blocks, SHA-256 patterns, UUID-like IDs, and `result_id`/`source_id`/`manifest` tokens in narrative fields. Cache records must include `schema_version`, `language`, `result_id`, `input_sha256`, `model`, `prompt_version`, `generated_at`, `narrative`, and `narrative_sha256`; write through a temporary sibling file and replace atomically.

- [ ] **Step 4: Run the tests**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/domain/test_bio_reader_narrative.py -q`
Expected: PASS.

---

### Task 2: Add strict model generation for the curated fact payload

**Files:**
- Modify: `backend/app/adapters/bio_reader_narrative.py`
- Test: `backend/tests/domain/test_bio_reader_narrative.py`
- Create: `script/generate_single_cell_reader_narratives.py`

**Interfaces:**
- `generate_reader_narrative(payload, language, *, provider=None, model=None) -> dict`
- Script arguments: `--project-id`, `--result-id`, `--data-root`, `--output-root`, `--languages zh-CN en`.

- [ ] **Step 1: Add fake-provider tests**

Test that the provider receives only the curated payload, that valid JSON is accepted, invalid JSON is rejected, and the returned record contains an input digest and narrative digest.

- [ ] **Step 2: Run the new tests to verify failure**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/domain/test_bio_reader_narrative.py -q`
Expected: FAIL for the missing generation function.

- [ ] **Step 3: Implement generation**

Use the configured `OPENAI_API_KEY`/`OPENAI_API_KEY_FILE`, `OPENAI_MODEL` (default `gpt-6.1-sol`), and official Responses endpoint through the existing provider boundary. Send a prompt that forbids IDs, hashes, JSON, unsupported numbers, causal claims, and invented biological interpretation. Parse the response as JSON, validate all fields, and return a cache record. The script must read existing result objects, build the curated payload for both languages, call the model once per language, and write only narrative cache files plus a redacted receipt; it must never modify database rows or original result files.

- [ ] **Step 4: Run offline tests**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/domain/test_bio_reader_narrative.py -q`
Expected: PASS with fake provider and no network.

- [ ] **Step 5: Run the real generation only after configuration check**

Run the script for the fixed result `dba8e833-697b-583a-a1d6-7c0e9896de87` and project `aff66334-4b3e-4897-8031-54f89ac42528`, with the acceptance assets root. Expected: two successful narrative cache records, one `zh-CN` and one `en`, with model name and hashes recorded but no key output.

---

### Task 3: Restructure the DOCX body

**Files:**
- Modify: `backend/app/adapters/single_cell_insight_report.py`
- Test: `backend/tests/domain/test_single_cell_insight_report.py`
- Test: `backend/tests/domain/test_single_cell_topic_report.py`

**Interfaces:**
- Extend `build_single_cell_insight_report(identifier, manifest_sha256, config, manifest, tables, figures, *, narrative=None)`.

- [ ] **Step 1: Add failing DOCX assertions**

Assert that with a valid narrative the body sections contain the natural-language fields and that result IDs, UUIDs, SHA-256, JSON and appendix headings do not occur anywhere in the DOCX.

- [ ] **Step 2: Run the focused tests**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/domain/test_single_cell_insight_report.py backend/tests/domain/test_single_cell_topic_report.py -q`
Expected: FAIL on the new body-only assertions.

- [ ] **Step 3: Implement the reader-facing layout**

Add title, abstract, design/data, quality control, methods summary, key findings, limitations and reader cautions from `narrative`; show concise saved result tables and figures; omit engineering identifiers, hashes, JSON parameters, source bindings and model provenance from the DOCX. Keep those fields in the cache and engineering receipt. With no narrative, retain a deterministic natural-language fallback only for offline unit fixtures and label it as non-model text; the real download path must require the generated cache.

- [ ] **Step 4: Run focused tests**

Run the same pytest command. Expected: PASS, including all existing numeric and topic assertions that check saved values.

---

### Task 4: Wire cache loading into the download path without network calls

**Files:**
- Modify: `backend/app/adapters/single_cell_insight_report.py`
- Modify: `backend/app/api/bio_insights.py` only if the loader needs an explicit root
- Test: `backend/tests/api/test_bio_insight_reproducibility.py` or a focused new API test

**Interfaces:**
- `download_single_cell_insight_report(..., narrative_root=None)` loads both the configured language cache and passes it to the builder.

- [ ] **Step 1: Add a test that download/build uses a cache and never calls a provider**

Provide a temporary cache under the test asset root, request a report, and assert the DOCX contains the cached abstract and no appendix heading or engineering identifiers. Monkeypatch any model generator to raise if called.

- [ ] **Step 2: Implement the loader**

Use the same data root visible to the API/worker (`store.assets.directory`), resolve the cache by project/result/language, and raise a controlled `bio_insight_reader_narrative_missing` error if the result is in the real reader-report mode but no cache exists. Do not add network calls to the endpoint.

- [ ] **Step 3: Run the focused API and domain tests**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/domain/test_single_cell_insight_report.py backend/tests/domain/test_single_cell_topic_report.py backend/tests/api/test_bio_insight_reproducibility.py -q`
Expected: PASS.

---

### Task 5: Generate, render, inspect, and start acceptance service

**Files:**
- Create/update ignored receipts under `script/.runtime/local-engineering-closeout/`
- Create/update generated Word files under `script/.runtime/local-engineering-closeout/word-reader-facing/`

- [ ] **Step 1: Run real model generation for both languages**

Use the configured local key, fixed result and acceptance asset root. Save redacted generation receipt, model name, prompt version, input digest, output digest, timestamps and failure status.

- [ ] **Step 2: Download/regenerate both DOCX files through the updated path**

Generate the Chinese and English Word reports from the fixed result without PDF output. Confirm existing source/result files remain byte-identical.

- [ ] **Step 3: Render DOCX and inspect representative pages**

Run `render_docx.py` without `--emit_pdf`; inspect title/abstract, methods, findings and figures for clipping, overlap, blank pages and raw JSON or identifiers in the body.

- [ ] **Step 4: Run final verification**

Run focused pytest, `git diff --check`, JSON receipt parse, and health checks. Record real model call count separately from offline tests.

- [ ] **Step 5: Start the acceptance service**

Start `paperassist-single-cell-acceptance`, verify HTTP 200 and browser download of the updated Word. Leave services running for user acceptance; do not stop or start another batch.


## 当前用户决定

2026-11-08：Word 只输出正文，不再生成追溯附录；追溯字段保留在叙述缓存、原始结果和工程回执。
