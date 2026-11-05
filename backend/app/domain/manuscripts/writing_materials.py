"""Local display of an already validated manuscript; no model wire or budget."""
from copy import deepcopy

from app.domain.manuscript_writing.context import normalize_sections
from app.domain.manuscript_review.facts import FACT_ROOTS, numeric_leaves
from .research_sources import KINDS, numeric


def _labels(value, prefix=''):
    if isinstance(value, dict):
        for key, item in value.items():
            path = prefix+'/'+str(key).replace('~', '~0').replace('/', '~1')
            if key in ('label', 'unit', 'name', 'term', 'method', 'alternative', 'reason') and isinstance(item, str):
                yield dict(path=path, value=item)
            elif isinstance(item, (dict, list)):
                yield from _labels(item, path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _labels(item, prefix+'/'+str(index))


def project_materials(snapshot):
    sources = []
    for index, source in enumerate(snapshot.get('sources', [])):
        content = source.get('content', {})
        entry = dict(alias='s'+str(index+1), kind=source['kind'], role=source['role'], facts=[], labels=[])
        if source['kind'] == 'analysis_run' and source['role'] == 'computed_results':
            for key in FACT_ROOTS:
                if key in content:
                    entry['facts'].extend(dict(fact_path=path, value=value)
                        for path, value in numeric_leaves(content[key], '/'+key))
                    entry['labels'].extend(_labels(content[key], '/'+key))
        if source['kind'] in KINDS:
            entry.update(facts=list(numeric(source)), methods=deepcopy(content.get('methods', [])),
                gaps=deepcopy(content.get('gaps', [])),
                warnings=deepcopy(content.get('warnings', [])+content.get('limitations', [])))
        if source['kind'] in ('analysis_report', 'collection_report'):
            entry.update(report_text=content['text'], report_text_truncated=content['text_truncated'])
        sources.append(entry)
    illustrations = []
    for group in snapshot.get('results_groups', []):
        for kind, key, fields in (
            ('table', 'tables', ('number', 'title', 'columns', 'rows')),
            ('figure', 'figures', ('number', 'title', 'caption', 'panels')),
        ):
            for item in group.get(key, []):
                illustrations.append(dict(kind=kind, **{k:deepcopy(item[k]) for k in fields if k in item}))
    return dict(schema_version=1, output_language=snapshot['output_language'], sources=sources,
        context=[dict(id=s['id'], paragraphs=[dict(text=p['text']) for p in s['paragraphs']])
            for s in normalize_sections(snapshot)], illustrations=illustrations)
