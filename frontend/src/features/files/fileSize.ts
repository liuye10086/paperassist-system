type Translate = (source: string, params?: Record<string, string | number>) => string

/** Readable upload size: bytes below 1 KB, then KB / MB with at most one decimal (1024-based). */
export function formatFileSize(bytes: number, locale: string, t: Translate) {
  if (bytes < 1024) return t('{count} 字节', { count: bytes })
  const number = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 })
  return bytes < 1024 * 1024 ? `${number.format(bytes / 1024)} KB` : `${number.format(bytes / (1024 * 1024))} MB`
}
