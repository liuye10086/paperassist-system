import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import NativeDeliveryArtifact,{type NativeDeliveryTarget} from '../analyst/NativeDeliveryArtifact'
import type {AnalysisNavigation} from '../projects/analysisViews'
import {BioMemberImage} from './BioSpatialShared'
import {orderMarkerPngMembers} from './markerFigureOrder'
import {projectBase} from './api'
import type {BioFigure,BioProcessed,SpatialMember} from './spatialContracts'
import {figureConfigName,isTechnicalResultFile,resultFileName} from './bioPresentation'

const stepLabels:Record<string,string>={
 import:'数据导入',parse:'数据解析',qc:'质量控制',raw_qc:'原始数据质控',filter:'观测与基因过滤',normalize:'标准化',
 log1p:'对数转换',hvg:'高变基因',embedding:'降维',pca:'PCA',neighbors:'构建近邻图',umap:'UMAP',leiden:'Leiden 聚类',
 integration:'批次整合',cluster:'聚类',h5ad_roundtrip:'H5AD 读写核对',markers:'marker 分析',
 annotation:'细胞注释',report:'报告生成',doublet:'双细胞检测',decontx:'环境 RNA 校正',
 cell_sample_donor_aggregation:'细胞、样本与供体汇总',
 sample_qc:'样本质量控制',feature_qc:'特征质量控制',value_transform:'数值变换',clustering:'样本聚类',
 sample_clustering:'样本聚类',sample_distance:'样本间距离',sample_correlation:'样本相关性',
}
const stepStatuses={
 completed:{label:'已完成',tone:'success'},partial:{label:'部分完成',tone:'warning'},failed:{label:'失败',tone:'error'},
 not_computable:{label:'不可计算',tone:'warning'},not_requested:{label:'未请求',tone:'neutral'},
}
const stepReasons:Record<string,string>={
 single_cluster:'仅有一个聚类，无法进行组间比较',independent_donor_design_not_confirmed:'尚未确认独立供体设计',
 insufficient_complete_features:'完整特征数量不足',insufficient_samples:'可用样本数量不足',
}

export function BioResultSteps({steps}:{steps:BioProcessed['steps']}){
 const {t}=useI18n()
 return <section className="bio-result-block">
  <h3>{t('实际步骤状态和缺口')}</h3>
  <div className="bio-table-scroll bio-check-table"><table aria-label={t('实际步骤状态和缺口')}>
   <thead><tr>{['处理步骤','状态','说明'].map(label=><th key={label} scope="col">{t(label)}</th>)}</tr></thead>
   <tbody>{steps.map(step=>{
    const {label,tone}=stepStatuses[step.status]
    return <tr key={step.key}><th scope="row">{t(stepLabels[step.key]??'其他处理步骤')}</th>
     <td><span className="status-badge" data-tone={tone}>{t(label)}</span></td>
     <td>{step.reason?t(stepReasons[step.reason]??(step.status==='not_computable'?'条件不足，未执行':'请结合处理状态核对')):'—'}</td></tr>
   })}</tbody>
  </table></div>
 </section>
}

export function BioResultFigures({projectId,figures,onNavigate}:{projectId:string;figures:BioFigure[];onNavigate:(n:AnalysisNavigation)=>void}){
 const {t,locale}=useI18n(),[selected,setSelected]=useState(''),[memberId,setMemberId]=useState('')
 const figure=figures.find(f=>f.id===selected)??figures[0]
 if(!figure)return <p className="bio-result-note">{t('当前板块暂无可预览的图。')}</p>
 const images=orderMarkerPngMembers(figure.members.filter(m=>m.format==='png'))
 const image=images.find(m=>m.id===memberId)??images[0]
 return <section className="bio-result-block">
  <div className="bio-result-toolbar">
   <label>{t('图表')}<select value={figure.id} onChange={e=>{setSelected(e.target.value);setMemberId('')}}>
    {figures.map(f=><option key={f.id} value={f.id}>{figureConfigName(f.config,t)}{f.task?.updated_at&&' · '+new Date(f.task.updated_at).toLocaleString(locale)}</option>)}
   </select></label>
   {images.length>1&&<label>{t('图版')}<select value={image.id} onChange={e=>setMemberId(e.target.value)}>
    {images.map((m,index)=><option key={m.id} value={m.id}>{t('第 {page} / {pages} 页',{page:index+1,pages:images.length})}</option>)}
   </select></label>}
   <button type="button" onClick={()=>onNavigate({view:'bio-figure',fileId:'',figureId:figure.id})}>{t('打开固定单图版本')}</button>
  </div>
  {image&&<div className="bio-result-image"><BioMemberImage key={image.id} projectId={projectId} member={image} label={figureConfigName(figure.config,t)}/></div>}
 </section>
}

const downloadsPerPage=10
export function BioResultDownloads({projectId,members,singleCell,processedId,deliveryTarget,figureKind}:{
 projectId:string;members:SpatialMember[];singleCell?:boolean;processedId?:string;deliveryTarget?:NativeDeliveryTarget;figureKind?:string
}){
 const {t,locale}=useI18n(),[format,setFormat]=useState(''),[page,setPage]=useState(1)
 const hasPdf=members.some(member=>member.format.toLowerCase()==='pdf')
 const downloadable=members.filter(member=>!isTechnicalResultFile(member.key,member.format)&&!['pdf',...(hasPdf?['zip']:[])].includes(member.format.toLowerCase())&&member.download_url.startsWith(projectBase(projectId)+'/'))
 const formats=[...new Set(downloadable.map(member=>member.format))].sort()
 const files=format?downloadable.filter(member=>member.format===format):downloadable
 const pages=Math.max(1,Math.ceil(files.length/downloadsPerPage))
 const size=new Intl.NumberFormat(locale,{maximumFractionDigits:1})
 return downloadable.length?<section className="bio-result-block">
  <div className="bio-result-toolbar">
   <label>{t('文件格式')}<select value={format} onChange={e=>{setFormat(e.target.value);setPage(1)}}>
    <option value="">{t('全部类型')}</option>
    {formats.map(item=><option key={item} value={item}>{item.toUpperCase()}</option>)}
   </select></label>
  </div>
  <div className="bio-table-scroll bio-result-data"><table aria-label={t('结果文件')}>
   <thead><tr>{['文件名','文件格式','文件大小','操作'].map(label=><th key={label} scope="col">{t(label)}</th>)}</tr></thead>
   <tbody>{files.slice((page-1)*downloadsPerPage,page*downloadsPerPage).map(member=>{
    const filename=resultFileName(member,t,figureKind)
    const amount=member.size_bytes
    const amountLabel=amount>=1024**2?size.format(amount/1024**2)+' MB':amount>=1024?size.format(amount/1024)+' KB':size.format(amount)+' B'
    return <tr key={member.id}><th scope="row">{filename}</th><td>{member.format.toUpperCase()}</td><td>{amountLabel}</td>
     <td><div className="bio-result-file-actions">
      <ProjectDownloadLink href={member.download_url} filename={filename} ariaLabel={t('下载 {name}',{name:filename})}>{t('下载')}</ProjectDownloadLink>
      {singleCell&&processedId&&member.format==='png'&&member.role==='figure_png'&&<NativeDeliveryArtifact {...{projectId,deliveryTarget}}
       source={{kind:'single_cell_png',version_id:processedId,member_id:member.id}} name={filename}/>}
     </div></td></tr>
   })}</tbody>
  </table></div>
  <nav className="analysis-pagination" aria-label={t('结果文件分页')}>
   <button type="button" disabled={page===1} onClick={()=>setPage(value=>value-1)}>{t('上一页')}</button>
   <span>{t('第 {page} / {pages} 页',{page,pages})}</span>
   <button type="button" disabled={page>=pages} onClick={()=>setPage(value=>value+1)}>{t('下一页')}</button>
  </nav>
 </section>:<p className="bio-result-note">{t('暂无已发布成员')}</p>
}
