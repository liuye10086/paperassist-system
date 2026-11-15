"""Reuse the native Bulk delivery proof; no archive copy or scientific execution."""
import csv
import io
from pydantic import ValidationError

from app.adapters.research_results_store import invalid
from app.domain.bio_insights.bulk_delivery import BulkDeliveryService
from app.domain.bio_insights.bulk_delivery_contracts import BulkDeliveryRequest
from app.domain.bio_insights.bulk_workflow import BulkWorkflowService
from app.domain.bio_insights.results import checked_members


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
