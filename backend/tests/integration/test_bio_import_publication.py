"""Synthetic end-to-end persistence in the existing random PostgreSQL schema.

The injected pure parser verifies task/storage/confirmation semantics; this is
explicitly separate from a real Linux isolated parser or queue acceptance.
"""
import copy
import sys
from uuid import uuid4

import pytest

from app.db.database import database_connection, migration_connection
from tests.api.test_projects import client, create_project
from tests.helpers.bio_fixtures import visium_bundle_bytes


def create_import(client):
    project = create_project(client)
    base = f"/api/v1/projects/{project['id']}"
    item = str(uuid4())
    content = visium_bundle_bytes()
    batch = client.post(base + "/bio-upload-batches", json={"items": [
        {"client_id": item, "filename": "GSE9999999_RAW.tar", "size_bytes": len(content)}]},
        headers={"Idempotency-Key": "bio-batch"})
    assert batch.status_code == 201, batch.text
    uploaded = client.post(base + f"/bio-upload-batches/{batch.json()['id']}/items/{item}",
                           files={"file": ("GSE9999999_RAW.tar", content)})
    assert uploaded.status_code == 202, uploaded.text
    file_id = uploaded.json()["file_id"]
    request = {"file_ids": [file_id], "assay": "visium", "name": "synthetic counts", "expected_dataset_revision": 0}
    response = client.post(base + "/bio-imports", json=request, headers={"Idempotency-Key": "bio-create"})
    assert response.status_code == 202, response.text
    return base, response.json(), file_id, content


def pure_registered_parser(manifest, output, settings):
    from app.adapters.bio_parser.visium import parse_registered_files
    from app.domain.bioinformatics.settings import BioLimits
    return parse_registered_files(manifest["files"], output, BioLimits.model_validate(settings)).summary()


def run(task, parser=pure_registered_parser):
    from app.domain.bioinformatics.execution import run_bio_import_task
    return run_bio_import_task(task["id"], task["revision"], parser=parser)


def read(client, base, created):
    response = client.get(base + "/bio-imports/" + created["id"])
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client, base, created, view, key="bio-confirm"):
    body = {"task_revision": view["task"]["revision"], "checkpoint_id": view["checkpoint_id"],
            "wait_id": view["wait_id"], "candidate_sha256": view["candidate"]["sha256"],
            "expected_dataset_revision": view["expected_dataset_revision"]}
    return client.post(base + "/bio-imports/" + created["id"] + "/confirm", json=body,
                       headers={"Idempotency-Key": key})


def test_candidate_wait_confirm_publish_and_mmap_preview(client):
    base, created, file_id, original = create_import(client)
    task = run(created["task"])
    assert task["status"] == "waiting_confirmation", task
    view = read(client, base, created)
    assert view["candidate"]["summary"] == {"features": 3, "observations": 2, "stored_entries": 4}
    with database_connection() as db:
        attempt = db.execute("SELECT * FROM task_attempts WHERE task_id=%s", (task["id"],)).fetchone()
        assert attempt["finished_at"] and attempt["lease_owner"] is None
        wait = db.execute("SELECT * FROM task_waits WHERE id=%s", (view["wait_id"],)).fetchone()
        assert wait["kind"] == "bio_import_confirmation"
        assert db.execute("SELECT count(*) AS n FROM storage_reservations WHERE task_id=%s AND state<>'settled'", (task["id"],)).fetchone()["n"] == 0
    queued = confirm(client, base, created, view)
    assert queued.status_code == 202, queued.text
    assert confirm(client, base, created, view).json() == queued.json()
    def forbid_parse(*args): pytest.fail("accepted candidate must not be parsed again")
    done = run(queued.json(), parser=forbid_parse)
    assert done["status"] == "succeeded", done
    published = read(client, base, created)["result_source"]
    version_base = base + f"/bio-datasets/{created['dataset_id']}/versions/{published['dataset_version_id']}"
    manifest = client.get(version_base + "/manifest")
    assert manifest.status_code == 200, manifest.text
    value = manifest.json()
    assert value["input_shape"] == {"features": 3, "observations": 2}
    assert all("id" in member and "key" in member and "object_key" not in member for member in value["members"])
    preview = client.get(version_base + "/matrix-preview")
    assert preview.status_code == 200, preview.text
    assert preview.json()["values"] == [[5, 2, 0], [1, 0, 4]]
    assert client.get(base + f"/files/{file_id}/download").content == original
    with database_connection() as db:
        assert db.execute("SELECT count(*) AS n FROM bio_dataset_versions").fetchone()["n"] == 1
        assert db.execute("SELECT count(*) AS n FROM bio_dataset_members").fetchone()["n"] > 6


def test_source_mutation_blocks_old_candidate_confirmation(client):
    from app.core.config import get_data_dir
    base, created, file_id, original = create_import(client)
    waiting = run(created["task"])
    assert waiting["status"] == "waiting_confirmation", waiting
    view = read(client, base, created)
    with database_connection() as db:
        file = db.execute("SELECT * FROM files WHERE id=%s", (file_id,)).fetchone()
    path = get_data_dir() / file["object_key"]
    path.write_bytes(b"x" * len(original))
    response = confirm(client, base, created, view)
    assert response.status_code == 409, response.text
    with database_connection() as db:
        assert db.execute("SELECT count(*) AS n FROM bio_dataset_versions").fetchone()["n"] == 0
        assert db.execute("SELECT status FROM tasks WHERE id=%s", (waiting["id"],)).fetchone()["status"] == "waiting_confirmation"


def test_interrupted_leaf_write_retries_same_reserved_manifest(client, monkeypatch):
    from app.adapters.bio_objects import BioObjects
    from app.core.exceptions import StorageError
    base, created, _, _ = create_import(client)
    original_write = BioObjects.write
    writes = []
    def fail_write(self, record, content):
        writes.append(record["object_key"])
        raise StorageError("storage_unavailable", "synthetic interrupted local write")
    monkeypatch.setattr(BioObjects, "write", fail_write)
    failed = run(created["task"])
    assert failed["status"] == "failed" and failed["error_code"] == "storage_unavailable", failed
    with database_connection() as db:
        reserved = list(db.execute("SELECT operation_key,object_key,sha256,size_bytes FROM storage_reservations WHERE task_id=%s ORDER BY operation_key", (failed["id"],)))
        assert len(reserved) > 6 and len(writes) == 1
        assert db.execute("SELECT candidate_object_id FROM bio_imports WHERE id=%s", (created["id"],)).fetchone()["candidate_object_id"] is None
    monkeypatch.setattr(BioObjects, "write", original_write)
    queued = client.post("/api/v1/tasks/" + failed["id"] + "/retry", json={"expected_revision": failed["revision"]})
    assert queued.status_code == 202, queued.text
    waiting = run(queued.json())
    assert waiting["status"] == "waiting_confirmation", waiting
    with database_connection() as db:
        after = list(db.execute("SELECT operation_key,object_key,sha256,size_bytes FROM storage_reservations WHERE task_id=%s ORDER BY operation_key", (failed["id"],)))
        assert after == reserved
        assert db.execute("SELECT count(*) AS n FROM storage_reservations WHERE task_id=%s AND state<>'settled'", (failed["id"],)).fetchone()["n"] == 0


def test_version_transaction_rollback_keeps_accepted_candidate_retryable(client):
    base, created, _, _ = create_import(client)
    waiting = run(created["task"])
    assert waiting["status"] == "waiting_confirmation", waiting
    view = read(client, base, created)
    queued = confirm(client, base, created, view)
    assert queued.status_code == 202, queued.text
    with migration_connection(write=True) as db:
        db.execute("CREATE FUNCTION reject_bio_version() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic rollback'; END $$")
        db.execute("CREATE TRIGGER reject_bio_version BEFORE INSERT ON bio_dataset_versions FOR EACH ROW EXECUTE FUNCTION reject_bio_version()")
    try:
        failed = run(queued.json())
        assert failed["status"] == "failed" and failed["error_code"] == "storage_unavailable", failed
        with database_connection() as db:
            assert db.execute("SELECT count(*) AS n FROM bio_dataset_versions").fetchone()["n"] == 0
            assert db.execute("SELECT next_node FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1", (failed["id"],)).fetchone()["next_node"] == "publish"
    finally:
        with migration_connection(write=True) as db:
            db.execute("DROP TRIGGER reject_bio_version ON bio_dataset_versions")
            db.execute("DROP FUNCTION reject_bio_version()")
    queued_again = client.post("/api/v1/tasks/" + failed["id"] + "/retry", json={"expected_revision": failed["revision"]})
    assert queued_again.status_code == 202, queued_again.text
    def forbid_parse(*args): pytest.fail("publish recovery must use the exact accepted candidate")
    done = run(queued_again.json(), parser=forbid_parse)
    assert done["status"] == "succeeded", done


@pytest.mark.skipif(sys.platform == "linux", reason="Windows fail-closed contract")
def test_windows_default_execution_preserves_environment_error_identity(client):
    from app.domain.bioinformatics.execution import run_bio_import_task
    _, created, _, _ = create_import(client)
    task = created["task"]
    failed = run_bio_import_task(task["id"], task["revision"])
    assert failed["status"] == "failed"
    assert failed["error_code"] == "bio_environment_unavailable"
    fetched = client.get("/api/v1/tasks/" + task["id"])
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["error_code"] == "bio_environment_unavailable"
