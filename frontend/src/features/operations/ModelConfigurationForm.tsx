import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import {businessNames,modelBusinesses,type ConfigBundle,type ConfigCatalog,type ModelBusiness,type ModelEntry} from './configurationTypes'
import {NumberField,ReadonlyField} from './ConfigurationFields'
export default function ModelConfigurationForm({bundle,catalog,onChange}:{bundle:ConfigBundle;catalog:ConfigCatalog;onChange:(bundle:ConfigBundle)=>void}){
 const{t}=useI18n(),[business,setBusiness]=useState<ModelBusiness>('writing'),entry=bundle.models[business]
 function update(value:ModelEntry|null){onChange({...bundle,models:{...bundle.models,[business]:value}})}
 const installed=catalog.default_bundle.models[business],constraint=catalog.installed.business_constraints[business]
 const policy=entry?.execution.policy,readonly=business==='literature'&&catalog.field_readonly['models.literature.execution.policy']!==false
 const setPolicy=(change:Partial<NonNullable<typeof policy>>)=>{if(entry&&policy)update({...entry,execution:{...entry.execution,policy:{...policy,...change}}})}
 const setExecution=(change:Partial<ModelEntry['execution']>)=>{if(entry)update({...entry,execution:{...entry.execution,...change}})}
 const sourceNames={installed_code:'已安装代码',deployment_policy:'部署政策',synthetic_fixture:'合成验收样例'}
 return <section><p>{t('部署限制与用户授权继续优先，后台配置不能解除。')}</p><p>{t('真实调用关闭')} · {t('真实连通未测试')}</p><label>{t('配置业务')}<select value={business} onChange={e=>setBusiness(e.target.value as ModelBusiness)}>{modelBusinesses.map(key=><option key={key} value={key}>{t(businessNames[key])}</option>)}</select></label>
 {!entry?<><p>{t('此业务尚未配置。')}</p>{installed?<button type="button" onClick={()=>update(structuredClone(installed))}>{t('使用已安装部署基线')}</button>:<p>{t('尚无已登记部署基线，不能创建执行政策。')}</p>}</>:<>
 {business!=='writing'&&<button type="button" onClick={()=>update(null)}>{t('清除此业务配置')}</button>}
 {readonly&&<p>{t('文献供应商政策固定，只允许收紧输入与任务预算。')}</p>}
 <fieldset disabled={readonly} className="configuration-fields"><legend>{t(businessNames[business])}</legend>
 <label>{t('模型名称')}<select value={policy!.model} onChange={e=>setPolicy({model:e.target.value,price:{...policy!.price,model:e.target.value}})}>{(constraint?.model?[constraint.model]:catalog.installed.models).map(model=><option key={model}>{model}</option>)}</select></label>
 <ReadonlyField label="提示词版本" value={policy!.prompt_version}/><ReadonlyField label="输出格式" value={policy!.output_format}/>
 <NumberField label="输出 Token 上限" min={1} max={installed?.execution.policy.max_output_tokens??policy!.max_output_tokens} value={policy!.max_output_tokens} onChange={n=>setPolicy({max_output_tokens:n})}/>
 <NumberField label="模型超时（秒）" min={1} max={3600} value={policy!.timeout_seconds} onChange={n=>setPolicy({timeout_seconds:n})}/>
 <label className="configuration-check"><input type="checkbox" disabled={business!=='plot'} checked={policy!.tools.includes('code_interpreter')} onChange={e=>setPolicy({tools:e.target.checked?['code_interpreter']:[]})}/>{t('允许代码解释工具')}<small>{t('工具由已安装业务约束限制。')}</small></label>
 <label>{t('价格版本')}<input required maxLength={128} pattern="[A-Za-z0-9_.:\-]+" value={policy!.price.version} onChange={e=>setPolicy({price:{...policy!.price,version:e.target.value}})}/></label>
 {([['input_micro_usd_per_million','输入价格（微美元/百万 Token）'],['cached_input_micro_usd_per_million','缓存输入价格（微美元/百万 Token）'],['output_micro_usd_per_million','输出价格（微美元/百万 Token）']] as const).map(([key,label])=><NumberField key={key} label={label} value={policy!.price[key]} onChange={n=>setPolicy({price:{...policy!.price,[key]:n}})}/>)}
 <label className="configuration-check"><input type="checkbox" checked={policy!.price.cache_write_micro_usd_per_million!==null} onChange={e=>setPolicy({price:{...policy!.price,cache_write_micro_usd_per_million:e.target.checked?0:null}})}/>{t('缓存写价已配置')}</label>
 {policy!.price.cache_write_micro_usd_per_million!==null&&<NumberField label="缓存写入价格（微美元/百万 Token）" value={policy!.price.cache_write_micro_usd_per_million} onChange={n=>setPolicy({price:{...policy!.price,cache_write_micro_usd_per_million:n}})}/>}
 </fieldset>
 <div className="configuration-fields"><NumberField label="输入 Token 预算" min={1} max={installed?.execution.input_token_allowance??entry.execution.input_token_allowance} value={entry.execution.input_token_allowance} onChange={n=>setExecution({input_token_allowance:n})}/><NumberField label="任务预算上限（微美元）" max={installed?.execution.task_limit_micro_usd??entry.execution.task_limit_micro_usd} value={entry.execution.task_limit_micro_usd} onChange={n=>setExecution({task_limit_micro_usd:n})}/>
 {business==='plot'&&<><NumberField label="工具预留（微美元）" min={1} value={entry.execution.tool_reserve_micro_usd??1} onChange={n=>setExecution({tool_reserve_micro_usd:n})}/><label>{t('工具预留版本')}<input required maxLength={128} value={entry.execution.tool_reserve_version??''} onChange={e=>setExecution({tool_reserve_version:e.target.value})}/></label></>}
 <label>{t('价格来源')}<select value={entry.price_source} onChange={e=>update({...entry,price_source:e.target.value as ModelEntry['price_source']})}>{Object.entries(sourceNames).map(([key,label])=><option key={key} value={key}>{t(label)}</option>)}</select></label>
 <label>{t('价格核实状态')}<select value={entry.price_status} onChange={e=>update({...entry,price_status:e.target.value as ModelEntry['price_status'],price_verified_on:null})}><option value="unverified">{t('来源尚未核实')}</option><option value="synthetic">{t('合成价格')}</option></select></label>
 <label>{t('价格核实日期')}<input type="date" disabled={entry.price_status==='unverified'} value={entry.price_verified_on??''} onChange={e=>update({...entry,price_verified_on:e.target.value||null})}/></label></div>
 </>}
 <div className="configuration-fields"><NumberField label="批次提交上限（次）" min={1} max={6} value={bundle.models.batch_max_posts} onChange={n=>onChange({...bundle,models:{...bundle.models,batch_max_posts:n}})}/><NumberField label="最多纠正次数" max={2} value={bundle.models.max_corrections} onChange={n=>onChange({...bundle,models:{...bundle.models,max_corrections:n}})}/><NumberField label="批次预算上限（微美元）" min={1} max={12000000} value={bundle.models.batch_cap_micro_usd} onChange={n=>onChange({...bundle,models:{...bundle.models,batch_cap_micro_usd:n}})}/></div>
 <ReadonlyField label="登记凭据引用" value={bundle.models.credential?bundle.models.credential.alias+' / '+bundle.models.credential.revision:'没有登记引用'}/><p>{t('只保存登记别名与修订，不接收秘密值。')}</p>
 </section>
}
