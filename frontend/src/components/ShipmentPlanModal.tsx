import { useMemo, useState } from 'react'
import { api } from '../api'
import { EMPTY_GUID, type DraftRow, type PreviewResponse, type PreviewRouteOptimizationPayload, type VehicleType } from '../types'
import { Modal } from './Modal'
import { RouteOptimizationMap } from './RouteOptimizationMap'
import { RouteOptimizationResults } from './RouteOptimizationResults'
import { initialPlanValues, ShipmentConfiguration, type PlanFormValues } from './ShipmentConfiguration'

interface Props {
  rows: DraftRow[]
  vehicleTypes: VehicleType[]
  onClose: () => void
  onProceeded: (routeCount: number) => void
}

/** Weight wins when any row has a real weight; volume when rows carry volume only. Mixed is rejected. */
function inferLoadDimension(rows: DraftRow[]): { dimension: 'weight' | 'volume' | null; error?: string } {
  const weight = rows.filter((r) => (r.weight ?? 0) > 0)
  const volumeOnly = rows.filter((r) => (r.weight ?? 0) <= 0 && (r.volume ?? 0) > 0)
  if (weight.length && volumeOnly.length) return { dimension: null, error: 'All route optimization rows must use the same load type' }
  if (weight.length + volumeOnly.length < rows.length) return { dimension: null, error: 'Some selected rows have neither weight nor volume' }
  return { dimension: weight.length ? 'weight' : 'volume' }
}

export function ShipmentPlanModal({ rows, vehicleTypes, onClose, onProceeded }: Props) {
  const [values, setValues] = useState<PlanFormValues>(initialPlanValues)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<PreviewResponse | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [focused, setFocused] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const { dimension, error: loadError } = useMemo(() => inferLoadDimension(rows), [rows])
  const totalLoad = rows.reduce((s, r) => s + ((dimension === 'volume' ? r.volume : r.weight) ?? 0), 0)

  const runRouteOptimizationPreview = async () => {
    setError(null)
    const unloading = Number(values.unloadingTimePerUnit)
    const vehicles = Object.entries(values.vehicleCounts)
      .filter(([, count]) => count > 0)
      .map(([vehicleTypeId, count]) => ({ vehicleTypeId, count }))
    if (!(unloading > 0)) return setError('Unloading time per unit must be greater than 0')
    if (!vehicles.length) return setError('Select at least one vehicle')
    if ((values.breakStart === '') !== (values.breakEnd === '')) return setError('Provide both break start and break end, or neither')

    // Multi Pick RO: no depot, empty pickupLocationId, multiPickup: true.
    const payload: PreviewRouteOptimizationPayload = {
      pickupLocationId: EMPTY_GUID,
      deliveryAsLastDestination: false,
      multiPickup: true,
      enableRouteTrip: values.enableRouteTrip,
      planDate: values.planDate,
      unloadingTimePerUnit: unloading,
      shiftStart: values.shiftStart,
      shiftEnd: values.shiftEnd,
      breakStart: values.breakStart || null,
      breakEnd: values.breakEnd || null,
      vehicles,
      truckUse: values.truckUse,
      shortestDistance: values.shortestDistance,
      avoidToll: values.avoidToll,
      loadCostFactor: values.deliverHeavyOrdersFirst ? 1 : 0,
      considerRoadTraffic: values.considerRoadTraffic,
      orderRows: rows.map(({ id, isMultiPickup: _m, isProceed: _p, createdAt: _c, ...r }) => ({ ...r, draftId: id })),
    }
    setRunning(true)
    try {
      const res = await api.preview(payload)
      setResult(res)
      setSelected(new Set(res.routes.map((r) => r.vehicleLabel)))
      setFocused(null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setRunning(false)
    }
  }

  const proceed = async () => {
    if (!result) return
    const routes = result.routes.filter((r) => selected.has(r.vehicleLabel))
    const usedDrafts = new Set(routes.flatMap((r) => r.visits.map((v) => v.draftId).filter(Boolean)))
    setSaving(true)
    setError(null)
    try {
      await api.saveShipmentPlanning({
        importBatchIds: [...new Set(rows.filter((r) => usedDrafts.has(r.id)).map((r) => r.importBatchId))],
        planDate: values.planDate,
        loadDimension: result.loadDimension,
        routes,
        metrics: {
          totalDurationSeconds: routes.reduce((s, r) => s + r.durationSeconds, 0),
          totalDistanceMeters: routes.reduce((s, r) => s + r.distanceMeters, 0),
          totalCost: result.metrics.totalCost,
          usedVehicleCount: routes.length,
        },
        skippedShipments: result.skippedShipments,
      })
      onProceeded(routes.length)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const hasBlockingError = result?.validationErrors.some((m) => m.severity === 'error') && !result.routes.length

  return (
    <Modal
      wide={!!result}
      title={result ? `Route plan — ${rows.length} orders` : `Plan Route — ${rows.length} orders`}
      onClose={onClose}
      footer={
        result ? (
          <>
            <span className="muted small push-left">Solver: {result.solver}</span>
            <button className="btn" onClick={() => setResult(null)}>
              Back to settings
            </button>
            <button className="btn primary" disabled={!selected.size || saving} onClick={proceed}>
              {saving ? 'Saving…' : `Proceed ${selected.size} route${selected.size === 1 ? '' : 's'}`}
            </button>
          </>
        ) : (
          <>
            <button className="btn" onClick={onClose}>
              Cancel
            </button>
            <button className="btn primary" disabled={running || !!loadError} onClick={runRouteOptimizationPreview}>
              {running ? 'Optimizing…' : 'Optimize routes'}
            </button>
          </>
        )
      }
    >
      {loadError && <div className="error">{loadError}</div>}
      {error && <div className="error">{error}</div>}
      {!result ? (
        <ShipmentConfiguration values={values} onChange={setValues} vehicleTypes={vehicleTypes} loadDimension={dimension} totalLoad={totalLoad} />
      ) : (
        <div className="result-layout">
          <div className="map-wrap">
            {hasBlockingError ? (
              <div className="empty">No routes were produced.</div>
            ) : (
              <RouteOptimizationMap routes={result.routes} focused={focused} planDate={values.planDate} />
            )}
          </div>
          <RouteOptimizationResults
            result={result}
            planDate={values.planDate}
            selected={selected}
            onToggle={(label) =>
              setSelected((prev) => {
                const next = new Set(prev)
                if (next.has(label)) next.delete(label)
                else next.add(label)
                return next
              })
            }
            onToggleAll={(all) => setSelected(all ? new Set(result.routes.map((r) => r.vehicleLabel)) : new Set())}
            focused={focused}
            onFocus={setFocused}
          />
        </div>
      )}
    </Modal>
  )
}
