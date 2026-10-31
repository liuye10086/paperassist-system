"""External declarations and original values never become system computations."""
from .bio_projection import fact_id
from .contracts import ResearchFact,ResearchFactCatalog


def project_external_facts(source):
    facts=[]
    if 'cell_value' in source.content:
        raw=source.content['cell_value']
        facts.append(ResearchFact(id=fact_id(source,source.locator),source_kind=source.source_kind,
            source_id=source.source_id,source_sha256=source.sha256,locator=source.locator,raw_value=raw,
            display_value='NA' if raw is None else str(raw),observation_level='unknown',
            verification_status='missing' if raw is None else 'unverified',origin='external_result',
            limitations=['外部结果未重算，独立样本、单位和统计口径须依据原始材料确认。']))
    return ResearchFactCatalog(source=source,facts=facts,methods=source.methods,
        gaps=source.content.get('gaps',[]),limitations=['外部材料仅作有来源的结果或观察，未由本系统重新计算。'])
