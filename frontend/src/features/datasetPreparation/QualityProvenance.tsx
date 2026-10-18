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
 const {t}=useI18n();const [version,setVersion]=useState<DerivationVersion|null>(null),[error,setError]=useState(''),[expanded,setExpanded]=useState(false),[refresh,setRefresh]=useState(0)
 useEffect(()=>{const c=new AbortController();let active=true;preparationRequest(`${fileBase(projectId,source.file_id)}/prepared-dataset-versions/${encodeURIComponent(source.dataset_id)}`,c,(v):v is DerivationVersion=>isDerivationVersion(v,source.file_id)&&sameSource(v.source,source),'整理版本读取失败，请重试。').then(v=>{if(active){setVersion(v);setError('')}}).catch(e=>{if(active)setError(safeError(e,'整理版本读取失败，请重试。'))});return()=>{active=false;c.abort()}},[projectId,source,refresh])
 return <aside className="quality-provenance"><p>{t('筛选后必须新建并独立确认计划；旧推荐仅保留溯源，不作为当前有效建议。')}</p>{error&&<p role="alert">{t(error)}<button onClick={()=>setRefresh(n=>n+1)}>{t('重试')}</button></p>}{version&&<><button aria-expanded={expanded} onClick={()=>setExpanded(v=>!v)}>{t('查看该版本质量策略与完整回执')}</button>{version.operation==='population_filter'?<><FilterCounts value={version.summary}/>{expanded&&<><PopulationFilterEditor value={version.recipe} onChange={()=>{}} disabled/><FilterImpacts url={version.impact_url} downloadUrl={version.impact_download_url}/></>}</>:<><QualitySummary summary={version.summary} baseVersion={version.base_source.dataset_version}/>{expanded&&<><QualityPolicyView recipe={version.recipe}/><QualityImpacts projectId={projectId} source={version.base_source} url={version.impact_url} downloadUrl={version.impact_download_url}/></>}</>}{expanded&&<QualityProvenance projectId={projectId} source={version.base_source}/>}</>}</aside>
}
function Provenance({ projectId, source }: { projectId: string; source: PreparedDatasetAnalysisSourceV2 }) {
 const { t } = useI18n(); const [version, setVersion] = useState<QualityVersion | null>(null); const [error, setError] = useState(''); const [expanded, setExpanded] = useState(false); const [attempt, setAttempt] = useState(0)
 useEffect(() => { const controller = new AbortController(); let active = true
  preparationRequest(`${fileBase(projectId, source.file_id)}/prepared-dataset-versions/${encodeURIComponent(source.dataset_id)}`, controller, (v): v is QualityVersion => isQualityVersionData(v, source.file_id) && sameSource(v.source, source), '整理版本读取失败，请重试。').then(v => { if (active) { setVersion(v); setError('') } }).catch(cause => { if (active) setError(safeError(cause, '整理版本读取失败，请重试。')) }); return () => { active = false; controller.abort() }
 }, [projectId, source, attempt])
 return <aside className="quality-provenance" aria-label={t('上游质量处理')}><p>{t('当前质量版本的累计整理排除已先应用；本计划再按所选变量计算有效记录或完整对。质量处理不证明观察独立性或研究设计成立。')}</p>{error && <p role="alert">{t(error)} <button type="button" onClick={() => setAttempt(n => n + 1)}>{t('重试')}</button></p>}{version && <>{!expanded && <p>{t('原始区域 {root} 行 − 累计整理排除 {excluded} 行 = 当前整理保留 {retained} 行。', { root: version.summary.root_record_count, excluded: version.summary.cumulative_excluded_row_count, retained: version.summary.retained_record_count })}</p>}<button type="button" aria-expanded={expanded} onClick={() => setExpanded(v => !v)}>{t('查看该版本质量策略与完整回执')}</button>{expanded && <><QualityPolicyView recipe={version.recipe} /><QualitySummary summary={version.summary} baseVersion={version.base_source.dataset_version} /><QualityImpacts projectId={projectId} source={version.base_source} url={version.impact_url} downloadUrl={version.impact_download_url} /></>}</>}</aside>
}
