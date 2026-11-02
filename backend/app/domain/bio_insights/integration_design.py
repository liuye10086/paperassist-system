"""Admission reads frozen metadata, never imports the scientific environment."""
import json
from pathlib import Path
from .design import DesignPreview,DesignReason,ResourceEstimate
from .integration_matching import match_samples,object_decision

class IntegrationPreview(DesignPreview):
    integration_units:dict
    correspondence_audit:list[dict]

def validate_integration_design(config,sources):
    by_id={s['source_id']:s for s in sources};reasons=[];units={};audit=[]
    def block(code,message):
        if not any(r.code==code for r in reasons):reasons.append(DesignReason(code=code,message=message))
    if not config.mapping_confirmed:block('mapping_confirmation_required','请先核对并确认冻结样本与对象对应关系。')
    data={}
    for sid,kind in [(config.sample_mapping_source_id,'sample_correspondence'),(config.object_mapping_source_id,'object_correspondence')]:
        if not sid:continue
        s=by_id[sid]
        if s['metadata'].get('kind')!=kind:block('correspondence_resource_kind_mismatch','对应资源类型不匹配。');continue
        data[kind]=json.loads(Path(s['members']['resource']['path']).read_bytes())['rows']
    for p in config.pairs:
        a,b=by_id[p.left_source_id]['metadata'],by_id[p.right_source_id]['metadata']
        if any(m.get('observation_level')!='sample' or config.analysis_layer not in m.get('layers',{}) for m in (a,b)):
            block('integration_requires_saved_sample_layer','需要已保存的样本轴定量层。');continue
        if set(data)!={'sample_correspondence','object_correspondence'}:continue
        axes=[[r['sample_id'] for r in m['observations'] if r.get('retained') in (True,'true','True','1',1)] for m in (a,b)]
        matches,ledger=match_samples(data['sample_correspondence'],p.left_source_id,p.right_source_id,*axes,inference=config.mode=='inference')
        units[p.pair_id]={'matched_observation_count':len(matches),'independent_n':len(matches) if config.mode=='inference' else None};audit.extend(dict(pair_id=p.pair_id,**r) for r in ledger)
        if any(not r['included'] for r in ledger) and not config.partial_subset_confirmed:block('partial_matching_requires_subset_confirmation','存在未配对或排除记录，必须先确认使用子集；全部记录将导出。')
        if config.mode=='inference' and any(r['reason'] in ('independent_unit_unverified','repeated_donor_requires_frozen_selection') for r in ledger):block('independent_units_not_resolved','独立供体未核实或重复；请先冻结单一时间/组织选择或已保存汇总结果。')
        _,reason=object_decision(data['object_correspondence'],p,a,b,inference=config.mode=='inference')
        if reason:block(reason,'对象对应缺失、身份不兼容或存在未解决的推断歧义。')
    for c in config.concordances:
        for sid in (c.left_result_source_id,c.right_result_source_id):
            s=by_id[sid];meta=s['metadata'];pathway=meta.get('kind') in ('ora','gsea_prerank')
            if meta.get('kind') not in ('comparison','result_import','ora','gsea_prerank') or (meta.get('summary_json') or {}).get('eligible_term_family_complete' if pathway else 'tested_universe_complete') is not True:
                block('concordance_requires_complete_saved_universe','一致性需要完整已受检比较或完整通路族结果；不能以显著子集冒充全集。')
    return IntegrationPreview(executable=not reasons,blocking_reasons=reasons,integration_units=units,correspondence_audit=audit,resource_estimate=ResourceEstimate(observations=sum(u['matched_observation_count'] for u in units.values()),features=len(config.pairs),contrasts=len(config.concordances),estimated_working_bytes=0),warnings=['描述性模式仅计算系数，独立供体 n 未知、P/q 为 NA；匹配观测数不等于独立供体数。','不同依赖组不证明独立；未显著不代表等效，相关不代表因果。'])
