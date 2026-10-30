import { useI18n } from '../../shared/i18n'
import type { Delivery } from './contracts'
import { deliveryLabels } from './contracts'
export default function DeliveryRegistry({items,capabilities}:{items:Delivery[];capabilities:Record<string,boolean>}){
 const {t}=useI18n();return <section><h2>{t('交付登记')}</h2><p>{t('交付登记与当前可执行流程分别显示。')}</p>{items.length===0&&<p>{t('暂无交付登记')}</p>}<ul>{items.map(d=><li key={d.id}><strong>{t(deliveryLabels[d.kind])}</strong> · {t((d.selected??d.active)?'已选服务':'已停用')} · {t(d.origin==='legacy_inferred'?'由旧项目类型登记':'客户选择')}<p>{t(d.kind==='analysis'?'可上传原件、核对和发布生信结构；生信分析流程未开放。':(d.workflow_available??capabilities.legacy_writing)?'沿用已有稿件流程。':'已登记，当前流程未开放')}</p></li>)}</ul></section>
}
