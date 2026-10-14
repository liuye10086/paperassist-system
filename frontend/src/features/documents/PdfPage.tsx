import { useState } from 'react'
import { useI18n } from '../../shared/i18n'
import type { PdfPage as Page, PdfTable } from './pdfApi'
export function PdfWarnings({ warnings }: { warnings: Page['warnings'] }) {
 const {t}=useI18n()
 const labels:Record<string,string>={no_extractable_text:'此页无可提取文字，当前未进行 OCR，请下载原件核对。',reading_order_candidate:'文字阅读顺序为几何排序候选，多栏内容请核对原件。',table_candidate:'有边框表格为候选结构，请核对原件。',undecoded_characters:'存在未解码的字体字符，请核对原件。'}
 return <ul className="warning-panel">{warnings.map(w=><li key={w.code}>{t(labels[w.code]??'存在提取限制，请核对原件。')} · {w.count}</li>)}</ul>
}
function CandidateTable({table,index,page}:{table:PdfTable;index:number;page:number}) {
 const {t}=useI18n();const [part,setPart]=useState(0)
 const start=part*20+1,end=Math.min(table.rows,start+19)
 return <article className="document-block document-table"><h5>{t('第 {page} 页 · 候选表格 {index}',{page,index})}</h5><p>{t('有边框表格为候选结构，请核对原件。')}</p><p>{t('当前显示第 {start}–{end} 行，共 {total} 行',{start,end,total:table.rows})}</p><div className="field-table-scroll"><table><tbody>{Array.from({length:Math.max(0,end-start+1)},(_,i)=>start+i).map(row=><tr key={row}>{Array.from({length:table.columns},(_,i)=>i+1).map(column=>{const cell=table.cells.find(c=>c.row===row&&c.column===column);return <td key={column}><small>{t('第 {page} 页 · 候选表格 {index} · 第 {row} 行第 {column} 列',{page,index,row,column})}</small><p className="pdf-text">{cell?.text??''}</p></td>})}</tr>)}</tbody></table></div><nav><button disabled={part===0} onClick={()=>setPart(n=>n-1)}>{t('上一页表格行')}</button><button disabled={end>=table.rows} onClick={()=>setPart(n=>n+1)}>{t('下一页表格行')}</button></nav></article>
}
export default function PdfPage({page}:{page:Page}) {
 const {t}=useI18n();const [part,setPart]=useState(0)
 return <section className="pdf-page"><h5>{t('PDF 第 {page} 页',{page:page.page_number})}</h5>{page.text_status==='no_extractable_text'&&<p className="warning-panel">{t('此页无可提取文字，当前未进行 OCR，请下载原件核对。')}</p>}<PdfWarnings warnings={page.warnings}/>{page.text_blocks.slice(part*20,(part+1)*20).map((block,i)=><article className="document-block" key={block.id}><small>{t('第 {page} 页 · 文本块 {index}',{page:page.page_number,index:part*20+i+1})}</small><p className="pdf-text">{block.text}</p></article>)}{page.text_blocks.length>20&&<nav><button disabled={part===0} onClick={()=>setPart(n=>n-1)}>{t('上一页文本块')}</button><span>{part+1}</span><button disabled={(part+1)*20>=page.text_blocks.length} onClick={()=>setPart(n=>n+1)}>{t('下一页文本块')}</button></nav>}{page.tables.map((table,i)=><CandidateTable key={table.id} table={table} index={i+1} page={page.page_number}/>)}</section>
}
