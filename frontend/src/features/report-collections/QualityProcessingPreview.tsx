import {useI18n} from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import {isDatasetSource,type DatasetAnalysisSource} from '../analysis/datasetSource'
import {fileBase} from '../datasetPreparation/preparationApi'
import {isQualityRecipe,isQualitySummary,qualityObject} from '../datasetPreparation/qualityApi'
import QualitySummary,{QualityPolicyView} from '../datasetPreparation/QualitySummary'
import {isFilterRecipe,isFilterSummary} from '../datasetPreparation/populationFilterApi'
import {FilterCounts} from '../datasetPreparation/PopulationFilter'
import PopulationFilterEditor from '../datasetPreparation/PopulationFilterEditor'

export default function QualityProcessingPreview({value,projectId,source}:{value:unknown;projectId?:string;source?:DatasetAnalysisSource}){
 const {t}=useI18n()
 if(qualityObject(value)&&value.schema_version===3){
  if(!isDatasetSource(value.base_source)||value.base_source.kind!=='prepared_dataset_version')return <p role="alert">{t('完整质量回执读取失败，请重试。')}</p>
  const parent=value.base_source,bound=source?.kind==='prepared_dataset_version'&&source.schema_version===3&&source.file_id===parent.file_id&&source.parent_dataset_id===parent.parent_dataset_id&&source.dataset_version>parent.dataset_version&&source.structure_id===parent.structure_id&&source.source_sha256===parent.source_sha256
  const filter=value.operation==='population_filter'&&isFilterRecipe(value.recipe)&&isFilterSummary(value.receipt),quality=value.operation==='quality'&&isQualityRecipe(value.recipe)&&isQualitySummary(value.receipt)
  if(!filter&&!quality)return <p role="alert">{t('完整质量回执读取失败，请重试。')}</p>
  return <div>{filter&&isFilterRecipe(value.recipe)&&isFilterSummary(value.receipt)?<><PopulationFilterEditor value={value.recipe} onChange={()=>{}} disabled/><FilterCounts value={value.receipt}/></>:isQualityRecipe(value.recipe)&&isQualitySummary(value.receipt)?<><QualityPolicyView recipe={value.recipe}/><QualitySummary summary={value.receipt} baseVersion={parent.dataset_version}/></>:null}{projectId&&bound&&<ProjectDownloadLink href={`${fileBase(projectId,source.file_id)}/prepared-dataset-versions/${encodeURIComponent(source.dataset_id)}/impacts/download`} filename="derivation-receipt.json">{t(filter?'下载完整筛选回执':'下载完整质量回执')}</ProjectDownloadLink>}{Array.isArray(value.ancestors)&&value.ancestors.map((a,i)=>qualityObject(a)&&isDatasetSource(a.source)&&a.source.kind==='prepared_dataset_version'?<details key={i}><summary>{t('查看直接父版本回执')} · v{a.source.dataset_version}</summary>{a.operation==='population_filter'&&isFilterRecipe(a.recipe)&&isFilterSummary(a.receipt)?<><PopulationFilterEditor value={a.recipe} onChange={()=>{}} disabled/><FilterCounts value={a.receipt}/></>:isQualityRecipe(a.recipe)&&isQualitySummary(a.receipt)?<QualitySummary summary={a.receipt} />:null}{projectId&&<ProjectDownloadLink href={`${fileBase(projectId,a.source.file_id)}/prepared-dataset-versions/${encodeURIComponent(a.source.dataset_id)}/impacts/download`} filename="ancestor-receipt.json">{t('下载完整 JSON')}</ProjectDownloadLink>}</details>:null)}</div>
 }
 if(!qualityObject(value)||value.schema_version!==2||!isQualityRecipe(value.recipe)||!isQualitySummary(value.receipt)||!isDatasetSource(value.base_source)||value.base_source.kind!=='prepared_dataset_version')return <p role="alert">{t('完整质量回执读取失败，请重试。')}</p>
 const parent=value.base_source
 const bound=source?.kind==='prepared_dataset_version'&&source.schema_version===2&&source.file_id===parent.file_id&&source.parent_dataset_id===parent.parent_dataset_id&&source.parent_dataset_version===parent.parent_dataset_version&&source.dataset_version>parent.dataset_version&&source.structure_id===parent.structure_id&&source.source_sha256===parent.source_sha256&&source.sheet_index===parent.sheet_index&&source.sheet_name===parent.sheet_name&&source.parser_version===parent.parser_version
 return <div><QualityPolicyView recipe={value.recipe}/><QualitySummary summary={value.receipt} baseVersion={parent.dataset_version}/>{projectId&&bound&&<ProjectDownloadLink href={`${fileBase(projectId,source.file_id)}/prepared-dataset-versions/${encodeURIComponent(source.dataset_id)}/impacts/download`} filename={`quality-receipt-v${source.dataset_version}.json`}>{t('下载完整质量回执')}</ProjectDownloadLink>}</div>
}
