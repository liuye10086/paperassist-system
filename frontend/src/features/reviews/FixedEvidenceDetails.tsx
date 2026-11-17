import {useI18n} from '../../shared/i18n'
import {contentText,object,type Evidence} from './revisionTypes'
import {customerEvidenceExcerpt,customerEvidenceLabel} from './customerReviewDisplay'

function evidenceLabel(evidence:Evidence){
 const value=evidence.content
 const filename=object(value)?[value.filename,value.label,value.title,object(value.file)?value.file.filename:null].find(v=>typeof v==='string'&&v.trim()):typeof value==='string'?value:null
 return evidence.kind+(typeof filename==='string'?' · '+filename.slice(0,100)+(filename.length>100?'…':''):'')
}

type Props = {evidence: Evidence; customer?: boolean; names?: ReadonlyMap<string, string>}

export function EvidenceLabel({evidence, customer, names}:Props) {
 const {t}=useI18n()
 return <>{customer ? customerEvidenceLabel(evidence,t,names) : evidenceLabel(evidence)}</>
}

export default function FixedEvidenceDetails({evidence,customer,names}:Props) {
 const {t}=useI18n()
 if(customer) {
  const excerpt=customerEvidenceExcerpt(evidence,t)
  return <div className="review-reader-evidence">
   <strong>{customerEvidenceLabel(evidence,t,names)}</strong>
   {excerpt&&<p>{excerpt}</p>}
  </div>
 }
 return <details className="review-fixed-evidence"><summary>{evidenceLabel(evidence)} · <small title={evidence.sha256}>SHA256 {evidence.sha256.slice(0,12)}…</small></summary><p>SHA256 {evidence.sha256}</p><pre className="review-original" aria-label={t('固定证据正文')}>{contentText(evidence.content)}</pre></details>
}

export function FixedChangeValue({value}:{value:unknown}){const {t}=useI18n();return value!==null&&typeof value==='object'?<details className="review-fixed-value"><summary>{t('展开固定结构化内容')}{Array.isArray(value)?' · '+t('{number} 项',{number:value.length}):''}</summary><pre className="review-original">{contentText(value)}</pre></details>:<>{contentText(value)}</>}
