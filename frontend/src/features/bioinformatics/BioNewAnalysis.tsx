import type {BioSetupRequest} from './spatialContracts'
import {useBioRead} from './spatialHooks'
import {useI18n} from '../../shared/i18n'
import type {AnalysisNavigation} from '../projects/analysisViews'
import useDraftLeaveGuard,{type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {projectBase} from './api'
import type {BioCapabilities,BioRecipe,RawBioSource} from './spatialContracts'
import {BioWriteStatus} from './BioSpatialShared'
import useBioWrite from './useBioWrite'
export default function BioNewAnalysis({projectId,source,onNavigate,registerLeaveGuard}:{projectId:string;source:RawBioSource;onNavigate:(n:AnalysisNavigation)=>void;registerLeaveGuard?:RegisterLeaveGuard}){
 const {t}=useI18n(),base=projectBase(projectId),read=useBioRead<BioCapabilities>(`${base}/bio-analysis-capabilities?dataset_id=${encodeURIComponent(source.dataset_id)}&version_id=${encodeURIComponent(source.dataset_version_id)}`)
 const writer=useBioWrite<BioRecipe>(projectId,'recipe',v=>onNavigate({view:'bio-analysis-setup',fileId:'',setupId:v.setup_id}),v=>onNavigate({view:'bio-analysis-setup',fileId:'',setupId:v.root_id!}))
 useDraftLeaveGuard(registerLeaveGuard,false,writer.busy||writer.unknown)
 return <section className="bio-workspace"><h3>{t('空间转录组分析')}</h3><p>{t('从此固定 raw 版本保存配置；保存、QC 确认与正式计算分开执行。')}</p>{read.error&&<p role="alert">{t(read.error)}</p>}{read.value&&<><ul>{read.value.blockers.map(v=><li key={v}>{v}</li>)}</ul><button type="button" disabled={writer.busy||writer.unknown||!writer.valid||!read.value.available} onClick={()=>void writer.submit(`${base}/bio-analysis-setups`,{name:'Visium exploratory analysis',raw_source:source,expected_revision:0,observation_map_version_id:null,design_version_id:null,params:read.value!.default_params} satisfies BioSetupRequest)}>{t('新建空间分析配置')}</button></>}<BioWriteStatus writer={writer}/></section>
}
