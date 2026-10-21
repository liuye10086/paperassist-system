import FigureDescription from '../figure-workbench/FigureDescription'
import {isPresentation} from '../figure-workbench/presentation'
import {useI18n} from '../../shared/i18n'
import {object} from '../figure-workbench/contracts'
import {publicEntries} from './contracts'
import {readableLabels,enumValues,enumFields} from './reportPreviewLabels'
import QualityProcessingPreview from './QualityProcessingPreview'
import type {DatasetAnalysisSource} from '../analysis/datasetSource'
const labels:Record<string,string>={source:'数据来源',sources:'数据来源',sheet_name:'工作表',sheet_index:'工作表位置',dataset_version:'数据版本',parent_dataset_version:'原始数据版本',kind:'类型',title:'标题',caption:'图注',n:'样本数 n',valid_count:'有效记录数',excluded_count:'排除记录数',row_count:'记录数',check:'检查结果',method:'分析方法',statistics:'统计结果',groups:'分组',label:'标签',mean:'均值',std:'样本标准差',min:'最小值',max:'最大值',median:'中位数',q1:'Q1',q3:'Q3',warnings:'提示',issues:'检查问题',figure_number:'图号',text:'内容',limitations:'局限',sections:'解释内容',missing:'待补充',coefficient:'相关系数',p_value:'P 值',confidence_interval:'95% 置信区间',low:'下限',high:'上限',value:'数值',unit:'单位',column:'字段',name:'名称',fields:'字段',plan:'已确认计划',selection:'变量选择',summary:'总结',receipt:'处理回执',recipe:'处理规则',columns:'字段',data_range:'数据范围',complete_rows:'完整记录',profile:'数据质量',processing:'处理方式',evidence:'事实依据'}
const statisticalLabels:Record<string,string>={mode:'分析模式',matrix:'相关系数矩阵',inference:'推断方法',alternative:'备择假设',level:'置信水平',reason:'原因',parameters:'已确认参数',coefficients:'回归效应',beta:'系数 β',se:'标准误',statistic:'检验统计量',ci_low:'区间下限',ci_high:'区间上限',or_value:'优势比 OR',or_ci_low:'OR 区间下限',or_ci_high:'OR 区间上限',term:'效应项',reference:'参照水平',df_residual:'残差自由度',p:'参数数（含截距）',r_squared:'R²',adjusted_r_squared:'调整 R²',residual_sd:'残差标准差',log_likelihood:'对数似然',deviance:'偏差',aic:'AIC',diagnostics:'模型诊断',rank:'秩',condition_number:'条件数',converged:'收敛',gradient_max:'最大梯度',residuals:'残差',fitted:'拟合值',leverage:'杠杆值',cooks_distance:'Cook 距离',auc:'AUC',variance:'方差',positive_n:'阳性',negative_n:'阴性',points:'曲线数据',threshold:'阈值',sensitivity:'灵敏度',specificity:'特异度',fpr:'假阳性率',time:'时间',survival:'生存率',n_at_risk:'风险人数',n_event:'事件数',n_censored:'删失数',event_n:'事件数',censored_n:'删失数',max_time:'最长随访',risk_table:'风险人数表',median_reason:'中位数不可用原因',observation_basis:'观察单位',missing_policy:'缺失规则',missing_count:'缺失数',count:'记录数',total_count:'记录总数',numeric:'数值概况',categorical:'类别概况',temporal:'时间概况',selected_fields:'所选字段',selected_count:'选择记录数',excluded_rows:'排除记录',included_rows:'纳入来源行',population_n:'投影人群记录数',valid_n:'投影有效记录数',excluded_n:'投影排除记录数',missing_y_n:'纵轴缺失记录数',original_statistical_n:'原统计有效记录数'}

const textValue=(v:unknown):v is string=>typeof v==='string'
function ValueTree({value,field='',preparedQuality=false}:{value:unknown;field?:string;preparedQuality?:boolean}){
 const {t,locale}=useI18n(),language=locale==='en'?1:0
 if(field==='caption_status'&&typeof value==='string'){const captions:Record<string,string>={supplied:'用户提供图注',source:'来源图注',candidate:'候选图注，需人工补充与确认',missing:'图注缺失，待补充'};if(captions[value])return <span>{t(captions[value])}</span>}
 if(value===null||value===undefined)return <span>{t('未提供或无法计算')}</span>
 if(Array.isArray(value))return value.length?<ol className="report-fact-list">{value.map((item,index)=><li key={index}><ValueTree value={item} field={field} preparedQuality={preparedQuality}/></li>)}</ol>:<span>{t('无已记录条目')}</span>
 if(object(value)){
  if(Object.hasOwn(value,'presentation')&&value.presentation!==undefined&&value.presentation!==null&&!isPresentation(value.presentation))return <p role="alert">{t('图说明格式无法核验，请重新读取。')}</p>
  if(field==='evidence')return <dl>{textValue(value.label)&&<dt>{value.label}</dt>}<dd><ValueTree value={value.value} field="value" preparedQuality={preparedQuality}/></dd></dl>
  if(isPresentation(value.presentation))return <FigureDescription title={textValue(value.title)?value.title:''} caption={textValue(value.caption)?value.caption:''} number={Number.isSafeInteger(value.figure_number)?Number(value.figure_number):1} presentation={value.presentation}/>
  const entries=publicEntries(value).filter(([,item])=>item!==undefined)
  if(!entries.length)return <span>{t('无已记录条目')}</span>
  const qualityLabels:Record<string,[string,string]>={row_count:['整理后保留记录数','Records retained after preparation'],excluded_count:['本分析排除记录数','Records excluded from this analysis']}
  return <dl>{entries.map(([key,item])=><div key={key}><dt>{(preparedQuality?qualityLabels[key]?.[language]:undefined)??readableLabels[key]?.[language]??(labels[key]||statisticalLabels[key]?t(labels[key]??statisticalLabels[key]):['units','aliases','sample_sizes'].includes(field)||/^[A-Z]{1,3}$/.test(key)?key:t('未识别字段：{name}',{name:key}))}</dt><dd><ValueTree value={item} field={key} preparedQuality={preparedQuality}/></dd></div>)}</dl>
 }
 return <span>{typeof value==='boolean'?t(value?'是':'否'):typeof value==='string'&&enumFields.has(field)?enumValues[value]?.[language]??t(value):String(value)}</span>
}
export default function ReportPreview({sections,ready,projectId,source}:{sections:{key:string;title:string;content:unknown}[];ready:boolean;projectId?:string;source?:DatasetAnalysisSource}){
 const {t}=useI18n()
 const preparedQuality=sections.some(section=>section.key==='processing'&&Array.isArray(section.content)&&section.content.some(value=>object(value)&&[2,3].includes(Number(value.schema_version))))
 return <div className="report-preview"><h4>{t('九类报告内容预览')}</h4><p className="muted">{t('按章节展开核对来源、质量、方法与结果；此处只展示冻结内容。')}</p>{!ready&&<p className="warning-panel">{t('图表或解释尚未齐备，自动整理将等待明确绑定的成果。')}</p>}{sections.map(section=><details key={section.key}><summary><strong>{section.title}</strong><span>{Array.isArray(section.content)?t('{count} 项记录',{count:section.content.length}):t('查看已保存内容')}</span></summary>{section.key==='processing'&&Array.isArray(section.content)&&section.content.some(value=>object(value)&&[2,3].includes(Number(value.schema_version)))?section.content.map((value,index)=>object(value)&&[2,3].includes(Number(value.schema_version))?<QualityProcessingPreview key={index} value={value} projectId={projectId} source={source}/>:<ValueTree key={index} value={value}/>):<ValueTree value={section.content} preparedQuality={preparedQuality}/>}</details>)}</div>
}
