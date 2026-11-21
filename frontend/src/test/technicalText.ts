// Test utility: find system identifiers and raw internal values in rendered pages.
// Allowed (DESIGN.md 9.1): business names, DOI/PMID, http(s) URLs (removed before matching), e-mail addresses,
// dates, editable user input, and file names whose snake_case stem is followed by ".ext", "(n).ext" or " (n).ext".
// User variable names, column names, sample IDs and citation keys must be marked, not rewritten or hidden:
// wrap them in [data-user-content] (or pass `exclude`), or list them in `allowValues`.

export type TechnicalTextKind = 'uuid' | 'hex' | 'system-id' | 'internal-value' | 'path' | 'json' | 'dev-symbol'
export type TechnicalTextFinding = {
  kind: TechnicalTextKind
  value: string
  where: 'text' | 'value' | (typeof attributes)[number] | 'label'
}
export type TechnicalTextOptions = {
  /** Raw codes that must not appear as whole words, e.g. single-word status values. */
  rawValues?: readonly string[]
  /** Stub UUIDs and hashes; reported in full or cut to their first 8 or 12 characters. */
  systemIds?: readonly string[]
  /** User values (variable names, sample IDs) that may appear anywhere as whole words. */
  allowValues?: readonly string[]
  /** Extra selector for user-content subtrees; [data-user-content] is always skipped. */
  exclude?: string
}

const attributes = ['aria-label', 'title', 'placeholder', 'alt', 'aria-valuetext', 'aria-description'] as const
const buttonInputs = new Set(['button', 'submit', 'reset'])
const nonTextInputs = new Set(['checkbox', 'radio', 'hidden', 'file', 'range', 'color', 'image'])

const segment = String.raw`[\w-]+(?:\.[\w-]+)*`
const extension = String.raw`\.[A-Za-z][A-Za-z0-9]{1,4}\b`
const patterns: [TechnicalTextKind, RegExp][] = [
  ['uuid', /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi],
  // Hash-like runs with both letters and digits. Matches inside a UUID are dropped by scan().
  ['hex', /(?<![0-9a-z])(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{12,}(?![0-9a-z])/gi],
  ['json', /\{\s*['"][^'"]+['"]\s*:/g],
  ['dev-symbol', /\[object \w+\]|\b\w*Error:/g],
  // Absolute paths: three or more segments, or two ending in an extension ("5 mg /kg/d" does not match).
  ['path', new RegExp(String.raw`(?<![\w.:/@])(?:(?:\/${segment}){3,}|\/${segment}\/[\w.-]*${extension})`, 'g')],
  // Windows drive paths with either separator.
  ['path', /(?<!\w)[A-Za-z]:[\\/][^\s\\/:*?"<>|]+(?:[\\/][^\s\\/:*?"<>|]+)*/g],
  // Relative storage paths such as word/document.xml; "1/2.5mg" and DOI do not match.
  ['path', new RegExp(String.raw`(?<![\w.:/@-])[\w-]{2,}\/(?:[\w-]+\/)*[\w.-]+${extension}`, 'g')],
  // snake_case codes; a following ".ext", "(n).ext", " (n).ext" or e-mail domain marks user content.
  ['internal-value', /(?<![\w.@/-])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![\w@-]|\.[A-Za-z0-9]| ?\(\d+\)\.[A-Za-z])/g],
]

const escape = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const wholeWord = (values: readonly string[], flags = 'g') =>
  new RegExp(`(?<![\\w-])(?:${values.map(escape).join('|')})(?![\\w-])`, flags)
const blank = (text: string, pattern: RegExp) => text.replace(pattern, match => ' '.repeat(match.length))

function rulesFor(options: TechnicalTextOptions) {
  const rules = [...patterns]
  if (options.rawValues?.length) rules.push(['internal-value', wholeWord(options.rawValues)])
  if (options.systemIds?.length) {
    const forms = [...new Set(options.systemIds.flatMap(id => [id, id.slice(0, 12), id.slice(0, 8)]))]
      .sort((a, b) => b.length - a.length)
    rules.push(['system-id', new RegExp(`(?<![0-9a-z])(?:${forms.map(escape).join('|')})(?![0-9a-z])`, 'gi')])
  }
  return rules
}

function scan(text: string, where: TechnicalTextFinding['where'], options: TechnicalTextOptions, rules: [TechnicalTextKind, RegExp][]) {
  let source = blank(text, /https?:\/\/\S+/g)
  if (options.allowValues?.length) source = blank(source, wholeWord(options.allowValues))
  const found: (TechnicalTextFinding & { index: number })[] = []
  for (const [kind, pattern] of rules) {
    for (const match of source.matchAll(pattern)) {
      const start = match.index, end = start + match[0].length
      // Earlier rules win: drop matches inside an earlier finding (UUID segments, a hash already reported).
      if (!found.some(item => item.index <= start && end <= item.index + item.value.length)) {
        found.push({ kind, value: match[0], where, index: start })
      }
    }
  }
  return found.sort((a, b) => a.index - b.index).map(({ kind, value, where }) => ({ kind, value, where }))
}

// Adjacent text nodes are read as one string: React renders {name}.{ext} as separate nodes.
function textRuns(element: Element) {
  const runs: string[] = []
  let run = ''
  for (const child of element.childNodes) {
    if (child.nodeType === Node.TEXT_NODE) run += child.textContent ?? ''
    else if (run) { runs.push(run); run = '' }
  }
  if (run) runs.push(run)
  return runs
}

// Editable fields hold what the user typed; read-only and disabled fields and button labels are page text.
function shownValue(element: Element) {
  if (element instanceof HTMLInputElement) {
    if (buttonInputs.has(element.type)) return element.value
    if (nonTextInputs.has(element.type)) return ''
  } else if (!(element instanceof HTMLTextAreaElement)) return ''
  return element.readOnly || element.disabled ? element.value : ''
}

export function findTechnicalText(root: Element, options: TechnicalTextOptions = {}): TechnicalTextFinding[] {
  const rules = rulesFor(options)
  const excluded = ['[data-user-content]', options.exclude].filter(Boolean).join(', ')
  const findings: TechnicalTextFinding[] = []
  for (const element of [root, ...root.querySelectorAll('*')]) {
    if (element.closest(excluded) || ['SCRIPT', 'STYLE'].includes(element.tagName)) continue
    if (element.tagName !== 'TEXTAREA') for (const run of textRuns(element)) findings.push(...scan(run, 'text', options, rules))
    const value = shownValue(element)
    if (value) findings.push(...scan(value, 'value', options, rules))
    for (const name of attributes) {
      const text = element.getAttribute(name)
      if (text) findings.push(...scan(text, name, options, rules))
    }
    const label = ['OPTION', 'OPTGROUP'].includes(element.tagName) ? element.getAttribute('label') : null
    if (label) findings.push(...scan(label, 'label', options, rules))
  }
  return findings
}
