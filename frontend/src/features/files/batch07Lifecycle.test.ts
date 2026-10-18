import { expect, test } from 'vitest'
import { isCounts, lifecycleCounts } from './fileLifecycleApi'
import { referenceLabels } from './fileLibraryApi'
import { setLocale, translate } from '../../shared/i18n'

test('quality receipt dependencies keep readable bilingual labels and accept retained legacy counts', () => {
 const legacy = Object.fromEntries(Object.keys(lifecycleCounts).map(key => [key, 0]))
 delete legacy.prepared_dataset_derivations
 expect(isCounts(legacy)).toBe(true)
 expect(isCounts({ ...legacy, prepared_dataset_derivations: 2 })).toBe(true)
 expect(lifecycleCounts).toHaveProperty('prepared_dataset_derivations', '质量派生与回执')
 expect(referenceLabels).toHaveProperty('prepared_dataset_derivations', '质量派生与回执')
 setLocale('en'); expect(translate('质量派生与回执')).toBe('Quality derivations and receipts'); setLocale('zh-CN')
})
