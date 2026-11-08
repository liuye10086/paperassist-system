from tests.api.test_projects import client, create_project, upload


def test_empty_project_points_to_upload(client):
    project = create_project(client, project_type="sci")
    response = client.get(f"/api/v1/projects/{project['id']}/workflow-state")
    assert response.status_code == 200
    assert response.json() == {
        "project_id": project["id"],
        "project_type": "sci",
        "files": {"total": 0, "ready": 0},
        "requirements": {"saved": False, "version": None, "services": ["sci_draft"]},
        "results": {"available": False},
        "next_step": "upload",
    }


def test_parsed_file_without_requirement_points_to_requirements(client):
    project = create_project(client, project_type="sci")
    upload(client, project["id"])
    response = client.get(f"/api/v1/projects/{project['id']}/workflow-state")
    assert response.status_code == 200
    body = response.json()
    assert body["files"] == {"total": 1, "ready": 1}
    assert body["next_step"] == "requirements"


def test_workflow_state_is_owner_scoped(client):
    project = create_project(client, project_type="sci")
    from tests.integration.test_project_ownership import account_client

    with account_client("workflow-state-other@example.test")[0] as other:
        response = other.get(f"/api/v1/projects/{project['id']}/workflow-state")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "project_not_found"


def test_next_step_precedence():
    from app.domain.workflow_state import derive_next_step

    assert derive_next_step(ready_files=0, requirements_saved=True,
                            services=["analysis"], results_available=True) == "upload"
    assert derive_next_step(ready_files=1, requirements_saved=False,
                            services=[], results_available=False) == "requirements"
    assert derive_next_step(ready_files=1, requirements_saved=True,
                            services=["analysis"], results_available=False) == "analysis"
    assert derive_next_step(ready_files=1, requirements_saved=True,
                            services=["sci_draft"], results_available=True) == "results"
    assert derive_next_step(ready_files=1, requirements_saved=True,
                            services=["sci_draft"], results_available=False) == "writing"
