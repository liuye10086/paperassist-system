"""Assemble the same statistics material for formal and local report renderers."""
import hashlib
import json

from app.adapters.research_results_store import invalid
from app.domain.bioinformatics.contracts import digest
from app.domain.reader_reports.content import _check_png, binding_digest
from app.domain.research_results.statistics_package import statistics_reproduction_files
from app.domain.research_results.statistics_projection import project_statistics_facts

from .narrative import ADAPTER_VERSION, ORIGIN, build_reader_output, clean, localized, method_name, observations, quality
from .tables import projection_table, result_tables


def raw_file(name, value):
    return dict(name=name, raw=json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False,
                                         default=lambda stamp: stamp.isoformat()).encode('utf-8'))


def report_overview(sources, items, language):
    facts = []
    methods = []
    summary = []
    source_index = []
    fields = {
        'check.row_count', 'check.valid_count', 'check.excluded_count', 'overall.n', 'overall.mean',
        'overall.median', 'overall.std', 'statistics.n', 'statistics.coefficient',
        'statistics.p_value.value', 'statistics.auc', 'statistics.r_squared',
    }
    for number, source in enumerate(sources, 1):
        result = source.content['result']
        summary.append(dict(method=method_name(result, language), results=observations(result, language),
                            quality=quality(result, language)))
        label = method_name(result, language)
        source_index.append(dict(source_kind='analysis_run', source_id=source.source_id, sha256=source.sha256,
                                 title=localized(language, f'分析 {number} · {label}', f'Run {number} · {label}')))
        catalog = project_statistics_facts(source)
        facts.extend(f.model_dump(mode='json') for f in catalog.facts if f.locator.field_path in fields)
        for method in catalog.methods:
            value = method.model_dump(mode='json')
            value['title'] = method_name(result, language)
            explanation = next((item['explanation'] for item in items
                                if item['result']['id'] == source.source_id and item.get('explanation')), None)
            if explanation:
                section = next(section for section in explanation['sections'] if section['key'] == 'methods')
                value['description'] = clean(section['text'])[:4000]
            # Full settings, executable environment and software identities
            # are already included in the original result reproduction files.
            value['parameters'] = {}
            value['software'] = {}
            methods.append(value)
    gaps = []
    if any(item.get('explanation') is None for item in items):
        gaps.append(localized(language, '所选内容未包含匹配图件和已保存解释。', 'The selection does not include a matched figure and saved explanation.'))
    limitations = [localized(language, '记录计数与独立受试者数的关系须由研究设计确认。',
                             'Use the study design to determine how record counts relate to independent participants.')]
    return dict(summary=summary, facts=facts, methods=methods, gaps=gaps, limitations=limitations, sources=source_index)


def assemble_statistics_material(*, title, language, sources, items, pngs, context_schema_version=2):
    """Pure assembly over previously verified result, explanation and PNG inputs."""
    sources_by_id = {source.source_id: source for source in sources}
    if (set(sources_by_id) != {item['result']['id'] for item in items}
            or any(sources_by_id[item['result']['id']].content['result'] != item['result'] for item in items)):
        raise invalid()
    sources = [sources_by_id[identifier] for identifier in dict.fromkeys(item['result']['id'] for item in items)]
    selected = [item for item in items if item.get('figure')]
    files = statistics_reproduction_files([source.model_dump(mode='json') for source in sources])
    figures = []
    images = []
    local_sources = []
    tables = []
    table_raws = []
    for number, source in enumerate(sources, 1):
        for table, raw in result_tables(source, number, language):
            tables.append(table)
            table_raws.append(raw)

    if len(selected) != len(pngs):
        raise invalid()
    for number, (item, png) in enumerate(zip(selected, pngs, strict=True), 1):
        figure, explanation = item['figure'], item['explanation']
        result_id = item['result']['id']
        sha = hashlib.sha256(png).hexdigest()
        if sha != figure['sha256']:
            raise invalid()
        try:
            _check_png(png)
        except ValueError as exc:
            raise invalid('research_output_invalid', 422) from exc
        config = dict(title=clean(figure.get('title')) or method_name(item['result'], language),
                      caption=clean(item.get('caption') or figure.get('caption')),
                      language=language, figure_language=figure.get('language', language))
        source = dict(analysis_run_id=result_id, result_sha256=sources_by_id[result_id].sha256,
                      figure_id=figure['id'], figure_sha256=sha, explanation_id=explanation['id'],
                      explanation_sha256=digest(explanation))
        local_sources.append(source)
        figures.append(dict(id=figure['id'], statistics_source=source, manifest_sha256=digest(figure), config=config,
                            document_image=dict(key='selected_png', format='png', sha256=sha)))
        caption_facts = [dict(section=section['key'], label=fact['label'], value=fact['value'])
                         for section in explanation['sections'] if section['key'] in ('data', 'results')
                         for fact in section['evidence']]
        images.append(dict(config=config, raw=png, format='png', caption_facts=caption_facts))
        prefix = f'figures/figure_{number:02d}/'
        files.extend((dict(name=prefix + 'selected_png.png', raw=png),
                      raw_file(prefix + 'figure.json', figure), raw_file(prefix + 'explanation.json', explanation)))
        if item.get('projection'):
            table, raw = projection_table(item, number, language)
            tables.append(table)
            table_raws.append(raw)
            files.append(raw_file(prefix + 'projection.json', item['projection']))
        if item.get('configuration'):
            files.append(raw_file(prefix + 'configuration.json', item['configuration']))
    if sum((t['expected_rows'] + 1) * len(t['columns']) for t in tables) > 5_000_000:
        raise invalid('research_export_limit_exceeded', 422)
    overview = report_overview(sources, items, language)
    try:
        output = build_reader_output(language, sources, items, context_schema_version=context_schema_version)
    except KeyError as exc:
        raise invalid('research_output_invalid', 422) from exc
    except ValueError:
        output = None
        overview['gaps'].append(localized(language, '已保存图解无法形成当前选材所需的完整读者正文。',
                                         'The saved explanations cannot supply the complete narrative for this selection.'))
    return dict(title=title, language=language, figures=figures, images=images, tables=tables, table_raws=table_raws,
                files=files, local_output=output, local_sources=local_sources, overview=overview)


def local_reader_record(snapshot, material):
    """Bind the checked local text to the same base snapshot used for model comparison."""
    output = material['local_output']
    if output is None:
        return None
    sources = material['local_sources']
    return dict(**output, origin=ORIGIN, sources=sources, binding_sha256=binding_digest(snapshot),
                provenance=dict(origin=ORIGIN, adapter_version=ADAPTER_VERSION, artifact_sha256=digest(output),
                                explanation_sources=sources, image_observation='saved_explanation_and_figure_metadata',
                                real_model_calls=0))
