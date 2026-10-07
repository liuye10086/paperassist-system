export function summaryFixture(projectId = 'p1', projectType: 'sci' | 'thesis' = 'sci') {
  return {
    project_id: projectId, project_type: projectType,
    tasks: { items: [], total: 0, page: 1, page_size: 10 },
    artifacts: { items: [], total: 0, page: 1, page_size: 10 },
    future: {
      writing: { state: 'not_available', tasks: [], current_manuscript: null, versions: [] },
      revision: { state: 'not_available', tasks: [], current_round: null, rounds: [], opinions: [], pending_materials: [] },
      sci: projectType === 'sci' ? { state: 'not_available', tasks: [], target_journal: null, recommendations: [], submission_progress: null } : null,
      thesis: projectType === 'thesis' ? { state: 'not_available', tasks: [], school: null, degree: null, template: null, review_progress: null } : null,
    },
  }
}
