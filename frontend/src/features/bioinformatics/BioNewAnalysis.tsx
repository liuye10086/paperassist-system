import {isTabularRaw,type TabularCapabilities,type TabularRecipe} from './tabularContracts'
import {useBioRead} from './spatialHooks'
import {useI18n} from '../../shared/i18n'
import type {AnalysisNavigation} from '../projects/analysisViews'
import useDraftLeaveGuard,{type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {projectBase} from './api'
import type {BioCapabilities,BioRecipe,RawBioSource} from './spatialContracts'
import {BioWriteStatus} from './BioSpatialShared'
import useBioWrite from './useBioWrite'
import SingleCellDirectStart from './SingleCellDirectStart'
type Props={projectId:string;source:RawBioSource;onNavigate:(n:AnalysisNavigation)=>void;registerLeaveGuard?:RegisterLeaveGuard}
export default function BioNewAnalysis(props:Props){
 if(props.source.parser_version==='single_cell_import_v1')return <SingleCellDirectStart {...props}/>
 return <LegacyNewAnalysis {...props}/>
}
function LegacyNewAnalysis({projectId,source,onNavigate,registerLeaveGuard}:Props){
 const {t}=useI18n(),base=projectBase(projectId),read=useBioRead<BioCapabilities|TabularCapabilities>(`${base}/bio-analysis-capabilities?dataset_id=${encodeURIComponent(source.dataset_id)}&version_id=${encodeURIComponent(source.dataset_version_id)}`)
 const tabular=isTabularRaw(source),singleCell=source.parser_version==='single_cell_import_v1'
 const writer=useBioWrite<BioRecipe|TabularRecipe>(projectId,'recipe',v=>onNavigate({view:'bio-analysis-setup',fileId:'',setupId:v.setup_id}),v=>onNavigate({view:'bio-analysis-setup',fileId:'',setupId:v.root_id!}))
 useDraftLeaveGuard(registerLeaveGuard,false,writer.busy||writer.unknown)
 return <section className="bio-workspace"><h3>{t(tabular?'样本定量分析':singleCell?'单细胞探索分析':'空间转录组分析')}</h3><p>{t('从此固定 raw 版本保存配置；保存、QC 确认与正式计算分开执行。')}</p>{read.error&&<p role="alert">{t(read.error)}</p>}{read.value&&<><ul>{read.value.blockers.map(v=><li key={v}>{v}</li>)}</ul><button type="button" disabled={writer.busy||writer.unknown||!writer.valid||!read.value.available} onClick={()=>void writer.submit(`${base}/bio-analysis-setups`,{...(tabular?{recipe_code:'tabular_quantitative_v1' as const}:singleCell?{recipe_code:'single_cell_explore_v1' as const}:{}),name:tabular?'Quantitative sample analysis':singleCell?'Single-cell exploratory analysis':'Visium exploratory analysis',raw_source:source,expected_revision:0,observation_map_version_id:null,design_version_id:null,params:read.value!.default_params})}>{t(tabular?'新建定量分析配置':singleCell?'新建单细胞分析配置':'新建空间分析配置')}</button></>}<BioWriteStatus writer={writer}/></section>
}
