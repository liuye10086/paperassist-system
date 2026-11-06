import type {Result} from './contracts'
import {DataDetails,DesignUnits} from './InsightShared'

export default function SingleCellTopicSummary({result}:{result:Result}){
 const s=result.summary,method=s.topic_method
 if(!method)return null
 return <section><h3>{({slingshot:'Slingshot 轨迹结果',genie3:'GENIE3 调控网络结果',cellchat:'CellChat 通讯结果'} as Record<string,string>)[String(method)]}</h3>
 <p>实际选择细胞：{String(s.selected_cells)} · 已知供者：{String(s.donor_count)} · 单位：{String(s.unit_count)} · 结果：{String(s.status)}</p>
 {method==='slingshot'&&<p>分支数：{String(s.lineage_count)} · 未覆盖细胞：{String(s.uncovered_cells)}。拟时序是相对坐标，未覆盖值保留 NA。</p>}
 {method==='genie3'&&<><p>TF：{String(s.tf_count)} · 基因：{String(s.gene_count)}。完整表保留两种子权重；这些权重不是 P 值或因果。</p><DataDetails title="两种子稳定性" value={s.stability}/></>}
 {method==='cellchat'&&<><p>LR 集合：{String(s.resource_id)} · 实际选择交互：{String(s.resource_interactions)} · 可计算单位：{String(s.computable_units)}。小规模文献演示集合不代表全库；细胞置换 P 与供者 P 分列保存。</p><DesignUnits value={s.actual_units} cell/></>}
 </section>
}
