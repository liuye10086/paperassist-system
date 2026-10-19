import {useCallback,useRef,useState} from 'react'
import {useI18n} from '../../shared/i18n'
import {basePath,validReference,validDetail,validPage,type Reference,type ReferenceDetail,type Page} from './literatureApi'
import {evidenceBase,validEvidenceConfig} from './evidenceApi'
import {useEvidenceResource} from './evidenceHooks'
import LiteratureMaterials,{EvidencePagination,type SelectedSource} from './LiteratureMaterials'
import LiteratureClaims,{type ClaimSelection} from './LiteratureClaims'
import LiteraturePmc from './LiteraturePmc'
import LiteratureAssistance from './LiteratureAssistance'
import SavedSearchContext from './SavedSearchContext'
type Props={projectId:string;researchTopic:string;outputLanguage?:string;onOpenTask?:(id:string)=>void;onDenied?:()=>void}
export default function EvidenceWorkspace(props:Props){return <EvidenceScope key={props.projectId} {...props}/>}
function EvidenceScope({projectId,researchTopic,outputLanguage,onOpenTask,onDenied}:Props){
 const {t,locale}=useI18n();const [denied,setDenied]=useState(false),[revision,setRevision]=useState(0),[referencePage,setReferencePage]=useState(1),[referenceId,setReferenceId]=useState(''),[sourcePage,setSourcePage]=useState(1),[searchId,setSearchId]=useState(''),[source,setSource]=useState<SelectedSource|null>(null),[claim,setClaim]=useState<ClaimSelection|null>(null)
 const materialsArea=useRef<HTMLDivElement>(null)
 const deny=useCallback(()=>{setDenied(true);onDenied?.()},[onDenied])
 const config=useEvidenceResource(denied?null:`${evidenceBase(projectId)}/config`,v=>validEvidenceConfig(v,projectId),revision,deny)
 const references=useEvidenceResource<Page<Reference>>(denied?null:`${basePath(projectId)}/references?page=${referencePage}`,v=>validPage(v,projectId,referencePage,x=>validReference(x,projectId)),revision,deny)
 const params=new URLSearchParams({page:String(sourcePage)});if(searchId)params.set('search_id',searchId)
 const detail=useEvidenceResource<ReferenceDetail>(!denied&&referenceId?`${basePath(projectId)}/references/${encodeURIComponent(referenceId)}?${params}`:null,(v):v is ReferenceDetail=>validDetail(v,projectId,referenceId,sourcePage)&&(!searchId||v.source.search_id===searchId),revision,deny)
 if(denied)return <p role="alert">{t('项目不存在或无权访问。')}</p>
 return <section className="literature-evidence-workspace" aria-label={t('项目论述证据工作区')}><div className="literature-actions"><h2>{t('论述与证据核验')}</h2><button type="button" onClick={()=>{setRevision(r=>r+1);setSource(null);setClaim(null)}}>{t('刷新证据记录')}</button></div><p>{t('从已保存摘要、用户材料或 PMC 正文片段，按论述版本保存人工核验。')}</p>
 {config.error&&<p role="alert">{t(config.error)}</p>}{config.data&&<p className="muted">{t('可读取用户材料与已保存 PMC 来源；新模型调用默认关闭；补搜最多 1 轮、20 篇。')}</p>}
 <section className="literature-panel" aria-label={t('选择证据来源')}><h3>{t('选择证据来源')}</h3>{references.error&&<p role="alert">{t(references.error)}</p>}<label>{t('选择项目文献')}<select value={referenceId} onChange={e=>{setReferenceId(e.target.value);setSearchId('');setSourcePage(1);setSource(null)}}><option value="">{t('请选择文献')}</option>{references.data?.items.map(r=><option key={r.id} value={r.id}>{r.record.title||t('题名未提供')} · PMID {r.pmid}</option>)}</select></label>{references.data&&<EvidencePagination page={referencePage} total={references.data.total} label="证据文献分页" onPage={p=>{setReferencePage(p);setReferenceId('');setSearchId('');setSource(null)}}/>}
 {detail.error&&<p role="alert">{t(detail.error)}</p>}{detail.data&&<><h4 className="literature-original">{detail.data.record.title}</h4><label>{t('摘要的已保存检索来源')}<select value={detail.data.source.search_id} onChange={e=>{setSearchId(e.target.value);setSource(null)}}>{[detail.data.source,...detail.data.sources.items.filter(s=>s.search_id!==detail.data!.source.search_id)].map(s=><option key={s.search_id} value={s.search_id}>{s.query} · {new Date(s.retrieved_at).toLocaleString(locale)}{s.source_kind==='synthetic_fixture'?` · ${t('合成测试资料')}`:''}</option>)}</select></label><EvidencePagination page={sourcePage} total={detail.data.sources.total} label="摘要来源分页" onPage={p=>{setSourcePage(p);setSource(null)}}/>
 <SavedSearchContext context={detail.data.source.source_context}/><p className="muted">{t('摘要摘录绑定所选检索快照，不使用手工输入的来源内容。')}</p>{detail.data.record.abstract_status==='available'?detail.data.record.abstract.map((a,i)=><article key={i}><p className="literature-original">{a.label&&<strong>{a.label}: </strong>}{a.text}</p><button type="button" disabled={!a.text} onClick={()=>setSource({source_kind:'abstract',search_id:detail.data!.source.search_id,text:a.text})}>{t('从此摘要段摘录')}</button></article>):<p>{t('所选来源没有已保存摘要，可选择用户材料。')}</p>}</>}
 </section>
 <LiteraturePmc key={`pmc:${referenceId}:${revision}`} projectId={projectId} referenceId={referenceId} onSource={value=>{setSource(value);if(value?.project_reference_id&&value.project_reference_id!==referenceId){setReferenceId(value.project_reference_id);setSearchId('');setSourcePage(1)}}} onDenied={deny}/>
 <div ref={materialsArea} tabIndex={-1}><LiteratureMaterials key={`${referenceId}:${revision}`} projectId={projectId} referenceId={referenceId} onSource={setSource} onDenied={deny}/></div>
 <LiteratureClaims key={`claims:${revision}`} projectId={projectId} outputLanguage={outputLanguage} referenceId={referenceId} referenceTitles={Object.fromEntries(references.data?.items.map(r=>[r.id,r.record.title||`PMID ${r.pmid}`])??[])} source={source} onDenied={deny} onSelection={setClaim} onOpenTask={onOpenTask} onAddMaterials={()=>{materialsArea.current?.scrollIntoView?.({behavior:'smooth',block:'start'});materialsArea.current?.focus()}}/>
 <LiteratureAssistance key={`assistance:${revision}`} projectId={projectId} researchTopic={researchTopic} outputLanguage={outputLanguage} referenceId={referenceId} selection={claim} onDenied={deny} onOpenTask={onOpenTask}/>
 </section>
}
