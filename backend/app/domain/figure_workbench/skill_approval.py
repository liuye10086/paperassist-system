"""Approval and replay of a fixed figure's optional statistical reading rules."""

from app.adapters.task_store import source_conflict
from app.auth.project_access import ProjectAssignment, require_current_assignment
from app.core.exceptions import StorageError
from app.domain.admin_configuration import bindings, model_consumption
from app.domain.external_processing import digest
from app.domain.figure_workbench.explanation_v5 import instructions_v5
from app.domain.runtime_skills import runtime


def enabled(payload):
    return (payload.get('figure_explanation_contract') == 5
            and runtime.is_enabled(runtime.STATISTICAL_EXPLANATION))


def delegated_approval(assignment):
    if assignment is None:
        return {}
    return {'confirmed_by': assignment.analyst_id, 'assignment_revision': assignment.revision}


def require_new_submission(db, task, *, synthetic_fixture):
    external = task['input_snapshot']['external_processing']
    if 'assignment_revision' in external:
        scope = ProjectAssignment(task['project_id'], task['user_id'], external['confirmed_by'],
                                  external['assignment_revision'])
        require_current_assignment(db, scope, lock=True)
    elif external['confirmed_by'] != task['user_id']:
        raise source_conflict()
    elif not db.execute("""SELECT 1 FROM users WHERE id=%s AND active AND review_status='approved'
            AND role IN ('analyst','admin') FOR SHARE""", (task['user_id'],)).fetchone():
        raise StorageError('permission_denied', '原确认账号当前无权提交图表解释。', 403)
    if not synthetic_fixture:
        # Serialize the admission decision with an administrator switching the current configuration.
        pointer = db.execute('SELECT version_id FROM admin_configuration_pointer WHERE id=1 FOR SHARE').fetchone()
        if pointer and pointer['version_id']:
            current = bindings.read(db, pointer['version_id'])
            if not current['bundle']['models']['real_calls_enabled']:
                raise StorageError('model_configuration_disabled', '当前配置已停用真实模型调用。', 409)


def _material(payload, figure, skills, base, configuration, delegation):
    effective = model_consumption.instructions(base + '\n\n' + skills.instructions, configuration, 'explanation')
    material = dict(payload=payload, figure_binding={'id':figure['id'], 'sha256':figure['sha256']},
                    skills_snapshot=skills.model_dump(mode='json'), effective_instructions=effective)
    return dict(**material, payload_sha256=digest({'version': 8, **material, **delegation}), requires_confirmation=True)


def prepare(payload, figure, configuration, delegation):
    step = runtime.load_step(runtime.STATISTICAL_EXPLANATION, 'explain_fixed_figure')
    base = instructions_v5(payload, use_validated_frames=True)
    return _material(payload, figure, runtime.SkillSnapshot.from_step(step), base, configuration, delegation), base


def replay(db, task, payload):
    snapshot = task['input_snapshot']
    external = snapshot['external_processing']
    skills = runtime.SkillSnapshot.model_validate(snapshot['skills_snapshot'])
    trace = skills.trace
    if (external['version'] != 8 or task['task_type'] != 'figure_explanation'
            or payload.get('figure_explanation_contract') != 5
            or (trace.workflow, trace.step, trace.tool.id) !=
               ('statistical_explanation', 'explain_fixed_figure', 'figure_explanation')
            or [ref.name for ref in trace.skills] != ['statistical-reading']):
        raise source_conflict()
    configuration = bindings.resolve(db, kind='task', object_id=task['id'])
    delegation = {}
    if 'assignment_revision' in external:
        revision = external['assignment_revision']
        actor = external['confirmed_by']
        if (type(revision) is not int or revision < 1 or actor == task['user_id'] or not db.execute(
                """SELECT 1 FROM project_assignment_events WHERE project_id=%s AND owner_id=%s
                AND analyst_id=%s AND revision=%s""", (task['project_id'],task['user_id'],actor,revision)).fetchone()):
            raise source_conflict()
        delegation = {'confirmed_by': actor, 'assignment_revision': revision}
    elif external['confirmed_by'] != task['user_id']:
        raise source_conflict()
    material = _material(payload, snapshot['figure'], skills, snapshot['explanation_base_instructions'], configuration, delegation)
    expected_request = dict(version_id=external['version_id'], figure_id=snapshot['figure']['id'],
                            external={'confirmed': True, 'payload_sha256': material['payload_sha256']})
    if external['payload_sha256'] != material['payload_sha256'] or digest(expected_request) != task['input_digest']:
        raise source_conflict()
    return material
