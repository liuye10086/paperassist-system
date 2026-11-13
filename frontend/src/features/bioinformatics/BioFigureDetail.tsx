import {isTabularProcessedSource,type TabularFigure} from './tabularContracts'
import NativeDeliveryArtifact,{type NativeDeliveryTarget} from '../analyst/NativeDeliveryArtifact'
import type {BioAnnotation,BioFigureRequest} from './spatialContracts'
import {useBioRead} from './spatialHooks'
import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import type {AnalysisNavigation} from '../projects/analysisViews'
import useDraftLeaveGuard,{type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {projectBase} from './api'
import {BioMemberImage,BioSource,BioWriteStatus} from './BioSpatialShared'
import {colorGroupNames,figureConfigName,layerNames,paletteNames,resultFileName} from './bioPresentation'
import type {BioFigure,BioProcessed,FigureConfig,BioFigurePanel} from './spatialContracts'
import {isProcessedBioSource,sameProcessedBioSource,sameRawBioSource} from './spatialContracts'
import useBioWrite from './useBioWrite'
import BioResultTable from './BioResultTable'
import {orderMarkerPngMembers} from './markerFigureOrder'
import ModuleViews,{ModuleView} from '../../shared/components/ModuleViews'
import {BioResultDownloads} from './BioResultPanels'
import './bioResults.css'
type EditableFigureConfig=FigureConfig&{panel:BioFigurePanel}
const initial:EditableFigureConfig={panel:'default',color_by:'cluster',kind:'qc',gene_ids:[],layer:'log1p',title:'',palette:'viridis',vmin:null,vmax:null,width:1800,height:1500,dpi:300,output_language:'en'}
const kinds:Record<FigureConfig['kind'],string>={qc:'质量控制图',pca:'PCA',umap:'UMAP',marker_dotplot:'标记基因气泡图',marker_heatmap:'标记基因热图',spatial_cluster:'空间聚类图',spatial_gene:'空间基因表达',annotation:'人工注释'}
const panels:Record<FigureConfig['kind'],BioFigurePanel[]>={qc:['default','distribution','violin','scatter','mitochondrial','sample_id','section','batch'],pca:['default','scores','variance'],umap:['default','scores'],marker_dotplot:['default'],marker_heatmap:['default'],spatial_cluster:['default'],spatial_gene:['default'],annotation:['default']}
const panelLabels:Record<BioFigurePanel,string>={default:'默认面板',scores:'得分散点图',variance:'解释方差图',distribution:'分布图',violin:'小提琴图',scatter:'counts 与检测基因散点图',mitochondrial:'线粒体比例图',sample_id:'按样本分组',section:'按切片分组',batch:'按批次分组'}
const marker=(kind:FigureConfig['kind'])=>kind==='marker_dotplot'||kind==='marker_heatmap'
const expressionScale=(kind:FigureConfig['kind'])=>kind==='spatial_gene'||marker(kind)
function editConfig(value:FigureConfig):EditableFigureConfig{return {...value,panel:value.panel??'default',layer:value.kind==='spatial_gene'?value.layer:'log1p',vmin:expressionScale(value.kind)?value.vmin:null,vmax:expressionScale(value.kind)?value.vmax:null}}
export function BioFigureComposer({projectId,result,onNavigate,registerLeaveGuard,previous,allowNewAnalysis=true}:{projectId:string;result:BioProcessed;onNavigate:(n:AnalysisNavigation)=>void;registerLeaveGuard?:RegisterLeaveGuard;previous?:BioFigure;allowNewAnalysis?:boolean}){
 const {t}=useI18n(),[config,setConfig]=useState<EditableFigureConfig>(()=>editConfig(previous?.config??initial)),[annotation,setAnnotation]=useState(previous?.annotation_version_id??''),[genesOpen,setGenesOpen]=useState(false),[dirty,setDirty]=useState(false)
 const singleCell=result.manifest.assay==='single_cell'
 const annotations=useBioRead<{items:BioAnnotation[]}>(singleCell&&config.kind==='annotation'?`${projectBase(projectId)}/bio-processed-datasets/${encodeURIComponent(result.id)}/annotations`:'')
 const availableAnnotations=annotations.value?.items.filter(v=>v.origin!=='SingleR'&&v.processed_dataset_version_id===result.id&&sameRawBioSource(v.raw_source,result.source.raw_source))??[]
 const fixedPrevious=!!previous&&previous.annotation_version_id===annotation&&sameProcessedBioSource(previous.processed_source,result.source)
 const validAnnotation=!singleCell||availableAnnotations.some(v=>v.id===annotation)||fixedPrevious
 const writer=useBioWrite<BioFigure>(projectId,'figure',v=>{setDirty(false);onNavigate({view:'bio-figure',fileId:'',figureId:v.id})},v=>{setDirty(false);onNavigate({view:'bio-figure',fileId:'',figureId:v.id})})
 useDraftLeaveGuard(registerLeaveGuard,dirty&&!writer.completed,writer.busy||writer.unknown)
 const update=<K extends keyof EditableFigureConfig>(key:K,value:EditableFigureConfig[K])=>{setConfig({...config,[key]:value});setDirty(true)}
 const changeKind=(kind:FigureConfig['kind'])=>{setConfig({...config,kind,panel:panels[kind].includes(config.panel)?config.panel:'default',layer:kind==='spatial_gene'?config.layer:'log1p',vmin:expressionScale(kind)?config.vmin:null,vmax:expressionScale(kind)?config.vmax:null});setDirty(true)}
 const needsGene=['spatial_gene'].includes(config.kind),blocked=writer.busy||writer.unknown||!writer.valid
 return <section className="intake-form bio-figure-composer"><h3>{t('单图绘制设置')}</h3><p>{t('调整设置会生成新图，沿用原有分析数据与聚类。')}</p><fieldset disabled={blocked}><legend>{t('图件设置')}</legend><div className="intake-rows"><label>{t('图片类型')}<select value={config.kind} onChange={e=>changeKind(e.target.value as FigureConfig['kind'])}>{Object.entries(kinds).filter(([k])=>result.manifest.assay!=='single_cell'||!['spatial_cluster','spatial_gene'].includes(k)).map(([k,l])=><option value={k} key={k}>{t(l)}</option>)}</select></label><label>{t('图片面板')}<select value={config.panel} onChange={e=>update('panel',e.target.value as BioFigurePanel)}>{panels[config.kind].map(v=><option key={v} value={v}>{t(panelLabels[v])}</option>)}</select></label>{['pca','umap'].includes(config.kind)&&config.panel!=='variance'&&<><label>{t('颜色分组来源')}<select value={config.color_by??'cluster'} onChange={e=>update('color_by',e.target.value as FigureConfig['color_by'])}>{Object.entries(colorGroupNames).map(([v,label])=><option key={v} value={v}>{t(label)}</option>)}</select></label><p>{t('未知映射单独显示为 unknown，不代表独立重复。')}</p></>}<label>{t('图片标题')}<input maxLength={200} value={config.title} onChange={e=>update('title',e.target.value)}/></label><label>{t('图片语言')}<select value={config.output_language} onChange={e=>update('output_language',e.target.value as 'en'|'zh-CN')}><option value="en">English</option><option value="zh-CN">简体中文</option></select></label>{expressionScale(config.kind)&&<label>{t('表达层')}<select value={config.layer} disabled={marker(config.kind)} onChange={e=>update('layer',e.target.value as FigureConfig['layer'])}>{(marker(config.kind)?['log1p']:['counts','normalized','log1p']).map(k=><option key={k} value={k}>{t(layerNames[k])}</option>)}</select></label>}{marker(config.kind)&&<p>{t('marker 颜色固定为平均 log1p 表达；检测比例与颜色含义分别记录。')}</p>}<label>{t('色盘')}<select value={config.palette} onChange={e=>update('palette',e.target.value as FigureConfig['palette'])}>{['viridis','magma','tab20'].map(k=><option key={k} value={k}>{t(paletteNames[k])}</option>)}</select></label>{expressionScale(config.kind)&&(['vmin','vmax'] as const).map(k=><label key={k}>{t(k==='vmin'?'色阶下限':'色阶上限')}<input type="number" step="any" value={config[k]??''} onChange={e=>update(k,e.target.value===''?null:Number(e.target.value))}/></label>)}{(['width','height','dpi'] as const).map(k=><label key={k}>{t(({width:'宽度（像素）',height:'高度（像素）',dpi:'分辨率（DPI）'})[k])}<input type="number" min="1" step="1" value={config[k]} onChange={e=>update(k,Number(e.target.value))}/></label>)}</div>{singleCell&&config.kind==='annotation'&&<label>{t('人工注释来源')}<select value={annotation} onChange={e=>{setAnnotation(e.target.value);setDirty(true)}}><option value="">{t('请选择当前人工注释')}</option>{availableAnnotations.map(v=><option key={v.id} value={v.id}>{v.name||t('未命名注释')} · {t('已保存')}</option>)}{previous?.annotation_version_id&&!availableAnnotations.some(v=>v.id===previous.annotation_version_id)&&<option value={previous.annotation_version_id}>{t('图件原固定人工标签')}</option>}</select></label>}<p>{t('稳定基因 ID')} · {config.gene_ids.join(', ')||t('尚未选择')}</p><button type="button" onClick={()=>setGenesOpen(!genesOpen)}>{t('搜索并选择稳定基因 ID')}</button>{config.gene_ids.map(id=><button type="button" key={id} onClick={()=>update('gene_ids',config.gene_ids.filter(v=>v!==id))}>{t('移除 {id}',{id})}</button>)}</fieldset>{genesOpen&&<BioResultTable projectId={projectId} processedId={result.id} tableKey="features" onSelectGene={id=>update('gene_ids',[...new Set([...config.gene_ids,id])])}/>}{annotations.error&&<p role="alert">{t(annotations.error)}</p>}{dirty&&<p className="warning-panel">{t('图片配置有未保存变更；界面语言切换不会重新生成已保存图片。')}</p>}<BioWriteStatus writer={writer}/><button type="button" disabled={blocked||!allowNewAnalysis||needsGene&&(!config.gene_ids.length||config.gene_ids.length>16)||config.kind==='annotation'&&(!annotation||!validAnnotation)} onClick={()=>allowNewAnalysis&&void writer.submit(previous?`${projectBase(projectId)}/bio-figures/${encodeURIComponent(previous.root_id)}/versions`:`${projectBase(projectId)}/bio-figures`,{processed_source:result.source,annotation_version_id:annotation||null,expected_version:previous?.version??0,config} satisfies BioFigureRequest)}>{t('生成独立单图版本')}</button></section>
}
export default function BioFigureDetail({projectId,figureId,onNavigate,registerLeaveGuard,allowNewAnalysis=true,deliveryTarget}:{projectId:string;deliveryTarget?:NativeDeliveryTarget;figureId:string;onNavigate:(n:AnalysisNavigation)=>void;registerLeaveGuard?:RegisterLeaveGuard;allowNewAnalysis?:boolean}){
 const {t}=useI18n(),read=useBioRead<BioFigure|TabularFigure>(`${projectBase(projectId)}/bio-figures/${encodeURIComponent(figureId)}`,v=>!!v.task&&['queued','running'].includes(v.task.status)),figure=read.value
 const valid=figure?.id===figureId&&(isProcessedBioSource(figure.processed_source,projectId)||isTabularProcessedSource(figure.processed_source,projectId))
 const spatial=valid&&figure.processed_source.schema_version===1?figure as BioFigure:null
 const result=useBioRead<BioProcessed>(spatial&&Object.hasOwn(panels,spatial.config.kind)?`${projectBase(projectId)}/bio-processed-datasets/${encodeURIComponent(spatial.processed_source.processed_dataset_version_id)}`:'')
 if(figure&&!valid)return <p role="alert">{t('固定来源身份不匹配，请重新打开。')}</p>
 const published=!!figure?.manifest_sha256
 return <section className="bio-workspace bio-fixed-result bio-fixed-figure">
  <header className="bio-fixed-result-heading">
   <div><h2>{figure?figureConfigName(figure.config,t):t('分析图件')}</h2>
    {published&&<span className="status-badge task-status task-status-succeeded">{t('图件已保存')}</span>}
    {figure?.processed_source.schema_version===2&&<p>{t('此图来自已保存的定量分析。')}</p>}
   </div>
   <div className="bio-result-toolbar">
    {figure&&<button type="button" onClick={()=>onNavigate({view:'bio-result',fileId:'',processedId:figure.processed_source.processed_dataset_version_id,tab:'methods'})}>{t('查看来源处理版本与方法')}</button>}
    <button type="button" onClick={read.reload}>{t('重新读取')}</button>
   </div>
  </header>
  {read.error&&<p role="alert">{t(read.error)}</p>}
  {!figure&&!read.error&&<p role="status">{t('正在读取固定版本……')}</p>}
  {figure&&<>
   {!published&&<div className="bio-result-toolbar"><p role="status">{t(figure.task?.status==='failed'
    ?'运行失败；原件和历史版本保留。':'单图任务已建立，尚无正式图片。')}</p>
    {figure.task&&<a href={`#project=${encodeURIComponent(projectId)}&section=tasks&task=${encodeURIComponent(figure.task.id)}`}>{t('查看项目任务')}</a>}
   </div>}
   <ModuleViews lazy label={t('单图详情')}>
    {published&&<ModuleView id="image" title={t('图表预览')}>
     <FigurePreview {...{projectId,deliveryTarget,figure}}/>
     {spatial&&!Object.hasOwn(panels,spatial.config.kind)&&<p className="bio-result-note">{t('此图记录整合处理前后的实际结果，可查看和下载。')}</p>}
    </ModuleView>}
    {published&&<ModuleView id="files" title={t('结果文件')}><BioResultDownloads projectId={projectId} members={figure.members} figureKind={figure.config.kind}/></ModuleView>}
    <ModuleView id="config" title={t('高级配置')}>
     <FigureConfiguration figure={figure}/>
     {figure.task&&<a href={`#project=${encodeURIComponent(projectId)}&section=tasks&task=${encodeURIComponent(figure.task.id)}`}>{t('查看项目任务')}</a>}
    </ModuleView>
    {spatial&&result.value&&<ModuleView id="revision" title={t('绘图设置')}>
     <BioFigureComposer allowNewAnalysis={allowNewAnalysis} projectId={projectId} result={result.value} previous={spatial} onNavigate={onNavigate} registerLeaveGuard={registerLeaveGuard}/>
    </ModuleView>}
   </ModuleViews>
  </>}
 </section>
}

function FigurePreview({projectId,deliveryTarget,figure}:{projectId:string;deliveryTarget?:NativeDeliveryTarget;figure:BioFigure|TabularFigure}){
 const {t}=useI18n(),[page,setPage]=useState(0)
 const images=orderMarkerPngMembers(figure.members.filter(member=>member.format==='png')),image=images[page]
 if(!image)return <p className="bio-result-note">{t('当前板块暂无可预览的图。')}</p>
 const filename=resultFileName(image,t,figure.config.kind)
 return <section className="bio-result-block">
  <div className="bio-result-toolbar bio-figure-preview-actions">
   <strong>{filename}</strong>
   {images.length>1&&<label>{t('图版')}<select value={page} onChange={e=>setPage(Number(e.target.value))}>
    {images.map((member,index)=><option key={member.id} value={index}>{t('第 {page} / {pages} 页',{page:index+1,pages:images.length})}</option>)}
   </select></label>}
   {image.download_url.startsWith(projectBase(projectId)+'/')&&
    <ProjectDownloadLink href={image.download_url} filename={filename}>{t('下载 PNG')}</ProjectDownloadLink>}
   {(!figure.task||figure.task.status==='succeeded')&&<NativeDeliveryArtifact {...{projectId,deliveryTarget}}
    source={{kind:'bio_figure_png',version_id:figure.id,member_id:image.id}} name={filename}/>}
  </div>
  <div className="bio-result-image"><BioMemberImage key={image.id} projectId={projectId} member={image} label={filename.slice(0,-4)}/></div>
 </section>
}

function FigureConfiguration({figure}:{figure:BioFigure|TabularFigure}){
 const {t}=useI18n(),config=figure.config
 const spatial=figure.processed_source.schema_version===1?config as FigureConfig:null
 const scale=spatial&&expressionScale(spatial.kind)
 const rows:[string,string|number][]=[
  ['图片类型',figureConfigName(config,t)],
  ['图片语言',config.output_language==='zh-CN'?'简体中文':'English'],
 ]
 if(typeof config.width==='number'&&typeof config.height==='number')rows.push(['像素尺寸',`${config.width} × ${config.height}`])
 if(typeof config.dpi==='number')rows.push(['分辨率',`${config.dpi} DPI`])
 if(typeof config.palette==='string')rows.push(['色盘',t(paletteNames[config.palette]??'自定义配色')])
 if(spatial?.panel&&spatial.panel!=='default')rows.push(['图片面板',t(panelLabels[spatial.panel])])
 if(spatial&&['pca','umap'].includes(spatial.kind)&&spatial.panel!=='variance')rows.push(['颜色分组来源',t(colorGroupNames[spatial.color_by]??'按聚类')])
 if(spatial&&scale){
  rows.push(['表达层',t(layerNames[spatial.layer])])
  if(spatial.vmin!=null)rows.push(['色阶下限',spatial.vmin])
  if(spatial.vmax!=null)rows.push(['色阶上限',spatial.vmax])
 }
 if(spatial?.gene_ids.length)rows.push(['稳定基因 ID',spatial.gene_ids.join(', ')])
 return <section className="bio-result-block bio-result-records">
  <h3>{t('查看高级图件配置')}</h3>
  <dl>{rows.map(([label,value])=><div key={label}><dt>{t(label)}</dt><dd>{value}</dd></div>)}</dl>
  <BioSource source={figure.processed_source.raw_source}/>
 </section>
}
