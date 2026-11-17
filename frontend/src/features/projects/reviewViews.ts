export const reviewViews = ['list','create','sources','items','plan','revision','comparison','response','documents','continuation','science','supplements','progress'] as const
export type ReviewView = typeof reviewViews[number]

export function isReviewItemId(value: string): boolean {
  if (value.length > 64) return false
  return /^[A-Za-z0-9_-]+$/.test(value) || /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}:[1-9][0-9]*$/i.test(value)
}

export const taskDetailViews = ['overview','actions','result','events','usage'] as const
export type TaskDetailView = typeof taskDetailViews[number]
