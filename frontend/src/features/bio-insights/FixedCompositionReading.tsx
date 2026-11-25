import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import {projectBase} from './api'
import type {Result} from './contracts'
import {useInsightRead} from './hooks'
import {Paging, ReadState} from './InsightShared'

type Preview = {
 schema_version: 1
 project_id: string
 result_version_id: string
 manifest_sha256: string
 table_sha256: string
 page: number
 page_size: number
 total: number
 design: {denominator:string;numerator:string;n_denominator:number;n_numerator:number}
 runtime: {speckle?:string}
 rows: {category:string;label_id:string;mean_proportion_denominator:string;mean_proportion_numerator:string;
  proportion_difference:string;p_adjust:string;inference_status:'tested'|'not_computable';reason:string}[]
}

const pageSize = 50

export default function FixedCompositionReading({projectId,result,active}: {projectId:string;result:Result;active:boolean}) {
 const {t} = useI18n()
 const [opened,setOpened] = useState(false)
 const [page,setPage] = useState(1)
 const endpoint = `${projectBase(projectId)}/bio-insight-results/${encodeURIComponent(result.id)}/composition-preview`
 const read = useInsightRead<Preview>(`${endpoint}?page=${page}&page_size=${pageSize}`,active&&opened,true)
 const data = active&&!read.loading&&!read.error ? read.data : null
 const member = result.members.find(row => row.key === 'composition_results')
 const preview = data?.schema_version === 1 && data.project_id === projectId && data.result_version_id === result.id
  && data.manifest_sha256 === result.manifest_sha256 && data.table_sha256 === member?.sha256
  && data.page === page && data.page_size === pageSize && data.design && Array.isArray(data.rows) ? data : null
 function open() {
  setOpened(true)
  if(opened) read.refresh()
 }
 return <section className="analysis-detail" aria-label={t('固定组成解读')}>
  <button type="button" aria-expanded={opened} disabled={read.loading} onClick={open}>{t('查看固定组成解读')}</button>
  {opened&&<ReadState {...read}/>}
  {opened&&data&&!preview&&<p role="alert">{t('读取的组成结果与当前固定版本不符。')}</p>}
  {opened&&preview&&<>
   <p>Propeller{preview.runtime?.speckle&&` ${preview.runtime.speckle}`} · {t('{denominator}（{referenceCount} 名供者）对照 {numerator}（{comparisonCount} 名供者）',{
    denominator:preview.design.denominator,referenceCount:preview.design.n_denominator,
    numerator:preview.design.numerator,comparisonCount:preview.design.n_numerator,
   })}</p>
   <p>{t('差值为分子组减参照组。相对比例的变化不能证明绝对丰度变化或因果关系。')}</p>
   <div className="field-table-scroll"><table className="field-table" aria-label={t('固定组成比例与检验')}>
    <thead><tr><th scope="col">{t('细胞类别')}</th><th scope="col">{preview.design.denominator}</th>
     <th scope="col">{preview.design.numerator}</th><th scope="col">{t('比例差值')}</th>
     <th scope="col">{t('BH 校正 P')}</th><th scope="col">{t('检验状态')}</th></tr></thead>
    <tbody>{preview.rows.map(row=><tr key={JSON.stringify([row.category,row.label_id])}>
     <th scope="row">{row.label_id||row.category}</th><td>{row.mean_proportion_denominator}</td>
     <td>{row.mean_proportion_numerator}</td><td>{row.proportion_difference}</td><td>{row.p_adjust||'—'}</td>
     <td>{t(row.inference_status==='tested'?'已计算':'不可计算')}{row.reason&&<> · <span>{row.reason}</span></>}</td>
    </tr>)}</tbody>
   </table></div>
   <Paging page={preview.page} total={preview.total} size={pageSize} onPage={setPage}/>
  </>}
 </section>
}
