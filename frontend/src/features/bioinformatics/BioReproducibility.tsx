import type {TabularProcessed} from './tabularContracts'
import {useI18n} from '../../shared/i18n'
import {BioJson,BioSpatialMembers} from './BioSpatialShared'
import type {BioProcessed} from './spatialContracts'
export default function BioReproducibility({projectId,result}:{projectId:string;result:BioProcessed|TabularProcessed}){const {t}=useI18n();return <section className="bio-workspace"><h3>{t('方法与可复现材料')}</h3><p>{t('仅固定算法计算；工程复现不等于生物学确认或用户验收。')}</p><dl><dt>{t('计算引擎')}</dt><dd>{result.source.engine_version}</dd></dl><h4>{t('方法记录')}</h4>{result.manifest.methods?<BioJson value={result.manifest.methods}/>:<p>{t('方法记录通过下方固定成员下载。')}</p>}<h4>{t('实际资源记录')}</h4><BioJson value={result.manifest.resources??null}/><details><summary>{t('完整冻结清单')}</summary><BioJson value={result.manifest}/></details><BioSpatialMembers projectId={projectId} members={result.members}/></section>}
