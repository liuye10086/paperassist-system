import {useI18n} from '../../shared/i18n'
import type {AnalysisNavigation} from './analysisViews'
import type {Version} from '../research-intake/contracts'
import type {ProjectFile} from '../files/fileLibraryApi'
import {analysisScopes,type EntryImport} from './analysisEntryState'

export default function AnalysisEntryContext({navigation,version,current,loading,error,onReload,onNavigate}:{navigation:AnalysisNavigation;version:Version|null;current:Version|null;loading:boolean;error:string;files:ProjectFile[];filesUnknown:boolean;imports:EntryImport[];onReload:()=>void;onNavigate:(n:AnalysisNavigation)=>void;onFile:(id:string)=>void}){
 const {t,locale}=useI18n(),entry=navigation.entry
 if(!entry)return null
 const scope=version&&analysisScopes(version).find(s=>s.id===entry.scopeItemId)
 return <section className="analysis-entry-context" aria-label={t('本次需求上下文')}>
  {loading&&<p role="status">{t('正在读取固定需求版本……')}</p>}
  {error&&<p role="alert">{t('固定需求读取失败，请重试。')} <button type="button" onClick={onReload}>{t('重新读取需求')}</button></p>}
  {version&&!scope&&<p role="alert">{t('该需求版本中没有此分析条目，请重新选择。')}</p>}
  {scope&&version&&<strong>{scope.title} · {t('提交时间')} <time dateTime={version.created_at}>{new Date(version.created_at).toLocaleString(locale)}</time></strong>}
  {current&&version&&current.id!==version.id&&current.version>version.version&&<p role="status">{t('已有更新的需求版本，当前仍保留原入口。切换前请核对现有草稿。')}</p>}
  <button type="button" className="button-quiet" onClick={()=>onNavigate({view:'overview',fileId:''})}>{t('查看当前需求清单')}</button>
 </section>
}
