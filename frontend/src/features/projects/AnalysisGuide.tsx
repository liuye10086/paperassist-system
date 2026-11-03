import { useI18n } from '../../shared/i18n'
import { projectBase, useResearchRead } from '../research-results/api'
import type { Intake } from '../research-intake/contracts'
import type { AnalysisNavigation } from './analysisViews'

export default function AnalysisGuide({ projectId, active, onNavigate, onRequirements }: {
  projectId: string; active: boolean; onNavigate: (view: AnalysisNavigation['view']) => void; onRequirements?: () => void
}) {
  const { t } = useI18n()
  const read = useResearchRead<Intake>(`${projectBase(projectId)}/research-intake`, active)
  const content = read.data?.current_requirement?.content
  const scopes = (Array.isArray(content?.scope_items) ? content.scope_items : []) as { id: string; title: string; status: string; delivery_kind: string }[]
  const selected = scopes.filter(item => item.delivery_kind === 'analysis' && item.status !== 'not_included')
  return <div className="analysis-guide">
    <header className="analysis-overview-heading"><h2>{t('执行分析')}</h2></header>
    <section className="analysis-choice-summary" aria-label={t('已保存的分析需求')}><h3>{t('本次想得到的成果')}</h3>
      {read.loading && <p role="status">{t('正在读取已保存的需求……')}</p>}
      {read.error ? <p role="alert">{t('需求读取失败，请重试。')} <button type="button" onClick={read.refresh}>{t('重新读取需求')}</button></p>
        : selected.length ? <ul>{selected.map(item => <li key={item.id}>{t(item.title)}</li>)}</ul>
          : !read.loading && <p>{t('还没有勾选分析项目。你也可以直接从下方的数据类型开始。')}</p>}
      {onRequirements && <button type="button" className="button-quiet" onClick={onRequirements}>{t('调整分析需求')}</button>}
    </section>
    <section className="analysis-overview-heading"><h3>{t('选择分析类型')}</h3></section>
    <div className="analysis-entry-grid">
      {([
        ['setup', '表格数据与统计', '适合实验指标、临床、行为学等表格；选择文件与分组后分析。'],
        ['bio-datasets', '组学与生信数据', '适合转录组、单细胞、空间、蛋白组等；先核对数据集与样本。'],
        ['bio-insights', '差异、通路与候选筛选', '基于已准备的数据开展组间比较、功能分析与候选筛选。'],
      ] as const).map(([view, title, help]) => <button key={view} type="button" onClick={() => onNavigate(view)}><strong>{t(title)}</strong><span>{t(help)}</span><span aria-hidden="true">→</span></button>)}
    </div>
    <section className="analysis-tools"><h3>{t('已有分析与工具')}</h3><div className="analysis-tool-grid">{([
      ['profile', '数据概况', '查看数据质量和字段分布。'],
      ['plan', '分析方案', '核对研究问题、分析方法与方案。'],
      ['statistics', '统计结果', '查看当前分析结果，按需要继续计算。'],
      ['figure', '图表工作台', '根据已有结果出图和调整样式。'],
      ['report', '报告与集合', '组织已有结果并导出报告。'],
      ['research-findings', '研究发现与核对', '核对研究结果，准备后续论文材料。'],
      ['research-request', '补充统计分析方案', '从研究问题或已有材料建立方案，并核对缺项。'],
    ] as const).map(([view, title, help]) => <button key={view} type="button" onClick={() => onNavigate(view)}><strong>{t(title)}</strong><span>{t(help)}</span></button>)}</div></section>
  </div>
}
