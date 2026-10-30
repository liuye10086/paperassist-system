import {useI18n} from '../../shared/i18n'
import {BioJson} from './BioSpatialShared'
import type {BioCheck} from './contracts'
export default function BioRepresentation({summary,checks}:{summary:Record<string,unknown>;checks:BioCheck[]}){
 const {t}=useI18n(),description=summary.representation??checks.find(c=>c.code==='representation_equivalence')?.value
 if(!description)return null
 return <section className="bio-workspace"><h3>{t('矩阵表示与实际核对记录')}</h3><p>{t('同一样本的 MTX / H5 比较不增加样本；派生表示与原件分别保留。')}</p><BioJson value={description}/></section>
}
