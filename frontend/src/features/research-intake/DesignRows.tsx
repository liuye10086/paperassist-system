import { useI18n } from '../../shared/i18n'
import type { Content, Declaration } from './contracts'
import DeclaredField from './DeclaredField'
import type { MaterialSource } from './MaterialReferences'

type Row = Record<string, unknown>
type Field = [key: string, label: string, declared?: boolean]
type Kind = 'experiments' | 'groups' | 'samples' | 'comparisons'
const specs: Record<Kind, {title: string; prefix: string; limit: number; fields: Field[]}> = {
  experiments: {title:'实验', prefix:'experiment', limit:50, fields:[['id','实验标识'],['data_type','数据类型'],['species','物种',true],['tissue','组织',true],['model','模型',true],['technology','技术',true],['reference','参考',true],['processing_stage','处理阶段',true],['source','实验来源',true]]},
  groups: {title:'样本分组', prefix:'group', limit:500, fields:[['id','分组标识'],['experiment_id','所属实验'],['name','分组名称'],['abbreviation','缩写'],['meaning','含义']]},
  samples: {title:'样本信息', prefix:'sample', limit:10000, fields:[['id','样本标识'],['experiment_id','所属实验'],['group_id','所属分组'],['donor','供体或个体',true],['tissue','组织',true],['section','切片',true],['batch','批次',true],['time','时间',true],['dose','剂量',true],['sex','性别',true],['age','年龄',true]]},
  comparisons: {title:'比较方向与阈值', prefix:'comparison', limit:100, fields:[['id','比较标识'],['experiment_id','所属实验'],['group_id','比较组'],['reference_group_id','参照组'],['positive_meaning','正值含义',true],['effect_threshold','效应量阈值',true],['p_value','P 值阈值',true],['adjusted_p_value','校正 P 阈值',true],['standard_source','标准来源',true]]},
}

type Props = {
  kind: Kind; value: Content; sources: MaterialSource[]; disabled: boolean; readOnly?: boolean
  page: number; setPage: (page: number) => void; onChange: (content: Content) => void
}

export default function DesignRows({kind, value, sources, disabled, readOnly, page, setPage, onChange}: Props) {
  const {t} = useI18n()
  const spec = specs[kind]
  const items = (value[kind] ?? []) as Row[]
  const groups = (value.groups ?? []) as Row[]
  const experiments = (value.experiments ?? []) as Row[]
  const pages = Math.max(1, Math.ceil(items.length / 5))
  const current = Math.min(page, pages)
  const offset = (current - 1) * 5
  const update = (index: number, patch: Row) =>
    onChange({...value, [kind]:items.map((row, i) => i === index ? {...row, ...patch} : row)})
  function add() {
    const ids = new Set(items.map(item => item.id))
    let index = items.length + 1
    while (ids.has(spec.prefix + '_' + index)) index++
    const row: Row = {id:spec.prefix + '_' + index}
    if (kind === 'groups') Object.assign(row, {experiment_id:experiments[0]?.id ?? groups[0]?.experiment_id ?? 'experiment_1', name:''})
    if (kind === 'samples') Object.assign(row, {experiment_id:groups[0]?.experiment_id ?? '', group_id:groups[0]?.id ?? ''})
    if (kind === 'comparisons') Object.assign(row, {experiment_id:'', group_id:'', reference_group_id:''})
    if (kind === 'experiments') {
      row.id = groups.find(group => !ids.has(group.experiment_id))?.experiment_id ?? row.id
      row.data_type = ''
    }
    onChange({...value, [kind]:[...items, row]})
    setPage(Math.ceil((items.length + 1) / 5))
  }
  function display(item: Row, field: Field) {
    const raw = item[field[0]]
    const declared = field[2] ? raw as Declaration | undefined : undefined
    if (field[2]) return declared?.value ?? t(declared?.state === 'not_applicable' ? '不适用' : '待确认')
    return String(raw || '—')
  }
  return <section className="questionnaire-section">
    <h3>{t(spec.title)} · {items.length}</h3>
    {readOnly && <p>{t('样本分组和样本信息由客户填写。需要更正时，请向客户请求补充资料。')}</p>}
    <div className="intake-rows">{items.slice(offset, offset + 5).map((item, i) => {
      const index = offset + i
      const source = sources.find(s => s.kind === 'file' ? s.id === item.file_id : s.id === item.bio_dataset_version_id)
      if (readOnly) return <dl key={index} className="analyst-project-info">
        {spec.fields.map(field => <div key={field[0]}><dt>{t(field[1])}</dt><dd>{display(item, field)}</dd></div>)}
        {(item.file_id || item.bio_dataset_version_id) ? <div><dt>{t('来源文件或数据集版本')}</dt><dd>{source?.name ?? String(item.file_id || item.bio_dataset_version_id)}</dd></div> : null}
      </dl>
      return <fieldset disabled={disabled} key={index}><legend>{t(spec.title)} {index + 1}</legend>
        {spec.fields.map(([field, label, declared]) => {
          if (declared) return <DeclaredField key={field} label={label} disabled={disabled} value={item[field] as Declaration | undefined}
            onChange={v => update(index, {[field]:v})}/>
          if (kind === 'samples' && field === 'group_id' && groups.length) {
            return <label key={field}>{t(label)}<select value={String(item.group_id ?? '')} onChange={e => {
              const group = groups.find(g => g.id === e.target.value)
              update(index, {group_id:e.target.value, experiment_id:group?.experiment_id ?? ''})
            }}><option value="">{t('请选择')}</option>{groups.map(g =>
              <option key={String(g.id)} value={String(g.id)}>{String(g.name || g.id)} · {String(g.id)}</option>)}</select></label>
          }
          return <label key={field}>{t(label)}<input maxLength={field === 'id' || field.endsWith('_id') ? 128 : 500}
            value={String(item[field] ?? '')} onChange={e => update(index, {[field]:e.target.value})}/></label>
        })}
        {kind === 'samples' && <label>{t('来源文件或数据集版本')}<select value={item.file_id ? 'file:'+item.file_id : item.bio_dataset_version_id ? 'bio:'+item.bio_dataset_version_id : ''}
          onChange={e => {
            const selected = sources.find(s => s.kind+':'+s.id === e.target.value)
            update(index,{file_id:selected?.kind === 'file' ? selected.id : null, bio_dataset_version_id:selected?.kind === 'bio' ? selected.id : null})
          }}><option value="">{t('待确认')}</option>{sources.map(s => <option key={s.kind+s.id} value={s.kind+':'+s.id}>{s.name}</option>)}</select></label>}
        <button type="button" onClick={() => onChange({...value,[kind]:items.filter((_, j) => j !== index)})}>{t('移除此行')}</button>
      </fieldset>
    })}</div>
    {pages > 1 && <div className="intake-pagination"><button type="button" disabled={current === 1} onClick={() => setPage(current - 1)}>{t('上一页')}</button>
      <span>{current} / {pages}</span><button type="button" disabled={current === pages} onClick={() => setPage(current + 1)}>{t('下一页')}</button></div>}
    {!readOnly && <button type="button" disabled={disabled || items.length >= spec.limit} onClick={add}>{t('添加{item}',{item:t(spec.title)})}</button>}
  </section>
}
