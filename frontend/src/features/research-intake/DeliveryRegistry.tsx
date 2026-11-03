import DeliveryPackagePanel from './DeliveryPackagePanel'
import {deliveryHref} from './deliveryPackageContracts'
import type {RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import { useI18n } from '../../shared/i18n'
import type { Delivery } from './contracts'
import { deliveryLabels } from './contracts'
export default function DeliveryRegistry({items,capabilities,projectId,active=true,selectedId,snapshotId,onSelect,registerLeaveGuard}:{items:Delivery[];capabilities:Record<string,boolean>;projectId:string;active?:boolean;selectedId?:string;snapshotId?:string;onSelect?:(delivery:string,snapshot?:string)=>void;registerLeaveGuard?:RegisterLeaveGuard}){
 const {t}=useI18n();return <section>{items.length===0&&<p>{t('暂无交付登记')}</p>}<ul>{items.map(d=><li key={d.id}><strong>{t(deliveryLabels[d.kind])}</strong> · {t((d.selected??d.active)?'已选服务':'已停用')} · {t(d.origin==='legacy_inferred'?'由旧项目类型登记':'客户选择')}<p>{t(d.kind==='analysis'?'按项目需求进入数据准备、分析与结果工作区；此处登记已有成果并整理交付。':(d.workflow_available??capabilities.legacy_writing)?'沿用已有稿件流程。':'已登记，当前流程未开放')}</p><a href={deliveryHref(projectId,d.id)} onClick={()=>onSelect?.(d.id,'')}>{t('打开此交付的固定快照')}</a></li>)}</ul>{selectedId&&!items.some(d=>d.id===selectedId)&&<p role="alert">{t('此交付不在当前项目登记中，请核对固定链接。')}</p>}{items.map(d=><DeliveryPackagePanel key={d.id} projectId={projectId} deliveryId={d.id} active={active&&selectedId===d.id} snapshotId={selectedId===d.id?snapshotId:''} onSelect={snapshot=>onSelect?.(d.id,snapshot)} registerLeaveGuard={registerLeaveGuard}/>)}</section>
}
