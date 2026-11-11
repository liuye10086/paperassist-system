import {useI18n} from '../../shared/i18n'
import {ConfigField, ConfigList, type ConfigProps} from './InsightShared'
import {strings} from './state'

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
    <ConfigList {...props} name="palette" label="配色（逐行 #RRGGBB）"/>
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
