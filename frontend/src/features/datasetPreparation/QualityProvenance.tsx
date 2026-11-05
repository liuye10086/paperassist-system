import ModuleViews,{ModuleView} from '../../shared/components/ModuleViews'
import { useEffect, useState } from 'react'
import { safeError, useI18n } from '../../shared/i18n'
import { sameSource, type DatasetAnalysisSource, type PreparedDatasetAnalysisSourceV2 } from '../analysis/datasetSource'
import { fileBase, preparationRequest } from './preparationApi'
import { isQualityVersionData, type QualityVersion } from './qualityApi'
import QualitySummary, { QualityPolicyView } from './QualitySummary'
import QualityImpacts from './QualityImpacts'
import {isDerivationVersion,type DerivationVersion} from './populationFilterApi'
import {FilterCounts,FilterImpacts} from './PopulationFilter'
import PopulationFilterEditor from './PopulationFilterEditor'

export default function QualityProvenance({ projectId, source }: { projectId: string; source?: DatasetAnalysisSource }) {
 return source?.kind === 'prepared_dataset_version' && source.schema_version === 3 ? <Derivation key={JSON.stringify(source)} projectId={projectId} source={source}/> : source?.kind === 'prepared_dataset_version' && source.schema_version === 2 ? <Provenance key={JSON.stringify(source)} projectId={projectId} source={source} /> : null
}
function Derivation({projectId,source}:{projectId:string;source:import('../analysis/datasetSource').PreparedDatasetAnalysisSourceV3}) {
 const {t}=useI18n();const [version,setVersion]=useState<DerivationVersion|null>(null),[error,setError]=useState(''),[refresh,setRefresh]=useState(0)
 useEffect(()=>{const c=new AbortController();let active=true;preparationRequest(`${fileBase(projectId,source.file_id)}/prepared-dataset-versions/${encodeURIComponent(source.dataset_id)}`,c,(v):v is DerivationVersion=>isDerivationVersion(v,source.file_id)&&sameSource(v.source,source),'整理版本读取失败，请重试。').then(v=>{if(active){setVersion(v);setError('')}}).catch(e=>{if(active)setError(safeError(e,'整理版本读取失败，请重试。'))});return()=>{active=false;c.abort()}},[projectId,source,refresh])
 return <aside className="quality-provenance">{error&&<p role="alert">{t(error)}<button onClick={()=>setRefresh(n=>n+1)}>{t('重试')}</button></p>}{version&&<ModuleViews label={t('质量处理记录')} lazy>
  <ModuleView id="summary" title={t('质量概况')}><p>{t('质量处理不证明观察独立性或研究设计成立。')}</p>{version.operation==='population_filter'?<FilterCounts value={version.summary}/>:<QualitySummary summary={version.summary} baseVersion={version.base_source.dataset_version}/>}</ModuleView>
  <ModuleView id="policy" title={t('处理策略')}>{version.operation==='population_filter'?<PopulationFilterEditor value={version.recipe} onChange={()=>{}} disabled/>:<QualityPolicyView recipe={version.recipe}/>}</ModuleView>
  <ModuleView id="impacts" title={t('影响记录')}>{version.operation==='population_filter'?<FilterImpacts url={version.impact_url} downloadUrl={version.impact_download_url}/>:<QualityImpacts projectId={projectId} source={version.base_source} url={version.impact_url} downloadUrl={version.impact_download_url}/>}</ModuleView>
  <ModuleView id="source" title={t('上游来源')}><QualityProvenance projectId={projectId} source={version.base_source}/></ModuleView>
 </ModuleViews>}</aside>
}
function Provenance({ projectId, source }: { projectId: string; source: PreparedDatasetAnalysisSourceV2 }) {
 const { t } = useI18n(); const [version, setVersion] = useState<QualityVersion | null>(null); const [error, setError] = useState(''); const [attempt, setAttempt] = useState(0)
 useEffect(() => { const controller = new AbortController(); let active = true
  preparationRequest(`${fileBase(projectId, source.file_id)}/prepared-dataset-versions/${encodeURIComponent(source.dataset_id)}`, controller, (v): v is QualityVersion => isQualityVersionData(v, source.file_id) && sameSource(v.source, source), '整理版本读取失败，请重试。').then(v => { if (active) { setVersion(v); setError('') } }).catch(cause => { if (active) setError(safeError(cause, '整理版本读取失败，请重试。')) }); return () => { active = false; controller.abort() }
 }, [projectId, source, attempt])
 return <aside className="quality-provenance" aria-label={t('上游质量处理')}>{error&&<p role="alert">{t(error)} <button type="button" onClick={()=>setAttempt(n=>n+1)}>{t('重试')}</button></p>}{version&&<ModuleViews label={t('质量处理记录')} lazy>
  <ModuleView id="summary" title={t('质量概况')}><p>{t('质量处理不证明观察独立性或研究设计成立。')}</p><QualitySummary summary={version.summary} baseVersion={version.base_source.dataset_version}/></ModuleView>
  <ModuleView id="policy" title={t('处理策略')}><QualityPolicyView recipe={version.recipe}/></ModuleView>
  <ModuleView id="impacts" title={t('影响记录')}><QualityImpacts projectId={projectId} source={version.base_source} url={version.impact_url} downloadUrl={version.impact_download_url}/></ModuleView>
 </ModuleViews>}</aside>
}
