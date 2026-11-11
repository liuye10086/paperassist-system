import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import {RESEARCH_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import type {ProjectFile} from '../files/fileLibraryApi'
import type {AnalysisNavigation} from '../projects/analysisViews'
import useResearchDraft from '../research-results/useResearchDraft'
import {insightBase} from './api'
import {bulkComparisonLabel,bulkFigureLabels,type BulkFigureType,type BulkSelection} from './bulk'
import {
  bulkEvidenceKinds,bulkRoute,bulkWorkflowBase,bulkWorkflowStatuses,compatibleBulkAttachments,
  type BulkDeliveryFacts,type BulkDeliveryRequest,type BulkEvidence,type BulkSensitivityRequest,
  type BulkWorkflowComparison,type BulkWorkflowDescendant,
} from './bulkWorkflow'
import {useBulkRequest} from './bulkWorkflowHooks'
import BulkSelectionFields,{BulkSelectionSummary,newBulkSelectionDraft,toBulkSelection,type BulkSelectionDraft} from './BulkSelectionFields'
import {bulkComparisonOption,BulkSensitivitySummary} from './BulkSensitivity'
import {bulkEnrichmentReason} from './BulkEnrichmentResult'
import {kindLabels,type Page,type SourceItem} from './contracts'
import {useInsightRead} from './hooks'
import {DataDetails,Field,Paging,ReadState} from './InsightShared'

type Props = {
  projectId:string;comparisons:BulkWorkflowComparison[];descendants:BulkWorkflowDescendant[];files:ProjectFile[]
  outputLanguage?:'zh-CN'|'en';initialId?:string;sensitivity:Record<string,BulkSensitivityRequest>
  onNavigate:(navigation:AnalysisNavigation)=>void
}
type Draft = {
  attachments:string[];language:'zh'|'en';filters:BulkSelection[];editingFilter:BulkSelectionDraft|null
  includeSensitivity:boolean;attachedSensitivity?:BulkSensitivityRequest|null;evidence:BulkEvidence[]
}
const evidencePageSize=20

export default function BulkDelivery({projectId,comparisons,initialId,onNavigate,sensitivity,...props}:Props) {
  const {t}=useI18n()
  const [savedId,setSavedId]=useResearchDraft(projectId,'bulk-delivery-comparison',()=> '')
  const selectedId=initialId??savedId
  const selected=comparisons.find(item=>item.refs.result_version_id===selectedId)
  return <section className="analysis-detail" aria-label={t('Bulk Word 与完整复现包')}>
    <h3>{t('Bulk Word 与完整复现包')}</h3>
    <p>{t('选择主比较与兼容固定结果。预览会核对来源、确认、科学口径和局限。')}</p>
    {!comparisons.length&&<p>{t('暂无可用的固定 Bulk 比较结果。')}</p>}
    {!!comparisons.length&&<Field label="报告主比较固定版本" value={selectedId} onChange={value=>{
      setSavedId(value)
      onNavigate(bulkRoute('delivery',value||undefined))
    }}>
      <option value="">{t('请选择')}</option>
      {selectedId&&!selected&&<option value={selectedId}>{selectedId} · {t('固定版本当前不可用')}</option>}
      {comparisons.map(item=><option key={item.refs.result_version_id!} value={item.refs.result_version_id!}>
        {bulkComparisonOption(item)}{item.stale?` · ${t('历史固定版本')}`:''}
      </option>)}
    </Field>}
    {selectedId&&!selected&&<p role="alert">{t('所选主比较固定版本当前不可用。')}</p>}
    {selected&&<SelectedBulkDelivery key={selectedId} {...props} {...{projectId,selected,onNavigate}} sensitivity={sensitivity[selectedId]??null}/>}
  </section>
}

function SelectedBulkDelivery({projectId,selected,descendants,files,outputLanguage,sensitivity,onNavigate}:{
  projectId:string;selected:BulkWorkflowComparison;sensitivity:BulkSensitivityRequest|null
}&Pick<Props,'descendants'|'files'|'outputLanguage'|'onNavigate'>) {
  const {t,locale}=useI18n()
  const id=selected.refs.result_version_id!
  const [draft,update]=useResearchDraft<Draft>(projectId,`bulk-delivery:${id}`,()=>({
    attachments:[],language:(outputLanguage??locale)==='en'?'en':'zh',filters:[],editingFilter:null,includeSensitivity:false,evidence:[],
  }))
  const read=useBulkRequest<BulkDeliveryFacts>()
  const compatible=compatibleBulkAttachments(selected,descendants)
  const missing=draft.attachments.filter(versionId=>!compatible.some(item=>item.refs.result_version_id===versionId))
  const attachedSensitivity=draft.includeSensitivity?(draft.attachedSensitivity??sensitivity):null
  const missingSensitivity=draft.includeSensitivity&&!attachedSensitivity
  const body:BulkDeliveryRequest={comparison_version_id:id,result_version_ids:draft.attachments,language:draft.language,
    selections:draft.filters,sensitivity:attachedSensitivity,evidence:draft.evidence}
  const signature=JSON.stringify(body)
  const facts=read.data?.signature===signature?read.data.value:null
  const checked=!!facts&&(!facts.project_id||facts.project_id===projectId)&&(!facts.language||facts.language===body.language)
    &&facts.comparison_version_id===id&&/^[a-f0-9]{64}$/.test(facts.facts_digest)
    &&facts.selected_result_version_ids.length===body.result_version_ids.length
    &&facts.selected_result_version_ids.every((version,index)=>version===body.result_version_ids[index])
  const exportBody=checked?{...body,facts_digest:facts.facts_digest}:null
  const base=`${bulkWorkflowBase(projectId)}/delivery`
  const editing=draft.editingFilter
  const pendingFilter=editing&&toBulkSelection(editing,selected.contrasts)

  function toggleAttachment(versionId:string,include:boolean) {
    update(current=>({...current,attachments:include?[...current.attachments,versionId]:current.attachments.filter(item=>item!==versionId)}))
  }

  return <>
    <p>{t('主比较版本')} <code>{id}</code>{selected.stale&&<> · {t('历史固定版本')}</>}</p>
    <div className="intake-actions">
      <button type="button" onClick={()=>onNavigate({view:'bio-insight-result',fileId:'',bulkView:'differential',resultVersionId:id})}>{t('查看主比较固定结果')}</button>
      <button type="button" onClick={()=>onNavigate(bulkRoute('differential',id))}>{t('查看稳健性对照设置')}</button>
    </div>
    <form onSubmit={event=>{event.preventDefault();if(!missing.length&&!missingSensitivity&&!editing)void read.submit(`${base}/preview`,body,signature)}}>
      <fieldset className="bulk-workflow-fields" disabled={read.busy||!read.valid}>
        <Field label="报告语言" value={draft.language} onChange={language=>update({...draft,language:language as Draft['language']})}>
          <option value="zh">{t('简体中文')}</option><option value="en">English</option>
        </Field>
        <fieldset><legend>{t('附入兼容固定结果')}</legend>
          <p>{t('只列出同一主比较或其质控来源的可交付图件、候选与功能结果。')}</p>
          {!compatible.length&&<p>{t('暂无兼容的可交付附件。')}</p>}
          {compatible.map(item=>{
            const versionId=item.refs.result_version_id!
            const included=draft.attachments.includes(versionId)
            return <label className="intake-check" key={versionId}>
              <input type="checkbox" checked={included} disabled={!included&&draft.attachments.length>=20}
                onChange={event=>toggleAttachment(versionId,event.target.checked)}/>
              <span>{item.label||t(kindLabels[item.kind as keyof typeof kindLabels]??item.kind)} · <code>{versionId}</code>
                {' · '}{t(bulkWorkflowStatuses[item.status]??item.status)}{item.stale&&<> · {t('历史固定版本')}</>}</span>
            </label>
          })}
          {missing.map(versionId=><p role="status" key={versionId}>{t('固定版本当前不可用')} · <code>{versionId}</code>{' '}
            <button type="button" onClick={()=>toggleAttachment(versionId,false)}>{t('移除')}</button></p>)}
        </fieldset>
        <fieldset><legend>{t('报告筛选口径')}</legend>
          {!draft.filters.length&&<p>{t('使用固定比较的默认筛选口径。')}</p>}
          {draft.filters.map(value=><p key={value.contrast_id}><code>{value.contrast_id}</code> · <BulkSelectionSummary value={value}/>{' '}
            <button type="button" onClick={()=>update({...draft,editingFilter:{...value,q_threshold:String(value.q_threshold),minimum_absolute_effect:String(value.minimum_absolute_effect)}})}>{t('编辑')}</button>{' '}
            <button type="button" onClick={()=>update({...draft,filters:draft.filters.filter(item=>item.contrast_id!==value.contrast_id)})}>{t('移除')}</button>
          </p>)}
          {!editing&&<button type="button" disabled={draft.filters.length>=Math.min(10,selected.contrasts.length)}
            onClick={()=>update({...draft,editingFilter:newBulkSelectionDraft(selected.contrasts.length===1?selected.contrasts[0].contrast_id:'')})}>{t('自定义比较筛选')}</button>}
          {editing&&<>
            <BulkSelectionFields title="报告比较筛选" value={editing} contrasts={selected.contrasts} onChange={value=>update({...draft,editingFilter:value})}/>
            <div className="intake-actions">
              <button type="button" disabled={!pendingFilter||draft.filters.length>=10&&!draft.filters.some(item=>item.contrast_id===pendingFilter?.contrast_id)}
                onClick={()=>pendingFilter&&update({...draft,editingFilter:null,filters:[...draft.filters.filter(item=>item.contrast_id!==pendingFilter.contrast_id),pendingFilter]})}>{t('应用报告筛选')}</button>
              <button type="button" onClick={()=>update({...draft,editingFilter:null})}>{t('取消')}</button>
            </div>
          </>}
        </fieldset>
        {(sensitivity||draft.includeSensitivity)&&<label className="intake-check"><input type="checkbox" checked={draft.includeSensitivity}
          onChange={event=>update({...draft,includeSensitivity:event.target.checked,attachedSensitivity:event.target.checked?sensitivity:null})}/>
          {t('附上已核对的稳健性对照')} · <code>{(attachedSensitivity??sensitivity)?.scenario_version_id??'—'}</code>
        </label>}
        {missingSensitivity&&<p role="status">{t('所选稳健性对照当前不可用。')}</p>}
        <EvidencePicker projectId={projectId} comparisonId={id} descendants={descendants} files={files} value={draft.evidence}
          onChange={evidence=>update({...draft,evidence})}/>
        <button className="button-primary" type="submit" disabled={!!missing.length||missingSensitivity||!!editing}>{t('预览报告事实')}</button>
      </fieldset>
    </form>
    {read.busy&&<p role="status">{t('正在核验固定来源，大文件可能需要数分钟。')} <button type="button" onClick={read.cancel}>{t('取消等待')}</button></p>}
    {read.error&&<p role="alert">{t(read.error)}</p>}
    {facts&&!checked&&<p role="alert">{t('固定来源身份不匹配，请重新打开。')}</p>}
    {checked&&<BulkFactsPreview facts={facts}/>}
    {exportBody&&<section>
      <h4>{t('下载已核对的交付')}</h4>
      <p>{t('完整包包含统计表、筛选表、对象、参数、任务日志、软件与资源版本以及复现说明。')}</p>
      <p>{t('包内清单标明复现支持。匹配运行环境未留存时，交付包含固定数据与来源记录。')}</p>
      <div className="intake-actions">
        <ProjectDownloadLink href={`${base}/report.docx`} filename={`bulk-rna-report-${exportBody.facts_digest.slice(0,12)}.docx`}
          postBody={exportBody} timeoutMs={RESEARCH_REQUEST_TIMEOUT_MS}>{t('下载 Bulk Word 报告')}</ProjectDownloadLink>
        <ProjectDownloadLink href={`${base}/reproducibility-package`} filename={`bulk-rna-reproducibility-${exportBody.facts_digest.slice(0,12)}.zip`}
          postBody={exportBody} timeoutMs={RESEARCH_REQUEST_TIMEOUT_MS}>{t('下载 Bulk 完整复现包')}</ProjectDownloadLink>
      </div>
    </section>}
  </>
}

function EvidencePicker({projectId,comparisonId,descendants,files,value,onChange}:{
  projectId:string;comparisonId:string;descendants:BulkWorkflowDescendant[];files:ProjectFile[];value:BulkEvidence[];onChange:(value:BulkEvidence[])=>void
}) {
  const {t}=useI18n()
  const [draft,update]=useResearchDraft<{kind:BulkEvidence['kind']|'';sourceId:string;note:string}>(projectId,`bulk-evidence:${comparisonId}`,()=>({kind:'',sourceId:'',note:''}))
  const [page,setPage]=useState(1)
  const independent=draft.kind==='independent_analysis'
  const sourceCatalog=useInsightRead<Page<SourceItem>>(`${insightBase(projectId)}/sources?source_kind=bio_insight_result_version&page=${page}&page_size=${evidencePageSize}`,independent)
  const sources=independent?sourceCatalog.data?.items.filter(item=>item.kind==='comparison'&&!!item.sha256&&item.source_id!==comparisonId&&
    !descendants.some(row=>row.refs.result_version_id===item.source_id&&row.comparison_version_ids.includes(comparisonId)))
    .map(item=>({id:item.source_id,title:item.title}))??[]:files.map(file=>({id:file.id,title:file.filename}))
  const picked=sources.find(item=>item.id===draft.sourceId)
  const addable=!!draft.kind&&!!picked&&value.length<12&&!value.some(item=>item.kind===draft.kind&&item.source_id===picked.id)
  return <fieldset><legend>{t('独立分析与实验材料')}</legend>
    <p>{t('独立分析提供计算支持。实验材料按所选原件引用，验证结论须有实验依据。')}</p>
    <div className="bulk-workflow-fields">
      <Field label="佐证类型" value={draft.kind} onChange={kind=>{setPage(1);update({...draft,kind:kind as typeof draft.kind,sourceId:''})}}>
        <option value="">{t('请选择')}</option>
        {Object.entries(bulkEvidenceKinds).map(([key,label])=><option key={key} value={key}>{t(label)}</option>)}
      </Field>
      {draft.kind&&<>
        <Field label={independent?'选择独立分析版本':'选择实验材料原件'} value={draft.sourceId} onChange={sourceId=>update({...draft,sourceId})}>
          <option value="">{t('请选择')}</option>
          {sources.map(item=><option key={item.id} value={item.id}>{item.title} · {item.id}</option>)}
        </Field>
        {independent&&<><ReadState {...sourceCatalog}/>{sourceCatalog.data&&<Paging page={page} size={evidencePageSize} total={sourceCatalog.data.total}
          onPage={next=>{setPage(next);update({...draft,sourceId:''})}}/>}</>}
        <label>{t('来源说明')}<textarea rows={3} maxLength={1000} value={draft.note} onChange={event=>update({...draft,note:event.target.value})}/></label>
        <button type="button" disabled={!addable} onClick={()=>{
          if(!draft.kind||!picked||!addable)return
          onChange([...value,{kind:draft.kind,source_id:picked.id,note:draft.note.trim()}]);update({...draft,sourceId:'',note:''})
        }}>{t('添加佐证引用')}</button>
      </>}
    </div>
    <ul className="bulk-evidence-list">{value.map(item=><li key={`${item.kind}:${item.source_id}`}>
      <strong>{t(bulkEvidenceKinds[item.kind])}</strong> · <code>{item.source_id}</code>{item.note&&<> · {item.note}</>}{' '}
      <button type="button" onClick={()=>onChange(value.filter(other=>other!==item))}>{t('移除')}</button>
    </li>)}</ul>
  </fieldset>
}

const qcLabels:Record<string,string>={raw_observations:'原始样本数',retained_observations:'保留样本数',excluded_observations:'排除样本数',
  raw_features:'原始特征数',retained_features:'保留特征数',excluded_features:'排除特征数'}
const countLabels:Record<string,string>={total:'总行数',tested:'已检验',excluded:'排除',not_computable:'不可计算',missing_metric:'缺少统计值',
  deg:'显著 DEG',up:'上调 DEG',down:'下调 DEG',selected:'筛选行数'}

function BulkFactsPreview({facts}:{facts:BulkDeliveryFacts}) {
  const {t,locale}=useI18n()
  const [details,setDetails]=useState(false)
  const confirmation=facts.design.confirmation
  return <section className="bulk-facts" aria-label={t('固定报告事实预览')}>
    <h4>{t('固定报告事实预览')}</h4>
    <p>{t('事实摘要校验值')} <code>{facts.facts_digest}</code></p>
    <h5>{t('样本质控与设计确认')}</h5>
    <p>{t('固定处理版本')} · {(facts.processed_version_ids??[facts.processed_version_id]).map(id=><code key={id}>{id}{' '}</code>)}</p>
    <dl className="bulk-workflow-metrics">{Object.entries(qcLabels).map(([key,label])=>{
      const value=facts.qc.summary[key]
      return typeof value==='number'?<div key={key}><dt>{t(label)}</dt><dd>{value}</dd></div>:null
    })}</dl>
    <p>{facts.design.formula&&<code>{facts.design.formula}</code>} · {t('设计秩')} {facts.design.rank??'—'} · {t('残差自由度')} {facts.design.residual_df??'—'}</p>
    <p>{t('物种分类号')} {facts.design.species_taxon_id??'—'} · {t('标识体系')} {facts.design.namespace??'—'} · {t('参考版本')} {facts.design.reference_version??'—'}</p>
    {confirmation&&<p>{t('固定模型确认')} · <code>{confirmation.plan_version_id}</code> · <time dateTime={confirmation.confirmed_at}>
      {new Date(confirmation.confirmed_at).toLocaleString(locale)}</time></p>}
    {!!facts.qc.input_files?.length&&<p>{t('固定输入文件')} · {facts.qc.input_files.map(item=>item.filename).join(' · ')}</p>}
    <h5>{t('固定比较与统计口径')}</h5>
    {facts.contrasts.map(contrast=><section key={contrast.contrast_id}>
      <p><strong>{bulkComparisonLabel(contrast)}</strong> · <BulkSelectionSummary value={contrast.selection}/></p>
      <dl className="bulk-workflow-metrics">{Object.entries(contrast.counts).map(([key,value])=><div key={key}>
        <dt>{t(countLabels[key]??key)}</dt><dd>{value}</dd>
      </div>)}</dl>
    </section>)}
    {facts.figures.length>0&&<><h5>{t('固定图件与来源')}</h5><ul>{facts.figures.map(item=><li key={`${item.version_id}:${item.figure_type}:${item.panel??''}`}>
      {item.title||t(bulkFigureLabels[item.figure_type as BulkFigureType]??item.figure_type)} · <code>{item.version_id}</code> · {t('固定来源版本')} <code>{item.source_version_id}</code>
    </li>)}</ul></>}
    {facts.enrichments.length>0&&<><h5>{t('功能分析实际状态')}</h5><ul>{facts.enrichments.map(item=><li key={item.version_id}>
      {t(kindLabels[item.kind as keyof typeof kindLabels]??item.kind)} · {t(bulkWorkflowStatuses[item.status]??item.status)} · <code>{item.version_id}</code>
      {item.not_applicable_reason&&<> · {t(bulkEnrichmentReason(item.not_applicable_reason))}</>}
    </li>)}</ul></>}
    {!!facts.resource_version_ids.length&&<p>{t('固定资源版本')} · {facts.resource_version_ids.map(id=><code key={id}>{id}{' '}</code>)}</p>}
    {facts.sensitivity&&<BulkSensitivitySummary result={facts.sensitivity}/>}
    {facts.evidence.length>0&&<><h5>{t('独立分析与实验材料')}</h5><ul>{facts.evidence.map(item=><li key={`${item.kind}:${item.source_id}`}>
      {t(bulkEvidenceKinds[item.kind])} · {item.filename&&<>{item.filename} · </>}<code>{item.source_id}</code>
      {item.verification_status==='saved_execution_verified'&&<> · {t('已核对固定计算记录')}</>}
      {item.verification_status==='attachment_integrity_verified'&&<> · {t('已核对原件完整性')}</>}
      {item.independence_status==='unverified'&&<> · {t('样本独立性尚未核对')}</>}
      {!!item.shared_processed_source_ids?.length&&<> · {t('共享固定处理来源')} {item.shared_processed_source_ids.join(', ')}</>}
      {item.note&&<> · {item.note}</>}
    </li>)}</ul></>}
    <h5>{t('方法局限与使用范围')}</h5><ul>{facts.limitations.map((item,index)=><li key={index}>{item}</li>)}</ul>
    <details onToggle={event=>setDetails(event.currentTarget.open)}><summary>{t('查看方法、来源与佐证详情')}</summary>
      {details&&<>
      <DataDetails title="样本质控" value={facts.qc}/>
      <DataDetails title="确认设计与方法" value={facts.design}/>
      <DataDetails title="固定候选" value={facts.candidates}/>
      <DataDetails title="固定来源与资源" value={facts.references}/>
      <DataDetails title="独立分析与实验材料" value={facts.evidence}/>
      </>}
    </details>
  </section>
}
