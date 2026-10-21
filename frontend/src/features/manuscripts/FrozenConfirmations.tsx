import {useI18n} from '../../shared/i18n'
import type {Snapshot} from './manuscriptTypes'
import {decisionStatus,formatValue,frozenDecisions,targetLabel} from './reviewPresentation'

type FrozenDecision=NonNullable<Snapshot['review']>['decisions'][number]
export function FrozenDecisionDetails({decision}:{decision:FrozenDecision}){
 const {t}=useI18n()
 return <div className="review-frozen-decision">
  <p><strong>{t('既有冻结状态')}</strong> · <span>{t(decisionStatus(decision.status))}</span></p>
  {decision.value&&<p>{decision.value}</p>}
  <details><summary>{t('冻结确认的理由与依据')}</summary>
   <p>{t('说明理由')} · {decision.reason}</p>
   <p>{t('证据依据')} · {decision.evidence}</p>
   <p>{t('基础版本 {number}',{number:decision.base_revision})} · {decision.created_by} · {decision.created_at}</p>
   <p>{t('来源版本与内容')} · {formatValue(decision.source_versions)}</p>
  </details>
 </div>
}
export default function FrozenConfirmations({snapshot}:{snapshot:Snapshot}){
 const {t}=useI18n(),decisions=frozenDecisions(snapshot)
 if(!decisions.length)return null
 return <section className="review-confirmations" aria-label={t('当前版本已冻结的确认')}>
  <h4>{t('当前版本已冻结的确认')}</h4>
  <p>{t('这些是当前保存版本的用户确认，不代表科研验证；不会自动加入本次提交。')}</p>
  {decisions.map(decision=><article key={decision.target_id}>
   <strong>{t(targetLabel(decision.target_id))}</strong>
   <FrozenDecisionDetails decision={decision}/>
  </article>)}
 </section>
}
