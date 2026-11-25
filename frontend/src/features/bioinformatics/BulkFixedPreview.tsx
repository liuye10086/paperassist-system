import {useState,type ReactNode} from 'react'
import {useI18n} from '../../shared/i18n'
import {projectBase} from './api'
import {useBioRead} from './spatialHooks'
import type {TabularProcessed} from './tabularContracts'

type FrozenPlot = {
  source_id:string
  source_sha256:string
  empty_reason:string|null
  sample_ids?:string[]
} & (
  {panel:'qc_missing';missing_fraction?:Array<number|null>} |
  {panel:'pca_scores';scores:number[][];condition?:string[];batch?:string[];components:number[];variance_ratio:number[]}
)
type PreviewReceipt = {
  schema_version:1
  project_id:string
  processed_version_id:string
  plot:FrozenPlot
}
type Props = {projectId:string;result:TabularProcessed;panel:FrozenPlot['panel']}

export default function BulkFixedPreview(props:Props){
  const {t}=useI18n()
  const [open,setOpen]=useState(false)
  return <div className="bio-result-block">
    <button type="button" aria-expanded={open} onClick={()=>setOpen(value=>!value)}>
      {t(open?'关闭固定 QC/PCA 预览':'查看固定 QC/PCA 预览')}
    </button>
    {open&&<Preview {...props}/>}
  </div>
}

function Preview({projectId,result,panel}:Props){
  const {t}=useI18n()
  const url=projectBase(projectId)+'/bio-processed-datasets/'+encodeURIComponent(result.id)+'/bulk-fixed-preview?panel='+panel
  const {value,error,reload}=useBioRead<PreviewReceipt>(url)
  if(error)return <div><p role="alert">{t(error)}</p><button type="button" onClick={reload}>{t('重新读取')}</button></div>
  if(!value)return <p role="status">{t('正在读取固定版本……')}</p>
  const plot=value.plot
  if(value.schema_version!==1||value.project_id!==projectId||value.processed_version_id!==result.id||
    plot?.source_id!==result.id||plot.source_sha256!==result.manifest_sha256||plot.panel!==panel){
    return <p role="alert">{t('固定来源身份不匹配，请重新打开。')}</p>
  }
  if(plot.empty_reason)return <p role="status">{t(plot.empty_reason==='insufficient_complete_nonconstant_features_or_samples'
    ?'样本或完整且非恒定的特征不足，固定版本未计算 PCA。':'固定版本无可显示的数值。')}</p>
  const samples=plot.sample_ids??[]
  if(plot.panel==='qc_missing')return <PreviewTable title={t('样本缺失比例')} headers={[t('样本'),t('样本缺失比例')]}>
    {samples.map((sample,i)=><tr key={sample}><th scope="row">{sample}</th><td>{plot.missing_fraction?.[i]??'NA'}</td></tr>)}
  </PreviewTable>
  return <>
    <p>{t('PCA 用于探索样本分布，组间差异需另行检验。')}</p>
    <PreviewTable title={t('样本 PCA 得分')} headers={[t('样本'),t('分组'),t('批次'),'PC1','PC2']}>
      {samples.map((sample,i)=><tr key={sample}><th scope="row">{sample}</th>
        <td>{plot.condition?.[i]||'NA'}</td><td>{plot.batch?.[i]||'NA'}</td>
        <td>{plot.scores[i][0]}</td><td>{plot.scores[i][1]}</td></tr>)}
    </PreviewTable>
    <PreviewTable title={t('PCA 方差解释率')} headers={[t('主成分'),t('PCA 方差解释率')]}>
      {plot.components.map((component,i)=><tr key={component}><th scope="row">{'PC'+component}</th><td>{plot.variance_ratio[i]}</td></tr>)}
    </PreviewTable>
  </>
}

function PreviewTable({title,headers,children}:{title:string;headers:string[];children:ReactNode}){
  return <div className="bio-table-scroll bio-result-data workspace-table-scroll" role="region" aria-label={title} tabIndex={0}>
    <table>
      <caption>{title}</caption>
      <thead><tr>{headers.map(header=><th key={header} scope="col">{header}</th>)}</tr></thead>
      <tbody>{children}</tbody>
    </table>
  </div>
}
