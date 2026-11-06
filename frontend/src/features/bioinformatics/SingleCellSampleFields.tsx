export type CellSampleDraft={sample_id:string;library_id:string;donor:string;batch:string;group:string;species_taxon_id?:string;reference_id?:string;reference_version?:string;library_chemistry?:string;pair_id?:string;file_ids:string[]}
export type CellSample={sample_id:string;library_id:string;donor:string|null;batch:string|null;group:string|null;species_taxon_id:number|null;reference_id:string|null;reference_version:string|null;library_chemistry:string|null;pair_id:string|null;file_ids:string[]}

export function cellSamplesBody(rows:CellSampleDraft[],selected:string[]):CellSample[]|null{
 if(!rows.length)return []
 const all=rows.flatMap(row=>row.file_ids)
 if(all.length!==selected.length||new Set(all).size!==all.length||all.some(id=>!selected.includes(id)))return null
 if(new Set(rows.map(row=>row.library_id.trim())).size!==rows.length)return null
 if(rows.some(row=>!row.sample_id.trim()||!row.file_ids.length||!/^[A-Za-z0-9_.-]{1,100}$/.test(row.library_id.trim())))return null
 if(rows.some(row=>row.species_taxon_id?.trim()&&(!/^[1-9]\d*$/.test(row.species_taxon_id.trim())||!Number.isSafeInteger(Number(row.species_taxon_id)))))return null
 const result=rows.map(row=>({sample_id:row.sample_id.trim(),library_id:row.library_id.trim(),donor:row.donor.trim()||null,batch:row.batch.trim()||null,group:row.group.trim()||null,
  species_taxon_id:row.species_taxon_id?.trim()?Number(row.species_taxon_id):null,reference_id:row.reference_id?.trim()||null,reference_version:row.reference_version?.trim()||null,library_chemistry:row.library_chemistry?.trim()||null,pair_id:row.pair_id?.trim()||null,file_ids:row.file_ids}))
 for(const field of ['species_taxon_id','reference_id','reference_version'] as const)if(new Set(result.map(row=>row[field]).filter(value=>value!==null)).size>1)return null
 const assignments=new Map<string,string>()
 for(const row of result){const value=JSON.stringify([row.donor,row.group]);if(assignments.has(row.sample_id)&&assignments.get(row.sample_id)!==value)return null;assignments.set(row.sample_id,value)}
 return result
}

export default function SingleCellSampleFields({rows,onChange,files}:{rows:CellSampleDraft[];onChange:(rows:CellSampleDraft[])=>void;files:{id:string;filename:string}[]}){
 const update=(index:number,key:keyof Omit<CellSampleDraft,'file_ids'>,value:string)=>onChange(rows.map((row,i)=>i===index?{...row,[key]:value}:row))
 function assign(index:number,id:string,checked:boolean){onChange(rows.map((row,i)=>({...row,file_ids:i===index&&checked?[...row.file_ids.filter(v=>v!==id),id]:row.file_ids.filter(v=>v!==id)})))}
 return <section><h4>样本信息（可选）</h4><p>同一次导入可以包含多个文库。每个文库选择自己的矩阵文件；合并时按基因 ID 对齐，细胞条码保留文库前缀。供者、物种、参考或配对未知可以留空，系统不会推断。</p>
 {rows.map((row,index)=><fieldset key={index}><legend>文库 {index+1}</legend>
 {([['sample_id','样本编号'],['library_id','文库编号'],['donor','供者'],['batch','批次'],['group','分组'],['species_taxon_id','物种 Taxon ID（正整数）'],['reference_id','参考标识'],['reference_version','参考版本'],['library_chemistry','建库方案'],['pair_id','配对编号']] as const).map(([key,label])=><label key={key}>{label} {index+1}<input value={row[key]??''} maxLength={key==='reference_id'||key==='reference_version'||key==='library_chemistry'?200:100} inputMode={key==='species_taxon_id'?'numeric':undefined} onChange={event=>update(index,key,event.target.value)}/></label>)}
 <p>文库编号使用字母、数字、点、下划线或连字符。同一样本的多个文库可以填写相同样本编号。</p>
 {files.map(file=><label key={file.id}><input type="checkbox" checked={row.file_ids.includes(file.id)} onChange={event=>assign(index,file.id,event.target.checked)}/>{file.filename} → 文库 {index+1}</label>)}
 <button type="button" onClick={()=>onChange(rows.filter((_,i)=>i!==index))}>移除文库 {index+1}</button></fieldset>)}
 <button type="button" disabled={rows.length>=10||!files.length} onClick={()=>onChange([...rows,{sample_id:'',library_id:'library'+(rows.length+1),donor:'',batch:'',group:'',file_ids:rows.length?[]:files.map(file=>file.id)}])}>{rows.length?'添加文库':'填写样本信息'}</button>
 {cellSamplesBody(rows,files.map(file=>file.id))===null&&<p role="alert">请填写样本和唯一文库编号，并将每个所选文件分配到一个文库；物种须为正整数，已知物种与参考必须一致，同一样本的供者和分组必须一致。</p>}
 </section>
}
