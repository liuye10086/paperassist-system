"""Offline execution boundary tests; database/queue integration is separate."""
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_candidate_member_ids_and_bytes_are_stable(tmp_path):
    from app.adapters.bio_dataset_execution import build_candidate
    from app.adapters.bio_parser.visium import parse_visium_bundle
    from app.domain.bioinformatics.settings import BioLimits
    from tests.helpers.bio_fixtures import visium_bundle_bytes
    task = {"id": "task", "input_digest": "a" * 64,
            "input_snapshot": {"import_id": "09ecb24d-64b6-471f-b3a9-9371ee2eaf09", "files": [{"id": "raw"}]}}
    result = parse_visium_bundle(visium_bundle_bytes(), tmp_path / "first", BioLimits()).summary()
    # The pure parser has no registered file ID; trusted execution assigns it.
    for out in result["outputs"]:
        out["source_file_id"] = "raw"
    result["manifest"]["members"] = [{k: v for k, v in o.items() if k != "path"} for o in result["outputs"]]
    from app.adapters.bio_objects import BioObjects
    objects = BioObjects(tmp_path / "assets")
    candidate, leaves = build_candidate(task, result, objects)
    repeated, _ = build_candidate(task, result, objects)
    assert candidate == repeated
    assert candidate["summary"] == {"features": 3, "observations": 2, "stored_entries": 4}
    assert len({m["id"] for m in candidate["members"]}) == len(result["outputs"])
    assert all(m["source_file_id"] == "raw" for m in candidate["members"])
    assert str(tmp_path) not in str(candidate)
    assert all("path" in leaf for leaf in leaves)


def test_execution_uses_isolated_parser_only_for_check(tmp_path, monkeypatch):
    from app.domain.bioinformatics import execution
    calls = []
    task = {"id": "t", "input_snapshot": {"parser_version": "geo_visium_import_v1", "settings": {}}}
    checkpoint = {"next_node": "check"}
    class Repository:
        assets = SimpleNamespace(directory=tmp_path)
        def __init__(self, **kwargs): pass
        def claim(self, *args, **kwargs): calls.append(("claim", kwargs)); return "lease"
        def heartbeat(self, lease): return True
        def fail(self, lease, code): calls.append(("fail", code)); return "failed"
    class Store:
        def __init__(self, repository): pass
        def load(self, lease): return task, checkpoint, [{"id": "raw", "path": "trusted"}]
        def wait(self, lease, current, result): calls.append(("wait", current, result)); return "waiting"
    def parser(manifest, output, settings):
        calls.append(("parser", manifest, Path(output).is_dir()))
        return {"manifest": {}}
    monkeypatch.setattr(execution, "TaskExecutionStore", Repository)
    monkeypatch.setattr(execution, "BioDatasetExecution", Store)
    assert execution.run_bio_import_task("t", 1, directory=tmp_path, parser=parser) == "waiting"
    assert calls[0] == ("claim", {"task_type": "bio_import"})
    assert calls[1][0] == "parser" and calls[1][1]["files"][0]["path"] == "trusted" and calls[1][2]
    assert calls[2][0] == "wait"


def test_execution_publish_does_not_reparse_and_lost_lease_stops(tmp_path, monkeypatch):
    from app.domain.bioinformatics import execution
    calls = []
    class Repository:
        assets = SimpleNamespace(directory=tmp_path)
        def __init__(self, **kwargs): pass
        def claim(self, *args, **kwargs): return "lease"
        def heartbeat(self, lease): return True
        def fail(self, lease, code): calls.append(("fail", code)); return "failed"
    class Store:
        def __init__(self, repository): pass
        def load(self, lease): return {"id": "t"}, {"next_node": "publish"}, []
        def publish(self, lease, checkpoint): calls.append("publish"); return "done"
    monkeypatch.setattr(execution, "TaskExecutionStore", Repository)
    monkeypatch.setattr(execution, "BioDatasetExecution", Store)
    def parser(*args): pytest.fail("accepted candidate must not be reparsed")
    assert execution.run_bio_import_task("t", 1, directory=tmp_path, parser=parser) == "done"
    assert calls == ["publish"]
    def lost(self, lease): raise execution.LeaseLost()
    monkeypatch.setattr(Store, "load", lost)
    assert execution.run_bio_import_task("t", 1, directory=tmp_path, parser=parser) is None
    assert calls == ["publish"]
