import type { DraftRow } from './types'

export type PlanningMode = 'multiPickRouteOptimization'

interface Column {
  key: string
  label: string
  render: (r: DraftRow) => string
}

const coord = (lat?: number | null, lng?: number | null) => (lat != null && lng != null ? `${lat.toFixed(5)}, ${lng.toFixed(5)}` : '—')
const timeWindow = (open?: string | null, close?: string | null) => (open || close ? `${open ?? '…'} – ${close ?? '…'}` : '—')

export const planningModes = {
  multiPickRouteOptimization: {
    label: 'Multi Pick RO',
    isMultiPickup: true,
    csvTemplate: 'sample-multi-pick-ro.csv',
    tableColumns: [
      { key: 'doNumber', label: 'DO Number', render: (r) => r.doNumber },
      { key: 'weight', label: 'Weight (t)', render: (r) => (r.weight != null ? String(r.weight) : '—') },
      { key: 'volume', label: 'Volume (m³)', render: (r) => (r.volume != null ? String(r.volume) : '—') },
      { key: 'pickupLocationCode', label: 'Pickup Location', render: (r) => r.pickupLocationCode ?? '—' },
      { key: 'pickupCoords', label: 'Pickup Coordinates', render: (r) => coord(r.pickupLatitude, r.pickupLongitude) },
      { key: 'deliveryLocationCode', label: 'Delivery Location', render: (r) => r.deliveryLocationCode ?? '—' },
      { key: 'deliveryCoords', label: 'Delivery Coordinates', render: (r) => coord(r.deliveryLatitude, r.deliveryLongitude) },
      { key: 'priority', label: 'Priority', render: (r) => r.priority ?? '—' },
      { key: 'pickupWindow', label: 'Pickup Window', render: (r) => timeWindow(r.pickupOpenTime, r.pickupCloseTime) },
      { key: 'deliveryWindow', label: 'Delivery Window', render: (r) => timeWindow(r.deliveryOpenTime, r.deliveryCloseTime) },
    ] satisfies Column[],
  },
} as const

export const formatDuration = (seconds: number) => {
  const h = Math.floor(seconds / 3600)
  const m = Math.round((seconds % 3600) / 60)
  return h ? `${h}h ${m}m` : `${m}m`
}

export const formatKm = (meters: number) => `${(meters / 1000).toFixed(1)} km`

/** "2026-10-21T08:15:00" -> "08:15" (with +1d when the time rolls past the plan date) */
export const formatClock = (iso?: string | null, planDate?: string) => {
  if (!iso) return '—'
  const t = iso.slice(11, 16)
  return planDate && iso.slice(0, 10) > planDate ? `${t} +1d` : t
}
