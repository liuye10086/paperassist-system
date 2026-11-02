import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import type {AnalysisNavigation,BioResultTab} from '../projects/analysisViews'
import type {TabularProcessed} from './tabularContracts'
import {assayLabels,isTabularProcessedSource} from './tabularContracts'
import {BioJson,BioMemberImage,BioSource,BioSpatialMembers} from './BioSpatialShared'
import BioResultTable from './BioResultTable'
import BioMatrixPreview from './BioMatrixPreview'
import BioQcSummary from './BioQcSummary'
import BioReproducibility from './BioReproducibility'

const tabs={qc:'QC 与过滤',embedding:'样本 PCA',clusters:'样本聚类',methods:'方法与复现'}
export default function TabularAnalysisResult({projectId,result,tab,onNavigate}:{projectId:string;result:TabularProcessed;tab:BioResultTab;onNavigate:(n:AnalysisNavigation)=>void}) {
 const {t}=useI18n(),[tableKey,setTableKey]=useState('')
 if(!isTabularProcessedSource(result.source,projectId)||result.source.processed_dataset_version_id!==result.id)return <p role="alert">{t('固定来源身份不匹配，请重新打开。')}</p>
 const supported=tab in tabs,active=supported?tab as keyof typeof tabs:'qc'
 const relevant=(key:string)=>active==='qc'?/qc|sample|feature/.test(key)&&!key.includes('clustering'):active==='embedding'?key.startsWith('pca'):active==='clusters'?key.includes('clustering'):false
 const tables=result.tables.filter(table=>relevant(table.key)),selected=tables.find(table=>table.key===tableKey)??tables[0]
 const summary=result.manifest.summary&&typeof result.manifest.summary==='object'?result.manifest.summary as Record<string,unknown>:{}
 return <section className="bio-workspace"><h2>{t('定量分析处理结果')}</h2>
  <p>{t(assayLabels[result.source.assay])} · {t('统计观察单位：样本；独立性与技术重复须结合样本设计判断。')}</p>
  <BioSource source={result.source.raw_source}/><p>{t('计算引擎')} · {result.source.engine_version}</p>
  <button type="button" onClick={()=>onNavigate({view:'bio-insights',fileId:'',processedId:result.id})}>{t('差异与功能分析')}</button><button type="button" onClick={()=>onNavigate({view:'research-findings',fileId:'',processedId:result.id})}>{t('整理研究发现与报告')}</button>
  <nav className="intake-actions" aria-label={t('生信结果标签页')}>{Object.entries(tabs).map(([key,label])=><button type="button" key={key} aria-current={key===active?'page':undefined} onClick={()=>onNavigate({view:'bio-result',fileId:'',processedId:result.id,tab:key as BioResultTab})}>{t(label)}</button>)}</nav>
  {!supported&&<p role="status">{t('此非空间版本不提供该标签页，当前显示样本 QC。')}</p>}
  <details><summary>{t('实际步骤状态和缺口')}</summary><ul>{result.steps.map(step=><li key={step.key}>{step.key}: {t(step.status==='completed'?'已完成':step.status==='not_computable'?'不可计算':'未请求')}{step.reason&&<> · <span>{step.reason}</span></>}</li>)}</ul></details>
  {active==='methods'?<BioReproducibility projectId={projectId} result={result}/>:<>
   {active==='qc'&&<><BioQcSummary summary={summary} observationLabel="样本" featureLabel="特征"/><BioMatrixPreview projectId={projectId} processedId={result.id} layers={['analysis','display']}/><details><summary>{t('原始尺度与处理记录')}</summary><BioJson value={{scale:result.manifest.scale,steps:result.steps}}/></details></>}
   {result.figures.filter(figure=>relevant(figure.config.kind)).map(figure=><section key={figure.id}><h3>{figure.config.title||figure.config.kind}</h3><button type="button" onClick={()=>onNavigate({view:'bio-figure',fileId:'',figureId:figure.id})}>{t('打开固定单图版本')}</button>{figure.members.filter(member=>member.format==='png').map(member=><BioMemberImage key={member.id} projectId={projectId} member={member}/>)}<BioSpatialMembers projectId={projectId} members={figure.members}/></section>)}
   {tables.length?<><label>{t('结果表')}<select value={selected?.key??''} onChange={e=>setTableKey(e.target.value)}>{tables.map(table=><option key={table.key} value={table.key}>{table.label}</option>)}</select></label>{selected?.status==='not_computable'?<p>{t('不可计算')} · {selected.reason}</p>:selected&&<BioResultTable key={selected.key} projectId={projectId} processedId={result.id} tableKey={selected.key}/>}</>:<p>{t('此标签页无可用结果表，请查看步骤状态和下载清单。')}</p>}
   <BioSpatialMembers projectId={projectId} members={result.members.filter(member=>relevant(member.key))}/>
  </>}
 </section>
}
