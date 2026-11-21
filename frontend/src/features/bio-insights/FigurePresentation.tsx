import {useI18n} from '../../shared/i18n'
import {ConfigField, ConfigList, Field, Toggle, type ConfigProps} from './InsightShared'
import {number,strings} from './state'

type DisplayProps=Pick<ConfigProps,'config'|'onChange'>
type PlotSize={width_inches:number;height_inches:number;dpi:number}

export function SingleCellPlotSize({config,onChange,composition=false}:DisplayProps&{composition?:boolean}) {
  const {t}=useI18n()
  const size=config.plot_size as PlotSize|undefined
  return <fieldset><legend>{t('PNG 图件尺寸')}</legend>
    <Toggle label="自定义 PNG 尺寸" value={!!size} onChange={enabled=>{
      const next={...config}
      if(enabled) next.plot_size={width_inches:composition?7:8,height_inches:5,dpi:composition?140:180}
      else delete next.plot_size
      onChange(next)
    }}/>
    {size?<div className="insight-grid">
      {([['width_inches','宽度（英寸）',2,20,.1],['height_inches','高度（英寸）',2,20,.1],
         ['dpi','分辨率（DPI）',72,600,1]] as const).map(([key,label,min,max,step])=>
        <Field key={key} label={label} type="number" value={size[key]} min={min} max={max} step={step}
          onChange={v=>onChange({...config,plot_size:{...size,[key]:Number(v)}})}/>)}
    </div>:<p>{t(composition?'默认根据供者与条件的组合数调整宽度，高 5 英寸，140 DPI。':'默认宽 8 英寸、高 5 英寸，180 DPI。')}</p>}
  </fieldset>
}

export function RegulationTopN({config,onChange,fallback=20}:DisplayProps&{fallback?:number}) {
  return <Field label="显示调控边 Top N" type="number" value={number(config.regulation_top_n,fallback)}
    min={1} max={500} onChange={value=>onChange({...config,regulation_top_n:Number(value)})}/>
}

export default function FigurePresentation({config,onChange,topLabel,topMax=500}:Pick<ConfigProps,'config'|'onChange'>&{
  topLabel?:string
  topMax?:number
}) {
  const {t} = useI18n()
  const props = {config,onChange}
  const formats = strings(config.formats)
  return <>
    <div className="insight-grid">
      <ConfigField {...props} name="title" label="图标题"/>
      {topLabel&&<ConfigField {...props} name="top_n" label={topLabel} type="number" min={1} max={topMax}/>}
      <ConfigField {...props} name="width_inches" label="宽度 inches" type="number" min={2} max={20} step={0.5}/>
      <ConfigField {...props} name="height_inches" label="高度 inches" type="number" min={2} max={20} step={0.5}/>
      <ConfigField {...props} name="dpi" label="像素 DPI" type="number" min={72} max={600}/>
    </div>
    {config.figure_type==='volcano'&&<>
      <Field label="着色 q 阈值" type="number" min={0} max={1} step="any" value={number(config.q_threshold,.05)}
        onChange={value=>onChange({...config,q_threshold:Number(value)})}/>
      <Field label="着色最小绝对效应" type="number" min={0} max={1000000} step="any" value={number(config.minimum_absolute_effect,1)}
        onChange={value=>onChange({...config,minimum_absolute_effect:Number(value)})}/>
      <p>{t('两个阈值只用于给固定结果中的点着色，所有可绘制的点均保留。')}</p>
    </>}
    {config.figure_type==='enrichment'&&<Field label="展示条目最大 q／FDR（留空显示全部）" type="number" min={0} max={1} step="any"
      value={typeof config.q_threshold==='number'?config.q_threshold:''} onChange={value=>{
        const next={...config}
        if(value==='') delete next.q_threshold
        else next.q_threshold=Number(value)
        onChange(next)
      }}/>}
    {config.figure_type==='topic_genie3'&&<RegulationTopN {...props} fallback={Math.min(20,number(config.top_n,20))}/>}
    {config.figure_type==='topic_cellchat'&&<Field label="通讯热图色阶" value={String(config.cellchat_colormap??'viridis')}
      onChange={value=>onChange({...config,cellchat_colormap:value})}>
      {['viridis','magma','cividis','custom'].map(value=><option key={value} value={value}>{value==='custom'?t('自定义配色'):value}</option>)}
    </Field>}
    {(config.figure_type!=='topic_cellchat'||config.cellchat_colormap==='custom')&&<ConfigList {...props} name="palette" label="配色（逐行 #RRGGBB）"/>}
    {formats.includes('pdf')&&<p role="alert">
      {t('PDF 图件不再支持，请移除 PDF 后继续；其他草稿内容保留。')}
      <button type="button" onClick={()=>onChange({...config,formats:formats.filter(format=>format!=='pdf')})}>{t('移除 PDF 格式')}</button>
    </p>}
    <fieldset><legend>{t('导出格式')}</legend>
      {['png','tiff','svg'].map(format=><label key={format}>
        <input type="checkbox" checked={formats.includes(format)} onChange={event=>onChange({
          ...config, formats:event.target.checked?[...formats,format]:formats.filter(item=>item!==format),
        })}/>{format.toUpperCase()}
      </label>)}
    </fieldset>
  </>
}
