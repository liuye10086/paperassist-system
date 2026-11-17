const keywordGroups = [
  { aliases: ['单细胞', 'single cell', 'single-cell'], terms: ['single cell'] },
  {
    aliases: ['单细胞RNA测序', '单细胞RNA-seq', '单细胞转录组', '单细胞转录组测序', 'scRNA-seq', 'scRNA seq', 'scRNAseq', 'single cell RNA sequencing', 'single-cell RNA sequencing'],
    terms: ['single cell RNA sequencing', 'single cell transcriptomics', 'scRNA seq'],
  },
  { aliases: ['批次效应', '批次效应校正', '批次校正'], terms: ['batch effects', 'batch correction'] },
  { aliases: ['跨样本整合', '数据整合', '数据集整合'], terms: ['data integration', 'dataset integration'] },
  { aliases: ['细胞注释', '细胞类型注释'], terms: ['cell type annotation', 'cell annotation'] },
  { aliases: ['表征学习', '表示学习'], terms: ['representation learning'] },
  { aliases: ['评估基准', '基准评估', '基准测试'], terms: ['benchmarking', 'benchmark'] },
  { aliases: ['空间转录组', '空间转录组学', '空间转录组测序'], terms: ['spatial transcriptomics'] },
  { aliases: ['差异表达', '差异基因表达'], terms: ['differential expression'] },
  { aliases: ['细胞通讯', '细胞间通讯'], terms: ['cell cell communication', 'intercellular communication'] },
]

const knownTerms = new Map(keywordGroups.flatMap(({ aliases, terms }) =>
  aliases.map(alias => [alias.toLowerCase(), terms] as const)))

function searchTerms(keyword: string): string[] {
  const normalized = keyword.normalize('NFKC').replace(/[\u2010-\u2015]/g, '-').replace(/\s+/g, ' ').trim()
  const known = knownTerms.get(normalized.toLowerCase())
  if (known) return known

  // A bilingual keyword can already contain a user-supplied English term.
  const bilingual = normalized.match(/^(.+)\(([^()]+)\)$/)
  const term = bilingual && /\p{Script=Han}/u.test(bilingual[1]) ? bilingual[2].trim() : normalized
  if (!/[\p{L}\p{N}]/u.test(term) || !/^[\p{Script=Latin}\p{Script=Greek}\p{N}\p{M} +\-.,'’/&]+$/u.test(term) ||
      /(?:^| )(?:AND|OR|NOT)(?: |$)/.test(term)) return []
  return [term]
}

export function suggestPubMedQuery(keywords: readonly string[]) {
  const concepts = new Map<string, string[]>()
  const omitted: string[] = []
  for (const keyword of keywords) {
    if (!keyword.trim()) continue
    const terms = searchTerms(keyword)
    if (terms.length) concepts.set(terms.join(' OR ').toLowerCase(), terms)
    else omitted.push(keyword)
  }

  const [primary, ...secondary] = concepts.values()
  const primaryQuery = primary?.join(' OR ') ?? ''
  const query = secondary.length ? `(${primaryQuery}) AND (${secondary.flat().join(' OR ')})` : primaryQuery
  const tooLong = query.length > 4000
  return {
    query: tooLong ? '' : query,
    hasSecondaryTerms: !tooLong && secondary.length > 0,
    tooLong,
    omitted,
  }
}

export function suggestManualPubMedQuery(input: string) {
  const raw = input.normalize('NFKC').trim()
  if (!/\p{Script=Han}/u.test(raw) || /[\[\]"*]|\b(?:AND|OR|NOT)\b/.test(raw)) return null

  return suggestPubMedQuery(raw.split(/[,、;\n]+/))
}
