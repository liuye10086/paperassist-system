"""Small, owner-scoped projection used to render the project main flow."""
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.adapters.research_intake_store import latest_confirmed_requirement
from app.adapters.storage import ProjectStore
from app.core.exceptions import StorageError


NextStep = Literal["upload", "requirements", "analysis", "results", "writing"]
_SERVICES = ("analysis", "sci_draft", "thesis_draft")


class WorkflowFiles(BaseModel):
    total: int = Field(ge=0)
    ready: int = Field(ge=0)


class WorkflowRequirements(BaseModel):
    saved: bool
    version: int | None = Field(default=None, ge=1)
    services: list[Literal["analysis", "sci_draft", "thesis_draft"]] = Field(default_factory=list)


class WorkflowResults(BaseModel):
    available: bool


class WorkflowState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    project_type: Literal["sci", "thesis", "research"]
    files: WorkflowFiles
    requirements: WorkflowRequirements
    results: WorkflowResults
    next_step: NextStep


def derive_next_step(*, ready_files: int, requirements_saved: bool,
                     services: list[str], results_available: bool) -> NextStep:
    if ready_files == 0:
        return "upload"
    if not requirements_saved:
        return "requirements"
    if results_available:
        return "results"
    if "analysis" in services:
        return "analysis"
    return "writing"


def _services(content_json) -> list[str]:
    if isinstance(content_json, str):
        try:
            content_json = json.loads(content_json)
        except (TypeError, ValueError):
            content_json = None
    values = content_json.get("services") if isinstance(content_json, dict) else None
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, str) and value in _SERVICES]


def read_workflow_state(store: ProjectStore, project_id: str) -> WorkflowState:
    """Read all flow gates in one repeatable, owner-scoped read transaction."""
    store.require_project_scope(project_id)
    scope = " AND p.owner_id = %s" if store.owner_id is not None else ""
    parameters = (project_id, store.owner_id) if store.owner_id is not None else (project_id,)
    assigned = store.assignment is not None
    with store.connection() as db:
        project = db.execute(
            "SELECT p.id, p.project_type, p.owner_id FROM projects p WHERE p.id = %s" + scope,
            parameters,
        ).fetchone()
        if project is None:
            raise StorageError("project_not_found", "项目不存在，请刷新项目列表。", 404)

        confirmed = latest_confirmed_requirement(db, project_id) if assigned else None
        confirmed_id = confirmed["id"] if confirmed else None
        row = db.execute(
            """
            SELECT
                p.id,
                p.project_type,
                (SELECT count(*) FROM files f WHERE f.project_id = p.id) AS file_total,
                (SELECT count(*) FROM files f WHERE f.project_id = p.id
                    AND f.parse_status IN ('parsed', 'stored')) AS file_ready,
                rrv.version AS requirement_version,
                rrv.content_json AS requirement_content,
                EXISTS (
                    SELECT 1 FROM analysis_runs ar
                    JOIN files af ON af.id = ar.file_id
                    WHERE af.project_id = p.id
                ) OR EXISTS (
                    SELECT 1 FROM bio_processed_dataset_versions bp
                    WHERE bp.project_id = p.id AND bp.created_by = p.owner_id
                ) OR EXISTS (
                    SELECT 1 FROM research_finding_versions rf
                    WHERE rf.project_id = p.id AND rf.user_id = p.owner_id
                ) OR EXISTS (
                    SELECT 1 FROM research_figure_versions rfig
                    WHERE rfig.project_id = p.id AND rfig.user_id = p.owner_id
                ) OR EXISTS (
                    SELECT 1 FROM research_report_versions rr
                    WHERE rr.project_id = p.id AND rr.user_id = p.owner_id
                ) OR EXISTS (
                    SELECT 1 FROM research_manuscript_candidates rmc
                    WHERE rmc.project_id = p.id AND rmc.user_id = p.owner_id AND %s
                ) AS results_available
            FROM projects p
            LEFT JOIN research_intakes ri ON ri.project_id = p.id
            LEFT JOIN research_requirement_versions rrv
                ON rrv.id = CASE WHEN %s THEN %s::text ELSE ri.current_requirement_version_id END
                AND rrv.project_id = p.id
            WHERE p.id = %s
            """,
            (not assigned, assigned, confirmed_id, project_id),
        ).fetchone()
        if row is None:
            raise StorageError("project_not_found", "项目不存在，请刷新项目列表。", 404)

        services = _services(row["requirement_content"])
        if assigned:
            services = [service for service in services if service == "analysis"]
        elif not services:
            deliveries = db.execute(
                "SELECT kind FROM research_deliveries WHERE project_id = %s AND active = true ORDER BY kind",
                (project_id,),
            ).fetchall()
            services = [item["kind"] for item in deliveries if item["kind"] in _SERVICES]
        requirement_version = row["requirement_version"]
        requirements_saved = requirement_version is not None and bool(services)
        ready_files = int(row["file_ready"] or 0)
        total_files = int(row["file_total"] or 0)
        results_available = bool(row["results_available"])
        return WorkflowState(
            project_id=row["id"],
            project_type=row["project_type"],
            files=WorkflowFiles(total=total_files, ready=ready_files),
            requirements=WorkflowRequirements(
                saved=requirements_saved,
                version=requirement_version if requirements_saved else None,
                services=services,
            ),
            results=WorkflowResults(available=results_available),
            next_step=derive_next_step(
                ready_files=ready_files,
                requirements_saved=requirements_saved,
                services=services,
                results_available=results_available,
            ),
        )
