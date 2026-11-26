"""Freeze, admit and read governed research report interpretations."""
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.adapters.research_results_store import ResearchResultsStore, invalid, now
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.admin_configuration.bindings import bind, resolve
from app.domain.bioinformatics.contracts import digest
from app.domain.dataset_preparation.service import append_checkpoint, require_key
from app.domain.model_usage.provenance import public_provider_provenance
from app.domain.model_usage.service import TERMINAL
from app.domain.research_results.contracts import ResearchReportRequest
from app.domain.runtime_skills import runtime

from .contracts import CALL_KEY, RETRYABLE_FAILURES, TASK_TYPE, WORKFLOW, NarrativeRequest, ReaderReportInputVersion


def input_version(task):
    snapshot = task['input_snapshot']
    if (
        task['task_type'] != TASK_TYPE or task['workflow_version'] != WORKFLOW
        or snapshot.get('schema_version') != 1 or snapshot.get('kind') != TASK_TYPE
        or snapshot.get('workflow_version') != WORKFLOW or snapshot.get('project_id') != task['project_id']
        or digest(snapshot) != task['input_digest']
    ):
        raise source_conflict()
    return ReaderReportInputVersion(narrative_id=snapshot['narrative_id'], binding_sha256=snapshot['binding_sha256'],
                                    bundle_sha256=snapshot['bundle']['bundle_sha256']).model_dump(mode='json')


def artifact_sha(row, raw, result, call_id):
    return digest(dict(input_digest=row['input_digest'], raw_output=raw, result=result, model_call_id=call_id))


def public_material(material):
    """Keep exact textual input and ordered figure descriptors, without image copies."""
    return {**material, 'figures': [{key: value for key, value in item.items() if key != 'image_url'}
                                  for item in material['figures']]}


def _report_images(figures):
    from app.adapters.research_report_images import as_png

    return [{'config': item['config'], 'caption_facts': item.get('caption_facts', []),
             'content': item['raw'] if item['format'] == 'png' else as_png(item['raw'], item['format'])}
            for item in figures]


def _material(content, payload, *, include_table_evidence=False):
    from .content import make_material

    try:
        return make_material(content, _report_images(payload['figures']),
                             table_raws=payload['table_raws'] if include_table_evidence else None,
                             trajectory_import=payload.get('trajectory_import'))
    except (OSError, TypeError, ValueError) as exc:
        raise StorageError('reader_report_input_limit', '所选事实或图件超出解读输入范围，请核对图件和资料。', 422) from exc


class ReaderReportService(ResearchResultsStore):
    def _base(self, db, project, report, *, check_revision=False):
        from app.domain.research_results.reports import ResearchReportService

        self.store.require_project(db, project)
        report = report.model_copy(update={'reader_narrative_id': None})
        if check_revision and report.root_id:
            parent = db.execute('''SELECT revision FROM research_report_versions
                WHERE project_id=%s AND user_id=%s AND root_id=%s ORDER BY revision DESC LIMIT 1''',
                (project, self.store.user_id, report.root_id)).fetchone()
            if not parent:
                raise invalid('research_source_not_found', 404)
            if parent['revision'] != report.expected_revision:
                raise invalid('research_revision_conflict')
        content, bindings, payload = ResearchReportService(self.assets).freeze(db, project, report, attach_reader=False)
        return content, sorted({fid for source in bindings for fid in source.source_file_ids}), payload

    def _prepare(self, db, project, report):
        from .content import binding_digest
        from .policy import bundle

        skills = None
        if runtime.is_enabled(runtime.RESEARCH_REPORT_READING):
            skills = runtime.SkillSnapshot.from_step(runtime.load_step(runtime.RESEARCH_REPORT_READING, 'explain_report'))
        content, files, payload = self._base(db, project, report, check_revision=True)
        if skills is not None:
            from .table_evidence import trajectory_import_counts

            payload['trajectory_import'] = trajectory_import_counts(self.assets, db, project, content)
        material = _material(content, payload, include_table_evidence=skills is not None)
        frozen = bundle(material, skills=skills) if skills is not None else bundle(material)
        return binding_digest(content), files, frozen

    def _lock_binding(self, db, project, binding):
        self.lock(db, project, 'reader-report-binding:' + binding)

    def _reusable(self, db, project, binding, bundle, *, exclude_id=None, reuse_reservation=False,
                  ignore_unreserved_budget_wait=False, confirmed_sha=None):
        # A retired cap or a change elsewhere in the installed skill pack does not change the
        # approved request. The selected skill hashes, instructions and exact material still match.
        ignored = ['bundle_sha256', 'task_limit_micro_usd', 'real_calls_enabled']
        comparable = {k: v for k, v in bundle.items() if k not in ignored}
        comparable['material'] = public_material(comparable['material'])
        return db.execute("""SELECT n.id,t.status FROM reader_report_narratives n JOIN tasks t ON t.id=n.task_id
            LEFT JOIN model_calls c ON c.task_id=t.id AND c.project_id=t.project_id AND c.user_id=t.user_id AND c.call_key=%s
            WHERE n.project_id=%s AND n.user_id=%s AND n.binding_sha256=%s AND
              (n.bundle_sha256=%s OR ((n.input_snapshot->'bundle') - %s::text[])
                    #- '{skills_snapshot,trace,manifest_sha256}'::text[]
                    = (%s::jsonb #- '{skills_snapshot,trace,manifest_sha256}'::text[]))
              AND (%s::text IS NULL OR n.bundle_sha256=%s)
              AND n.id IS DISTINCT FROM %s
              AND NOT (%s AND t.status='waiting_confirmation' AND t.reason_code IS NOT DISTINCT FROM 'budget_exceeded'
                       AND c.id IS NULL)
              AND (t.status IN ('succeeded','queued','running','waiting_confirmation')
                   OR (t.status='failed' AND (n.result_json IS NULL OR COALESCE(c.provider_status,'') <> ALL(%s))
                       AND (c.provider_response_id IS NOT NULL OR c.status IN ('submitting','submission_unknown')))
                   OR (%s AND t.status='failed' AND n.result_json IS NULL AND t.error_code=ANY(%s)
                       AND c.status='reserved' AND c.provider_response_id IS NULL))
            ORDER BY (t.status='succeeded') DESC,(c.status='reserved' AND t.status='failed') ASC NULLS FIRST,
                     n.created_at,n.id LIMIT 1""",
            (CALL_KEY, project, self.store.user_id, binding, bundle['bundle_sha256'], ignored, Jsonb(comparable), confirmed_sha, confirmed_sha, exclude_id, ignore_unreserved_budget_wait,
             sorted(TERMINAL), reuse_reservation, list(RETRYABLE_FAILURES))).fetchone()

    def require_no_replacement(self, db, row, *, has_reservation):
        project, binding = row['project_id'], row['binding_sha256']
        bundle = row['input_snapshot']['bundle']
        self._lock_binding(db, project, binding)
        # A legacy replacement waiting for a second reservation must not trap the original hold.
        if self._reusable(db, project, binding, bundle, exclude_id=row['id'],
                          ignore_unreserved_budget_wait=has_reservation):
            raise StorageError('task_revision_conflict', '已有相同材料和策略的解读任务，请在任务列表查看该任务。', 409)

    def preview(self, project, report):
        with self.store.connection() as db:
            binding, _, frozen = self._prepare(db, project, report)
            config = resolve(db)
            reusable = self._reusable(db, project, binding, frozen)
            cached = bool(reusable and reusable['status'] == 'succeeded')
            if cached:
                self._result_call(db, *self.row(db, project, reusable['id']))
        material = public_material(frozen['material'])
        return dict(
            binding_sha256=binding, bundle_sha256=frozen['bundle_sha256'], model=frozen['policy']['model'],
            reserved_micro_usd=0 if cached else frozen['reserved_micro_usd'],
            real_calls_enabled=frozen['real_calls_enabled'] and (not config or config['bundle']['models']['real_calls_enabled']),
            facts=material['facts'], fact_count=len(material['facts']['facts']), figures=material['figures'],
            cached=cached,
        )

    def _receipt(self, db, project, key):
        self.store.require_project(db, project)
        return db.execute('''SELECT narrative_id,request_digest FROM reader_report_narrative_requests
            WHERE project_id=%s AND user_id=%s AND idempotency_key=%s''', (project, self.store.user_id, key)).fetchone()

    def create(self, project, request, key):
        require_key(key)
        request = NarrativeRequest.model_validate(request)
        body = request.model_dump(mode='json')
        request_sha = digest(body)
        with self.store.connection(write=True) as db:
            self.lock(db, project, 'reader-report-request:' + key)
            existing = self._receipt(db, project, key)
            if existing:
                if request_sha != existing['request_digest']:
                    raise invalid('research_idempotency_conflict')
                return self.view(db, project, existing['narrative_id']), 200
            binding, files, full_bundle = self._prepare(db, project, request.report)
            from app.domain.storage_governance.guards import require_scope_open
            require_scope_open(db, project, file_ids=files)
            self._lock_binding(db, project, binding)
            # A retry can reuse the existing provider call identity before submission.
            previous_sha = request.bundle_sha256 if request.bundle_sha256 != full_bundle['bundle_sha256'] else None
            old = self._reusable(db, project, binding, full_bundle, reuse_reservation=True, confirmed_sha=previous_sha)
            if previous_sha and not old:
                raise source_conflict()
            if old:
                identifier, status = old['id'], 200
            else:
                configuration = resolve(db)
                if configuration and not configuration['bundle']['models']['real_calls_enabled']:
                    raise StorageError('model_configuration_disabled', '当前生效的管理配置禁止生成新模型解读。', 409)
                frozen = {**full_bundle, 'material': public_material(full_bundle['material'])}
                identifier = self._insert(db, project, body, binding, files, frozen, configuration)
                status = 202
            db.execute('''INSERT INTO reader_report_narrative_requests(project_id,user_id,idempotency_key,narrative_id,request_digest)
                VALUES (%s,%s,%s,%s,%s)''', (project, self.store.user_id, key, identifier, request_sha))
            return self.view(db, project, identifier), status

    def _insert(self, db, project, body, binding, files, frozen, configuration):
        identifier, task_id = str(uuid4()), str(uuid4())
        moment = now()
        snapshot = dict(schema_version=1, kind=TASK_TYPE, workflow_version=WORKFLOW, project_id=project,
                        narrative_id=identifier, request=body, binding_sha256=binding, bundle=frozen,
                        source_file_ids=files)
        input_sha = digest(snapshot)
        task = dict(id=task_id, project_id=project, user_id=self.store.user_id, task_type=TASK_TYPE,
                    idempotency_key=TASK_TYPE+':'+identifier, input_digest=input_sha, input_snapshot=snapshot,
                    workflow_version=WORKFLOW, status='queued', phase='interpret', revision=1, current_attempt=0,
                    reason_code=None, created_at=moment, updated_at=moment)
        self.store.insert_task(db, task, validated_file_ids=files)
        bind(db, kind='task', object_id=task_id, version=configuration)
        db.execute('''INSERT INTO reader_report_narratives
            (id,project_id,user_id,task_id,request_json,request_digest,input_snapshot,input_digest,
             binding_sha256,bundle_sha256,created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (identifier, project, self.store.user_id, task_id, Jsonb(body), digest(body), Jsonb(snapshot),
             input_sha, binding, frozen['bundle_sha256'], moment))
        append_checkpoint(db, task, 'check', 'check', dict(input_digest=input_sha))
        self.store.append_event(db, task, 'created')
        self.store.enqueue(db, task, validated_file_ids=files)
        return identifier

    def row(self, db, project, identifier):
        self.store.require_project(db, project)
        row = db.execute('SELECT * FROM reader_report_narratives WHERE id=%s AND project_id=%s AND user_id=%s',
                         (identifier, project, self.store.user_id)).fetchone()
        if not row:
            raise invalid('research_source_not_found', 404)
        task = self.store.require_task(db, row['task_id'])
        version = input_version(task)
        snapshot = row['input_snapshot']
        if (
            task['project_id'] != project or task['user_id'] != row['user_id']
            or snapshot != task['input_snapshot'] or row['input_digest'] != task['input_digest']
            or snapshot['request'] != row['request_json'] or digest(row['request_json']) != row['request_digest']
            or any(row[key] != version[key] for key in ('binding_sha256', 'bundle_sha256'))
            or version['narrative_id'] != identifier
            or row['request_json']['bundle_sha256'] != version['bundle_sha256']
        ):
            raise source_conflict()
        return row, task

    def _result_call(self, db, row, task):
        if row['result_json'] is None:
            if task['status'] == 'succeeded':
                raise source_conflict()
            return None
        result, raw, call_id = row['result_json'], row['raw_output_json'], row['model_call_id']
        if artifact_sha(row, raw, result, call_id) != row['artifact_sha256']:
            raise source_conflict()
        call = db.execute('''SELECT * FROM model_calls WHERE id=%s AND task_id=%s AND project_id=%s
            AND user_id=%s AND call_key=%s''', (call_id, task['id'], task['project_id'], task['user_id'], CALL_KEY)).fetchone()
        if not call or call['input_digest'] != row['input_snapshot']['bundle']['input_digest']:
            raise source_conflict()
        if task['status'] == 'succeeded':
            from .content import validate_output
            try:
                rebuilt = validate_output(raw, row['input_snapshot']['bundle']['material'])
            except (ValueError, TypeError, KeyError) as exc:
                raise source_conflict() from exc
            if rebuilt != result or call['provider_status'] != 'completed':
                raise source_conflict()
        elif result != {'validation_status': 'invalid'} or task['status'] != 'failed':
            raise source_conflict()
        return call

    def record_for(self, db, project, identifier, base_content):
        from .content import binding_digest

        row, task = self.row(db, project, identifier)
        if row['binding_sha256'] != binding_digest(base_content):
            raise invalid()
        if task['status'] != 'succeeded':
            raise StorageError('reader_report_narrative_required', '请先生成与此报告输入匹配的完整解读。', 409)
        call = self._result_call(db, row, task)
        return {
            **row['result_json'], 'binding_sha256': row['binding_sha256'],
            'provenance': dict(origin='model', provider=call['provider'],
                               prompt_version=call['policy_snapshot']['prompt_version'],
                               narrative_id=row['id'], artifact_sha256=row['artifact_sha256'],
                               bundle_sha256=row['bundle_sha256'], input_sha256=call['input_digest'],
                               model=call['model'], model_call_id=call['id'], provider_response_id=call['provider_response_id'],
                               source=public_provider_provenance(call, task)),
        }

    def material_for_task(self, db, row, task):
        """Re-read content, including the exact image bytes, before new outbound work."""
        from .content import binding_digest, make_figure_inputs
        from app.domain.model_usage.gateway import input_digest

        report = ResearchReportRequest.model_validate(row['request_json']['report'])
        content, files, payload = self._base(db, task['project_id'], report)
        if binding_digest(content) != row['binding_sha256'] or files != task['input_snapshot']['source_file_ids']:
            raise source_conflict()
        frozen = row['input_snapshot']['bundle']
        # Text and figure descriptors were frozen at consent. Only reattach the
        # bytes read from the matching immutable source before transmission.
        try:
            images = make_figure_inputs(_report_images(payload['figures']))
            figures = [{**saved, 'image_url': current['image_url']}
                       for saved, current in zip(frozen['material']['figures'], images, strict=True)]
        except (OSError, TypeError, ValueError) as exc:
            raise source_conflict() from exc
        material = {**frozen['material'], 'figures': figures}
        if input_digest(instructions=frozen['instructions'], payload=material) != frozen['input_digest']:
            raise source_conflict()
        return material

    def view(self, db, project, identifier):
        from app.domain.tasks.waits import allowed_recovery_actions, get_open_wait

        row, task = self.row(db, project, identifier)
        result_call = self._result_call(db, row, task)
        calls = db.execute('''SELECT * FROM model_calls WHERE task_id=%s AND user_id=%s AND project_id=%s
            ORDER BY created_at,id''', (task['id'], task['user_id'], task['project_id'])).fetchall()
        return dict(id=identifier, task=self.store.public_task(task),
                    result=row['result_json'] if task['status'] == 'succeeded' else None,
                    binding_sha256=row['binding_sha256'], bundle_sha256=row['bundle_sha256'],
                    artifact_sha256=row['artifact_sha256'] if task['status'] == 'succeeded' else None,
                    allowed_actions=allowed_recovery_actions(db, task), wait=get_open_wait(db, task),
                    can_regenerate=bool(task['status'] == 'failed' and result_call and result_call['provider_response_id']
                                        and result_call['provider_status'] in TERMINAL),
                    model_calls=[{key: call[key] for key in ('id','model','status','estimated_cost_micro_usd')} |
                                 dict(provider_provenance=public_provider_provenance(call, task)) for call in calls])

    def get(self, project, identifier):
        with self.store.connection() as db:
            return self.view(db, project, identifier)

    def request(self, project, key):
        require_key(key)
        with self.store.connection() as db:
            receipt = self._receipt(db, project, key)
            if not receipt:
                raise invalid('research_source_not_found', 404)
            return self.view(db, project, receipt['narrative_id'])

    def retry(self, project, identifier, revision):
        from .execution import retry_in_transaction

        with self.store.connection(write=True) as db:
            _, task = self.row(db, project, identifier)
            retry_in_transaction(self.store, db, task, revision, assets=self.assets)
            return self.view(db, project, identifier)
