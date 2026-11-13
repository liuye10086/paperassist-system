import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import {projectBase} from './api'
import {useBioRead} from './spatialHooks'
import {layerNames} from './bioPresentation'
type Axis=string|{id?:string;feature_id?:string;barcode?:string;sample_id?:string;symbol?:string}
type Preview={features:Axis[];observations:Axis[];features_total:number;observations_total:number;values?:unknown[][];matrix?:unknown[][]}
export default function BioMatrixPreview({projectId,processedId,layers=['counts','normalized','log1p']}:{projectId:string;processedId:string;layers?:string[]}){
 const {t}=useI18n(),[layer,setLayer]=useState(layers[0]),[requested,setRequested]=useState(''),[fpage,setFpage]=useState(1),[opage,setOpage]=useState(1)
 const read=useBioRead<Preview>(requested?`${projectBase(projectId)}/bio-processed-datasets/${encodeURIComponent(processedId)}/matrix-preview?layer=${requested}&features_page=${fpage}&observations_page=${opage}`:''),data=read.value
 const label=(v:Axis)=>typeof v==='string'?v:v.id??v.feature_id??v.barcode??v.sample_id??'',symbol=(v:Axis)=>typeof v==='object'?v.symbol:null,values=data?.values??data?.matrix??[]
 const featurePages=Math.max(1,Math.ceil((data?.features_total??0)/40)),observationPages=Math.max(1,Math.ceil((data?.observations_total??0)/20))
 return <section className="bio-workspace bio-matrix-preview">
  <h3>{t('原始与派生矩阵层核对')}</h3>
  <div className="bio-result-toolbar">
   <label>{t('有界矩阵数据层')}<select value={layer} onChange={e=>setLayer(e.target.value)}>
    {layers.map(v=><option key={v} value={v}>{t(layerNames[v]??'处理后的数据')}</option>)}
   </select></label>
   <button type="button" onClick={()=>{setRequested(layer);setFpage(1);setOpage(1);if(requested===layer)read.reload()}}>{t('读取处理层有界预览')}</button>
  </div>
  <p className="bio-result-note">{t('此处是有界预览，不能代替完整处理对象与逐轴下载。')}</p>
  {read.error&&<p role="alert">{t(read.error)}</p>}
  {data&&<>
   <div className="bio-table-scroll bio-result-data workspace-table-scroll" role="region" tabIndex={0} aria-label={t('矩阵预览')}>
    <table aria-label={t(layerNames[requested]??'处理后的数据')}>
     <thead><tr><th scope="col">{t('观测 / 特征')}</th>{data.features.map((v,i)=><th key={i} scope="col">
      <span>{label(v)}</span>{symbol(v)&&<><br/><span>{symbol(v)}</span></>}
     </th>)}</tr></thead>
     <tbody>{data.observations.map((v,i)=><tr key={i}><th scope="row">{label(v)}</th>{data.features.map((_,j)=><td key={j}>
      {typeof values[i]?.[j]==='number'?String(values[i][j]):'NA'}
     </td>)}</tr>)}</tbody>
    </table>
   </div>
   <div className="bio-result-pagination-pair">
    <nav className="analysis-pagination bio-result-pagination" aria-label={t('特征分页')}>
     <button type="button" disabled={fpage===1} onClick={()=>setFpage(p=>p-1)}>{t('上一特征页')}</button>
     <span>{t('第 {page} / {pages} 页',{page:fpage,pages:featurePages})}</span>
     <button type="button" disabled={fpage>=featurePages} onClick={()=>setFpage(p=>p+1)}>{t('下一特征页')}</button>
    </nav>
    <nav className="analysis-pagination bio-result-pagination" aria-label={t('观测分页')}>
     <button type="button" disabled={opage===1} onClick={()=>setOpage(p=>p-1)}>{t('上一观测页')}</button>
     <span>{t('第 {page} / {pages} 页',{page:opage,pages:observationPages})}</span>
     <button type="button" disabled={opage>=observationPages} onClick={()=>setOpage(p=>p+1)}>{t('下一观测页')}</button>
    </nav>
   </div>
  </>}
 </section>
}
