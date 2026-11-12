import { projectBase } from '../research-intake/api'
import type { DeliveryKind } from '../research-intake/contracts'

export const customerBase = (projectId: string) => `${projectBase(projectId)}/customer-workspace`

export type Feedback = { id: string; message: string; created_at: string }
export type Progress = {
  status: 'draft' | 'pending_assignment' | 'assigned' | 'analyzing' | 'needs_materials' | 'delivered'
  requirement_version: number | null
  submitted_at: string | null
  updated_at: string | null
  note: string | null
  feedback: Feedback[]
}
export type DeliverySummary = {
  id: string
  title: string
  kind: DeliveryKind
  revision: number
  published_at: string
  member_count: number
}
export type DeliveryMember = { id: string; name: string; format: string; size_bytes: number; download_url: string }
export type DeliveryDetail = DeliverySummary & {
  members: DeliveryMember[]
  package_url: string | null
  feedback: Feedback[]
}
