import { useI18n } from './i18n'
import { versionMinute } from './versionLabelText'
import './versionLabel.css'

type Props = {
  /** Business revision as returned by the server (e.g. `delivery_snapshots.revision`); never renumbered. */
  revision: number
  /** ISO time the version was saved or published. */
  savedAt: string
  /** Marks the version currently in use. */
  current?: boolean
}

// “第 {revision} 版 · {time}” / “Version {revision} · {time}”, plus “当前” / “Current”.
// Inside `<option>`, use `versionLabelText()` from './versionLabelText' for the same text.
export default function VersionLabel({ revision, savedAt, current = false }: Props) {
  const { t, locale } = useI18n()
  const time = versionMinute(savedAt, locale)
  return <span className="version-label">
    {t('第 {revision} 版', { revision })}
    {time && <> · <time dateTime={savedAt}>{time}</time></>}
    {current && <span className="version-label-current">{t('当前')}</span>}
  </span>
}
