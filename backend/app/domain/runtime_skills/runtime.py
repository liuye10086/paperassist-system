"""Deterministic step selection and frozen skill provenance."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from app.core.exceptions import StorageError
from app.core.paths import PROJECT_ROOT
from app.domain.model_usage.contracts import StrictContract

from .registry import (
    Manifest, Name, Release, Sha256, SkillError, Version, open_release, sha256, valid_file,
)

SCI_NARRATIVE_REVIEW = 'sci_narrative_review'
SCI_RESEARCH_ARTICLE = 'sci_research_article'
THESIS_INITIAL_DRAFT = 'thesis_initial_draft'
STATISTICAL_EXPLANATION = 'statistical_explanation'
RESEARCH_REPORT_READING = 'research_report_reading'
_RETIRED_WORKFLOWS = {'bulk_fixed_preview', 'single_cell_composition_preview'}
MAX_INSTRUCTIONS = 8192
_KEY = Annotated[str, Field(min_length=1, max_length=64, pattern=r'^[a-z][a-z0-9_]*$')]
_log = logging.getLogger(__name__)


class ToolTrace(StrictContract):
    id: _KEY
    version: Version


class ResourceTrace(StrictContract):
    path: str = Field(max_length=270)
    sha256: Sha256

    @field_validator('path')
    @classmethod
    def validate_path(cls, value):
        if not valid_file(value, body=False):
            raise ValueError('invalid frozen skill resource path')
        return value


class SkillReference(StrictContract):
    name: Name
    version: Version
    sha256: Sha256
    resources: tuple[ResourceTrace, ...] = Field(strict=False, max_length=8)

    @model_validator(mode='after')
    def unique_resources(self):
        if len({resource.path for resource in self.resources}) != len(self.resources):
            raise ValueError('duplicate frozen skill resource')
        return self


class SkillTrace(StrictContract):
    workflow: _KEY
    workflow_version: Version
    step: _KEY
    tool: ToolTrace
    manifest_sha256: Sha256
    skills: tuple[SkillReference, ...] = Field(strict=False, min_length=1, max_length=8)

    @model_validator(mode='after')
    def unique_skills(self):
        if len({skill.name for skill in self.skills}) != len(self.skills):
            raise ValueError('duplicate frozen skill')
        return self


class SkillSnapshot(StrictContract):
    schema_version: Literal[1] = 1
    trace: SkillTrace
    instructions: str = Field(min_length=1, max_length=MAX_INSTRUCTIONS)
    instructions_sha256: Sha256

    @model_validator(mode='after')
    def require_instruction_digest(self):
        body = self.instructions.encode('utf-8')
        if len(body) > MAX_INSTRUCTIONS or sha256(body) != self.instructions_sha256:
            raise ValueError('frozen skill instructions differ from the approved text')
        return self

    @classmethod
    def from_step(cls, loaded):
        return cls(trace=loaded.trace, instructions=loaded.instructions,
                   instructions_sha256=sha256(loaded.instructions.encode('utf-8')))


class WritingSkillsSnapshot(SkillSnapshot):
    """Frozen skill instructions used by the manuscript contracts."""


@dataclass(frozen=True)
class SkillSpec:
    requires: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Step:
    version: str
    tool: str
    skills: tuple[str, ...]


SKILLS = {
    'scientific-writing': SkillSpec(),
    'statistical-reading': SkillSpec(),
    'research-report-reading': SkillSpec(),
    'narrative-review': SkillSpec(requires=('scientific-writing',)),
    'research-article': SkillSpec(requires=('scientific-writing',)),
    'thesis-writing': SkillSpec(requires=('scientific-writing',)),
    'citation-verification': SkillSpec(requires=('scientific-writing',), resources=('references/evidence-scope.md',)),
}
TOOLS = {
    'figure_explanation': ToolTrace(id='figure_explanation', version='1.0.0'),
    'reader_report': ToolTrace(id='reader_report', version='1.0.0'),
    'manuscript_writing': ToolTrace(id='manuscript_writing', version='1.0.0'),
}
STEPS = {
    (STATISTICAL_EXPLANATION, 'explain_fixed_figure'): Step(
        '1.0.0', 'figure_explanation', ('statistical-reading',),
    ),
    (RESEARCH_REPORT_READING, 'explain_report'): Step(
        '1.0.0', 'reader_report', ('research-report-reading',),
    ),
    (SCI_NARRATIVE_REVIEW, 'initial_draft'): Step(
        '1.0.0', 'manuscript_writing', ('narrative-review', 'citation-verification'),
    ),
    (SCI_RESEARCH_ARTICLE, 'initial_draft'): Step(
        '1.0.0', 'manuscript_writing', ('research-article', 'citation-verification'),
    ),
    (THESIS_INITIAL_DRAFT, 'initial_draft'): Step(
        '1.0.0', 'manuscript_writing', ('thesis-writing', 'citation-verification'),
    ),
}
WORKFLOWS = frozenset(workflow for workflow, _ in STEPS)


@dataclass(frozen=True)
class LoadedStep:
    trace: SkillTrace
    instructions: str

    def freeze_writing(self) -> WritingSkillsSnapshot:
        if self.trace.tool.id != 'manuscript_writing':
            raise SkillError('step has no writing tool')
        return WritingSkillsSnapshot.from_step(self)


def skills_root() -> Path:
    configured = os.getenv('PAPERASSIST_SKILLS_DIR')
    root = Path(configured) if configured else PROJECT_ROOT / 'SKILLS'
    if not root.is_absolute():
        raise SkillError('skill package root must be absolute')
    return root


def _installed_release() -> Release:
    return open_release(skills_root(), expected_sha256=os.getenv('PAPERASSIST_SKILLS_MANIFEST_SHA256') or None)


def _requested_workflows() -> tuple[str, ...]:
    names = (value.strip() for value in os.getenv('PAPERASSIST_SKILL_WORKFLOWS', '').split(','))
    return tuple(name for name in names if name and name not in _RETIRED_WORKFLOWS)


def _validate_workflows(requested: tuple[str, ...]) -> None:
    if len(set(requested)) != len(requested) or not set(requested) <= WORKFLOWS:
        raise SkillError('unrecognized or duplicate skill workflow')


def is_enabled(workflow: str) -> bool:
    return workflow in WORKFLOWS and workflow in _requested_workflows()


def resolve_step(manifest: Manifest, step: Step, specs: dict[str, SkillSpec]) -> tuple[str, ...]:
    if step.tool not in TOOLS:
        raise SkillError('skill step tool is missing')
    ordered: dict[str, None] = {}
    visiting = set()

    def visit(name: str):
        if name in visiting:
            raise SkillError('cyclic skill dependency')
        if name in ordered:
            return
        if name not in specs or name not in manifest.skills:
            raise SkillError('required skill or dependency is missing')
        if len(ordered) + len(visiting) >= 8:
            raise SkillError('skill step size exceeds limit')
        spec = specs[name]
        if (len(spec.resources) > 8 or len(set(spec.resources)) != len(spec.resources)
                or any(not valid_file(path, body=False) or path not in manifest.skills[name].files
                       for path in spec.resources)):
            raise SkillError('required skill resource is missing or invalid')
        visiting.add(name)
        for dependency in spec.requires:
            visit(dependency)
        visiting.remove(name)
        ordered[name] = None

    for name in step.skills:
        visit(name)
    if not ordered:
        raise SkillError('skill step is empty')
    if any(set(specs[name].conflicts).intersection(ordered) for name in ordered):
        raise SkillError('conflicting skills in one step')
    return tuple(ordered)


def _load(release: Release, workflow: str, step: str) -> LoadedStep:
    plan = STEPS.get((workflow, step))
    if plan is None:
        raise SkillError('skill step is missing')
    ordered = resolve_step(release.manifest, plan, SKILLS)
    chunks = []
    refs = []
    for name in ordered:
        entry = release.manifest.skills[name]
        chunks.append(release.instructions(name))
        resources = []
        for path in SKILLS[name].resources:
            data, digest = release.resource(name, path)
            try:
                text = data.decode('utf-8').strip()
            except UnicodeError:
                raise SkillError('skill instruction resource is not UTF-8 text') from None
            if not text or '\x00' in text:
                raise SkillError('skill instruction resource is empty or invalid')
            chunks.append(text)
            resources.append(ResourceTrace(path=path, sha256=digest.sha256))
        refs.append(SkillReference(
            name=name, version=entry.version, sha256=entry.files['SKILL.md'].sha256,
            resources=tuple(resources),
        ))
    joined = '\n\n'.join(chunks)
    if len(joined.encode('utf-8')) > MAX_INSTRUCTIONS:
        raise SkillError('skill step instruction size exceeds limit')
    trace = SkillTrace(
        workflow=workflow, workflow_version=plan.version, step=step, tool=TOOLS[plan.tool],
        manifest_sha256=release.sha256, skills=tuple(refs),
    )
    return LoadedStep(trace, joined)


def verify_steps(release: Release) -> None:
    for workflow, step in STEPS:
        _load(release, workflow, step)


def load_step(workflow: str, step: str) -> LoadedStep:
    requested = _requested_workflows()
    if workflow not in WORKFLOWS or workflow not in requested:
        raise StorageError('runtime_skills_disabled', '此技能流程尚未启用。', 404)
    try:
        _validate_workflows(requested)
        return _load(_installed_release(), workflow, step)
    except SkillError as exc:
        _log.warning('Skills step unavailable (%s/%s): %s', workflow, step, exc)
        raise StorageError('runtime_skills_unavailable', '所需技能包无法校验，请联系管理员核对版本。', 503) from None


def log_configured_installation() -> None:
    """Check installation at process startup without affecting frozen tasks."""
    requested = _requested_workflows()
    if not requested:
        return
    try:
        _validate_workflows(requested)
        release = _installed_release()
        for workflow, step in STEPS:
            if workflow in requested:
                _load(release, workflow, step)
        _log.info('Skills manifest %s for %s', release.sha256, ','.join(requested))
    except SkillError as exc:
        _log.warning('Skills installation unavailable: %s', exc)
