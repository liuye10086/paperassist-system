"""Pure label shim, also packaged verbatim for offline report reconstruction."""
import re


def labels():
    from .tables import LABELS, SECTIONS
    return {**LABELS, **SECTIONS}


def install(document_module, mapping, workbook_module):
    """Install only inside the dedicated renderer/rebuild process."""
    original=document_module.location_label
    def location_label(value,en):
        return mapping[value][int(en)] if value in mapping else original(value,en)
    document_module.location_label=location_label
    original_index=document_module.reader_fact_index
    def reader_fact_index(finding,en):
        facts,titles,locations=original_index(finding,en)
        locations=dict(locations)
        for identifier,fact in facts.items():
            # The base index accepts a title only when kind/id/SHA match and
            # the matched frozen sources agree. Missing/ambiguous matches keep
            # its neutral label; row order, values and figures are not evidence.
            if fact.get('source_kind')!='analysis_run' or not re.fullmatch(r'[a-f0-9]{64}',fact.get('source_sha256') or ''):
                continue
            title=titles[identifier]
            number=re.fullmatch(r'(?:Run|Analysis) ([1-9][0-9]*) · .+' if en else r'分析 ([1-9][0-9]*) · .+',title)
            if number:
                locations[identifier]=('Analysis ' if en else '分析 ')+number[1]+' / '+locations[identifier]
        return facts,titles,locations
    document_module.reader_fact_index=reader_fact_index
    # XLSX has its own Source column and retains the original index alias.
    # Reuse the existing width-based wrapping/row-height calculation only here.
    workbook_module.WRAPPED_SHEETS=(*workbook_module.WRAPPED_SHEETS,'Facts')
