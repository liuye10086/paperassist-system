"""Server-side source/axis and original alias admission, without statistics."""
from pathlib import Path
from .design import DesignPreview,DesignReason,ResourceEstimate
from .external_matrix import build_matrix
from app.domain.external_evidence.typed import EvidenceLocator,TypedEvidence,verify_locators

class EvidencePreview(DesignPreview):
    evidence_matrix:list[dict]
    dependency_groups:dict


def validate_evidence_design(config,sources):
    by_id={s['source_id']:s for s in sources};reasons=[]
    def block(code,message):reasons.append(DesignReason(code=code,message=message))
    for c in config.candidates:
        source=by_id[c.source_id];m=source['metadata']
        if c.feature_id not in m.get('retained_feature_ids',m.get('feature_ids',[])):block('candidate_not_on_fixed_axis','候选原 ID 不在固定处理层保留轴。')
        if any(getattr(c,k)!=m.get(k) for k in ('namespace','species_taxon_id','reference_version')):block('candidate_identity_mismatch','候选物种、命名空间或参考版本与固定层不同；未知值必须原样保留。')
        if c.object_id!=c.feature_id:
            alias=by_id[c.mapping_evidence_source_id];e=TypedEvidence.model_validate(alias['metadata']['typed_evidence'])
            try:
                if not all(token.casefold() in c.mapping_quote.casefold() for token in (c.object_id,c.feature_id)):raise ValueError('alias_names_missing')
                loc=EvidenceLocator(kind='xml_id' if alias['metadata']['filename'].lower().endswith('.xml') else 'text',value=c.mapping_locator,quote=c.mapping_quote)
                verify_locators(Path(alias['members']['original_file']['path']).read_bytes(),alias['metadata']['filename'],e.model_copy(update={'locators':[loc]}))
            except (ValueError,KeyError,UnicodeError):block('candidate_alias_original_not_matched','候选别名需要同时含原 ID 和目标 ID 的固定原文定位。')
    for sid in config.integration_result_source_ids:
        if by_id[sid]['metadata'].get('kind')!='integration':block('integration_result_required','整合关联必须引用固定 integration 结果；不将外部对象冒称对应相关对。')
    data=build_matrix([c.model_dump(mode='json') for c in config.candidates],[by_id[s] for s in config.evidence_source_ids],[r.model_dump(mode='json') for r in config.independent_support_requests],sources)
    return EvidencePreview(executable=not reasons,blocking_reasons=reasons,evidence_matrix=data['matrix'],dependency_groups=data['dependency_groups'],resource_estimate=ResourceEstimate(observations=0,features=len(config.candidates),contrasts=0,estimated_working_bytes=0),warnings=['原文声明、人工核对、系统整理与独立支持分别记录；不同依赖组不证明独立。','未知不是阴性；条件/物种不同时不推广结论；没有真实 KO 或独立 run 时保留缺口。'])
