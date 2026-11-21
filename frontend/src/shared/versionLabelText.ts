import type { Locale, Params } from './i18n'

type Translate = (source: string, params?: Params) => string

const minuteFormat: Intl.DateTimeFormatOptions = { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }

/** Saved time to the minute, or '' when the value is not a readable time. */
export function versionMinute(value: string, locale: Locale) {
  const time = new Date(value)
  return Number.isNaN(time.getTime()) ? '' : time.toLocaleString(locale, minuteFormat)
}

/** Plain-text form of `VersionLabel` for places that cannot hold markup, such as `<option>`. */
export function versionLabelText(t: Translate, locale: Locale, revision: number, savedAt: string) {
  const time = versionMinute(savedAt, locale)
  return t('第 {revision} 版', { revision }) + (time ? ' · ' + time : '')
}
