import hashlib
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import storage
from app.storage import ProjectStore
from test_excel import workbook_bytes


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPERASSIST_DATA_DIR", str(tmp_path / "data"))
    with TestClient(app) as instance:
        yield instance


def create_project(client, name="研究项目", project_type="sci"):
    response = client.post("/api/v1/projects", json={
        "name": name, "project_type": project_type, "research_topic": "治疗组与对照组比较",
    })
    assert response.status_code == 201, response.text
    return response.json()


def upload(client, project_id, content=None, filename="研究.xlsx"):
    return client.post(f"/api/v1/projects/{project_id}/files", files={
        "file": (filename, workbook_bytes() if content is None else content),
    })


def test_empty_projects_then_create_both_types(client):
    assert client.get("/api/v1/projects").json() == []
    first = create_project(client, "  药学研究  ")
    second = create_project(client, "毕业论文", "thesis")
    assert first["name"] == "药学研究"
    assert first["file_count"] == 0
    assert first["id"] != second["id"]
    assert first["created_at"] and first["updated_at"]
    assert len(client.get("/api/v1/projects").json()) == 2
    assert client.get(f'/api/v1/projects/{first["id"]}').json() == first


@pytest.mark.parametrize("field, value", [
    ("name", "  "), ("name", "x" * 121), ("project_type", "other"),
    ("research_topic", ""), ("research_topic", "x" * 501),
])
def test_project_validation(client, field, value):
    data = {"name": "项目", "project_type": "sci", "research_topic": "主题"}
    data[field] = value
    assert client.post("/api/v1/projects", json=data).status_code == 422


def test_upload_list_reopen_and_download_original(client):
    project = create_project(client)
    content = workbook_bytes()
    response = upload(client, project["id"], content)
    assert response.status_code == 201, response.text
    result = response.json()
    record = result["file"]
    assert record["filename"] == "研究.xlsx"
    assert record["project_id"] == project["id"]
    assert record["size_bytes"] == len(content)
    assert record["sha256"] == hashlib.sha256(content).hexdigest()
    assert record["file_type"] == "xlsx"
    assert record["parse_status"] == "parsed"
    assert record["error"] is None
    assert record["uploaded_at"]
    assert "path" not in record
    assert len(result["preview"]["sheets"]) == 3
    assert len(result["preview"]["sheets"][0]["preview_rows"]) == 20
    base = f'/api/v1/projects/{project["id"]}/files'
    assert client.get(base).json() == [record]
    assert client.get(f'{base}/{record["id"]}/preview').json() == result["preview"]
    downloaded = client.get(f'{base}/{record["id"]}/download')
    assert downloaded.status_code == 200
    assert downloaded.content == content
    assert "attachment" in downloaded.headers["content-disposition"]
    project_now = client.get(f'/api/v1/projects/{project["id"]}').json()
    assert project_now["file_count"] == 1
    assert project_now["updated_at"] >= project["updated_at"]


def test_same_filename_never_overwrites_previous_upload(client):
    project = create_project(client)
    original = workbook_bytes()
    first = upload(client, project["id"], original).json()["file"]
    second = upload(client, project["id"], b"different content").json()["file"]
    assert first["id"] != second["id"]
    assert first["filename"] == second["filename"]
    assert len(client.get(f'/api/v1/projects/{project["id"]}/files').json()) == 2
    for record, expected in ((first, original), (second, b"different content")):
        assert client.get(f'/api/v1/projects/{project["id"]}/files/{record["id"]}/download').content == expected


def test_failed_parse_is_saved_with_reason_and_raw_file(client):
    project = create_project(client)
    response = upload(client, project["id"], b"broken")
    assert response.status_code == 201
    result = response.json()
    record = result["file"]
    assert record["parse_status"] == "failed"
    assert record["error"]["code"] == "invalid_workbook"
    assert result["preview"] is None
    base = f'/api/v1/projects/{project["id"]}/files/{record["id"]}'
    assert client.get(base + "/preview").status_code == 422
    assert client.get(base + "/download").content == b"broken"


@pytest.mark.parametrize("filename, content, status", [
    ("bad.xls", b"bad", 415), ("empty.xlsx", b"", 422), ("large.xlsx", b"a" * 1025, 413),
])
def test_rejected_upload_does_not_create_file_record(client, monkeypatch, filename, content, status):
    project = create_project(client)
    monkeypatch.setenv("EXCEL_MAX_UPLOAD_BYTES", "1024")
    assert upload(client, project["id"], content, filename).status_code == status
    assert client.get(f'/api/v1/projects/{project["id"]}/files').json() == []


def test_project_upload_also_limits_chunked_request(client, monkeypatch):
    project = create_project(client)
    monkeypatch.setenv("EXCEL_MAX_UPLOAD_BYTES", "10")
    response = client.post(f'/api/v1/projects/{project["id"]}/files', content=iter([b"x" * 70000]))
    assert response.status_code == 413


def test_files_cannot_be_accessed_via_another_project(client):
    first = create_project(client)
    second = create_project(client, "第二个项目")
    record = upload(client, first["id"]).json()["file"]
    base = f'/api/v1/projects/{second["id"]}/files'
    assert client.get(base).json() == []
    for endpoint in ("preview", "download"):
        assert client.get(f'{base}/{record["id"]}/{endpoint}').status_code == 404
    assert client.get('/api/v1/projects/missing').status_code == 404
    assert upload(client, "missing").status_code == 404


def test_filename_path_is_never_used_as_storage_path(client):
    project = create_project(client)
    response = upload(client, project["id"], filename="../../研究.xlsx")
    assert response.status_code == 201
    record = response.json()["file"]
    assert record["filename"] == "研究.xlsx"
    stored = list(Path(os.environ["PAPERASSIST_DATA_DIR"]).rglob("*.xlsx"))
    assert len(stored) == 1
    assert stored[0].stem == record["id"]


def test_data_is_readable_in_new_python_process(client):
    project = create_project(client)
    record = upload(client, project["id"]).json()["file"]
    code = '''
import json, sys
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as client:
    project = client.get('/api/v1/projects/' + sys.argv[1]).json()
    files = client.get('/api/v1/projects/' + sys.argv[1] + '/files').json()
    preview = client.get('/api/v1/projects/' + sys.argv[1] + '/files/' + sys.argv[2] + '/preview')
    print(json.dumps([project['id'], files[0]['id'], preview.status_code]))
'''
    result = subprocess.run([sys.executable, "-c", code, project["id"], record["id"]],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True, timeout=30)
    assert json.loads(result.stdout) == [project["id"], record["id"], 200]


def test_missing_original_returns_clear_error(client):
    project = create_project(client)
    record = upload(client, project["id"]).json()["file"]
    path = next(Path(os.environ["PAPERASSIST_DATA_DIR"]).rglob("*.xlsx"))
    path.unlink()  # Disposable synthetic fixture in pytest's temporary directory.
    for endpoint in ("preview", "download"):
        response = client.get(f'/api/v1/projects/{project["id"]}/files/{record["id"]}/{endpoint}')
        assert response.status_code == 410
        assert response.json()["detail"]["code"] == "file_missing"


def test_changed_original_returns_clear_error(client):
    project = create_project(client)
    record = upload(client, project["id"]).json()["file"]
    path = next(Path(os.environ["PAPERASSIST_DATA_DIR"]).rglob("*.xlsx"))
    original = path.read_bytes()
    path.write_bytes(b"x" + original[1:])  # Same size but different SHA256.
    for endpoint in ("preview", "download"):
        response = client.get(f'/api/v1/projects/{project["id"]}/files/{record["id"]}/{endpoint}')
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "file_changed"


def test_database_write_failure_rolls_back_upload(client):
    project = create_project(client)
    directory = Path(os.environ["PAPERASSIST_DATA_DIR"])
    with sqlite3.connect(directory / "paperassist.sqlite3") as db:
        db.execute("CREATE TRIGGER reject_file BEFORE INSERT ON files BEGIN SELECT RAISE(ABORT, 'test failure'); END;")
    response = upload(client, project["id"])
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "storage_unavailable"
    assert list((directory / "files").iterdir()) == []
    assert client.get(f'/api/v1/projects/{project["id"]}').json() == project
    assert client.get(f'/api/v1/projects/{project["id"]}/files').json() == []


def test_unavailable_directory_does_not_break_health(client, tmp_path, monkeypatch):
    blocked = tmp_path / "blocked"
    blocked.write_text("regular file, not a directory", encoding="utf-8")
    monkeypatch.setenv("PAPERASSIST_DATA_DIR", str(blocked))
    response = client.get('/api/v1/projects')
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "storage_unavailable"
    assert str(blocked) not in response.text
    assert client.get('/api/v1/health').json()["status"] == "ok"


def test_concurrent_upload_keeps_project_update_time_monotonic(client, monkeypatch):
    project = create_project(client)
    store = ProjectStore(Path(os.environ["PAPERASSIST_DATA_DIR"]))
    started, resume = Event(), Event()
    original_open = Path.open

    def delay_first_write(path, *args, **kwargs):
        if path.suffix == ".part" and not started.is_set():
            started.set()
            assert resume.wait(5), "second upload did not finish"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", delay_first_write)
    now = datetime.now(timezone.utc)
    times = iter([now + timedelta(seconds=1), now + timedelta(seconds=2)])

    class UploadClock:
        @staticmethod
        def now(_timezone):
            return next(times)

    monkeypatch.setattr(storage, "datetime", UploadClock)
    error = {"code": "parse_failed", "message": "test fixture"}
    with ThreadPoolExecutor(max_workers=1) as executor:
        earlier = executor.submit(store.save_file, project["id"], "same.xlsx", b"first", None, error)
        try:
            assert started.wait(5)
            later = store.save_file(project["id"], "same.xlsx", b"second", None, error)
        finally:
            resume.set()
        first = earlier.result(timeout=5)
    assert store.project(project["id"])["updated_at"] >= later["uploaded_at"]
    assert len(store.files(project["id"])) == 2
    assert store.original(first) == b"first"
    assert store.original(later) == b"second"
