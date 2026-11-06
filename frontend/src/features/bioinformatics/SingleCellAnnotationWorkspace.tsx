import {useState} from 'react'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import {useI18n} from '../../shared/i18n'
import type {AnalysisNavigation} from '../projects/analysisViews'
import type {RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import useDraftLeaveGuard from '../projects/useDraftLeaveGuard'
import {projectBase} from './api'
import BioAnnotationEditor,{type AnnotationDraft} from './BioAnnotationEditor'
import {SingleCellCandidateTask,SingleCellCandidateReview} from './SingleCellCandidates'
import {BioWriteStatus} from './BioSpatialShared'
import {sameRawBioSource,type BioAnnotation,type BioFigure,type BioProcessed,type BioRecipeParameters,type BioRun} from './spatialContracts'
import {useBioRead} from './spatialHooks'
import useBioWrite from './useBioWrite'

const ids=(text:string)=>[...new Set(text.split(/[\s,]+/).filter(Boolean))]
function subsetParameters(parent:BioRecipeParameters){
 const params:BioRecipeParameters&{min_gene_spots?:unknown}={...parent,cell_labels:[],doublet:{enabled:false,exclude_predicted:false,expected_rate:null},decontx:{enabled:false}}
 delete params.min_gene_spots
 return params
}
export default function SingleCellAnnotationWorkspace({projectId,result,onNavigate,registerLeaveGuard}:{projectId:string;result:BioProcessed;onNavigate:(n:AnalysisNavigation)=>void;registerLeaveGuard?:RegisterLeaveGuard}){
 const {t}=useI18n(),base=projectBase(projectId)
 const read=useBioRead<{items:BioAnnotation[]}>(`${base}/bio-processed-datasets/${encodeURIComponent(result.id)}/annotations`)
 const [create,setCreate]=useState(false),[report,setReport]=useState(''),[adopted,setAdopted]=useState<AnnotationDraft|null>(null)
 const matches=(item:BioAnnotation)=>item.processed_dataset_version_id===result.id&&sameRawBioSource(item.raw_source,result.source.raw_source)
 const all=read.value?.items.filter(matches)??[],items=all.filter(item=>item.origin!=='SingleR'),candidates=all.filter(item=>item.origin==='SingleR')
 const parent=((result.manifest.subset as {parent_processed_source?:unknown}|undefined)?.parent_processed_source??result.manifest.parent_processed_source) as {processed_dataset_version_id?:string}|undefined
 return <section className="intake-form"><h3>{t('细胞注释与亚群')}</h3>
  <p>{t('人工标签与基础计算独立保存。候选工具结果需要研究者逐项核对；保存标签不会重新运行基础分析。')}</p>
  {parent?.processed_dataset_version_id&&<button type="button" onClick={()=>onNavigate({view:'bio-result',fileId:'',processedId:parent.processed_dataset_version_id,tab:'spatial'})}>{t('返回父处理结果')} · {parent.processed_dataset_version_id}</button>}
  <section><h4>{t('当前人工注释')}</h4>{read.error&&<p role="alert">{t(read.error)}</p>}
   {read.value?.items.some(item=>!matches(item))&&<p role="alert">{t('固定来源身份不匹配，请重新打开。')}</p>}
   <ul>{items.map(item=><li key={item.id}><strong>{item.name||item.set_id}</strong> · v{item.version} · {item.labels.length} {t('标签')}
    <button type="button" onClick={()=>onNavigate({view:'bio-annotation',fileId:'',annotationSetId:item.set_id,annotationVersionId:item.id})}>{t('编辑 {name}',{name:item.name||item.set_id})}</button>
    <ul>{item.labels.map(label=><li key={label.id}>{label.name} · {t(label.status==='confirmed'?'研究者已确认':label.status==='uncertain'?'不确定':label.status==='unknown'?'未知':'候选')} · cluster {label.cluster_ids.join(', ')||'—'} · {label.cell_ids?.length??0} explicit cells</li>)}</ul>
   </li>)}</ul>{read.value&&!items.length&&<p>{t('尚无人工标签。')}</p>}
   <button type="button" onClick={read.reload}>{t('刷新人工注释')}</button><button type="button" disabled={create} onClick={()=>{setAdopted(null);setCreate(true)}}>{t(create?'人工草稿已打开':'新建人工注释')}</button>
   {create&&<BioAnnotationEditor key={adopted?.labels[0]?.id??'new'} initialDraft={adopted??undefined} projectId={projectId} result={result} onNavigate={onNavigate} registerLeaveGuard={registerLeaveGuard}/>}
  </section>
  <SingleCellCandidateTask projectId={projectId} result={result} onPublished={read.reload}/>
  {candidates.map(candidate=><SingleCellCandidateReview key={candidate.id} projectId={projectId} candidate={candidate} canAdopt={!create} onAdopt={draft=>{setAdopted(draft);setCreate(true)}}/>)}
  <section><h4>{t('带人工标签的 Word 报告')}</h4><label>{t('报告使用的人工标签')}<select value={report} onChange={e=>setReport(e.target.value)}><option value="">{t('请选择当前人工注释')}</option>{items.map(item=><option key={item.id} value={item.id}>{item.name||item.set_id} · v{item.version}</option>)}</select></label>
   {items.some(item=>item.id===report)&&<ProjectDownloadLink href={`${base}/bio-processed-datasets/${encodeURIComponent(result.id)}/report.docx?annotation_version_id=${encodeURIComponent(report)}`} filename="single-cell-annotated-analysis.docx">{t('下载包含所选标签的 Word 报告')}</ProjectDownloadLink>}
   <AnnotationUmap projectId={projectId} result={result} annotationId={items.some(item=>item.id===report)?report:''} onNavigate={onNavigate} registerLeaveGuard={registerLeaveGuard}/>
  </section>
  <SingleCellSubset projectId={projectId} result={result} onNavigate={onNavigate} registerLeaveGuard={registerLeaveGuard}/>
 </section>
}

function AnnotationUmap({projectId,result,annotationId,onNavigate,registerLeaveGuard}:{projectId:string;result:BioProcessed;annotationId:string;onNavigate:(n:AnalysisNavigation)=>void;registerLeaveGuard?:RegisterLeaveGuard}){
 const {t}=useI18n(),writer=useBioWrite<BioFigure>(projectId,'figure',v=>onNavigate({view:'bio-figure',fileId:'',figureId:v.id}),v=>onNavigate({view:'bio-figure',fileId:'',figureId:v.id}))
 useDraftLeaveGuard(registerLeaveGuard,false,writer.busy||writer.unknown)
 return <><button type="button" disabled={!annotationId||writer.busy||writer.unknown||!writer.valid} onClick={()=>void writer.submit(`${projectBase(projectId)}/bio-figures`,{processed_source:result.source,annotation_version_id:annotationId,expected_version:0,config:{kind:'annotation',panel:'default',color_by:'cluster',gene_ids:[],layer:'log1p',title:'',palette:'tab20',vmin:null,vmax:null,width:1800,height:1500,dpi:300,output_language:(result.manifest.params as BioRecipeParameters|undefined)?.output_language??'en'}})}>{t('按此标签绘制 UMAP')}</button><BioWriteStatus writer={writer}/></>
}

function SingleCellSubset({projectId,result,onNavigate,registerLeaveGuard}:{projectId:string;result:BioProcessed;onNavigate:(n:AnalysisNavigation)=>void;registerLeaveGuard?:RegisterLeaveGuard}){
 const {t}=useI18n(),[mode,setMode]=useState<'cluster'|'cell'>('cluster'),[selection,setSelection]=useState(''),[name,setName]=useState('Single-cell subset'),[draft,setDraft]=useState<BioRecipeParameters|null>(null)
 const inherited=result.manifest.params as BioRecipeParameters|undefined,params=draft??inherited
 const open=(id:string)=>onNavigate({view:'bio-analysis',fileId:'',runId:id})
 const writer=useBioWrite<BioRun>(projectId,'run',value=>open(value.id),value=>open(value.id))
 useDraftLeaveGuard(registerLeaveGuard,!!selection&&!writer.completed,writer.busy||writer.unknown)
 const blocked=writer.busy||writer.unknown||!writer.valid
 const fields:[keyof BioRecipeParameters,string,number,number,number][]=[['hvg_count','亚群 HVG 数量',3,10000,1],['pca_components','亚群 PCA 成分数',2,100,1],['neighbors','亚群邻居数',2,100,1],['resolution','亚群 Leiden resolution',0.01,10,0.01],['seed','亚群随机 seed',0,2147483647,1]]
 return <section><h4>{t('选择亚群并重新聚类')}</h4><p>{t('继承父 QC 与保留基因，只重做降维/聚类；保留原始 cell ID 和父结果关系，不重新判定捕获文库的双细胞或环境 RNA。')}</p>
  <p>{t('选择来源')}：{result.id} · {String(result.shape.retained_observations??(Array.isArray(result.shape.shape)?result.shape.shape[0]:undefined)??result.shape.observations??'—')} cells</p><button type="button" onClick={()=>onNavigate({view:'bio-result',fileId:'',processedId:result.id,tab:'clusters'})}>{t('查看父 cluster 与细胞结果表')}</button>
  {!params?<p role="alert">{t('父结果缺少分析参数，暂不能创建亚群。')}</p>:<form onSubmit={event=>{event.preventDefault();if(!ids(selection).length)return;void writer.submit(`${projectBase(projectId)}/bio-single-cell-subsets`,{name,parent_processed_source:result.source,cluster_ids:mode==='cluster'?ids(selection):[],cell_ids:mode==='cell'?ids(selection):[],params:subsetParameters(params)})}}>
   <fieldset disabled={blocked}><legend>{t('亚群选择与参数')}</legend><label>{t('亚群名称')}<input required value={name} maxLength={200} onChange={e=>setName(e.target.value)}/></label>
    <label>{t('选择方式')}<select value={mode} onChange={e=>{setMode(e.target.value as 'cluster'|'cell');setSelection('')}}><option value="cluster">{t('父 cluster')}</option><option value="cell">{t('明确 cell ID')}</option></select></label>
    <label>{t(mode==='cluster'?'父 cluster ID 列表':'子集 cell ID 列表')}<textarea required value={selection} onChange={e=>setSelection(e.target.value)}/></label><p>{t('已选择 {number} 个标识；实际细胞数由服务端核对。',{number:ids(selection).length})}</p>
    <div className="intake-rows">{fields.map(([key,label,min,max,step])=><label key={key}>{t(label)}<input required type="number" min={min} max={max} step={step} value={String(params[key])} onChange={e=>setDraft({...params,[key]:Number(e.target.value)})}/></label>)}</div>
   </fieldset><button type="submit" disabled={blocked||!ids(selection).length}>{t('创建亚群并重新聚类')}</button>
  </form>}<BioWriteStatus writer={writer}/>
 </section>
}
