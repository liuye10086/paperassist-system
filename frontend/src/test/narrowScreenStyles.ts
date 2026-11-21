import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

// jsdom parses stylesheets but does not calculate media-query layout.
export function narrowScreenStyles(element: Element, featureStylesheet: string): CSSStyleDeclaration[] {
  const features = resolve(dirname(fileURLToPath(import.meta.url)), '../features')
  const style = document.createElement('style')
  style.textContent = readFileSync(resolve(features, featureStylesheet), 'utf8')
  document.head.appendChild(style)
  try {
    const declarations: CSSStyleDeclaration[] = []
    for (const rule of Array.from(style.sheet!.cssRules)) {
      if (!('media' in rule)) continue
      const mediaRule = rule as CSSMediaRule
      const maximum = /^\(max-width:\s*(\d+)px\)$/.exec(mediaRule.media.mediaText)
      if (!maximum || Number(maximum[1]) < 375) continue
      for (const child of Array.from(mediaRule.cssRules) as CSSStyleRule[]) {
        if (child.selectorText && element.matches(child.selectorText)) declarations.push(child.style)
      }
    }
    return declarations
  } finally {
    style.remove()
  }
}
