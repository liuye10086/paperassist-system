import { useSyncExternalStore } from 'react'
import { rootMessages } from './rootMessages'
import { workflowMessages } from './workflowMessages'
import { errorMessages } from './errorMessages'

export type Locale = 'zh-CN' | 'en'
export type Params = Record<string, string | number>
let locale: Locale = 'zh-CN'
const listeners = new Set<() => void>()
const errorPrefix = '\u001ePA_ERROR:'
const messagePrefix = '\u001ePA_MESSAGE:'

export function isLocale(value: unknown): value is Locale { return value === 'zh-CN' || value === 'en' }
export function setLocale(value: Locale) {
  if (!isLocale(value)) return
  locale = value
  document.documentElement.lang = value
  document.title = value === 'en' ? 'PaperAssist — Research workspace' : 'PaperAssist — 科研论文辅助系统'
  listeners.forEach(listener => listener())
}

function interpolate(text: string, params: Params) {
  return text.replace(/\{([a-zA-Z0-9_]+)\}/g, (_, key: string) => Object.hasOwn(params, key) ? String(params[key]) : '—')
}

function cleanParams(value: unknown): Params {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  return Object.fromEntries(Object.entries(value).filter(([key, item]) => /^[a-zA-Z][a-zA-Z0-9_]*$/.test(key)
    && ((typeof item === 'number' && Number.isFinite(item)) || (typeof item === 'string' && item.length <= 500))))
}

function errorParams(code: string, value: unknown): Params {
  const params = cleanParams(value)
  const result: Params = {}
  const rules: Record<string, Record<string, [number, number]>> = {
    file_too_large: { max_bytes: [1, Number.MAX_SAFE_INTEGER] },
    numeric_precision: { row: [1, 1_048_576] },
    plot_label_too_long: { max_chars: [1, 10_000] },
    openai_request_failed: { provider_status: [400, 599] },
  }
  for (const [name, [min, max]] of Object.entries(Object.hasOwn(rules, code) ? rules[code] : {})) {
    const item = params[name]
    if (typeof item === 'number' && Number.isSafeInteger(item) && item >= min && item <= max) result[name] = item
  }
  if (code === 'numeric_precision' && typeof params.column === 'string' && /^[A-Z]{1,3}$/.test(params.column)) result.column = params.column
  return result
}

/** Store an error identifier; translate at render time, never trust server prose. */
export function apiError(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== 'object') return fallback
  const outer = payload as Record<string, unknown>
  const detail = (outer.detail && typeof outer.detail === 'object' ? outer.detail : outer) as Record<string, unknown>
  if (typeof detail.code !== 'string' || !Object.hasOwn(errorMessages, detail.code)) return fallback
  return errorPrefix + JSON.stringify({ code: detail.code, params: errorParams(detail.code, detail.params), fallback })
}

export function message(source: string, params: Params): string {
  return messagePrefix + JSON.stringify({ source, params })
}

export function safeError(cause: unknown, fallback: string): string {
  if (!(cause instanceof Error)) return fallback
  const value = cause.message
  return value.startsWith(errorPrefix) || value.startsWith(messagePrefix)
    || Object.hasOwn(rootMessages, value) || Object.hasOwn(workflowMessages, value) ? value : fallback
}

export function translate(source: string, params: Params = {}): string {
  if (source.startsWith(messagePrefix)) {
    try {
      const item = JSON.parse(source.slice(messagePrefix.length)) as { source: string; params: Params }
      if (Object.hasOwn(rootMessages, item.source) || Object.hasOwn(workflowMessages, item.source)) return translate(item.source, item.params)
    } catch { /* Invalid identifiers use a local fallback. */ }
    return locale === 'en' ? 'Request failed. Please try again.' : '请求失败，请重试。'
  }
  if (source.startsWith(errorPrefix)) {
    try {
      const item = JSON.parse(source.slice(errorPrefix.length)) as { code: string; params: Params; fallback: string }
      if (Object.hasOwn(errorMessages, item.code)) {
        const entry = errorMessages[item.code]
        const template = locale === 'en' ? entry.en : entry.zh
        const parameters = errorParams(item.code, item.params)
        if ([...template.matchAll(/\{([a-zA-Z0-9_]+)\}/g)].some(match => !Object.hasOwn(parameters, match[1]))) {
          const fallback = Object.hasOwn(rootMessages, item.fallback) || Object.hasOwn(workflowMessages, item.fallback) ? item.fallback : '请求失败，请重试。'
          return translate(fallback)
        }
        return interpolate(template, parameters)
      }
    } catch { /* Only locally created identifiers are accepted. */ }
    return locale === 'en' ? 'Request failed. Please try again.' : '请求失败，请重试。'
  }
  const translated = locale === 'en'
    ? Object.hasOwn(rootMessages, source) ? rootMessages[source]
      : Object.hasOwn(workflowMessages, source) ? workflowMessages[source] : source
    : source
  return interpolate(translated, params)
}

const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } }
const snapshot = () => locale
export function useI18n() {
  const current = useSyncExternalStore(subscribe, snapshot, snapshot)
  return { locale: current, t: translate }
}
