import {useI18n} from '../../shared/i18n'
import type {ConfigCatalog} from './configurationTypes'
const nodeNames:Record<string,string>={material:'材料准备',policy:'政策选择',authorization:'用户授权',admission:'预算准入',provider:'供应商执行',validation:'输出验证'}
const templateNames:Record<string,string>={'sci-writing-v1':'论文写作模板（v1）','sci-writing-v2':'论文写作模板（v2）',literature_assistance_v1:'文献辅助模板（v1）','analysis_explanation_v1-v4':'结果解释模板（v1至v4）','analysis_recommendation_v1-v5':'分析建议模板（v1至v5）','openai_figure_workbench_v1-v3':'图表工作台模板（v1至v3）','figure_explanation_v1-v4':'图表解释模板（v1至v4）'}
export default function InstalledConfigurationCapabilities({catalog}:{catalog:ConfigCatalog}){
 const{t}=useI18n(),workflows=catalog.installed.workflows??[],templates=catalog.installed.templates??[]
 return <details><summary>{t('已安装工作流与模板范围')}</summary><p>{t('以下为已安装的只读范围；不能新增节点、替换代码或解除安全门槛。')}</p><h4>{t('已安装工作流')}</h4>{workflows.length===0&&<p>{t('尚无可用的安装范围信息。')}</p>}{workflows.map(flow=><section key={flow.id}><h5>{t(flow.id==='installed-v1'?'标准科研工作流':'已安装工作流')}</h5><ol>{flow.nodes.map(node=><li key={node}>{t(nodeNames[node]??'未知节点')}</li>)}</ol><small>{t('只读')} · {flow.id}</small></section>)}<h4>{t('已安装模板')}</h4>{templates.length===0?<p>{t('尚无可用的安装范围信息。')}</p>:<ul>{templates.map(template=><li key={template}>{t(templateNames[template]??'已安装模板')}<small>{template}</small></li>)}</ul>}</details>
}
