import { useI18n } from '../../shared/i18n'
import type { ArtifactNavigation } from './analysisViews'
import './projectResults.css'

const views = [
  ['list', '成果列表'],
  ['research-figures', '研究单图与组图'],
  ['research-reports', '分析报告与成果包'],
  ['layout', '排版导出记录'],
] as const

export default function ProjectResultNavigation({ navigation, onNavigate }: { navigation: ArtifactNavigation; onNavigate: (next: ArtifactNavigation) => void }) {
  const { t } = useI18n()
  const current = navigation.view === 'detail' ? 'list' : navigation.view
  return <nav className="project-result-nav" aria-label={t('成果分类')}>
    {views.map(([view, label]) => <button type="button" key={view} aria-current={current === view ? 'page' : undefined} onClick={() => {
      if (navigation.view !== view) onNavigate({ view, artifactId: '', kind: '', page: view === 'list' ? navigation.page : 1 })
    }}>{t(label)}</button>)}
  </nav>
}
