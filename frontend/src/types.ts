export const EMPTY_GUID = '00000000-0000-0000-0000-000000000000'

export interface DraftRowInput {
  doNumber: string
  weight?: number | null
  volume?: number | null
  pickupLocationCode?: string | null
  pickupLatitude?: number | null
  pickupLongitude?: number | null
  deliveryLocationCode?: string | null
  deliveryLatitude?: number | null
  deliveryLongitude?: number | null
  priority?: string | null
  pickupOpenTime?: string | null
  pickupCloseTime?: string | null
  deliveryOpenTime?: string | null
  deliveryCloseTime?: string | null
}

export interface DraftRow extends DraftRowInput {
  id: string
  importBatchId: string
  isMultiPickup: boolean
  isProceed: boolean
  createdAt: string
}

export interface VehicleType {
  id: string
  name: string
  maxWeight: number
  maxVolume: number
}

export type TruckUse = 'minimizeVehicleCount' | 'useAllVehicles' | 'balanced'

export interface OrderRowPayload extends DraftRowInput {
  draftId?: string
  importBatchId?: string
}

export interface PreviewRouteOptimizationPayload {
  pickupLocationId: string
  deliveryLocationId?: string
  deliveryAsLastDestination: boolean
  multiPickup: boolean
  enableRouteTrip: boolean
  planDate: string
  unloadingTimePerUnit: number
  shiftStart: string
  shiftEnd: string
  breakStart?: string | null
  breakEnd?: string | null
  vehicles: { vehicleTypeId: string; count: number }[]
  truckUse: TruckUse
  shortestDistance: boolean
  avoidToll: boolean
  loadCostFactor: 0 | 1
  considerRoadTraffic: boolean
  orderRows: OrderRowPayload[]
}

export interface RouteVisit {
  sequence: number
  type: 'pickup' | 'delivery'
  doNumber?: string | null
  draftId?: string | null
  locationName?: string | null
  latitude: number
  longitude: number
  arrivalTime?: string | null
  departureTime?: string | null
  loadAfter?: number | null
  isReturn: boolean
}

export interface RouteResult {
  vehicleLabel: string
  vehicleTypeId: string
  vehicleTypeName: string
  visits: RouteVisit[]
  polyline: string
  durationSeconds: number
  distanceMeters: number
  loadAmount: number
  peakLoad: number
  capacity: number
  utilizationPercent: number
  vehicleStartTime?: string | null
  vehicleEndTime?: string | null
  isRoundTrip: boolean
}

export interface SkippedShipment {
  draftId?: string | null
  doNumber: string
  reason: string
  priority?: string | null
  loadAmount: number
}

export interface Metrics {
  totalDurationSeconds: number
  totalDistanceMeters: number
  totalCost: number
  usedVehicleCount: number
}

export interface ValidationMessage {
  severity: 'error' | 'warning'
  message: string
}

export interface PreviewResponse {
  solver: string
  loadDimension?: 'weight' | 'volume' | null
  routes: RouteResult[]
  skippedShipments: SkippedShipment[]
  unassignedVehicles: string[]
  metrics: Metrics
  validationErrors: ValidationMessage[]
}
