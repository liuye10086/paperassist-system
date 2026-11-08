import {isTabularRaw} from './tabularContracts'
import BioRepresentation from './BioRepresentation'
import BioNewAnalysis from './BioNewAnalysis'
import {isRawBioSource} from './spatialContracts'
import type {AnalysisNavigation} from '../projects/analysisViews'
import type {RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import BioCoordinates from './BioCoordinates'
import {useEffect,useState} from 'react'
import {apiFetch,onApiSessionChanged} from '../../shared/api/client'
import {safeError,useI18n} from '../../shared/i18n'
import {bioRequest,projectBase} from './api'
import type {BioVersion} from './contracts'
import {BioChecks,BioCounts,BioMembers} from './BioDetails'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import ModuleViews,{ModuleView} from '../../shared/components/ModuleViews'
import useResearchDraft from '../research-results/useResearchDraft'
import './bioLayout.css'
export default function BioDatasetDetail({allowNewAnalysis=true,projectId,datasetId,versionId,onNavigate,registerLeaveGuard}:{allowNewAnalysis?:boolean;projectId:string;datasetId:string;versionId:string;onNavigate?:(n:AnalysisNavigation)=>void;registerLeaveGuard?:RegisterLeaveGuard}){
 const {t}=useI18n();const [data,setData]=useState<BioVersion|null>(null);const [error,setError]=useState('');const [attempt,setAttempt]=useState(0);const [valid,setValid]=useState(true);const [image,setImage]=useState('');const [matrix,setMatrix]=useState<Record<string,unknown>|null>(null)
 const [panel,setPanel]=useResearchDraft<string>(projectId,`bio-dataset-panel:${datasetId}:${versionId}`,()=> 'overview')
 const singleCell=!!data&&isRawBioSource(data.source,projectId)&&data.source.parser_version==='single_cell_import_v1'
 const tabular=!!data&&isRawBioSource(data.source,projectId)&&isTabularRaw(data.source)
 const base=`${projectBase(projectId)}/bio-datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}`
 useEffect(()=>onApiSessionChanged(()=>{setValid(false);setData(null);setMatrix(null);setImage('')}),[])
 useEffect(()=>{if(!valid)return;const c=new AbortController();let live=true;void bioRequest<BioVersion>(base,{signal:c.signal}).then(v=>{if(live){setData(v);setError('')}}).catch(cause=>{if(live)setError(safeError(cause,'生信数据集读取失败，请重试。'))});return()=>{live=false;c.abort()}},[base,attempt,valid])
 useEffect(()=>{const member=data?.members.find(m=>['tissue_hires_image','tissue_lowres_image','image','tissue_image'].includes(m.role)&&m.download_url?.startsWith(projectBase(projectId)+'/'));if(!member?.download_url||!valid)return;const c=new AbortController();let live=true;let url='';void apiFetch(member.download_url,{signal:c.signal}).then(async r=>{if(!r.ok)return;const blob=await r.blob();if(!live)return;url=URL.createObjectURL(blob);setImage(url)}).catch(()=>{});return()=>{live=false;c.abort();if(url)URL.revokeObjectURL(url);setImage('')}},[data,projectId,valid])
 async function preview(){try{setMatrix(await bioRequest<Record<string,unknown>>(`${base}/matrix-preview?features_page=1&observations_page=1`))}catch(cause){setError(safeError(cause,'矩阵预览读取失败，请重试。'))}}
 return <section className="bio-workspace bio-module-workspace">
  <header className="bio-workspace-header"><h2>{t('生信数据集')}</h2>{data&&<span>{t('数据已保存')}</span>}<button type="button" disabled={!valid} onClick={()=>setAttempt(v=>v+1)}>{t('重新读取')}</button></header>
  {error&&<p className="error-panel" role="alert">{t(error)}</p>}
  {data&&<ModuleViews label={t('数据集模块')} value={panel} onChange={setPanel}>
   <ModuleView id="overview" title={t('数据概况')}><BioCounts summary={data.shape}/></ModuleView>
   <ModuleView id="checks" title={t('结构检查')}><BioChecks checks={data.checks} singleCell={singleCell}/>{!tabular&&!singleCell&&<BioRepresentation summary={data.summary} checks={data.checks}/>}</ModuleView>
   <ModuleView id="files" title={t('数据文件')}><BioMembers projectId={projectId} members={data.members}/><ProjectDownloadLink href={`${base}/manifest`} filename="bio-manifest.json">{t('下载导入核对清单')}</ProjectDownloadLink></ModuleView>
   {(!tabular&&!singleCell||image)&&<ModuleView id="coordinates" title={t('坐标与图像')}>{!tabular&&!singleCell&&<BioCoordinates projectId={projectId} datasetId={datasetId} versionId={versionId} members={data.members}/>}{image&&<figure><img className="bio-coordinate-preview" src={image} alt={t('组织原图核对')}/><figcaption>{t('原组织图，用于配套核对；不表示空间表达或细胞类型。')}</figcaption></figure>}</ModuleView>}
   <ModuleView id="matrix" title={t('矩阵预览')}><button type="button" disabled={!valid} onClick={()=>void preview()}>{t('读取有界矩阵预览')}</button>{matrix&&<MatrixPreview value={matrix}/>}</ModuleView>
   {onNavigate&&isRawBioSource(data.source,projectId)&&<ModuleView id="analysis" title={t('分析入口')}><BioNewAnalysis allowNewAnalysis={allowNewAnalysis} projectId={projectId} source={data.source} onNavigate={onNavigate} registerLeaveGuard={registerLeaveGuard}/></ModuleView>}
  </ModuleViews>}
  {data&&onNavigate&&isRawBioSource(data.source,projectId)&&panel!=='analysis'&&<footer className="bio-confirmation-actions"><p>{t('矩阵已就绪，下一步选择参数并检查分析设置。')}</p><button type="button" className="button-primary" onClick={()=>setPanel('analysis')}>{t('下一步：配置分析')}</button></footer>}
 </section>
}
function MatrixPreview({value}:{value:Record<string,unknown>}){const {t}=useI18n();const features=(value.features??[]) as unknown[];const observations=(value.observations??[]) as unknown[];const values=(value.values??value.matrix??[]) as unknown[][];const label=(v:unknown)=>typeof v==='object'&&v?String((v as Record<string,unknown>).id??(v as Record<string,unknown>).sample_id??(v as Record<string,unknown>).barcode??(v as Record<string,unknown>).feature_id??''):String(v);const symbol=(v:unknown)=>v&&typeof v==='object'&&typeof (v as Record<string,unknown>).symbol==='string'?String((v as Record<string,unknown>).symbol):'';return <div className="bio-table-scroll"><table><caption>{t('少量原始矩阵值；保留稳定标识，未标准化或筛选。')}</caption><thead><tr><th>{t('观测 / 特征')}</th>{features.slice(0,40).map((f,i)=><th key={i} scope="col"><span>{label(f)}</span>{symbol(f)&&<><br/><span>{symbol(f)}</span></>}</th>)}</tr></thead><tbody>{observations.slice(0,20).map((o,i)=><tr key={i}><th>{label(o)}</th>{features.slice(0,40).map((_,j)=><td key={j}>{typeof values[i]?.[j]==='number'?String(values[i][j]):'—'}</td>)}</tr>)}</tbody></table></div>}
