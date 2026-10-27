import { fireEvent, screen, within } from '@testing-library/react'
import { translate } from '../../shared/i18n'

// Follow the same configuration panes as a user before querying an action.
function openPane(name: string) {
  const pane = name.startsWith('选择配置版本') ? '版本列表'
    : ['离线验证', '查看配置差异', '对比依据'].includes(name) ? '对比与验证'
    : ['启用此修订', '回退到此版本', '重试原配置操作', '配置变更理由'].includes(name) ? '启用与回退'
    : ['读取当前配置与事件', '从已安装设置创建基线草稿'].includes(name) ? '配置概览'
    : ['绑定对象标识', '查询安全绑定'].includes(name) ? '运行绑定' : '所选版本'
  const tab = within(screen.getByRole('navigation', { name: translate('配置治理视图') }))
    .getByRole('button', { name: translate(pane) })
  if (tab.getAttribute('aria-pressed') !== 'true') fireEvent.click(tab)
}

export function configurationButton(name: string) {
  openPane(name)
  return screen.getByRole('button', { name: translate(name) })
}

export function findConfigurationButton(name: string) {
  openPane(name)
  return screen.findByRole('button', { name: translate(name) })
}

export function configurationField(name: string) {
  openPane(name)
  return screen.getByLabelText(translate(name))
}
