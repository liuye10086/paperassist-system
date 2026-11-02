import {useI18n} from '../../shared/i18n'
import ManuscriptImage from './ManuscriptImage'
import type {InventoryItem} from './writingLiveTypes'
import {imageLocation,resolveReviewFigure,type ReviewFigure} from './languageImageLocation'
export default function LanguageItemLocation({item,figures=[],inventory=[]}:{item:InventoryItem;figures?:ReviewFigure[];inventory?:InventoryItem[]}){
 const {t}=useI18n()
 if(item.kind!=='image'&&item.kind!=='figure_text'&&!imageLocation(item.location).startsWith('image:'))return null
 const figure=resolveReviewFigure(item,figures)
 const location=imageLocation(item.location)
 const roots=[...new Set(inventory.filter(i=>i.kind==='image').map(i=>i.location))]
 const root=roots.find(root=>item.location===root||item.location.startsWith(root+':'))
 const imageIndex=root?roots.indexOf(root)+1:undefined
 const field=figure&&location.startsWith('image:'+figure.id+':')?location.slice(('image:'+figure.id+':').length):''
 const fieldLabel=field?({title:'图标题',caption:'图注',x_label:'X 轴标签',y_label:'Y 轴标签'}[field]??(field.startsWith('series.')?'系列文字':field.startsWith('tick.')?'刻度文字':field.startsWith('sample_count.')?'样本量文字':'图内文字项目')):''
 return <div className="language-image-location">{figure?<><p>{figure.number?`${t('图')} ${figure.number}`:t('未编号图像')} · {figure.title}</p>{fieldLabel&&<p>{t(fieldLabel)}</p>}{figure.preview_url&&<details><summary>{t('查看对应图像')}</summary><ManuscriptImage url={figure.preview_url} title={figure.title}/></details>}</>:<><p role="status">{t('图像定位待确认；请返回当前固定版本的图表清单核对。')}</p>{imageIndex&&<p>{t('本次清单中的第 {number} 个图像项目（不是图号）',{number:imageIndex})}</p>}{figures.length>0&&<details><summary>{t('查看当前固定版本的图表清单')}</summary><p>{t('以下仅供逐图核对，尚未确认本项目对应哪张图。')}</p><ul>{figures.map((f,index)=><li key={`${f.id}:${index}`}>{f.number?`${t('图')} ${f.number}`:t('未编号图像')} · {f.title}{f.preview_url&&<ManuscriptImage url={f.preview_url} title={f.title}/>}</li>)}</ul></details>}</>}</div>
}
