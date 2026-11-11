"""Project-owned Bulk RNA-seq delivery from published, versioned outputs."""
from collections import Counter
import csv
from dataclasses import dataclass
from heapq import nsmallest
from itertools import islice
import json

from app.adapters.bio_analysis_store import BioAnalysisStore
from app.adapters.bio_insights_store import invalid
from app.domain.bioinformatics.contracts import canonical, digest
from app.domain.source_byte_verification import VerificationPhase

from .bulk_delivery_contracts import bulk_attachment_supported
from .bulk_results import (
    BULK_DIRECTIONS, _REQUIRED_COLUMNS, _counts, bulk_contrast_labels, bulk_rank_key,
    bulk_row_class, finite_metric, is_reviewed_bulk,
)
from .contracts import BulkSelection
from .results import BioInsightResultService, checked_members
from .service import BioInsightsService


PROCESSED = 'bio_processed_dataset_version'
RESULT = 'bio_insight_result_version'
RESOURCE = 'bio_resource_version'
_QC_FIGURES = ('qc_missing', 'expression_distribution', 'pca', 'correlation_heatmap')
_ENRICHMENT_KINDS = ('ora', 'gsea_prerank')
_TOP_ROWS = 5
_MAX_IMAGE_BYTES = 32 * 1024 * 1024
_LIMITS = {
    'zh': (
        '样本和生物学单位按已确认的设计记录。生物学独立性和统计功效需要实验依据。',
        '质控与展示图用于检查数据。推断基于已保存的原始 counts 模型。',
        '本报告展示原始统计的摘要。0、缺失、不适用和未选入报告的项目各有独立含义。',
        '候选筛选、通路富集和独立计算的支持属于计算证据。实验材料的状态和来源单独列出。',
    ),
    'en': (
        'Samples and biological units follow the reviewed design. Biological independence and statistical power require experimental evidence.',
        'Quality checks and display plots characterize the data. Inference uses the saved raw-count model.',
        'This report summarizes saved statistics. Zero, missing values, inapplicable analyses and items omitted from the report have distinct meanings.',
        'Candidate selection, enrichment and independent computational support are computational evidence. Experimental materials have their own sources and status.',
    ),
}


def _member(members, key, format):
    member = members.get(key)
    if not member or member['format'] != format:
        raise invalid('bio_insight_source_incomplete', 422)
    return member


def _table_rows(objects, member):
    with objects.path(member['object_key']).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t', strict=True)
        fields = reader.fieldnames or []
        if not fields or len(fields) != len(set(fields)):
            raise invalid()
        for row in reader:
            if None in row or None in row.values():
                raise invalid()
            yield row


def _report_contrasts(objects, member, labels, selections, design):
    counts = {cid: Counter() for cid in labels}
    top = {cid: [] for cid in labels}
    for row in _table_rows(objects, member):
        cid = row.get('contrast_id')
        if (not _REQUIRED_COLUMNS.issubset(row) or labels.get(cid) != (row['numerator'], row['denominator'])
                or not row['feature_id'] or not row['row_key']):
            raise invalid()
        selection = selections[cid]
        category = bulk_row_class(row, selection)
        counts[cid][category] += 1
        if category in BULK_DIRECTIONS and selection.direction in ('both', category):
            rank = bulk_rank_key(row, selection)
            best = top[cid]
            if len(best) < _TOP_ROWS or rank < best[-1][0]:
                best.append((rank, row | {'direction': category}))
                best.sort(key=lambda item: item[0])
                del best[_TOP_ROWS:]
    if any(not counter for counter in counts.values()):
        raise invalid('bio_insight_source_incomplete', 422)
    units = {unit['contrast_id']: unit for unit in design['actual_units']}
    results = []
    for cid, (numerator, denominator) in labels.items():
        selection = selections[cid]
        totals = _counts(counts[cid])
        totals['selected'] = totals['deg' if selection.direction == 'both' else selection.direction]
        results.append(dict(contrast_id=cid, numerator=numerator, denominator=denominator,
                            direction='numerator_relative_to_denominator', counts=totals, units=units.get(cid),
                            selection=selection.model_dump(mode='json'), top_rows=[row for _, row in top[cid]]))
    return results


def _selection_map(labels, selections):
    by_id = {}
    for value in selections:
        selection = BulkSelection.model_validate(value)
        cid = selection.contrast_id
        if cid not in labels or cid in by_id:
            raise invalid()
        by_id[cid] = selection
    return {cid: by_id.get(cid) or BulkSelection(contrast_id=cid) for cid in labels}


@dataclass(frozen=True)
class _Published:
    row: dict
    manifest: dict
    members: dict
    envelope: dict

    @property
    def config(self):
        return self.envelope['config']

    @property
    def methods(self):
        return self.manifest.get('methods', {})

    @property
    def summary(self):
        return self.manifest.get('summary', {})


class BulkDeliveryService(BioInsightResultService):
    def _published(self, db, project, identifier, phase, *, resource=False):
        table = 'bio_resource_versions' if resource else 'bio_insight_result_versions'
        row = self.require(db, table, project, identifier)
        manifest, members = checked_members(self, db, project, row, resource=resource)
        task = self.store.require_task(db, row['task_id'])
        envelope = BioInsightsService(self.assets)._require_sources_in_phase(db, task, phase=phase, runtime=False)
        return _Published(row, manifest, {m['key']: m for m in members}, envelope)

    def _result_reference(self, project, value, *, resource=False):
        row = value.row
        public = dict(version_id=row['id'], task_id=row['task_id'], kind=row['kind'],
                      manifest_sha256=row['manifest_sha256'], engine_version=value.manifest.get('engine_version'),
                      identity=value.manifest.get('identity', {}), members=[
                          self.public_member(project, row['id'], item, resource) for item in value.members.values()
                          if item['role'] not in ('input_snapshot', 'original_resource')])
        if resource:
            return public | dict(title=row.get('title'), species_taxon_id=row['species_taxon_id'],
                                 namespace=row['namespace'], release=row['release'], source=row['source_json'],
                                 usage=row['usage_json'])
        return public | dict(run_id=row['run_id'], plan_version_id=row['plan_version_id'],
                             provenance=row['provenance'], inference_scope=row['inference_scope'])

    def _processed(self, db, project, source, phase):
        analysis = BioAnalysisStore(self.assets)
        version = source['source_id']
        row, manifest, records = analysis._processed_lineage_in_phase(db, project, version, phase=phase)
        if row['manifest_sha256'] != source['sha256'] or manifest.get('assay') != 'bulk_rna_counts':
            raise invalid()
        if self.store.require_task(db, row['task_id'])['status'] != 'succeeded':
            raise invalid('bio_insight_source_incomplete', 422)
        members = {m['key']: m for m in records}
        raw_source = manifest.get('raw_source') or manifest['identity']['raw_source']
        _, raw_manifest, raw_members = analysis._raw_lineage_in_phase(db, project, raw_source, phase=phase)
        raw_lookup = {item['key']: item for item in raw_members}
        mapping_member = raw_lookup.get('sample_mapping')
        mapping = json.loads(analysis.raw_store.objects.read(mapping_member)) if mapping_member else None
        sample_qc = _member(members, 'sample_qc', 'tsv')
        samples = [{**sample, 'processed_version_id': version} for sample in _table_rows(analysis.objects, sample_qc)]
        input_files = [{k: item[k] for k in ('id', 'filename', 'sha256', 'size_bytes') if k in item}
                       for item in raw_manifest.get('source_files', [])]
        summary = {key: item for key, item in manifest['summary'].items() if key != 'qc_metrics'}
        context = dict(version_id=version, raw_dataset_id=raw_source['dataset_id'],
                       raw_dataset_version_id=raw_source['dataset_version_id'], summary=summary, samples=samples,
                       sample_mapping=mapping, steps=manifest.get('steps', []), input_files=input_files,
                       methods=manifest.get('methods', {}), parameters=manifest.get('params', {}),
                       scale=manifest.get('scale', {}), layers=manifest.get('layers', {}),
                       quality_reports=raw_manifest.get('checks', {}).get('quality_reports', []))
        reference = dict(version_id=version, task_id=row['task_id'], manifest_sha256=row['manifest_sha256'],
                         engine_version=manifest.get('engine_version'), identity=manifest.get('identity', {}),
                         raw_source=raw_source, members=[analysis.public_member(project, version, m) for m in records])
        figures = []
        for kind in _QC_FIGURES:
            png = members.get(kind + '_png')
            if png:
                public = analysis.public_member(project, version, png)
                figures.append((dict(version_id=version, source_version_id=version, source_kind=PROCESSED,
                                     source_manifest_sha256=source['sha256'], figure_type=kind, title=None,
                                     summary={'output_language': context['parameters'].get('output_language')}, png=public),
                                png, analysis.objects))
        return context, reference, figures

    def _figure(self, project, value, source):
        config, methods = value.config, value.methods
        figure_type, kind = config['figure_type'], source['source_kind']
        processed = figure_type in ('bulk_qc', 'bulk_pca')
        enrichment = config.get('bulk_enrichment_render') is True and figure_type in ('enrichment', 'gsea')
        if (not (figure_type.startswith('bulk_') or enrichment) or processed != (kind == PROCESSED)
                or methods.get('figure_type') != figure_type or methods.get('analysis_recomputed') is not False
                or methods.get('source_id') != source['source_id'] or methods.get('source_sha256') != source['sha256']
                or config.get('result_source_id') != source['source_id']):
            raise invalid()
        png = value.members.get('figure_png')
        if png and (png['format'], png['role']) != ('png', 'figure'):
            raise invalid()
        identifier = value.row['id']
        reference = dict(version_id=identifier, source_version_id=source['source_id'], source_kind=kind,
                         source_manifest_sha256=source['sha256'], figure_type=figure_type, title=config.get('title'),
                         panel=config.get('bulk_panel'), selection=config.get('bulk_selection'),
                         manifest_sha256=value.row['manifest_sha256'], summary=value.summary,
                         parameters=config, axes=methods.get('axes'), source_member=methods.get('input_member'),
                         png=self.public_member(project, identifier, png) if png else None)
        return reference, png, self.objects

    def _candidate(self, project, value, comparison, labels):
        selection = value.methods.get('bulk_selection') or {}
        table = _member(comparison.members, 'comparison_results', 'tsv')
        if (not value.config.get('bulk_selection') or selection.get('source_result_version_id') != comparison.row['id']
                or selection.get('source_manifest_sha256') != comparison.row['manifest_sha256']
                or selection.get('comparison_sha256') != table['sha256']
                or labels.get(selection.get('contrast_id')) != (selection.get('numerator'), selection.get('denominator'))):
            raise invalid()
        top = _member(value.members, 'bulk_candidate_top', 'tsv')
        return dict(version_id=value.row['id'], selection=selection, summary=value.summary,
                    ranking=value.methods.get('ranking'), top_rows=list(islice(_table_rows(self.objects, top), _TOP_ROWS)),
                    table=self.public_member(project, value.row['id'], _member(value.members, 'candidate_results', 'tsv')))

    def _enrichment(self, project, value, sources, labels):
        config, methods, summary = value.config, value.methods, value.summary
        bulk = methods.get('bulk_enrichment')
        kind = value.row['kind']
        contrast_ids = config['contrast_ids'] if kind == 'ora' else [config['contrast_id']]
        collections, mappings = config['resource_source_ids'], config.get('mapping_source_ids', [])
        if (not isinstance(bulk, dict) or config.get('bulk_enrichment') is None or not set(contrast_ids) <= labels.keys()
                or set(collections + mappings) != {source['source_id'] for source in sources}
                or set(bulk['resource_references']) != set(collections)):
            raise invalid()
        status = summary.get('enrichment_status')
        reason = summary.get('not_applicable_reason')
        count = summary['row_count']
        if (status not in ('completed', 'no_significant_terms', 'not_applicable')
                or (status == 'not_applicable') != (count == 0) or (status == 'not_applicable') != bool(reason)):
            raise invalid()
        member = _member(value.members, 'enrichment_results', 'tsv')
        metric = 'q_value' if kind == 'ora' else 'fdr_q_value'
        total, significant = 0, 0
        def terms():
            nonlocal total, significant
            for row in _table_rows(self.objects, member):
                total += 1
                value = finite_metric(row.get(metric))
                significant += value is not None and 0 <= value <= 0.05
                yield row

        def rank(row):
            number = finite_metric(row.get(metric))
            return (number is None, number or 0, row.get('contrast_id', ''), row['resource_id'], row['term_id'])

        top = nsmallest(_TOP_ROWS, terms(), key=rank)
        if total != count or significant != summary['significant_terms'] or (status == 'completed') != (significant > 0):
            raise invalid()
        return dict(version_id=value.row['id'], kind=kind, contrast_ids=contrast_ids, status=status,
                    not_applicable_reason=reason, summary=summary, method=methods.get('name'), parameters=config,
                    coverage=bulk['coverage'], source_reference=bulk['source_reference'],
                    resource_references=bulk['resource_references'], resource_version_ids=collections + mappings,
                    mapping=methods.get('mapping'), background=methods.get('background'), correction=methods.get('correction'),
                    top_rows=top, table=self.public_member(project, value.row['id'], member))

    def _snapshot(self, db, project, comparison_version_id, *, result_version_ids, selections, language,
                  sensitivity, evidence, include_images, cached_facts=None):
        comparison_id = comparison_version_id
        if language not in ('zh', 'zh-CN', 'en') or len(result_version_ids) > 20:
            raise invalid('bio_insight_source_unsupported', 422)
        if comparison_id in result_version_ids or len(set(result_version_ids)) != len(result_version_ids):
            raise invalid()
        language = 'zh' if language == 'zh-CN' else language
        with VerificationPhase(db, self.assets, project) as phase:
            comparison = self._published(db, project, comparison_id, phase)
            metadata = dict(kind=comparison.row['kind'], plan_config=comparison.config)
            if not is_reviewed_bulk(metadata):
                raise invalid('bio_insight_source_unsupported', 422)
            if comparison.summary.get('tested_universe_complete') is not True:
                raise invalid('bio_insight_source_incomplete', 422)
            if sensitivity is not None and (
                sensitivity['baseline']['result_version_id'] != comparison_id
                or sensitivity['baseline']['manifest_sha256'] != comparison.row['manifest_sha256']
            ):
                raise invalid()
            labels = bulk_contrast_labels(metadata)
            selection_map = _selection_map(labels, selections)
            plan = self.require(db, 'bio_insight_plan_versions', project, comparison.row['plan_version_id'])
            design_member = _member(comparison.members, 'comparison_design', 'json')
            frozen_design = json.loads(self.objects.read(design_member))
            model = frozen_design['bulk_model']
            if not model or frozen_design.get('executable') is not True:
                raise invalid()
            design = model | {key: comparison.config.get(key) for key in (
                'species_taxon_id', 'namespace', 'reference_version', 'design', 'design_basis',
                'independence_basis', 'inference_unit', 'inference_goal', 'batch_adjustment', 'pairing_field')}
            design.update(inference_scope=comparison.row['inference_scope'], residual_df=model.get('residual_degrees_freedom'),
                          exclusions=frozen_design.get('exclusions', []), warnings=frozen_design.get('warnings', []),
                          confirmation=dict(plan_version_id=plan['id'], plan_id=plan['plan_id'],
                              confirmed_at=plan['confirmed_at'].isoformat(), confirmed_by=plan['confirmed_by'],
                              reviewed_design_sha256=plan['design_checks_json']['reviewed_design_sha256']))
            reusable = (cached_facts is not None
                        and cached_facts['references']['comparison'] == self._result_reference(project, comparison)
                        and cached_facts['selections'] == [selection_map[cid].model_dump(mode='json') for cid in labels])
            contrasts = (cached_facts['contrasts'] if reusable else
                         _report_contrasts(self.objects, _member(comparison.members, 'comparison_results', 'tsv'),
                                          labels, selection_map, frozen_design))
            if sum(item['counts']['total'] for item in contrasts) != comparison.summary.get('row_count'):
                raise invalid()
            processed, qc, processed_refs, figures = {}, [], [], []
            for source in comparison.envelope['sources']:
                if source['source_kind'] == PROCESSED:
                    dataset, ref, qc_figures = self._processed(db, project, source, phase)
                    processed[source['source_id']] = source['sha256']
                    qc.append(dataset)
                    processed_refs.append(ref)
                    figures.extend(qc_figures)
            if not processed or any(sample['processed_version_id'] not in processed for sample in design.get('samples', [])):
                raise invalid()

            result_refs, resource_refs, candidates, enrichments, visiting = {}, {}, [], [], set()

            def check_comparison(source):
                if (source['source_kind'], source['source_id'], source['sha256']) != (RESULT, comparison_id, comparison.row['manifest_sha256']):
                    raise invalid()

            def attach(identifier):
                if identifier in visiting:
                    raise invalid()
                if identifier in result_refs:
                    return result_refs[identifier]
                visiting.add(identifier)
                value = self._published(db, project, identifier, phase)
                kind, sources = value.row['kind'], value.envelope['sources']
                if not bulk_attachment_supported(kind, value.config, sources):
                    raise invalid('bio_insight_source_unsupported', 422)
                if kind == 'figure' and len(sources) == 1:
                    source = sources[0]
                    if source['source_kind'] == PROCESSED:
                        if processed.get(source['source_id']) != source['sha256']:
                            raise invalid()
                    elif value.config.get('bulk_enrichment_render') is True and source['source_kind'] == RESULT:
                        upstream = attach(source['source_id'])
                        if upstream['kind'] not in _ENRICHMENT_KINDS or upstream['manifest_sha256'] != source['sha256']:
                            raise invalid()
                    else:
                        check_comparison(source)
                    figures.append(self._figure(project, value, source))
                elif kind == 'candidate' and len(sources) == 1:
                    check_comparison(sources[0])
                    candidates.append(self._candidate(project, value, comparison, labels))
                elif kind in _ENRICHMENT_KINDS:
                    upstream = [source for source in sources if source['source_kind'] == RESULT]
                    resources = [source for source in sources if source['source_kind'] == RESOURCE]
                    if len(upstream) != 1 or not resources or len(upstream) + len(resources) != len(sources):
                        raise invalid()
                    check_comparison(upstream[0])
                    for source in resources:
                        sid = source['source_id']
                        if sid not in resource_refs:
                            resource = self._published(db, project, sid, phase, resource=True)
                            resource_refs[sid] = self._result_reference(project, resource, resource=True)
                        expected = 'gene_sets' if sid in value.config['resource_source_ids'] else 'id_mapping'
                        ref = resource_refs[sid]
                        if ref['kind'] != expected or ref['manifest_sha256'] != source['sha256']:
                            raise invalid()
                    enrichments.append(self._enrichment(project, value, resources, labels))
                else:
                    raise invalid('bio_insight_source_unsupported', 422)
                visiting.remove(identifier)
                result_refs[identifier] = self._result_reference(project, value)
                return result_refs[identifier]

            for identifier in result_version_ids:
                attach(identifier)

            if include_images and sum(member['size_bytes'] for _, member, _ in figures if member) > _MAX_IMAGE_BYTES:
                raise invalid('bio_insight_limit_exceeded', 422)
            images = [objects.read(member) if include_images and member else None for _, member, objects in figures]
        qc_summary = qc[0]['summary'] if len(qc) == 1 else {
            key: sum(dataset['summary'][key] for dataset in qc)
            for key in ('raw_observations', 'retained_observations', 'excluded_observations')}
        snapshot = dict(schema_version=1, project_id=project, language=language, comparison_version_id=comparison_id,
                        processed_version_id=next(iter(processed)), processed_version_ids=list(processed),
                        selected_result_version_ids=list(result_version_ids), result_version_ids=list(result_refs),
                        resource_version_ids=list(resource_refs), selections=[contrast['selection'] for contrast in contrasts],
                        design=design, comparison_summary=comparison.summary, comparison_methods=comparison.methods,
                        qc=dict(summary=qc_summary, datasets=qc, samples=[sample for dataset in qc for sample in dataset['samples']],
                                sample_mapping=qc[0]['sample_mapping'] if len(qc) == 1 else None,
                                steps=qc[0]['steps'] if len(qc) == 1 else [],
                                input_files=[item for dataset in qc for item in dataset['input_files']]),
                        contrasts=contrasts, figures=[figure for figure, _, _ in figures], candidates=candidates,
                        enrichments=enrichments, sensitivity=sensitivity, evidence=list(evidence), limitations=list(_LIMITS[language]),
                        references=dict(comparison=self._result_reference(project, comparison), processed=processed_refs,
                                        results=list(result_refs.values()), resources=list(resource_refs.values())))
        # Detach the facts from database values and caller-owned inputs before hashing.
        snapshot = json.loads(canonical(snapshot))
        return snapshot | {'facts_digest': digest(snapshot)}, images

    def facts(self, project, comparison_version_id, *, result_version_ids=(), selections=(), language='zh',
              sensitivity=None, evidence=(), cached_facts=None):
        with self.store.connection() as db:
            try:
                facts, _ = self._snapshot(db, project, comparison_version_id, result_version_ids=result_version_ids,
                                          selections=selections, language=language, sensitivity=sensitivity,
                                          evidence=evidence, include_images=False, cached_facts=cached_facts)
            except (KeyError, TypeError, IndexError, ValueError, csv.Error, OSError) as exc:
                raise invalid() from exc
        return facts

    def docx(self, project, facts, *, verified_contrasts=False):
        from app.adapters.bulk_insight_report import build_bulk_insight_report
        from app.adapters.bio_reader_narrative import load_bulk_cached_narrative

        with self.store.connection() as db:
            try:
                if facts['project_id'] != project:
                    raise invalid('bio_insight_not_found', 404)
                frozen, images = self._snapshot(db, project, facts['comparison_version_id'],
                    result_version_ids=facts['selected_result_version_ids'], selections=facts['selections'],
                    language=facts['language'], sensitivity=facts['sensitivity'], evidence=facts['evidence'], include_images=True,
                    cached_facts=facts if verified_contrasts else None)
                if frozen != facts:
                    raise invalid()
            except (KeyError, TypeError, IndexError, ValueError, csv.Error, OSError) as exc:
                raise invalid() from exc
        language = 'zh-CN' if frozen['language'] == 'zh' else 'en'
        narrative = load_bulk_cached_narrative(self.assets.directory, project, frozen['facts_digest'], language)
        return build_bulk_insight_report(frozen, images, narrative=narrative)
