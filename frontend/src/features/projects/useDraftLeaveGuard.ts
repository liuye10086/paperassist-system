import { useLayoutEffect } from 'react'
import { useI18n } from '../../shared/i18n'

export type RegisterLeaveGuard = (guard: () => boolean, isDirty?: () => boolean) => () => void

// The project remains mounted during view changes. Guard only navigation that
// would replace it; beforeunload uses the same dirty/pending state without a dialog.
export default function useDraftLeaveGuard(register: RegisterLeaveGuard | undefined, dirty: boolean, pending: boolean) {
  const { t } = useI18n()
  useLayoutEffect(() => register?.(() => {
    if (pending) { window.alert(t('当前保存请求尚未完成或结果待确认，请先核对保存结果。')); return false }
    return !dirty || window.confirm(t('当前项目有未保存的修改。离开并放弃这些修改？'))
  }, () => dirty || pending), [register, dirty, pending, t])
}
