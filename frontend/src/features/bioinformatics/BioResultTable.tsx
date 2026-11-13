import {useBioRead} from './spatialHooks'
import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import {projectBase} from './api'

import type {BioTable} from './spatialContracts'
const columnLabels:Record<string,string>={cluster:'聚类',feature_id:'特征编号',n_group:'组内数量',n_rest:'组外数量',score:'得分',p_value:'p 值',
 q_value:'q 值',effect_log2_normalized:'log₂ 效应',detected_group:'组内检出率',detected_rest:'组外检出率',reason:'原因'}
export default function BioResultTable({projectId,processedId,tableKey,title,onSelectGene}:{projectId:string;processedId:string;tableKey:string;title?:string;onSelectGene?:(id:string)=>void}){
 const {t}=useI18n(),[page,setPage]=useState(1),[query,setQuery]=useState(''),[search,setSearch]=useState(''),[cluster,setCluster]=useState(''),[filter,setFilter]=useState(''),[sort,setSort]=useState(''),[sortColumn,setSortColumn]=useState(''),[direction,setDirection]=useState('asc'),[order,setOrder]=useState('asc')
 const read=useBioRead<BioTable>(`${projectBase(projectId)}/bio-processed-datasets/${encodeURIComponent(processedId)}/tables/${encodeURIComponent(tableKey)}?page=${page}&page_size=50${search?'&query='+encodeURIComponent(search):''}${filter?'&cluster='+encodeURIComponent(filter):''}${sortColumn?'&sort_by='+encodeURIComponent(sortColumn)+'&order='+order:''}`),data=read.value
 const cell=(v:unknown)=>v===null||v===undefined||v===''?'NA':typeof v==='object'?JSON.stringify(v):String(v)
 const pages=data?Math.max(1,Math.ceil(data.total/data.page_size)):1
 return <section className="bio-result-table">
  {!title&&<div className="bio-result-toolbar">
   <h3>{tableKey}</h3>
   {data&&<button type="button" onClick={read.reload}>{t('重新读取')}</button>}
  </div>}
  <form className="bio-result-toolbar bio-result-filters" onSubmit={e=>{
   e.preventDefault();setSearch(query);setFilter(cluster);setSortColumn(sort);setOrder(direction);setPage(1)
  }}>
   <label><span>{t(title?'基因搜索':'搜索稳定基因 ID 或符号')}</span><input aria-label={t('搜索稳定基因 ID 或符号')} value={query} onChange={e=>setQuery(e.target.value)}/></label>
   {tableKey.includes('marker')&&<label className="bio-cluster-filter">{t('聚类')}<input value={cluster} onChange={e=>setCluster(e.target.value)}/></label>}
   {data&&<>
    <label>{t('排序列')}<select value={sort} onChange={e=>setSort(e.target.value)}>
     <option value="">{t('默认顺序')}</option>{data.columns.map(c=><option key={c} value={c}>{title?t(columnLabels[c]??c):c}</option>)}
    </select></label>
    <label>{t('排序方向')}<select value={direction} onChange={e=>setDirection(e.target.value)}>
     <option value="asc">{t('升序')}</option><option value="desc">{t('降序')}</option>
    </select></label>
   </>}
   <button type="submit">{t('筛选结果表')}</button>
   {title&&<button type="button" onClick={read.reload}>{t('重新读取')}</button>}
  </form>
  <p className="bio-result-note">{t('重名符号保留独立稳定 ID；NA 表示未计算或缺失，0 表示实际零值。')}</p>
  {read.error&&<p role="alert">{t(read.error)}</p>}
  {!data&&!read.error&&<p role="status">{t('正在读取固定版本……')}</p>}
  {data&&<>
   <div className="bio-table-scroll bio-result-data workspace-table-scroll" role="region" aria-label={title??tableKey} tabIndex={0}>
    <table aria-label={title??tableKey}>
     <thead><tr>{data.columns.map(c=><th key={c} scope="col">{title?t(columnLabels[c]??c):c}</th>)}{onSelectGene&&<th scope="col">{t('稳定 ID 选择')}</th>}</tr></thead>
     <tbody>{data.items.map((row,i)=>{
      const id=String(row.feature_id??row.gene_id??row.id??'')
      return <tr key={id+'-'+i}>{data.columns.map(c=>{const value=cell(row[c]);return <td key={c} title={value.length>24?value:undefined}>{value}</td>})}
       {onSelectGene&&<td><button type="button" disabled={!id} aria-label={t('选择 {id}',{id})} onClick={()=>onSelectGene(id)}>{t('选择')}</button></td>}</tr>
     })}</tbody>
    </table>
   </div>
   {!data.items.length&&<p>{t('此筛选条件下暂无结果')}</p>}
   <nav className="analysis-pagination bio-result-pagination" aria-label={t('结果表分页')}>
    <button type="button" disabled={page===1} onClick={()=>setPage(p=>p-1)}>{t('上一页')}</button>
    <span>{t('共 {total} 项 · 第 {page} / {pages} 页',{total:data.total,page,pages})}</span>
    <button type="button" disabled={page>=pages} onClick={()=>setPage(p=>p+1)}>{t('下一页')}</button>
   </nav>
  </>}
 </section>
}
