"""Reuse the native Bulk delivery proof; no archive copy or scientific execution."""
import csv
import io
from pydantic import ValidationError

from app.adapters.research_results_store import invalid
from app.domain.bio_insights.bulk_delivery import BulkDeliveryService
from app.domain.bio_insights.bulk_delivery_contracts import BulkDeliveryRequest
from app.domain.bio_insights.bulk_workflow import BulkWorkflowService
from app.domain.bio_insights.results import checked_members


_REPORT_SUPPORT_TABLES = frozenset({
    'candidate_results', 'enrichment_results', 'posthoc_results',
    'model_sample_metadata', 'sample_exclusions', 'size_factors',
    'samples', 'sample_qc', 'normalization_factors', 'sample_clustering', 'pca_scores', 'pca_variance_ratio',
})


def _reader_text_cells(figure_count):
    from app.domain.reader_reports import content as reader_report

    labels = [[label + ': ' for label in language] for language in reader_report.CAPTION_LABELS.values()]
    max_field = reader_report.MAX_NARRATIVE_FIELD_CHARS
    # At most one row per two characters, rounded up per field. Adjacent
    # rows either use a line break or cover a wrap at 700 columns.
    narrative_rows = len(reader_report.NARRATIVE_FIELDS) * ((max_field + 1) // 2)
    caption_rows = max(sum((max_field + len(label) + 1) // 2 for label in language) for language in labels)
    by_field = 2 * narrative_rows + 5 * figure_count * caption_rows

    # A non-empty row also needs at least three bytes of the JSON response:
    # one character plus a separator (two bytes or more in JSON). Soft wraps
    # consume more characters, and each field's quotes cover its first row.
    caption_prefix_bytes = max(sum(len(label.encode('utf-8')) for label in language) for language in labels)
    text_bytes = reader_report.MAX_READER_OUTPUT_BYTES + figure_count * caption_prefix_bytes
    by_response = (5 if figure_count else 2) * (text_bytes // 3)
    return min(by_field, by_response)


def _workbook_metadata_cells(content):
    from app.adapters.research_method_text import reader_method
    from app.adapters.research_report_docx import reader_facts

    # A native report has exactly one finding source. A manually reviewed
    # finding can add up to 100 conflicts. Allow either report language so
    # both localized preparations retain the same analysis tables.
    facts = sum(1 for _ in reader_facts(content))
    methods = max(sum(len(reader_method(method, language)['paragraphs']) for method in content['methods'])
                  for language in ('en', 'zh-CN'))
    cautions = sum(len(content[kind]) for kind in ('gaps', 'warnings', 'limitations'))
    return (4                              # Report narrative header and scope
            + 7 * (1 + facts)              # Facts
            + 2 * (1 + 1)                  # Sources
            + 3 * (1 + methods)            # Methods
            + 5                            # Figures header
            + 2 * (1 + cautions + 100)     # Limitations and possible review conflicts
            + 4                            # Export counts header
            + _reader_text_cells(len(content['figures'])))


def _table_priority(table):
    if 'selection' in table['source']:
        return 0
    if table['key'] == 'comparison_results':
        return 1
    return 2 if table['key'] in _REPORT_SUPPORT_TABLES else 3


def _limit_workbook_tables(content):
    from app.adapters import research_results_xlsx as workbook
    from .materials import MAX_REPORT_TABLE_CELLS, table_cell_count

    tables = content['tables']
    rows_per_sheet = workbook.MAX_SHEET_ROWS - 1
    # Each worksheet adds a header and each table adds an export index row.
    table_cells = [table_cell_count(table) for table in tables]
    workbook_cells = [cells + len(table['columns']) * (max(table['expected_rows'] - 1, 0) // rows_per_sheet) + 4
                      for table, cells in zip(tables, table_cells)]
    budget = workbook.MAX_CELLS - _workbook_metadata_cells(content)
    raw_budget = MAX_REPORT_TABLE_CELLS
    if sum(workbook_cells) <= budget and sum(table_cells) <= raw_budget:
        return

    budget -= 2  # The omission notice occupies one row in Limitations.
    retained = set()
    for index in sorted(range(len(tables)), key=lambda index: _table_priority(tables[index])):
        if workbook_cells[index] <= budget and table_cells[index] <= raw_budget:
            retained.add(index)
            budget -= workbook_cells[index]
            raw_budget -= table_cells[index]
    omitted = len(tables) - len(retained)
    if not omitted:
        return
    content['tables'] = [table for index, table in enumerate(tables) if index in retained]
    content['table_blobs'] = [blob for index, blob in enumerate(content['table_blobs']) if index in retained]
    content['workbook_limited'] = True
    content['workbook_limit_notice'] = {
        'en': f'{omitted} result table(s) exceeded the workbook cell budget. Complete source tables and reproduction files can be downloaded from the original Bulk analysis.',
        'zh-CN': f'有 {omitted} 张结果表因工作簿单元格额度不足而未收录。完整来源表和复现文件可在原 Bulk 分析结果中下载。',
    }


def selected_rows(raw, selection):
    from app.domain.bio_insights.bulk_results import bulk_row_class
    from app.domain.bio_insights.contracts import BulkSelection
    selected = BulkSelection.model_validate(selection)
    rows = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')), delimiter='\t')
    return [row for row in rows if row['contrast_id'] == selected.contrast_id and
            bulk_row_class(row, selected) in (('up', 'down') if selected.direction == 'both' else (selected.direction,))]


def resolve_bulk(builder, raw):
    requested_digest = raw.get('facts_digest')
    try:
        request = BulkDeliveryRequest.model_validate({key: value for key, value in raw.items() if key != 'facts_digest'})
    except ValidationError as exc:
        raise invalid('research_source_conflict', 422) from exc
    service = BulkDeliveryService(builder.assets)
    workflow = BulkWorkflowService(builder.assets)
    sensitivity = None
    if request.sensitivity:
        selected = request.sensitivity
        result = workflow.sensitivity(builder.project, selected.baseline_version_id, selected.scenario_version_id,
                                      selected.baseline_selection, selected.scenario_selection, page_size=20)
        sensitivity = {key: value for key, value in result.items() if key not in ('page', 'page_size')}
        builder.source('bio_insight_result_version', selected.scenario_version_id)
    evidence = workflow.evidence(builder.project, [value.model_dump() for value in request.evidence],
                                baseline_version_id=request.comparison_version_id) if request.evidence else []
    for value in request.evidence:
        if value.kind == 'independent_analysis':
            builder.source('bio_insight_result_version', value.source_id)
        else:
            builder.source('original_file', value.source_id)
    facts, _ = service._snapshot(builder.db, builder.project, request.comparison_version_id,
        result_version_ids=request.result_version_ids, selections=request.selections, language=request.language,
        sensitivity=sensitivity, evidence=evidence, include_images=True)
    if requested_digest is not None and facts['facts_digest'] != requested_digest:
        raise invalid('bio_insight_source_conflict', 409)
    # Include the exact primary comparison and ordered native attachment closure,
    # not any unrelated source tables encountered while checking their lineage.
    for identifier in [request.comparison_version_id, *facts['result_version_ids']]:
        fixed = builder.source('bio_insight_result_version', identifier)
        row = service.require(builder.db, 'bio_insight_result_versions', builder.project, identifier)
        _, members = checked_members(service, builder.db, builder.project, row)
        for member in members:
            if member['format'] in ('tsv', 'csv'):
                source = dict(source_kind='bio_insight_result_member', source_id=member['id'], result_version_id=identifier)
                builder.add_table(member, service.objects, source)
                if identifier == request.comparison_version_id and member['key'] == 'comparison_results':
                    from .materials import tsv
                    raw = service.objects.read(member)
                    source_blob, columns = builder.blobs[-1], builder.tables[-1]['columns']
                    for contrast in facts['contrasts']:
                        selected = contrast['selection']
                        builder.add_projected_table('selected_' + selected['contrast_id'], tsv(selected_rows(raw, selected), columns),
                            dict(kind='bulk_selection', source_blob=source_blob, selection=selected, columns=columns), source | {'selection': selected})
    for identifier in facts['processed_version_ids']:
        builder.source('bio_processed_dataset_version', identifier)
        _, _, members = builder.bio._processed_lineage_in_phase(builder.db, builder.project, identifier, phase=builder.phase)
        for member in members:
            if member['format'] in ('csv', 'tsv'):
                builder.add_table(member, builder.bio.objects, dict(source_kind='bio_analysis_artifact', source_id=member['id'], processed_version_id=identifier))
    # The native service controls QC/attachment image ordering and repeated keys.
    for figure in facts['figures']:
        png = figure.get('png')
        if not png:
            continue
        if figure['source_kind'] == 'bio_processed_dataset_version' and figure['version_id'] == figure['source_version_id']:
            member = builder.bio.require(builder.db, 'bio_analysis_artifacts', builder.project, png['id'])
            obj = __import__('app.adapters.bio_analysis_store', fromlist=['scoped_object']).scoped_object(builder.db, builder.project, builder.assets.owner_id, member['storage_object_id'])
            member = dict(member, object_key=obj['object_key'])
            objects = builder.bio.objects
            native = dict(source_kind='bio_analysis_artifact', source_id=member['id'], processed_version_id=figure['version_id'])
        else:
            row = service.require(builder.db, 'bio_insight_result_versions', builder.project, figure['version_id'])
            _, members = checked_members(service, builder.db, builder.project, row)
            member = next(member for member in members if member['id'] == png['id'])
            objects = service.objects
            native = dict(source_kind='bio_insight_result_member', source_id=member['id'], result_version_id=row['id'])
        caption = {key: value for key, value in figure.items() if key not in ('png', 'version_id', 'source_version_id', 'source_manifest_sha256', 'manifest_sha256')}
        builder.add_image(member, objects, native, figure.get('manifest_sha256', figure['source_manifest_sha256']),
                          [caption, dict(contrasts=facts['contrasts'], design=facts['design'])], figure.get('title'))
    delivery = request.model_dump(mode='json') | {'facts_digest': facts['facts_digest'], 'selections': facts['selections'],
        'result_version_ids': facts['selected_result_version_ids']}
    builder.selection = dict(kind='bulk', delivery=delivery)
    builder.supporting.append(dict(kind='bulk', delivery=delivery, facts=facts))
    return dict(summary={key: value for key, value in facts.items() if key not in ('references', 'figures')},
                study_design=facts['design'], methods=facts['comparison_methods'], limitations=facts['limitations'], assay='bulk_rna_counts', observation_level='sample')
