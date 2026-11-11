"""Reference compatibility for enrichment of reviewed Bulk comparisons."""
from .bulk_results import is_reviewed_bulk
from .contracts import OraConfig
from .design import DesignPreview, DesignReason, ResourceEstimate


def bulk_namespace(value):
    if isinstance(value, str) and ''.join(c for c in value.casefold() if c not in ' _-') in {
        'ensemblgeneid', 'ensemblgeneids',
    }:
        return 'ensembl_gene_id'
    return value


def bulk_enrichment_reference(metadata, scope):
    """Fill a missing taxon only from the explicit frozen plan declaration."""
    plan = metadata.get('plan_config', {})
    taxon = metadata.get('species_taxon_id') or plan.get('species_taxon_id')
    namespace = metadata.get('namespace') or plan.get('namespace')
    if taxon is None:
        if scope.source_taxon_id is None:
            raise ValueError('bulk_source_taxon_required')
        taxon, origin = scope.source_taxon_id, 'explicit_plan_declaration'
    else:
        if scope.source_taxon_id is not None and scope.source_taxon_id != taxon:
            raise ValueError('bulk_source_taxon_conflict')
        origin = 'fixed_result'
    if type(taxon) is not int or taxon <= 0:
        raise ValueError('bulk_source_taxon_required')
    if not namespace:
        raise ValueError('explicit_namespace_required')
    return dict(species_taxon_id=taxon, namespace=bulk_namespace(namespace), original_namespace=namespace,
                reference_version=metadata.get('reference_version') or plan.get('reference_version'),
                taxon_origin=origin, taxon_evidence=scope.taxon_evidence)


def bulk_resource_compatibility(source_reference, resource_metadata):
    """Check an explicit resource reference; stable IDs do not attest assembly."""
    taxon = resource_metadata.get('species_taxon_id')
    if type(taxon) is not int or taxon != source_reference['species_taxon_id']:
        raise ValueError('incompatible_species')
    namespace = bulk_namespace(resource_metadata.get('namespace'))
    if not namespace:
        raise ValueError('explicit_namespace_required')
    reference = resource_metadata.get('reference_version') or resource_metadata.get('plan_config', {}).get('reference_version')
    if reference:
        if reference != source_reference['reference_version']:
            raise ValueError('bulk_reference_version_mismatch')
        status = 'declared_reference_matches'
    else:
        status = ('stable_id_resource_no_assembly_declared' if namespace == 'ensembl_gene_id'
                  else 'resource_reference_not_declared')
    return dict(species_taxon_id=taxon, namespace=namespace, release=resource_metadata.get('release'),
                reference_version=reference, reference_status=status)


_MESSAGES = {
    'bulk_complete_comparison_required': 'Bulk 富集需要已确认的固定差异全集。',
    'bulk_source_taxon_required': '固定结果缺少物种，请填写 taxon ID 和来源依据。',
    'bulk_source_taxon_conflict': '填写的物种与固定结果登记的物种不一致。',
    'bulk_reference_version_mismatch': '资源声明的参考版本与固定结果不一致或无法核对。',
    'incompatible_species': '所选结果和资源必须具有明确且相同的物种 taxon ID。',
    'explicit_namespace_required': '固定结果和资源必须有明确的 ID 命名空间。',
    'bulk_enrichment_resource_required': '请选择已经发布的本地基因集或 ID 映射资源。',
    'namespace_mapping_required': '结果和基因集命名空间不同，需要固定且方向匹配的 ID 映射资源。',
    'multiple_mapping_releases_ambiguous': '同一个 ID 映射方向只能选择一个固定资源版本。',
    'joint_gsea_requires_common_target_namespace': '联合 GSEA 需要所有基因集使用同一目标命名空间。',
    'contrast_not_found': '所选比较 ID 不存在于该固定结果版本。',
}


def _resource_sources(sources, ids, kind, source_reference, reasons):
    records = []
    for identifier in ids:
        resource = sources.get(identifier, {})
        metadata = resource.get('metadata', {})
        try:
            if (resource.get('source_kind') != 'bio_resource_version' or metadata.get('kind') != kind
                    or 'resource' not in resource['members']):
                raise ValueError('bulk_enrichment_resource_required')
            records.append((identifier, metadata, bulk_resource_compatibility(source_reference, metadata)))
        except ValueError as error:
            reasons.append(str(error))
    return records


def preview_bulk_enrichment(config, sources):
    ora = isinstance(config, OraConfig)
    source_id = config.result_source_ids[0] if ora else config.result_source_id
    contrasts = config.contrast_ids if ora else [config.contrast_id]
    by_id = {source['source_id']: source for source in sources}
    source = by_id.get(source_id, {})
    metadata = source.get('metadata', {})
    summary = metadata.get('summary_json') or metadata.get('manifest', {}).get('summary', {})
    reasons = []
    compatibility = {'source': None, 'resources': []}
    try:
        if (source.get('source_kind') != 'bio_insight_result_version' or not is_reviewed_bulk(metadata)
                or summary.get('tested_universe_complete') is not True or 'comparison_results' not in source['members']):
            raise ValueError('bulk_complete_comparison_required')
        compatibility['source'] = bulk_enrichment_reference(metadata, config.bulk_enrichment)
        available = {item['contrast_id'] for item in metadata['plan_config'].get('contrasts', [])}
        if not set(contrasts) <= available:
            reasons.append('contrast_not_found')
    except ValueError as error:
        reasons.append(str(error))

    reference = compatibility['source']
    if reference is not None:
        collections = _resource_sources(by_id, config.resource_source_ids, 'gene_sets', reference, reasons)
        mappings = _resource_sources(by_id, config.mapping_source_ids, 'id_mapping', reference, reasons)
        if not ora and len({info['namespace'] for _, _, info in collections}) > 1:
            reasons.append('joint_gsea_requires_common_target_namespace')
        for identifier, _, info in collections:
            matches = [sid for sid, meta, _ in mappings if
                       (bulk_namespace(meta.get('mapping_source_namespace')), bulk_namespace(meta.get('mapping_target_namespace')))
                       == (reference['namespace'], info['namespace'])]
            if len(matches) > 1:
                reasons.append('multiple_mapping_releases_ambiguous')
            if not matches and reference['namespace'] != info['namespace']:
                reasons.append('namespace_mapping_required')
            compatibility['resources'].append(dict(resource_id=identifier, **info,
                mapping_source_id=matches[0] if len(matches) == 1 else None))

    return DesignPreview(executable=not reasons,
        blocking_reasons=[DesignReason(code=code, message=_MESSAGES[code]) for code in dict.fromkeys(reasons)],
        family=contrasts, enrichment_compatibility=compatibility,
        resource_estimate=ResourceEstimate(observations=0, features=summary.get('feature_count', 0),
                                           contrasts=len(contrasts), estimated_working_bytes=0))
