import pytest
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_manuscripts import setup,body
from tests.api.test_literature_evidence import post
from app.domain.tasks.execution import run_task


@pytest.fixture(autouse=True)
def fake_renderer(monkeypatch):
    """Existing Word fixtures use the preserved field-renderer identity."""
    monkeypatch.setattr('app.adapters.pdf_renderer.renderer_identity',lambda: {'contract':'test-v1'})

def successful_docx(client):
    path,_,_=setup(client)
    root=post(client,path,body(),'draft').json()
    run_task(root['versions'][0]['task_id'],1)
    exported=post(client,path+'/'+root['id']+'/versions/1/exports',{},'docx').json()
    run_task(exported['task_id'],1)
    return path.removesuffix('/manuscripts')+'/pdf-exports',exported
