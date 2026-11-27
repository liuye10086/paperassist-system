import { useI18n } from '../../shared/i18n'
import { articleTypes, isLegacySciSettings, journalChoices, type LegacySciContent, type SciSettings } from './sciProjectSettings'

function LegacySciFields({ settings }: { settings: LegacySciContent }) {
  const { t } = useI18n()
  return <>
    {settings.main_results && <><dt>{t('主要结果或结论')}</dt><dd>{settings.main_results}</dd></>}
    {settings.figure_plan.length > 0 && <>
      <dt>{t('图表计划（Figure plan）')}</dt><dd><ol>{settings.figure_plan.map((item, index) =>
        <li key={index}><strong>{item.title}</strong><p>{item.description}</p></li>)}</ol></dd>
    </>}
  </>
}

export function LegacySciHistory({ settings, heading = '原建项资料' }: { settings: LegacySciContent; heading?: string }) {
  const { t } = useI18n()
  if (!settings.main_results && !settings.figure_plan.length) return null
  return <section className="sci-settings-history">
    <h3>{t(heading)}</h3>
    <dl className="sci-settings-summary">
      <LegacySciFields settings={settings} />
    </dl>
  </section>
}

export default function SciSettingsSummary({ settings }: { settings: SciSettings }) {
  const { t } = useI18n()
  const requirements = isLegacySciSettings(settings) ? null : settings
  return <dl className="sci-settings-summary">
    <dt>{t('论文类型')}</dt><dd>{t(articleTypes[settings.article_type])}</dd>
    {requirements && <><dt>{t('拟定论文题目')}</dt><dd>{requirements.proposed_title}</dd></>}
    {settings.target_journal && <><dt>{t('目标期刊')}</dt><dd>{settings.target_journal.name ?? t(journalChoices[settings.target_journal.choice])}</dd></>}
    <dt>{t('关键词')}</dt><dd>{settings.keywords.join(' · ')}</dd>
    {isLegacySciSettings(settings) && <LegacySciFields settings={settings} />}
    {requirements?.article_type === 'research' && requirements.figure_findings.length > 0 && <>
      <dt>{t('主要发现')}</dt><dd>{requirements.figure_findings.map(item => item.finding).join('\n\n')}</dd>
    </>}
  </dl>
}
