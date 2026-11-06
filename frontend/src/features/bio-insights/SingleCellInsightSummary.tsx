import {useI18n} from '../../shared/i18n'
import {DesignUnits} from './InsightShared'
import type {Result} from './contracts'
import {displayRaw} from './state'
export default function SingleCellInsightSummary({result}:{result:Result}){
 const{t}=useI18n(),config=result.methods.config as Record<string,unknown>|undefined,composition=config?.schema_version===5,selection=result.methods.single_cell_selection??config?.single_cell_selection
 if(!composition&&!selection)return null
 return <section><h3>{t(composition?'供者组成与推断边界':'同类型供者比较与推断边界')}</h3>{composition&&<><p>{t(config?.mode==='descriptive'?'供者组成仅描述；不生成 P 值。':'组成推断以真实供者为统计单位，最低重复数不保证统计功效。')}</p>{config?.mode==='descriptive'&&typeof config.numerator==='string'&&config.numerator.length>0&&config.numerator===config.denominator&&<p>{t('单条件组成描述；相同条件只计数一次，不计算组间差值、比值或 P 值。')}</p>}<p>分母细胞 n = {displayRaw(result.summary.total_cells)} · donor × condition 单元数 = {displayRaw(result.summary.unit_count)}</p><p>{t('分母包括其他已分配标签、unknown、uncertain、conflict 与 unlabeled；完整分子分母见 composition_counts。')}</p><p>{t('标签身份人工确认')} · {t(result.summary.labels_confirmed===true?'已确认':'尚未确认')}</p><p>{t('实际推断状态')} · {displayRaw(result.summary.inference_status)} · {displayRaw(result.summary.inference_reason)}</p></>}
 <DesignUnits value={result.summary.actual_units??result.methods.actual_units} cell singleCondition={composition&&config?.mode==='descriptive'&&typeof config.numerator==='string'&&config.numerator.length>0&&config.numerator===config.denominator}/>
 <p>{t('细胞数和技术文库数不会增加独立供者 n；缺少供者或设计条件时不能据此宣称群体差异。')}</p></section>
}
