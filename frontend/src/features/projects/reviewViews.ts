export const reviewViews = ['list','create','sources','items','plan','revision','comparison','response','documents','continuation','science','supplements','progress'] as const
export type ReviewView = typeof reviewViews[number]
export const taskDetailViews = ['overview','actions','result','events','usage'] as const
export type TaskDetailView = typeof taskDetailViews[number]
