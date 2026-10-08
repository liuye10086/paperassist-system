import { useSyncExternalStore } from 'react'

const visible = () => document.visibilityState !== 'hidden'
function subscribe(listener: () => void) {
  document.addEventListener('visibilitychange', listener)
  return () => document.removeEventListener('visibilitychange', listener)
}

// Suspend reads, not the mounted action component or its in-flight POST.
export function useDocumentVisible() { return useSyncExternalStore(subscribe, visible) }
