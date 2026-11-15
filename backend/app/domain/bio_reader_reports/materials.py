"""Resolve native bytes once and freeze only the expressly selected tables and images."""
from collections import Counter
import csv
import hashlib
import io
import json
import re

from app.adapters.bio_analysis_store import BioAnalysisStore, scoped_object
from app.adapters.bio_annotation_store import BioAnnotationStore
from app.adapters.bio_figure_store import BioFigureStore
from app.adapters.research_results_store import invalid
from app.domain.bioinformatics.contracts import canonical, digest
from app.domain.research_results.sources import ResearchSourceReader
from app.domain.source_byte_verification import VerificationPhase


def annotation_identity(view, row):
    return dict(version_id=view['id'], set_id=view['set_id'], view_sha256=digest(view),
                **{key: row[key] for key in ('geometry_sha256', 'assignments_sha256', 'geometry_object_id', 'assignments_object_id')})


def checked_context_size(content):
    # Leave room for jsonb's whitespace representation before the database's
    # 4 MiB constraint. Large results remain in immutable native objects.
    if len(json.dumps(content, ensure_ascii=False).encode('utf-8')) > 4_000_000:
        raise invalid('research_export_limit_exceeded', 422)
    return content


def table_descriptor(member, raw, source):
    fmt = member['format']
    if fmt not in ('csv', 'tsv'):
        raise invalid('research_source_unsupported', 422)
    rows = csv.reader(io.StringIO(raw.decode('utf-8-sig')), delimiter=',' if fmt == 'csv' else '\t', strict=True)
    columns = next(rows, None)
    if not columns or len(columns) != len(set(columns)):
        raise invalid('research_output_invalid', 422)
    count = 0
    for row in rows:
        if len(row) != len(columns):
            raise invalid('research_output_invalid', 422)
        count += 1
    return dict(key=member['key'], format=fmt, columns=columns, expected_rows=count,
                source=source, sha256=hashlib.sha256(raw).hexdigest())


def tsv(rows, columns):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
    writer.writerow(columns)
    for row in rows:
        writer.writerow([json.dumps(row.get(key), ensure_ascii=False, sort_keys=True) if isinstance(row.get(key), (dict, list)) else row.get(key) for key in columns])
    return stream.getvalue().encode('utf-8')


def scientific_title(key, language):
    from app.adapters.single_cell_report import _reader_figure_label
    from app.adapters.single_cell_insight_report import _reader_figure_title
    normalized = re.sub(r'_page_\d+', '', key).removesuffix('_png')
    titles = {
        'qc_missing': ('样本缺失比例', 'Missing fraction by sample'),
        'expression_distribution': ('表达分布', 'Expression distribution'),
        'sample_clustering': ('样本聚类', 'Sample clustering'),
        'correlation_heatmap': ('样本相关性热图', 'Sample correlation heatmap'),
        'distance_heatmap': ('样本距离热图', 'Sample distance heatmap'),
        'volcano': ('差异效应与显著性火山图', 'Differential effect and significance volcano plot'),
        'enrichment': ('基因集富集图', 'Gene-set enrichment'),
        'gsea': ('排序基因集富集图', 'Ranked gene-set enrichment'),
        'topic_slingshot': ('单细胞轨迹', 'Single-cell trajectory'),
        'topic_genie3': ('单细胞调控网络', 'Single-cell regulatory network'),
        'topic_cellchat': ('细胞通讯概率热图', 'Cell communication probability heatmap'),
    }
    if normalized in titles:
        return titles[normalized][language == 'en']
    title = _reader_figure_label(normalized, language)
    if title in ('Analysis figure', '分析图件'):
        title = _reader_figure_title(normalized.removesuffix('_png'), language == 'en')
    page = re.search(r'_page_(\d+)', key)
    if page:
        title += (' — continuation ' if language == 'en' else ' — 续图 ') + page.group(1)
    return title


class MaterialBuilder:
    def __init__(self, assets, db, project, language, phase):
        self.assets, self.db, self.project, self.language, self.phase = assets, db, project, language, phase
        self.reader = ResearchSourceReader(assets, allow_stale_labels=True)
        self.bio = self.reader.bio
        self.sources, self.tables, self.images, self.blobs, self.dependencies = [], [], [], [], []
        self.file_ids = set()
        self.annotation = None
        self.subset = None
        self.supporting = []
        self.selection = None

    def source(self, kind, identifier):
        fixed = self.reader._read_source_in_phase(self.project, dict(source_kind=kind, source_id=identifier), db=self.db, phase=self.phase)
        value = fixed.model_dump(mode='json')
        if value not in self.sources:
            self.sources.append(value)
        self.file_ids.update(fixed.source_file_ids)
        self.dependency(kind, identifier, fixed.sha256)
        return fixed

    def dependency(self, kind, identifier, sha):
        value = dict(kind=kind, id=identifier, sha256=sha)
        if value not in self.dependencies:
            self.dependencies.append(value)

    def blob(self, member, objects, native):
        raw = objects.read(member)
        if hashlib.sha256(raw).hexdigest() != member['sha256']:
            raise invalid()
        # A database object id, not a caller path, is the fixed byte reference.
        object_id = member.get('storage_object_id')
        if not object_id:
            from app.adapters.bio_analysis_store import object_by_key
            object_id = object_by_key(self.db, self.project, self.assets.owner_id, member)['id']
        return raw, dict(object_id=object_id, sha256=member['sha256'], size_bytes=member['size_bytes'], native_source=native)

    def add_table(self, member, objects, source):
        raw, blob = self.blob(member, objects, source)
        self.tables.append(table_descriptor(member, raw, source))
        self.blobs.append(blob)

    def add_generated_table(self, key, rows, columns, source):
        raw = tsv(rows, columns)
        self.tables.append(table_descriptor(dict(key=key, format='tsv'), raw, source))
        self.blobs.append(dict(generated=dict(rows=rows, columns=columns), sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw), native_source=source))

    def add_projected_table(self, key, raw, projection, source):
        self.tables.append(table_descriptor(dict(key=key, format='tsv'), raw, source))
        self.blobs.append(dict(projection=projection, sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw), native_source=source))

    def add_image(self, member, objects, native, manifest_sha, caption, title=None):
        raw, blob = self.blob(member, objects, native)
        from app.domain.reader_reports.content import _check_png
        _check_png(raw)
        self.images.append(dict(id=member['id'], native_source=native, manifest_sha256=manifest_sha,
            config=dict(title=title or scientific_title(member['key'], self.language), caption=''),
            document_image={key: member[key] for key in ('key', 'format', 'sha256')},
            caption_facts=caption, blob=blob))

    def processed(self, selection):
        from app.adapters.single_cell_report import _marker_page_order
        fixed = self.source('bio_processed_dataset_version', selection.processed_version_id)
        row, manifest, members = self.bio._processed_lineage_in_phase(self.db, self.project, selection.processed_version_id, phase=self.phase)
        scientific = {key: fixed.content[key] for key in ('summary', 'params', 'steps', 'assay', 'observation_level', 'methods', 'source_accessions') if key in fixed.content}
        scientific['summary'] = dict(scientific.get('summary', {}))
        self.subset = manifest.get('subset') or scientific['summary'].get('subset')
        if self.subset:
            # The exact selection remains in the local immutable context and
            # native manifest. Model facts and per-image captions need its
            # scope, not a repeated list of up to 20,000 cell identifiers.
            clusters = self.subset.get('cluster_ids', [])
            cells = self.subset.get('cell_ids', [])
            scientific['summary']['subset'] = dict(
                parent_processed_source=self.subset['parent_processed_source'],
                selection_mode='clusters_and_cells' if clusters and cells else 'clusters' if clusters else 'cells',
                cluster_ids=clusters, explicit_cell_count=len(cells),
                selected_cell_count=len(self.subset['resolved_cell_ids']))
        raw_source = manifest.get('raw_source') or manifest['identity']['raw_source']
        _, raw_manifest = self.bio.raw_store.require_version(self.db, self.project, raw_source['dataset_id'], raw_source['dataset_version_id'])
        if raw_manifest.get('samples'):
            scientific['samples'] = raw_manifest['samples']
        for member in members:
            if member['format'] in ('tsv', 'csv'):
                self.add_table(member, self.bio.objects, dict(source_kind='bio_analysis_artifact', source_id=member['id'], processed_version_id=row['id']))
        if selection.annotation_version_id:
            scientific['summary']['annotation'] = self.select_annotation(selection, row)
        captions = [scientific]
        if not selection.figure_version_ids:
            for member in sorted(members, key=_marker_page_order):
                if member['format'] == 'png':
                    self.add_image(member, self.bio.objects, dict(source_kind='bio_analysis_artifact', source_id=member['id'], processed_version_id=row['id']), row['manifest_sha256'], captions)
        else:
            figures = BioFigureStore(self.assets)
            for identifier in selection.figure_version_ids:
                selected = figures.require(self.db, 'bio_figure_versions', self.project, identifier)
                if (selected['processed_dataset_version_id'] != row['id']
                        or selected['annotation_version_id'] not in (None, selection.annotation_version_id)):
                    raise invalid()
                self.source('bio_figure_version', identifier)
                view = figures.get(self.project, identifier)
                pngs = [member for member in view['members'] if member['format'] == 'png']
                if not pngs:
                    raise invalid('research_source_incomplete', 422)
                for member in sorted(pngs, key=_marker_page_order):
                    stored = self.db.execute('SELECT * FROM bio_figure_members WHERE id=%s AND project_id=%s', (member['id'], self.project)).fetchone()
                    obj = scoped_object(self.db, self.project, self.assets.owner_id, stored['storage_object_id'])
                    full = dict(stored, object_key=obj['object_key'])
                    self.add_image(full, figures.reader(obj), dict(source_kind='bio_figure_version', source_id=identifier, member_id=member['id'], processed_version_id=row['id'], annotation_version_id=selected['annotation_version_id']), selected['manifest_sha256'], captions, view['config'].get('title') or None)
        self.supporting.append(dict(kind='processed', version_id=row['id'], manifest_sha256=row['manifest_sha256']))
        return scientific

    def select_annotation(self, selection, processed):
        store = BioAnnotationStore(self.assets)
        row = store.require(self.db, 'bio_annotation_versions', self.project, selection.annotation_version_id)
        if row['processed_dataset_version_id'] != processed['id'] or row['raw_dataset_version_id'] != processed['raw_dataset_version_id']:
            raise invalid()
        view = store.get(self.project, row['set_id'], row['id'])
        view.pop('is_current', None)
        self.annotation = annotation_identity(view, row)
        self.dependency('bio_annotation_version', row['id'], digest(self.annotation))
        for evidence in view['evidence']:
            if evidence.get('file_id'):self.source('original_file',evidence['file_id'])
        source = dict(source_kind='bio_annotation_version', source_id=row['id'], processed_version_id=processed['id'])
        for key, rows, columns in (
            ('annotation_assignments', view['assignments'], ['barcode', 'label_id', 'status', 'region_ids']),
            ('annotation_labels', view['labels'], ['id', 'name', 'status', 'cluster_ids', 'cell_ids']),
            ('annotation_evidence', view['evidence'], ['label_id', 'kind', 'analysis_artifact_id', 'file_id', 'note']),
        ):
            self.add_projected_table(key, tsv(rows, columns), dict(kind='annotation', annotation=self.annotation,
                field=key.removeprefix('annotation_'), columns=columns), source)
        geometry = scoped_object(self.db, self.project, self.assets.owner_id, row['geometry_object_id'])
        for member in json.loads(store.annotation_objects.read(geometry)).get('members', []):
            if member['format'] in ('csv', 'tsv'):
                self.add_table(member, store.annotation_objects, source | {'member_id': member['id']})
        counts = Counter((r['label_id'], r['status']) for r in view['assignments'])
        labels = [{**{k: v for k, v in label.items() if k != 'cell_ids'}, 'selected_cell_count': len(label.get('cell_ids', []))} for label in view['labels']]
        return dict(name=view['name'], labels=labels, checks=view['checks'], evidence=view['evidence'],
                    algorithm=view['algorithm'], origin=view['origin'], overlap_policy=view['overlap_policy'],
                    assignment_counts=[dict(label_id=label, status=status, count=count) for (label, status), count in sorted(counts.items(), key=lambda x: str(x[0]))])

    def insight(self, selection):
        from app.domain.bio_insights.service import BioInsightsService
        from app.domain.bio_insights.results import checked_members
        from app.domain.bio_insights.bulk_results import is_reviewed_bulk
        fixed = self.source('bio_insight_result_version', selection.result_version_id)
        service = BioInsightsService(self.assets)
        row = service.require(self.db, 'bio_insight_result_versions', self.project, selection.result_version_id)
        config = fixed.content['config']
        comparison, attachments = None, []
        if is_reviewed_bulk(dict(kind=row['kind'], plan_config=config)):
            comparison, attachments = row['id'], selection.figure_version_ids
        elif row['kind'] in ('ora', 'gsea_prerank') and config.get('bulk_enrichment'):
            ids = config['result_source_ids'] if row['kind'] == 'ora' else [config['result_source_id']]
            if len(ids) != 1:
                raise invalid()
            comparison, attachments = ids[0], [row['id'], *selection.figure_version_ids]
        if comparison:
            from .bulk import resolve_bulk
            # The resolved Bulk proof is the same scientific selection across
            # direct and result-shortcut entries. Rebuild its ordered closure.
            self.sources, self.dependencies, self.file_ids = [], [], set()
            return resolve_bulk(self, dict(comparison_version_id=comparison, result_version_ids=attachments, language='en' if self.language == 'en' else 'zh'))
        manifest, members = checked_members(service, self.db, self.project, row)
        scientific = dict(summary=fixed.content['summary'], methods=fixed.content['methods'],
            study_design=config, assay=config.get('mode', config.get('method', row['kind'])),
            observation_level=fixed.content.get('inference_scope', 'unknown'))
        for member in members:
            if member['format'] in ('tsv', 'csv'):
                self.add_table(member, service.objects, dict(source_kind='bio_insight_result_member', source_id=member['id'], result_version_id=row['id']))
        if selection.figure_version_ids:
            for identifier in selection.figure_version_ids:
                figure = self.source('bio_insight_result_version', identifier)
                fr = service.require(self.db, 'bio_insight_result_versions', self.project, identifier)
                fm, fmembers = checked_members(service, self.db, self.project, fr)
                methods = fm.get('methods', {})
                if (fr['kind'] != 'figure' or methods.get('source_id') != row['id'] or methods.get('source_sha256') != row['manifest_sha256'] or methods.get('analysis_recomputed') is not False):
                    raise invalid()
                if config.get('kind') == 'integration' and config.get('schema_version') == 2:
                    from app.adapters.single_cell_insight_report import validate_report_figure
                    validate_report_figure(row['id'], row['manifest_sha256'], config['method'], methods)
                pngs = [m for m in fmembers if m['key'] == 'figure_png' and m['format'] == 'png']
                if len(pngs) != 1:
                    raise invalid('research_source_incomplete', 422)
                self.add_image(pngs[0], service.objects, dict(source_kind='bio_insight_result_member', source_id=pngs[0]['id'], result_version_id=identifier), fr['manifest_sha256'], [scientific, dict(summary=figure.content['summary'], methods=methods)], methods.get('config', {}).get('title') or scientific_title(methods.get('figure_type', ''), self.language))
        else:
            for member in members:
                if member['format'] == 'png':
                    title_key = 'topic_' + config['method'] if member['key'] == 'topic_plot' and config.get('kind') == 'integration' and config.get('schema_version') == 2 else member['key']
                    self.add_image(member, service.objects, dict(source_kind='bio_insight_result_member', source_id=member['id'], result_version_id=row['id']), row['manifest_sha256'], [scientific], scientific_title(title_key, self.language))
        self.supporting.append(dict(kind='insight', version_id=row['id'], manifest_sha256=row['manifest_sha256']))
        return scientific

    def finish(self, request, scientific):
        from app.domain.research_results.contracts import FrozenResearchSource
        catalogs = [self.reader.catalog(FrozenResearchSource.model_validate(source)) for source in self.sources]
        def unique(field):
            return list(dict.fromkeys(value for catalog in catalogs for value in getattr(catalog, field)))
        facts = {fact.id: fact.model_dump(mode='json') for catalog in catalogs for fact in catalog.facts}
        methods = {method.id: method.model_dump(mode='json') for catalog in catalogs for method in catalog.methods}
        if len(self.images) > 50 or sum((t['expected_rows'] + 1) * len(t['columns']) for t in self.tables) > 5_000_000:
            raise invalid('research_export_limit_exceeded', 422)
        return checked_context_size(json.loads(canonical(dict(schema_version=1, title=request.title, language=request.language,
            selection=self.selection or request.selection.model_dump(mode='json'), scientific=scientific, sources=self.sources,
            source_file_ids=sorted(self.file_ids), dependencies=self.dependencies, annotation=self.annotation, subset=self.subset,
            tables=self.tables, table_blobs=self.blobs, figures=self.images, facts=list(facts.values()), methods=list(methods.values()),
            limitations=unique('limitations'), gaps=unique('gaps'), warnings=unique('warnings'), supporting_sources=self.supporting))))


def prepare_material(assets, db, project, request):
    with VerificationPhase(db, assets, project) as phase:
        builder = MaterialBuilder(assets, db, project, request.language, phase)
        if request.selection.kind == 'processed':
            scientific = builder.processed(request.selection)
        elif request.selection.kind == 'insight':
            scientific = builder.insight(request.selection)
        else:
            from .bulk import resolve_bulk
            scientific = resolve_bulk(builder, request.selection.delivery.model_dump(mode='json'))
        return builder.finish(request, scientific)
