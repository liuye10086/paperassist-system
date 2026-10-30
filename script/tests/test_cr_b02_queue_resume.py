"""A resumed acceptance run must not wait for a completed QC transition."""
import importlib.util
from pathlib import Path


def verification(progress):
    source = Path(__file__).resolve().parents[1] / 'verify_cr_b02_queue.py'
    spec = importlib.util.spec_from_file_location('queue_resume_contract', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    value = object.__new__(module.Verification)
    value.progress = progress
    return value


def test_completed_v2_import_reuses_saved_source_before_reading_mutable_revision():
    source = {'dataset_id': 'raw-root', 'dataset_version_id': 'raw-version'}
    value = verification({'import-v2': {'result_source': source}})
    assert value.import_raw([], version2=True, original=None) == source


def test_completed_analysis_reuses_published_result_without_reconfirming():
    result = {'id': 'processed-version'}
    value = verification({'analysis': {'result': result}})
    assert value.run_analysis({}, None, {}) == result
