import { expect, test } from 'vitest'
import { setLocale, translate } from '../../shared/i18n'
import { issueDescription, limitationDescription } from './diagnostics'

test('translates plan diagnostics by stable code and rules while retaining range data', () => {
  setLocale('en')
  expect(translate(issueDescription('numeric_precision', '数值超出安全精度或可表示范围，请修订字段或重新整理。'))).toContain('precision')
  expect(translate(limitationDescription('分析使用已确认整理版本的 C5:D10 区域，保留区域内空行；普通小数采用 binary64，可能存在浮点误差。'))).toContain('C5:D10')
  expect(translate(limitationDescription('数值最小值和最大值是观察范围，不是临床或业务合理范围。'))).toContain('observed range')
  setLocale('zh-CN')
})
