import { expect, it } from 'vitest'
import bulkWorkflow from '../bio-insights/BulkWorkflowWorkspace.tsx?raw'
import bulkDelivery from '../bio-insights/BulkDelivery.tsx?raw'
import bulkModel from '../bio-insights/BulkModelReview.tsx?raw'
import insightResults from '../bio-insights/InsightResults.tsx?raw'
import explanation from '../explanations/AnalysisExplanation.tsx?raw'
import narrative from '../research-results/ResearchReportNarrative.tsx?raw'
import resources from '../projects/ProjectResources.tsx?raw'
import evidence from '../parsedEvidence/ParsedEvidencePanel.tsx?raw'
import layout from '../layout-exports/LayoutExports.tsx?raw'

// Page inventory section 9, batch B02: analyst-reachable folds are replaced by views or shown directly.
const sources = {
  BulkWorkflowWorkspace: bulkWorkflow, BulkDelivery: bulkDelivery, BulkModelReview: bulkModel, InsightResults: insightResults,
  AnalysisExplanation: explanation, ResearchReportNarrative: narrative, ProjectResources: resources,
  ParsedEvidencePanel: evidence, LayoutExports: layout,
}

it.each(Object.entries(sources))('%s renders no details fold or expand toggle', (_, source) => {
  expect(source).not.toMatch(/<details|<summary/)
  expect(source).not.toMatch(/aria-expanded/)
})
