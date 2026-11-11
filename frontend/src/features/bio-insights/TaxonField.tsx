import {useI18n} from '../../shared/i18n'
import {Field} from './InsightShared'

const commonSpecies = [
 [9606,'人类'],[10090,'小鼠'],[10116,'大鼠'],[7955,'斑马鱼'],[7227,'黑腹果蝇'],
 [6239,'秀丽隐杆线虫'],[3702,'拟南芥'],[4932,'酿酒酵母'],[9031,'鸡'],[9823,'猪'],[9913,'牛'],
] as const

export default function TaxonField({label,value,onChange,registered=[]}:{
 label:string;value?:number|null;onChange:(taxon:number|null)=>void;registered?:number[]
}) {
 const {t} = useI18n()
 const options = new Map<number,string>(commonSpecies)
 for (const taxon of [...registered,value]) {
  if (typeof taxon==='number'&&Number.isInteger(taxon)&&taxon>0&&taxon<=2147483647&&!options.has(taxon)) options.set(taxon,'已登记物种')
 }
 return <Field label={label} value={value||''} onChange={next=>onChange(next?Number(next):null)}>
  <option value="">{t('请选择物种')}</option>
  {[...options].map(([taxon,name])=><option key={taxon} value={taxon}>{t('{species}（NCBI Taxonomy {taxon}）',{species:t(name),taxon})}</option>)}
 </Field>
}
