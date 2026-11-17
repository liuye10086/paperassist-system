import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import {manuscriptBase,validCandidates,type SourceCandidate,type Snapshot,type FrozenSource} from './manuscriptTypes'
import {useManuscriptDraft} from './useManuscriptDraft'
import {object,listOf,validFigureVersion,type FigureVersion} from './writingLiveTypes'
import {useWritingOperation} from './useWritingOperation'
import ManuscriptImage from './ManuscriptImage'

type Figure=Snapshot['results_groups'][number]['figures'][number]
type FigureLanguage=Snapshot['output_language']
type Texts={title:string;x_label:string;y_label:string;caption:string;series:string[]}
type FigureMode=FigureVersion['mode']
const textLabels={title:'图标题',x_label:'X 轴标签',y_label:'Y 轴标签',caption:'图注'} as const

function originalTexts(source:FrozenSource):Texts|null{
 const c=source.content
 if(!['title','x_label','y_label','caption'].every(k=>typeof c[k]==='string')||!Array.isArray(c.series)||!c.series.every(s=>object(s)&&typeof s.label==='string'))return null
 return {title:String(c.title),x_label:String(c.x_label),y_label:String(c.y_label),caption:String(c.caption),series:c.series.map(s=>String((s as {label:string}).label))}
}

function FigureForm({projectId,source,figure,onCreated,confirmOnly,initialLanguage,reviewLanguage}:{
 projectId:string;source:FrozenSource;figure:Figure;onCreated:(version:FigureVersion)=>void;
 confirmOnly:boolean;initialLanguage:FigureLanguage;reviewLanguage?:FigureLanguage
}){
 const {t}=useI18n(),op=useWritingOperation()
 const programFigure=source.kind==='figure'
 const original=programFigure?originalTexts(source):null
 const editable=programFigure?!!original:['original','document_version'].includes(source.kind)
 const [texts,setTexts]=useState(original)
 const [language,setLanguage]=useState(initialLanguage)
 const [mode,setMode]=useState<FigureMode>(confirmOnly?'no_text_confirmation':programFigure?'local_boxplot':'uploaded_replacement')
 const [replacement,setReplacement]=useState('')
 const [reason,setReason]=useState('')
 const [title,setTitle]=useState(figure.title)
 const [caption,setCaption]=useState(figure.caption)
 const [items,setItems]=useState<{location:string;text:string}[]>([])
 const [result,setResult]=useState<FigureVersion|null>(null)
 const [replacementOptions,setReplacementOptions]=useState<SourceCandidate[]|null>(null)
 const selectedReplacement=replacementOptions?.find(item=>item.file_id===replacement)
 const formSignature=JSON.stringify({texts,language,mode,replacement,reason,title,caption,items})
 const [cleanForm,setCleanForm]=useState(formSignature)
 useManuscriptDraft(formSignature!==cleanForm)

 async function replacements(){
  const value=await op.run(`${manuscriptBase(projectId)}/candidates`,v=>validCandidates(v,projectId))
  if(!value)return
  const options=value.items.filter(s=>s.kind==='original'&&s.allowed_roles.includes('image_observation')&&/\.(?:png|jpe?g)$/i.test(s.label))
  setReplacementOptions(options)
  if(replacement&&!options.some(item=>item.file_id===replacement))setReplacement('')
 }

 const completeInventory=items.length>0&&items.every(item=>item.location.trim()&&item.text.trim())&&new Set(items.map(item=>item.location)).size===items.length
 const canSave=editable&&!!reason.trim()&&(mode==='local_boxplot'||!!title.trim()&&!!caption.trim()&&
  (mode==='no_text_confirmation'||!!selectedReplacement&&completeInventory))

 async function save(){
  if(!canSave)return
  const created=await op.run(`/api/v1/projects/${encodeURIComponent(projectId)}/manuscript-figure-language-versions`,(v):v is FigureVersion=>validFigureVersion(v,projectId),{
   source:{kind:source.kind,id:source.id,file_id:source.file_id,...(figure.image_id?{image_id:figure.image_id}:{})},
   original_sha256:figure.sha256,output_language:reviewLanguage??language,mode,reason,
   ...(mode==='local_boxplot'?{texts}:{title,caption,...(mode==='uploaded_replacement'?{replacement_file_id:replacement,text_items:items}:{})}),
  })
  if(created){setResult(created);setCleanForm(formSignature);onCreated(created)}
 }

 return <section>
  {!reviewLanguage&&<><h5>{figure.title}</h5><p>{t('原图 SHA')} {figure.sha256}</p></>}
  {!reviewLanguage&&figure.preview_url&&<ManuscriptImage url={figure.preview_url} title={figure.title}/>}
  <fieldset disabled={op.busy||!op.valid||!editable}>
   {reviewLanguage?<><legend>{t('图')} {figure.number}. {figure.title}</legend><p>{t('新图输出语言')} · {t(reviewLanguage==='en'?'英文':'中文')}</p></>:
    <label>{t('新图输出语言')}<select value={language} onChange={e=>{setLanguage(e.target.value as FigureLanguage);setResult(null)}}>
     <option value="en">English</option><option value="zh-CN">简体中文</option>
    </select></label>}
   {programFigure?<>
    <p>{t('逐字段保留原数字、正负号与单位数字；新图另存，数据和几何指纹保持可核对。')}</p>
    {texts&&original&&<>
     {(['title','x_label','y_label','caption'] as const).map(key=><label key={key}>{t(textLabels[key])}
      <blockquote>{original[key]}</blockquote>
      <textarea aria-label={t(textLabels[key])} value={texts[key]} onChange={e=>{setTexts({...texts,[key]:e.target.value});setResult(null)}}/>
     </label>)}
     {texts.series.map((value,index)=><label key={index}>{t('系列 {index}',{index})}
      <blockquote>{original.series[index]}</blockquote>
      <input aria-label={t('系列 {index}',{index})} value={value} onChange={e=>{setTexts({...texts,series:texts.series.map((text,i)=>i===index?e.target.value:text)});setResult(null)}}/>
     </label>)}
    </>}
   </>:<>
    {!confirmOnly&&<label>{t('外部图处理方式')}<select value={mode} onChange={e=>{setMode(e.target.value as FigureMode);setResult(null)}}>
     <option value="uploaded_replacement">{t('已上传替代图与完整文字清单')}</option>
     <option value="no_text_confirmation">{t('明确确认原图没有文字')}</option>
    </select></label>}
    {mode==='no_text_confirmation'&&<p>{t('仅当人工确认该原图无文字时，才保存无字图的固定版本。')}</p>}
    {mode==='uploaded_replacement'&&<>
     <p>{t(reviewLanguage?'请在「写作资料与引用」的「项目文件」上传替代 PNG/JPEG，然后选择文件。':'请先在项目文件中上传替代 PNG/JPEG，再选择其文件 ID。')}</p>
     <button type="button" onClick={()=>void replacements()}>{t('读取可用替代图')}</button>
     <label>{t('选择已上传替代图')}<select value={replacement} disabled={!replacementOptions?.length} onChange={e=>{setReplacement(e.target.value);setResult(null)}}>
      <option value="">{t('尚未选择')}</option>
      {replacementOptions?.map(s=><option key={s.id} value={s.file_id}>{s.label}</option>)}
     </select></label>
     {replacementOptions?.length===0&&<p role="status">{t('本项目暂无可选的 PNG/JPEG 替代图。')}</p>}
     {reviewLanguage&&selectedReplacement?.download_url&&<ManuscriptImage key={selectedReplacement.file_id} url={selectedReplacement.download_url} title={selectedReplacement.label}/>}
    </>}
    <label>{t('新图标题')}<textarea value={title} onChange={e=>setTitle(e.target.value)}/></label>
    <label>{t('新图图注')}<textarea value={caption} onChange={e=>setCaption(e.target.value)}/></label>
    {mode==='uploaded_replacement'&&<>
     {items.map((item,index)=><div key={index}>
      <label>{t('图中文字位置')}<input value={item.location} onChange={e=>setItems(old=>old.map((entry,i)=>i===index?{...entry,location:e.target.value}:entry))}/></label>
      <label>{t('图内精确文字')}<textarea value={item.text} onChange={e=>setItems(old=>old.map((entry,i)=>i===index?{...entry,text:e.target.value}:entry))}/></label>
      <button type="button" onClick={()=>setItems(old=>old.filter((_,i)=>i!==index))}>{t('移除文字项')}</button>
     </div>)}
     <button type="button" onClick={()=>setItems(old=>[...old,{location:'',text:''}])}>{t('添加图内文字')}</button>
    </>}
   </>}
   <label>{t('图版本修改或无字检查理由')}<textarea value={reason} onChange={e=>setReason(e.target.value)}/></label>
   <button type="button" disabled={!canSave} onClick={()=>void save()}>{t('创建独立图语言版本')}</button>
  </fieldset>
  {!editable&&<p role="alert">{t('此图不支持受限本地重绘；请在项目文件补充独立替代图并明确选择，不得只改语言标签。')}</p>}
  {op.error&&<p role="alert">{t(op.error)}</p>}
  {result&&(reviewLanguage?<p role="status">{t('图语言版本已创建，请在语言清单中明确选择。')} {result.title}</p>:<>
   <p>SHA {result.sha256}</p>
   <p>{t('数据指纹')} {result.data_fingerprint??t('人工替代图，不声明数值等价')} · {t('几何指纹')} {result.geometry_fingerprint??'—'}</p>
   <ManuscriptImage url={result.download_url} title={result.title}/>
  </>)}
 </section>
}

export default function FigureLanguagePanel({projectId,snapshot,onCreated,confirmOnly=false,reviewLanguageForFigure}:{
 projectId:string;snapshot:Snapshot;onCreated?:(version:FigureVersion)=>void;confirmOnly?:boolean;
 reviewLanguageForFigure?:(figureId:string)=>FigureLanguage|undefined
}){
 const {t}=useI18n(),op=useWritingOperation()
 const [open,setOpen]=useState(false)
 const [visited,setVisited]=useState(false)
 const [versions,setVersions]=useState<FigureVersion[]>([])
 async function refresh(){
  const result=await op.run(`/api/v1/projects/${encodeURIComponent(projectId)}/manuscript-figure-language-versions`,listOf((v):v is FigureVersion=>validFigureVersion(v,projectId)))
  if(result)setVersions(result.items)
 }
 const figures=snapshot.results_groups.flatMap(group=>group.figures).flatMap(figure=>{
  const source=snapshot.sources.find(item=>item.id===figure.source_ids[0])
  if(!source)return []
  if(confirmOnly&&!['original','document_version'].includes(source.kind))return []
  const reviewLanguage=reviewLanguageForFigure?.(figure.id)
  if(reviewLanguageForFigure&&(!reviewLanguage||!['original','document_version','figure'].includes(source.kind)))return []
  return [{figure,source,reviewLanguage}]
 })
 if((confirmOnly||reviewLanguageForFigure)&&!figures.length)return null
 const forms=figures.map(({figure,source,reviewLanguage})=><FigureForm key={`${figure.id}:${figure.sha256}:${reviewLanguage??''}`}
  projectId={projectId} source={source} figure={figure} confirmOnly={confirmOnly} reviewLanguage={reviewLanguage}
  initialLanguage={reviewLanguage??(confirmOnly?snapshot.output_language:'en')}
  onCreated={version=>{if(!reviewLanguageForFigure)void refresh();onCreated?.(version)}}/>)

 if(reviewLanguageForFigure)return <section className="manuscript-review">
  <h5>{t('独立图语言版本')}</h5>
  {forms}
 </section>
 return <section className="manuscript-review">
  <button type="button" onClick={()=>{setOpen(!open);setVisited(true);if(!open)void refresh()}}>{t('独立图语言版本')}</button>
  {visited&&op.valid&&<div hidden={!open}>
   <p>{t('创建后刷新稿件资料，在初始来源选择中勾选图语言版本并关联分组。')}</p>
   {forms}
   <button type="button" disabled={op.busy} onClick={()=>void refresh()}>{t('刷新图语言版本')}</button>
   {versions.map(v=><p key={v.id}>{v.title} · {v.output_language} · {v.id} · <ProjectDownloadLink href={v.download_url} filename={`${v.id}.png`}>{t('查看图语言版本')}</ProjectDownloadLink></p>)}
  </div>}
  {op.error&&<p role="alert">{t(op.error)}</p>}
 </section>
}
