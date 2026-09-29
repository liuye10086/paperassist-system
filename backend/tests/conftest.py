import pytest


@pytest.fixture(autouse=True)
def isolate_cloud_worker(monkeypatch):
    # Tests control cloud completion explicitly; never touch a developer's live API.
    monkeypatch.setenv('PAPERASSIST_PLOT_WORKER_ENABLED', '0')
