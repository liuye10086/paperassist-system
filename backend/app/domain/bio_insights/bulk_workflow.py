"""Read the current and historical Bulk RNA-seq workflow from saved records."""
from collections import defaultdict
from functools import cache
import json

from app.adapters.bio_analysis_store import BioAnalysisStore, scoped_object
from app.adapters.bio_insights_store import BioInsightsStore, invalid
from app.core.exceptions import StorageError
from app.domain.bioinformatics.contracts import digest
from app.domain.files import require_file
from app.domain.tasks.errors import safe_error_code

from .bulk_delivery_contracts import bulk_attachment_supported
from .bulk_results import bulk_contrast_labels, is_reviewed_bulk
from .bulk_sensitivity import compare_saved_bulk
from .results import checked_members


_TASK_FIELDS = ('t.id AS task_id, t.status, t.phase, t.revision AS task_revision, '
                't.reason_code, t.error_code')
_RESULT_SOURCE = 'bio_insight_result_version'
_PROCESSED_SOURCE = 'bio_processed_dataset_version'
_DESIGN_SOURCE = 'research_design_version'
_MAP_SOURCE = 'bio_observation_map_version'
_RESOURCE_SOURCE = 'bio_resource_version'
_ENRICHMENT = frozenset(('ora', 'gsea_prerank'))
_DISPLAY_RECIPE_PARAMS = frozenset(('normalization', 'transform', 'log1p_offset', 'scaling', 'pca_components', 'seed'))


class BulkWorkflowService(BioInsightsStore):
    def overview(self, project):
        with self.store.connection() as db:
            self.store.require_project(db, project)
            records = self._read_workflow_rows(db, project)
        return project_workflow(project, records)

    def _read_workflow_rows(self, db, project):
        user = self.store.user_id

        def read(statement, *extra):
            return [dict(row) for row in db.execute(statement, (project, user, *extra)).fetchall()]

        datasets = read("""SELECT id,name,current_version_id,updated_at FROM bio_datasets
            WHERE project_id=%s AND created_by=%s AND assay='bulk_rna_counts' ORDER BY updated_at DESC,id""")
        dataset_ids = [row['id'] for row in datasets]
        imports = read(f"""SELECT i.id,i.dataset_id,i.created_at,i.parser_version,v.id AS dataset_version_id,
                   t.input_snapshot->'tabular_config' AS config,t.input_snapshot->'files' AS files,{_TASK_FIELDS}
            FROM bio_imports i JOIN tasks t ON t.id=i.task_id AND t.project_id=i.project_id
            LEFT JOIN bio_dataset_versions v ON v.import_id=i.id AND v.project_id=i.project_id
            WHERE i.project_id=%s AND t.user_id=%s AND i.dataset_id=ANY(%s)""", dataset_ids)
        raw_ids = [row['dataset_version_id'] for row in imports if row['dataset_version_id']]
        designs = read("""SELECT v.id,v.operation,v.content_json,v.created_at,
                   i.current_design_version_id AS current_version_id
            FROM research_design_versions v JOIN research_intakes i ON i.project_id=v.project_id
            WHERE v.project_id=%s AND v.created_by=%s""")
        maps = read("""SELECT v.id,v.set_id,v.raw_dataset_version_id,v.design_version_id,v.mapping_object_id,
                   v.mapping_sha256,v.created_at,s.name,s.current_version_id
            FROM bio_observation_map_versions v JOIN bio_observation_map_sets s
              ON s.id=v.set_id AND s.project_id=v.project_id
            WHERE v.project_id=%s AND v.created_by=%s AND v.raw_dataset_version_id=ANY(%s)""", raw_ids)
        maps_by_id = {row['id']: row for row in maps}
        mapping_revisions = set()
        for row in maps:
            current = maps_by_id.get(row['current_version_id'])
            if current and current['mapping_sha256'] != row['mapping_sha256']:
                mapping_revisions.update((row['id'], current['id']))
        if mapping_revisions:
            objects = BioAnalysisStore(self.assets).mapping_objects
            for identifier in mapping_revisions:
                row = maps_by_id[identifier]
                try:
                    obj = scoped_object(db, project, user, row['mapping_object_id'])
                    if obj['sha256'] == row['mapping_sha256']:
                        rows = json.loads(objects.read(obj))['rows']
                        row['mapping_signature'] = digest(sorted(rows, key=lambda item: item['barcode']))
                except (StorageError, KeyError, TypeError, ValueError):
                    # The fixed map route reports byte integrity. The overview still lists its identity.
                    continue
        recipes = read("""SELECT v.id,v.setup_id,v.raw_dataset_version_id,v.observation_map_version_id,
                   v.design_version_id,v.params_json,v.created_at,s.name,s.current_recipe_version_id AS current_version_id
            FROM bio_analysis_recipe_versions v JOIN bio_analysis_setups s ON s.id=v.setup_id AND s.project_id=v.project_id
            WHERE v.project_id=%s AND v.created_by=%s AND v.raw_dataset_version_id=ANY(%s)
              AND v.recipe_code='tabular_quantitative_v1'""", raw_ids)
        analysis_runs = read(f"""SELECT r.id,r.raw_dataset_version_id,r.recipe_version_id,r.created_at,
                   r.processed_dataset_version_id AS processed_version_id,p.steps_json AS steps,{_TASK_FIELDS}
            FROM bio_analysis_runs r JOIN tasks t ON t.id=r.task_id AND t.project_id=r.project_id
            LEFT JOIN bio_processed_dataset_versions p ON p.id=r.processed_dataset_version_id AND p.project_id=r.project_id
            WHERE r.project_id=%s AND r.created_by=%s AND r.recipe_version_id=ANY(%s)
              AND t.user_id=r.created_by""", [row['id'] for row in recipes])
        processed_ids = [row['processed_version_id'] for row in analysis_runs if row['processed_version_id']]
        plans = read("""WITH RECURSIVE bulk_plans(id,plan_id,project_id,user_id) AS (
            SELECT v.id,v.plan_id,v.project_id,v.user_id FROM bio_insight_plan_versions v
            WHERE v.project_id=%s AND v.user_id=%s AND (
                (v.kind='comparison' AND v.config_json->>'mode'='bulk_counts'
                    AND v.config_json->>'bulk_model'='shared_wald_v1')
                OR EXISTS (SELECT 1 FROM bio_insight_plan_sources s WHERE s.plan_version_id=v.id
                    AND s.project_id=v.project_id AND s.user_id=v.user_id AND s.processed_version_id=ANY(%s)))
            UNION
            SELECT v.id,v.plan_id,v.project_id,v.user_id FROM bulk_plans b
            JOIN bio_insight_result_versions r ON r.plan_version_id=b.id AND r.project_id=b.project_id AND r.user_id=b.user_id
            JOIN bio_insight_plan_sources s ON s.source_result_version_id=r.id AND s.project_id=r.project_id AND s.user_id=r.user_id
            JOIN bio_insight_plan_versions v ON v.id=s.plan_version_id AND v.project_id=s.project_id AND v.user_id=s.user_id
        ), roots AS (
            SELECT DISTINCT plan_id,project_id,user_id FROM bulk_plans
        )
        SELECT v.id,v.plan_id,v.kind,v.decision,v.config_json,v.created_at,p.current_version_id,
               COALESCE(v.design_checks_json->>'plan_name',p.name) AS name,
               (v.design_checks_json->>'executable')::boolean AS executable,
               v.design_checks_json->'blocking_reasons' AS blockers,
               CASE WHEN v.kind='comparison' THEN (
                   SELECT COALESCE(jsonb_agg(jsonb_build_object(
                       'processed_version_id', sample.value->>'processed_version_id',
                       'sample_id', sample.value->>'sample_id', 'condition', sample.value->>'condition')), '[]'::jsonb)
                   FROM jsonb_array_elements(COALESCE(v.design_checks_json->'bulk_model'->'samples', '[]'::jsonb)) AS sample(value)
               ) END AS bulk_model_samples,
               EXISTS (SELECT 1 FROM bulk_plans b WHERE b.id=v.id) AS bulk_related
        FROM roots b JOIN bio_insight_plans p ON p.id=b.plan_id AND p.project_id=b.project_id AND p.user_id=b.user_id
        JOIN bio_insight_plan_versions v ON v.plan_id=p.id AND v.project_id=p.project_id AND v.user_id=p.user_id""", processed_ids)
        plan_ids = [row['id'] for row in plans]
        bindings = read("""SELECT plan_version_id,source_kind,source_id,role,source_sha256,locator_json
            FROM bio_insight_plan_sources WHERE project_id=%s AND user_id=%s AND plan_version_id=ANY(%s)
            ORDER BY plan_version_id,ordinal""", plan_ids)
        insight_runs = read(f"""SELECT r.id,r.plan_version_id,r.result_version_id,r.created_at,
                   v.summary_json->>'enrichment_status' AS outcome,v.summary_json->>'not_applicable_reason' AS reason,
                   {_TASK_FIELDS}
            FROM bio_insight_runs r JOIN tasks t ON t.id=r.task_id AND t.project_id=r.project_id AND t.user_id=r.user_id
            LEFT JOIN bio_insight_result_versions v ON v.id=r.result_version_id AND v.project_id=r.project_id AND v.user_id=r.user_id
            WHERE r.project_id=%s AND r.user_id=%s AND r.plan_version_id=ANY(%s)""", plan_ids)
        resource_ids = [row['source_id'] for row in bindings if row['source_kind'] == _RESOURCE_SOURCE]
        resources = read(f"""WITH roots AS (
            SELECT DISTINCT root_id,project_id,user_id FROM bio_resource_versions
            WHERE project_id=%s AND user_id=%s AND (id=ANY(%s) OR config_json->>'offline_enrichment'='true')
        )
        SELECT v.id,v.root_id,v.version,v.title AS name,v.config_json,v.created_at,{_TASK_FIELDS}
        FROM roots r JOIN bio_resource_versions v ON v.root_id=r.root_id AND v.project_id=r.project_id AND v.user_id=r.user_id
        JOIN tasks t ON t.id=v.task_id AND t.project_id=v.project_id AND t.user_id=v.user_id""", resource_ids)
        return dict(datasets=datasets, imports=imports, designs=designs, maps=maps, recipes=recipes,
                    analysis_runs=analysis_runs, plans=plans, bindings=bindings, insight_runs=insight_runs,
                    resources=resources)

    def sensitivity(self, project, baseline_version_id, scenario_version_id, baseline_selection, scenario_selection,
                    *, page=1, page_size=100, change_stream=None):
        from .bulk_delivery_cache import heavy_slot
        with heavy_slot(self.assets, project), self.store.connection() as db:
            self.store.require_project(db, project)
            return compare_saved_bulk(self, db, project, baseline_version_id, scenario_version_id,
                                      baseline_selection, scenario_selection, page=page, page_size=page_size,
                                      change_stream=change_stream)

    def evidence(self, project, evidence_requests, *, baseline_version_id=None):
        from .service import BioInsightsService
        from .sources import InsightSourceReader

        reader = InsightSourceReader(self.assets)
        insights = BioInsightsService(self.assets)
        with self.store.connection() as db:
            self.store.require_project(db, project)
            baseline = (self.require(db, 'bio_insight_result_versions', project, baseline_version_id)
                        if baseline_version_id else None)
            baseline_sources = self._processed_evidence_sources(db, project, baseline) if baseline else set()
            resolved = []
            seen = set()
            for request in evidence_requests:
                kind, identifier = request['kind'], request['source_id']
                if (kind, identifier) in seen:
                    raise invalid('bio_insight_source_unsupported', 422)
                seen.add((kind, identifier))
                common = dict(kind=kind, source_id=identifier, note=request.get('note'))
                if kind == 'experimental_material':
                    row = dict(require_file(db, project, identifier))
                    if row['uploader_id'] is None:
                        self.assets.original(row)
                    else:
                        row, _, _ = reader.original(db, project, identifier)
                    resolved.append(dict(**common, classification='user_declared_experimental_material',
                                         verification_status='attachment_integrity_verified', file_id=row['id'],
                                         sha256=row['sha256'], filename=row['filename'], file_type=row['file_type'],
                                         size_bytes=row['size_bytes']))
                elif kind == 'independent_analysis':
                    result = self.require(db, 'bio_insight_result_versions', project, identifier)
                    plan = self.require(db, 'bio_insight_plan_versions', project, result['plan_version_id'])
                    if result['kind'] != 'comparison' or result['provenance'] != 'system_computed' or plan['decision'] != 'confirmed':
                        raise invalid('bio_insight_source_unsupported', 422)
                    if baseline and (identifier == baseline['id'] or self._is_evidence_descendant(db, project, result, baseline['id'])):
                        raise invalid('bio_insight_source_unsupported', 422)
                    task = self.store.require_task(db, result['task_id'])
                    insights.require_sources(db, task, runtime=False)
                    checked_members(self, db, project, result)
                    sources = self._processed_evidence_sources(db, project, result)
                    resolved.append(dict(**common, classification='independent_computational_analysis',
                                         verification_status='saved_execution_verified', independence_status='unverified',
                                         result_version_id=identifier, run_id=result['run_id'], task_id=task['id'],
                                         plan_version_id=plan['id'], sha256=result['manifest_sha256'],
                                         provenance=result['provenance'], inference_scope=result['inference_scope'],
                                         shared_processed_source_ids=sorted(sources & baseline_sources)))
                else:
                    raise invalid('bio_insight_source_unsupported', 422)
            return resolved

    def _processed_evidence_sources(self, db, project, result):
        rows = db.execute("""SELECT processed_version_id FROM bio_insight_plan_sources
            WHERE project_id=%s AND user_id=%s AND plan_version_id=%s AND processed_version_id IS NOT NULL""",
            (project, self.store.user_id, result['plan_version_id'])).fetchall()
        return {row['processed_version_id'] for row in rows}

    def _is_evidence_descendant(self, db, project, result, baseline_id):
        return bool(db.execute("""WITH RECURSIVE parents(id) AS (
            SELECT source_result_version_id FROM bio_insight_plan_sources
              WHERE project_id=%s AND user_id=%s AND plan_version_id=%s AND source_result_version_id IS NOT NULL
            UNION
            SELECT s.source_result_version_id FROM parents p
            JOIN bio_insight_result_versions r ON r.id=p.id AND r.project_id=%s AND r.user_id=%s
            JOIN bio_insight_plan_sources s ON s.plan_version_id=r.plan_version_id AND s.project_id=r.project_id
              AND s.user_id=r.user_id AND s.source_result_version_id IS NOT NULL
        ) SELECT 1 FROM parents WHERE id=%s""",
            (project, self.store.user_id, result['plan_version_id'], project, self.store.user_id, baseline_id)).fetchone())


def _scientific_input(raw):
    files = {file['id']: file['sha256'] for file in raw.get('files') or []}
    config = {key: value for key, value in (raw.get('config') or {}).items()
              if key not in ('name', 'dataset_id', 'expected_dataset_revision', 'file_ids', 'quality_reports')}
    config['tables'] = [{**table, 'file_id': files.get(table['file_id'], table['file_id'])}
                        for table in config.get('tables', [])]
    return digest((raw.get('parser_version'), config))


def _scientific_design(design, samples):
    content = design['content_json']
    records = [row for row in content.get('samples', []) if not samples or row['id'] in samples]
    experiments = {row['experiment_id'] for row in records}
    return digest(dict(
        samples=sorted(records, key=lambda row: row['id']),
        experiments=sorted(({key: value for key, value in row.items() if key not in ('source', 'processing_stage')}
                            for row in content.get('experiments', []) if row['id'] in experiments),
                           key=lambda row: row['id']),
        observation=content.get('observation'),
        comparisons=sorted(({key: row[key] for key in ('id', 'experiment_id', 'group_id', 'reference_group_id')}
                            for row in content.get('comparisons', []) if row['experiment_id'] in experiments),
                           key=lambda row: row['id']),
        exclusions=sorted(content.get('exclusions', [])),
    ))


def _version_change(kind, fixed, current, projection):
    if fixed and current and fixed['id'] != current['id'] and projection(fixed) != projection(current):
        return frozenset(((kind, fixed['id'], current['id']),))
    return frozenset()


def _recipe_parameters(row, presentation=False):
    ignore = {'output_language'} if presentation else _DISPLAY_RECIPE_PARAMS | {'output_language'}
    params = {key: value for key, value in row['params_json'].items() if key not in ignore}
    for key in ('exclude_samples', 'exclude_features'):
        params[key] = sorted(params.get(key, []))
    return params


def _resource_parameters(row):
    return {key: value for key, value in row['config_json'].items()
            if key not in ('title', 'output_language', 'expected_revision')}


def _comparison_parameters(config):
    def samples(group):
        keys = group.get('sample_keys', [])
        return sorted(keys, key=lambda key: (key['processed_version_id'], key['sample_id']))

    contrasts = []
    for contrast in config.get('contrasts', []):
        groups = [dict(group, sample_keys=samples(group)) for group in contrast['groups']]
        contrasts.append({key: value for key, value in contrast.items() if key != 'name'} | {'groups': groups})
    return config | dict(contrasts=contrasts, family_contrast_ids=sorted(config.get('family_contrast_ids', [])),
                         covariates=[{key: value for key, value in field.items() if key != 'name'}
                                     for field in config.get('covariates', [])],
                         excluded_samples=sorted(
                             (item['processed_version_id'], item['sample_id']) for item in config.get('excluded_samples', [])))


def _record(kind, row, refs, reasons=(), *, status=None, **extra):
    return dict(kind=kind, label=row.get('name'), created_at=row['created_at'], refs={k: v for k, v in refs.items() if v},
                status=status or row.get('status') or 'ready', stale=bool(reasons),
                stale_reasons=[dict(kind=kind, version_id=old, current_version_id=new) for kind, old, new in sorted(reasons)],
                reason=row.get('reason') or row.get('reason_code'), task_status=row.get('status'),
                task_revision=row.get('task_revision'), phase=row.get('phase'),
                error_code=safe_error_code(row.get('error_code')), **extra)


def _stage(key, items, depends_on=(), *, chosen=None, status=None):
    return dict(key=key, items=items, depends_on=depends_on,
                status=status or (chosen['status'] if chosen else 'ready'),
                refs=chosen['refs'] if chosen else {}, stale=chosen['stale'] if chosen else False,
                stale_reasons=chosen['stale_reasons'] if chosen else [], reason=chosen['reason'] if chosen else None)


def _ordered(items):
    return sorted(items, key=lambda item: (item['created_at'], tuple(item['refs'].values())), reverse=True)


def _primary(items):
    return next((item for item in items if not item['stale']), next(iter(items), None))


def project_workflow(project, records):
    datasets, designs, maps, recipes, plans = ({row['id']: row for row in records[key]}
                                                for key in ('datasets', 'designs', 'maps', 'recipes', 'plans'))
    raw = {row['dataset_version_id']: row for row in records['imports'] if row['dataset_version_id']}
    processed = {row['processed_version_id']: row for row in records['analysis_runs'] if row['processed_version_id']}
    results = {row['result_version_id']: row for row in records['insight_runs'] if row['result_version_id']}
    resources = {row['id']: row for row in records['resources']}
    current_resources = {}
    for row in sorted(resources.values(), key=lambda item: item['version']):
        if row['status'] == 'succeeded':
            current_resources[row['root_id']] = row
    sources, runs, versions_with_runs = defaultdict(list), defaultdict(list), defaultdict(set)
    for row in records['bindings']:
        sources[row['plan_version_id']].append(row)
    for row in records['insight_runs']:
        runs[row['plan_version_id']].append(row)
        versions_with_runs[plans[row['plan_version_id']]['plan_id']].add(row['plan_version_id'])

    @cache
    def raw_signature(identifier):
        return _scientific_input(raw[identifier]) if identifier in raw else identifier

    @cache
    def raw_reasons(identifier):
        fixed = raw.get(identifier)
        if not fixed:
            return frozenset()
        current = raw.get(datasets[fixed['dataset_id']]['current_version_id'])
        if current and raw_signature(identifier) != raw_signature(current['dataset_version_id']):
            return frozenset((('dataset_version', identifier, current['dataset_version_id']),))
        return frozenset()

    @cache
    def design_signature(identifier, raw_id):
        sample_columns = (raw.get(raw_id, {}).get('config') or {}).get('sample_columns') or []
        return _scientific_design(designs[identifier], set(sample_columns)) if identifier in designs else identifier

    @cache
    def design_reasons(identifier, raw_id=None):
        fixed = designs.get(identifier)
        current = designs.get(fixed['current_version_id']) if fixed else None
        return _version_change('design_version', fixed, current, lambda row: design_signature(row['id'], raw_id))

    @cache
    def map_signature(identifier):
        row = maps.get(identifier)
        return (row.get('mapping_signature') or row['mapping_sha256']) if row else identifier

    @cache
    def map_reasons(identifier):
        row = maps.get(identifier)
        if not row:
            return frozenset()
        current = maps.get(row['current_version_id'])
        return (raw_reasons(row['raw_dataset_version_id'])
                | design_reasons(row.get('design_version_id'), row['raw_dataset_version_id'])
                | _version_change('observation_map_version', row, current, lambda item: map_signature(item['id'])))

    @cache
    def recipe_signature(identifier, presentation):
        row = recipes[identifier]
        raw_id = row['raw_dataset_version_id']
        return digest(dict(raw=raw_signature(raw_id), params=_recipe_parameters(row, presentation),
                           design=design_signature(row.get('design_version_id'), raw_id),
                           mapping=map_signature(row.get('observation_map_version_id'))))

    @cache
    def recipe_reasons(identifier, presentation):
        row = recipes[identifier]
        raw_id = row['raw_dataset_version_id']
        current = recipes.get(row['current_version_id'])
        return (raw_reasons(raw_id) | design_reasons(row.get('design_version_id'), raw_id)
                | map_reasons(row.get('observation_map_version_id'))
                | _version_change('recipe_version', row, current, lambda item: recipe_signature(item['id'], presentation)))

    @cache
    def processed_signature(identifier):
        row = processed.get(identifier)
        if not row:
            return identifier
        return digest((raw[row['raw_dataset_version_id']]['dataset_id'], recipe_signature(row['recipe_version_id'], False)))

    @cache
    def plan_signature(identifier):
        row = plans[identifier]
        config = {key: value for key, value in row['config_json'].items()
                  if key != 'output_language' or row['kind'] == 'figure'}
        substitutions = {source['source_id']: processed_signature(source['source_id'])
                         for source in sources[identifier]
                         if row['kind'] == 'comparison' and source['source_kind'] == _PROCESSED_SOURCE}

        def project_values(value):
            if isinstance(value, dict):
                return {key: project_values(member) for key, member in value.items()}
            if isinstance(value, (list, tuple)):
                return [project_values(member) for member in value]
            return substitutions.get(value, value) if isinstance(value, str) else value

        projected_config = project_values(config)
        if row['kind'] == 'comparison':
            projected_config = _comparison_parameters(projected_config)
        return digest(dict(config=projected_config, sources=[
            (source['source_kind'], substitutions.get(source['source_id'], source['source_id']),
             source.get('role'), source.get('locator_json'))
            for source in sources[identifier]
        ]))

    @cache
    def resource_reasons(identifier):
        row = resources.get(identifier)
        return _version_change('resource_version', row, current_resources.get(row['root_id']), _resource_parameters) if row else frozenset()

    @cache
    def plan_reasons(identifier):
        row = plans[identifier]
        reasons = _version_change('plan_version', row, plans.get(row['current_version_id']), lambda item: plan_signature(item['id']))
        for source in sources[identifier]:
            kind, source_id = source['source_kind'], source['source_id']
            if kind == _PROCESSED_SOURCE and source_id in processed:
                reasons |= recipe_reasons(processed[source_id]['recipe_version_id'], row['kind'] == 'figure')
            elif kind == _RESULT_SOURCE and source_id in results:
                reasons |= plan_reasons(results[source_id]['plan_version_id'])
            elif kind == _RESOURCE_SOURCE:
                reasons |= resource_reasons(source_id)
            elif kind == _DESIGN_SOURCE:
                reasons |= design_reasons(source_id)
            elif kind == _MAP_SOURCE:
                reasons |= map_reasons(source_id)
        return reasons

    @cache
    def reviewed(identifier):
        plan = plans[identifier]
        return is_reviewed_bulk({'kind': plan['kind'], 'plan_config': plan['config_json']})

    @cache
    def delivery_eligible(identifier):
        plan = plans[identifier]
        bindings = sources[identifier]
        if not bulk_attachment_supported(plan['kind'], plan['config_json'], bindings):
            return False
        source = next(binding for binding in bindings if binding['source_kind'] in (_RESULT_SOURCE, _PROCESSED_SOURCE))
        if source['source_kind'] == _PROCESSED_SOURCE:
            return source['source_id'] in processed
        upstream = results.get(source['source_id'])
        if not upstream or upstream['status'] != 'succeeded':
            return False
        upstream_id = upstream['plan_version_id']
        if plan['kind'] == 'figure' and plan['config_json'].get('bulk_enrichment_render') is True:
            return plans[upstream_id]['kind'] in _ENRICHMENT and delivery_eligible(upstream_id)
        return reviewed(upstream_id)

    @cache
    def lineage(identifier):
        direct_processed = {s['source_id'] for s in sources[identifier] if s['source_kind'] == _PROCESSED_SOURCE}
        direct_results = {s['source_id'] for s in sources[identifier] if s['source_kind'] == _RESULT_SOURCE}
        direct_comparisons = {sid for sid in direct_results if sid in results and reviewed(results[sid]['plan_version_id'])}
        all_processed, all_comparisons = set(direct_processed), set(direct_comparisons)
        for result in direct_results & results.keys():
            upstream = lineage(results[result]['plan_version_id'])
            all_processed.update(upstream['processed_version_ids'])
            all_comparisons.update(upstream['comparison_version_ids'])
        return dict(processed_version_ids=sorted(all_processed), direct_processed_version_ids=sorted(direct_processed),
                    comparison_version_ids=sorted(all_comparisons), direct_comparison_version_ids=sorted(direct_comparisons),
                    dataset_ids=sorted({raw[processed[sid]['raw_dataset_version_id']]['dataset_id']
                                        for sid in all_processed if sid in processed}))

    def raw_refs(raw_id):
        row = raw.get(raw_id, {})
        return dict(dataset_id=row.get('dataset_id'), dataset_version_id=raw_id, import_id=row.get('id'))

    def recipe_refs(recipe_id):
        row = recipes[recipe_id]
        mapping_id = row.get('observation_map_version_id')
        return dict(**raw_refs(row['raw_dataset_version_id']), setup_id=row['setup_id'], recipe_version_id=recipe_id,
                    design_version_id=row.get('design_version_id'), observation_map_version_id=mapping_id,
                    observation_map_set_id=maps.get(mapping_id, {}).get('set_id'))

    def run_refs(row):
        return dict(**recipe_refs(row['recipe_version_id']), analysis_run_id=row['id'],
                    processed_version_id=row['processed_version_id'], task_id=row['task_id'])

    def insight_record(plan, row=None):
        identifier = plan['id']
        parents = lineage(identifier)
        versions = parents['processed_version_ids']
        refs = run_refs(processed[versions[0]]) if len(versions) == 1 and versions[0] in processed else {}
        refs = dict(refs, plan_id=plan['plan_id'], plan_version_id=identifier,
                    insight_run_id=row['id'] if row else None, task_id=row['task_id'] if row else None,
                    result_version_id=row['result_version_id'] if row else None)
        if row:
            status = row['outcome'] if row['status'] == 'succeeded' and row.get('outcome') in ('skipped', 'not_applicable') else row['status']
        else:
            status = ('dependency_blocked' if plan.get('executable') is False
                      else 'waiting_confirmation' if plan['decision'] == 'draft' else 'ready')
        contrasts = []
        if reviewed(identifier):
            labels = bulk_contrast_labels({'plan_config': plan['config_json']})
            contrasts = [dict(contrast_id=cid, numerator=pair[0], denominator=pair[1]) for cid, pair in labels.items()]
        return _record(plan['kind'], dict(row or plan, name=plan['name']), refs, plan_reasons(identifier), status=status,
                       contrasts=contrasts, figure_type=plan['config_json'].get('figure_type'), decision=plan['decision'],
                       blockers=plan.get('blockers') or [], **parents)

    def comparison_eligibility(item):
        plan = plans[item['refs']['plan_version_id']]
        raw_by_processed = {sid: processed[sid]['raw_dataset_version_id'] for sid in item['processed_version_ids'] if sid in processed}
        raw_lineage = sorted({(raw[rid]['dataset_id'], rid) for rid in raw_by_processed.values() if rid in raw})
        samples = plan.get('bulk_model_samples') or []
        sample_keys = sorted({(digest((raw_by_processed[s['processed_version_id']], s['sample_id'])), s['condition'])
                              for s in samples if s.get('processed_version_id') in raw_by_processed
                              and s.get('sample_id') and s.get('condition')})
        return dict(item, sensitivity_lineage=[list(value) for value in raw_lineage],
                    sensitivity_samples=[list(value) for value in sample_keys],
                    sensitivity_identity=[plan['config_json'].get(key) for key in
                                          ('species_taxon_id', 'namespace', 'reference_version')])

    design_items = _ordered([_record('design', row, {'design_version_id': row['id']},
                                    status='succeeded', operation=row['operation'])
                             for row in designs.values()])
    current_design_id = next((row['current_version_id'] for row in designs.values()), None)
    current_design = next((item for item in design_items if item['refs']['design_version_id'] == current_design_id), None)
    design_stage = _stage('design', design_items, chosen=current_design)
    if current_design:
        design_stage['operation'] = current_design['operation']
    data_items = _ordered([_record('import', dict(row, name=datasets[row['dataset_id']]['name']),
                                  dict(dataset_id=row['dataset_id'], dataset_version_id=row['dataset_version_id'],
                                       import_id=row['id'], task_id=row['task_id']), raw_reasons(row['dataset_version_id']))
                           for row in records['imports']])
    map_items = _ordered([_record('observation_map', row, dict(**raw_refs(row['raw_dataset_version_id']),
                                  observation_map_version_id=row['id'], observation_map_set_id=row['set_id'],
                                  design_version_id=row.get('design_version_id')), map_reasons(row['id']), status='succeeded')
                          for row in maps.values()])
    qc_items = [_record('analysis', row, run_refs(row), recipe_reasons(row['recipe_version_id'], True),
                        steps=[dict(step, status={'completed': 'succeeded', 'not_requested': 'skipped',
                                                 'not_computable': 'not_applicable'}.get(step['status'], step['status']))
                               for step in row.get('steps') or []])
                for row in records['analysis_runs']]
    recipe_runs = {row['recipe_version_id'] for row in records['analysis_runs']}
    for row in recipes.values():
        if row['id'] == row['current_version_id'] and row['id'] not in recipe_runs:
            qc_items.append(_record('recipe', row, recipe_refs(row['id']), recipe_reasons(row['id'], True)))
    qc_items = _ordered(qc_items)
    insight_items = []
    for plan in plans.values():
        identifier = plan['id']
        if plan.get('bulk_related') is False or plan['kind'] == 'comparison' and not reviewed(identifier):
            continue
        insight_items.extend(insight_record(plan, run) for run in runs[identifier])
        if identifier != plan['current_version_id'] or runs[identifier]:
            continue
        reusable = any(plan_signature(prior) == plan_signature(identifier)
                       and any(run['status'] in ('queued', 'running', 'waiting_confirmation', 'succeeded')
                               for run in runs[prior])
                       for prior in versions_with_runs[plan['plan_id']])
        if not reusable:
            insight_items.append(insight_record(plan))
    insight_items = _ordered(insight_items)
    comparisons = [item for item in insight_items if item['kind'] == 'comparison' and item['refs'].get('result_version_id')]
    descendants = [dict(item, delivery_eligible=delivery_eligible(item['refs']['plan_version_id']))
                   for item in insight_items if item['kind'] != 'comparison' and item['refs'].get('result_version_id')]
    resource_items = _ordered([_record('resource', row, dict(resource_version_id=row['id'], task_id=row['task_id']),
                                       resource_reasons(row['id'])) for row in resources.values()])

    selected_data = _primary(data_items)
    dataset_id = selected_data['refs'].get('dataset_id') if selected_data else None
    selected_qc_items = [item for item in qc_items if item['refs'].get('dataset_id') == dataset_id]
    selected_qc = _primary(selected_qc_items)
    selected_setup = selected_qc['refs']['setup_id'] if selected_qc else None
    current_qc = next((item for item in selected_qc_items if item['refs']['setup_id'] == selected_setup
                       and item['status'] == 'succeeded' and item['refs'].get('processed_version_id')
                       and not recipe_reasons(item['refs']['recipe_version_id'], False)), None)
    differential_items = [item for item in insight_items if item['kind'] == 'comparison']
    current_differential = [item for item in differential_items if dataset_id in item['dataset_ids']]
    selected_differential = _primary(current_differential)
    baseline = _primary([item for item in current_differential if item['status'] == 'succeeded'
                         and item['refs'].get('result_version_id')])
    baseline_id = baseline['refs']['result_version_id'] if baseline else None
    functional_items = [item for item in insight_items if item['kind'] in _ENRICHMENT]
    selected_functional = _primary([item for item in functional_items if baseline_id in item['comparison_version_ids']])
    ready_baseline = baseline and not baseline['stale']
    functional_figures = [item for item in insight_items if item['kind'] == 'figure'
                          and item['figure_type'] in ('enrichment', 'gsea')]
    qc_figures = [item for item in insight_items if item['kind'] == 'figure'
                  and item['direct_processed_version_ids'] and not item['comparison_version_ids']]
    differential_extras = [item for item in insight_items if item['kind'] == 'candidate'
                           or item['kind'] == 'figure' and item['comparison_version_ids']
                           and item['figure_type'] not in ('enrichment', 'gsea')]
    qc_blocked = not selected_qc and (not selected_data or selected_data['status'] != 'succeeded')
    qc_stage = _stage('qc', _ordered(qc_items + qc_figures), ('data',), chosen=selected_qc,
                      status='dependency_blocked' if qc_blocked else None)
    if current_qc and (current_qc is not selected_qc or current_qc['stale']):
        qc_stage['reusable_processed_refs'] = current_qc['refs']
    differential_blocked = not current_qc and (not selected_differential or selected_differential['stale'])
    stages = [
        design_stage,
        _stage('data', _ordered(data_items + map_items), chosen=selected_data),
        qc_stage,
        _stage('differential', _ordered(differential_items + differential_extras), ('qc',), chosen=selected_differential,
               status='dependency_blocked' if differential_blocked else None),
        _stage('functional', _ordered(functional_items + functional_figures + resource_items), ('differential',), chosen=selected_functional,
               status='dependency_blocked' if not selected_functional and not ready_baseline else None),
        _stage('delivery', comparisons + descendants, ('differential',), chosen=baseline,
               status='ready' if ready_baseline else 'dependency_blocked'),
    ]
    return dict(project_id=project, stages=stages,
                comparisons=[comparison_eligibility(item) if item['status'] == 'succeeded' else item for item in comparisons],
                descendants=descendants)
