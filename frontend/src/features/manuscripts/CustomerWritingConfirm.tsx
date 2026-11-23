import {useEffect,useState} from 'react'
import {useI18n} from '../../shared/i18n'
import VersionLabel from '../../shared/VersionLabel'
import type {ManuscriptVersion} from './manuscriptTypes'
import WritingBundlePreview from './WritingBundlePreview'
import {intactBundle,materialsChanged} from './useCustomerWritingSubmit'
import type {Bundle,WritingCapabilities} from './writingLiveTypes'

type Props={
 bundle:Bundle|null;version:ManuscriptVersion;capabilities:WritingCapabilities|null;customerThesis:boolean
 /** This version already has a writing request: the page warns about the new fee. */
 generated:boolean
 /** A request of this version is still queued or running: generating again waits until it ends. */
 generating?:boolean
 /** The input changed after the last preview, so a new one is needed. */
 edited:boolean
 /** An authorization or writing request has an unknown result. */
 unknown:boolean
 /** A writing preview request has an unknown result; it costs nothing and may be resent. */
 previewUnknown:boolean
 busy:boolean
 onPreview:()=>void;onSubmit:(bundle:Bundle)=>Promise<void>;onCheckResult:()=>void
}
const articleNames:Record<string,string>={research:'研究型论文',brief:'简报',narrative_review:'综述',methods:'方法论文'}
// Rounded up to the cent, so the displayed cost estimate is never lower than the server's.
const estimatedCost=(micro:number)=>`US$${(Math.ceil(micro/10000)/100).toFixed(2)}`
// The server names the receiver by its endpoint and the storage scope by an English notice. Only known values are
// shown, as a service name and a localized sentence; anything else falls back to the generic wording.
const providerNames:Record<string,string>={'https://api.openai.com/v1/responses':'OpenAI','OpenAI':'OpenAI'}
const storageScopes:Record<string,string>={'OpenAI stores background responses; selected material is transmitted externally.':'所选材料会发送到外部服务，后台生成记录由服务商保留'}

// Customer SCI and thesis writing: materials, external send notice, fee and one confirmation (DESIGN 8.2, 总案 D5).
export default function CustomerWritingConfirm({bundle,version,capabilities,customerThesis,generated,generating=false,edited,unknown,previewUnknown,busy,onPreview,onSubmit,onCheckResult}:Props){
 const {t}=useI18n(),[confirmed,setConfirmed]=useState(false),[check,setCheck]=useState<'checking'|'ok'|'failed'>('checking'),[sending,setSending]=useState(false)
 // A new preview starts a new confirmation.
 // oxlint-disable-next-line react/set-state-in-effect
 useEffect(()=>{setConfirmed(false);setCheck('checking');if(!bundle)return;let current=true;void intactBundle(bundle).then(ok=>{if(current)setCheck(ok?'ok':'failed')});return()=>{current=false}},[bundle])
 const enabled=!!capabilities?.real_calls_enabled
 const request=bundle?.request_json,articleType=request?.schema_version===4?request.article_type:undefined
 const provider=providerNames[capabilities?.provider?.trim()??''],scopeKey=storageScopes[capabilities?.storage_scope?.trim()??''],scope=scopeKey&&t(scopeKey)
 const notice=provider?(scope?t('本次材料将发送给 {provider}，生成结果由服务商保存（{scope}）。',{provider,scope}):t('本次材料将发送给 {provider}，生成结果由服务商保存。',{provider}))
  :(scope?t('本次材料将发送给外部写作服务，生成结果由服务商保存（{scope}）。',{scope}):t('本次材料将发送给外部写作服务，生成结果由服务商保存。'))
 const canSubmit=!!bundle&&check==='ok'&&confirmed&&enabled&&!busy&&!unknown&&!sending&&!generating
 async function submit(){
  if(!canSubmit||!bundle)return
  setSending(true)
  try{await onSubmit(bundle)}finally{setSending(false);setConfirmed(false)}
 }
 const action=generated?'再次生成正文':'生成正文初稿'
 return <section className="customer-writing-confirm" aria-label={t('生成正文确认')}>
  <p className="muted"><VersionLabel revision={version.revision} savedAt={version.created_at}/>{articleType&&<> · {t(articleNames[articleType]??'研究型论文')}</>}{request&&<> · {t(request.output_language==='zh-CN'?'中文':'英文')}</>}</p>
  {!enabled&&capabilities&&<p role="status">{t('写作服务暂未开启，暂时不能生成正文。')}</p>}
  {unknown?<>
   <p role="alert" className="warning-panel">{t('暂时无法确定这次提交是否成功。请先查看提交结果。')}</p>
   <div className="actions"><button type="button" disabled>{t(action)}</button><button type="button" disabled={busy} onClick={onCheckResult}>{t('查看提交结果')}</button></div>
  </>:!bundle?<>
   <p role="status">{t(previewUnknown?'写作材料预览还没有准备好，请重新准备。':busy?'正在准备写作材料预览……':edited?'写作材料已修改，请更新写作材料预览后再生成。':'请先准备本次写作材料预览。')}</p>
   <button type="button" disabled={busy} onClick={onPreview}>{t(previewUnknown?'重新准备写作材料预览':'更新写作材料预览')}</button>
  </>:<>
   <h4>{t('本次将使用以下材料生成正文')}</h4>
   <WritingBundlePreview bundle={bundle} customerThesis={customerThesis} readableSnapshot={version.snapshot} materialsOnly savedAt={version.created_at}/>
   {check==='failed'&&<p role="alert">{t(materialsChanged)}</p>}
   <p>{notice}</p>
   <p>{t('生成正文会产生写作费用。')}{bundle.reserved_micro_usd!=null&&bundle.reserved_micro_usd>0&&t('预计费用 {amount}。',{amount:estimatedCost(bundle.reserved_micro_usd)})}{t('实际费用以用量记录为准。提交失败或结果未知时，不会自动重新提交。')}</p>
   {generated&&<p className="warning-panel">{t('这一版已经生成过正文。再次生成会产生新的写作费用，之前的生成结果仍可查看。')}</p>}
   <label><input type="checkbox" checked={confirmed} disabled={check!=='ok'||!enabled||busy||sending} onChange={e=>setConfirmed(e.target.checked)}/>{t('我确认用以上材料生成正文，接受本次写作费用和外部保存范围。')}</label>
   <div className="actions"><button type="button" className="button-primary" disabled={!canSubmit} onClick={()=>void submit()}>{t(action)}</button></div>
  </>}
 </section>
}
