import {useI18n} from '../../shared/i18n'
import type {Source} from './literatureApi'

export default function SavedSearchContext({context}:{context:Source['source_context']}){
 const {t}=useI18n()
 return context&&(context.label.trim()||context.text.trim())?<div><p>{t('保存的检索背景')}</p>{context.label.trim()&&<p className="literature-original">{context.label}</p>}{context.text.trim()&&<p className="literature-original">{context.text}</p>}</div>:null
}
