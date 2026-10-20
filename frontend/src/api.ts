import type {
  DraftRow,
  DraftRowInput,
  Metrics,
  PreviewResponse,
  PreviewRouteOptimizationPayload,
  RouteResult,
  SkippedShipment,
  VehicleType,
} from './types'

const BASE = import.meta.env.VITE_API_BASE ?? '/api'
const TOKEN = import.meta.env.VITE_API_TOKEN as string | undefined

export class ApiError extends Error {
  constructor(message: string, public status: number, public body: unknown) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}),
      ...init?.headers,
    },
  })
  const text = await res.text()
  const body = text ? JSON.parse(text) : null
  if (!res.ok) {
    const detail = body?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: { msg: string; loc: string[] }) => `${d.loc.slice(1).join('.')}: ${d.msg}`).join('; ')
          : `Request failed (${res.status})`
    throw new ApiError(message, res.status, body)
  }
  return body as T
}

const post = <T>(path: string, body: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(body) })

export const api = {
  health: () => request<{ status: string; solver: string }>('/health'),
  vehicleTypes: () => request<VehicleType[]>('/vehicle-types'),
  createVehicleType: (body: Omit<VehicleType, 'id'>) => post<VehicleType>('/vehicle-types', body),
  saveDrafts: (rows: DraftRowInput[], isMultiPickup: boolean) =>
    post<{ importBatchId: string; rows: DraftRow[] }>('/orders/route-optimization/drafts', { rows, isMultiPickup }),
  searchDrafts: (isMultiPickup: boolean) => post<DraftRow[]>('/orders/route-optimization/drafts/search', { isMultiPickup }),
  deleteDrafts: (ids: string[]) => post<{ deleted: number }>('/orders/route-optimization/drafts/delete', { ids }),
  /** Preview never writes shipments. A 400 still carries validationErrors in the body. */
  preview: async (payload: PreviewRouteOptimizationPayload): Promise<PreviewResponse> => {
    try {
      return await post<PreviewResponse>('/orders/route-optimization/preview', payload)
    } catch (e) {
      if (e instanceof ApiError && e.status === 400 && (e.body as PreviewResponse)?.validationErrors) {
        return e.body as PreviewResponse
      }
      throw e
    }
  },
  saveShipmentPlanning: (body: {
    importBatchIds: string[]
    planDate: string
    loadDimension?: string | null
    routes: RouteResult[]
    metrics: Metrics
    skippedShipments: SkippedShipment[]
  }) => post<{ id: string; routeCount: number; proceededDraftIds: string[] }>('/orders/route-optimization/shipment-planning', body),
}
