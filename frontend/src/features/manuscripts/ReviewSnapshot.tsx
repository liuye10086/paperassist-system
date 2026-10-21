import {useI18n} from '../../shared/i18n'
import {formatValue} from './reviewPresentation'
import type {FrozenReview,Report} from './reviewTypes'
export function ReviewReport({report,onLocate}:{report:Report;onLocate?:(location:string)=>void}){
 const {t}=useI18n()
 return <div className="review-report"><p className={report.can_publish?'muted':'warning-panel'}>{t(report.issues.some(i=>i.id==='workflow:v2_scientific_language_review'&&i.severity==='error')?'该版本已完成 v2 科学与语言审核。此处仅可重新检查；修改或发布请返回受控的 v2 科学与语言审核工作区。':report.can_publish?'确定性检查未发现阻断项；自由文本与科研结论仍需人工核实。':'存在不可豁免的数值、来源或引用错误，禁止发布。')}</p><small>{t('规则版本')} · {report.rules_version}</small>
 {report.impacts.map((impact,i)=><article key={i}><strong>{t('影响待核对')}</strong><p>{impact.source_id} · {t(impact.scope==='linked'?'精确关联范围':'保守影响范围')}</p><p>{impact.reasons.join(' · ')}</p>{impact.locations.map(location=><button type="button" key={location} disabled={!onLocate} onClick={()=>onLocate?.(location)}>{location}</button>)}</article>)}
 <ul>{report.issues.map(issue=><li key={issue.id}><strong>{t(issue.severity==='error'?'硬错误':issue.severity==='warning'?'提醒':'需人工核实')}</strong> · {issue.id==='workflow:v2_scientific_language_review'?t(issue.message):issue.message}<details><summary>{t('问题依据与预期')}</summary><p>{t('位置')} · {issue.location}</p><p>{t('实际内容')} · {formatValue(issue.actual)}</p><p>{t('期望内容')} · {formatValue(issue.expected)}</p><p>{t('证据依据')} · {formatValue(issue.source_evidence)}</p><p>{t('规则版本')} · {issue.rules_version}</p></details>{onLocate&&<button type="button" onClick={()=>onLocate(issue.location)}>{t('定位资料')}</button>}</li>)}</ul></div>
}
export default function ReviewSnapshot({review,historical=false,historicalNotice='正文已重写，旧检查仅供历史查阅，须重新检查。'}:{review:FrozenReview;historical?:boolean;historicalNotice?:string}){
 const {t}=useI18n()
 return <details className="review-frozen"><summary>{t(historical?'历史检查记录（不适用于当前正文）':'冻结的确认资料与检查')}</summary><p className="warning-panel">{t(historical?historicalNotice:'用户确认不代表科研验证；以下记录与本版本导出一致。')}</p>
 {review.decisions.map((d,i)=><article key={i}><strong>{t('确认资料')} · {d.target_id}</strong><p>{t(d.status==='supplied'?'已补充':d.status==='selected'?'已选择':d.status==='pending'?'待核实':'不适用')} · {d.value}</p><p>{t('说明理由')} · {d.reason}</p><p>{t('证据依据')} · {d.evidence}</p><small>{d.created_by} · {d.created_at}</small></article>)}
 {review.metadata.length>0&&<details><summary>{t('已记录的元数据')}</summary>{review.metadata.map((m,i)=><p key={i}>{m.target_id} · {m.field} = {m.value} · {m.evidence}{m.stale&&<strong> · {t('已过期，须重新确认')}</strong>}</p>)}</details>}
 {review.relationships.associations.map(a=><article key={a.id}><strong>{t('研究关联')} · {a.research_question}</strong><p>{[...a.method_ids,...a.source_ids,...a.paragraph_ids,...a.figure_ids].join(' · ')}</p><p>{a.evidence}</p></article>)}
 {review.addendum.map(p=><p key={p.id}>{p.text}{p.pending_impact&&<> · {t('影响待核对')}</>}</p>)}
 {review.selected_sources.length>0&&<details><summary>{t('显式选择的补充来源')}</summary>{review.selected_sources.map(s=><p key={s.id}>{s.label} · {s.id} · {s.sha256}</p>)}{review.selected_facts.map(f=><p key={f.id}>{f.path} = {f.value} · {f.source_id}</p>)}</details>}
 <ReviewReport report={review.report}/></details>
}
