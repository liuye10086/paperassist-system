import type {TabularProcessed} from './tabularContracts'
import {useI18n} from '../../shared/i18n'
import {BioJson,BioSpatialMembers} from './BioSpatialShared'
import type {BioProcessed} from './spatialContracts'
export default function BioReproducibility({projectId,result}:{projectId:string;result:BioProcessed|TabularProcessed}){
 const {t}=useI18n()
 return <section className="bio-workspace"><h3>{t('方法与可复现材料')}</h3>
  <p>{t('仅固定算法计算；工程复现不等于生物学确认或用户验收。')}</p>
  {Boolean(result.manifest.methods)&&<><h4>{t('方法记录')}</h4><BioJson value={result.manifest.methods}/></>}
  <h4>{t('结果文件')}</h4><BioSpatialMembers projectId={projectId} members={result.members}/>
 </section>
}
