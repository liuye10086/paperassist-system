export const manuscriptViews = ['list','materials','body','evidence','checks','versions','writing','exports','school'] as const
export type ManuscriptView = typeof manuscriptViews[number]
export const journalViews = ['overview','research','sources','recommendations','guidelines','adaptation','submission'] as const
export type JournalView = typeof journalViews[number]
export const schoolTemplateViews = ['list','profile','upload','detail','rules','confirm','binding'] as const
export type SchoolTemplateView = typeof schoolTemplateViews[number]
export type SchoolTemplateNavigation = {view:SchoolTemplateView;templateId:string}
