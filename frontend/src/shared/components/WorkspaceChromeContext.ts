import { createContext } from 'react'

/** Layout slots only; navigation and permissions stay with their owning workspace. */
export const WorkspaceChromeContext = createContext<{
  navigation: HTMLDivElement | null
  accountMenu: HTMLDivElement | null
  closeAccount: () => void
} | null>(null)

export const ProjectWorkspaceVisibleContext = createContext(true)
