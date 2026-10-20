import { useState } from 'react'
import { formatClock, formatDuration, formatKm } from '../orderPlanningModes'
import type { PreviewResponse } from '../types'
import { ROUTE_COLORS } from './RouteOptimizationMap'

interface Props {
  result: PreviewResponse
  planDate: string
  selected: Set<string>
  onToggle: (label: string) => void
  onToggleAll: (all: boolean) => void
  focused: string | null
  onFocus: (label: string | null) => void
}

export function RouteOptimizationResults({ result, planDate, selected, onToggle, onToggleAll, focused, onFocus }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const unit = result.loadDimension === 'volume' ? 'm³' : 't'
  const allSelected = result.routes.length > 0 && result.routes.every((r) => selected.has(r.vehicleLabel))

  return (
    <div className="results">
      <div className="metrics">
        <Metric label="Routes" value={String(result.metrics.usedVehicleCount)} />
        <Metric label="Distance" value={formatKm(result.metrics.totalDistanceMeters)} />
        <Metric label="Duration" value={formatDuration(result.metrics.totalDurationSeconds)} />
        <Metric label="Skipped" value={String(result.skippedShipments.length)} tone={result.skippedShipments.length ? 'warn' : undefined} />
      </div>

      {result.validationErrors.map((m, i) => (
        <div key={i} className={m.severity === 'error' ? 'error' : 'warn'}>
          {m.message}
        </div>
      ))}

      {result.routes.length > 0 && (
        <label className="check select-all">
          <input type="checkbox" checked={allSelected} onChange={(e) => onToggleAll(e.target.checked)} />
          <span>Select all routes to proceed</span>
        </label>
      )}

      <ul className="route-list">
        {result.routes.map((r, i) => {
          const color = ROUTE_COLORS[i % ROUTE_COLORS.length]
          const open = expanded === r.vehicleLabel
          return (
            <li key={r.vehicleLabel} className={`route-card ${focused === r.vehicleLabel ? 'focused' : ''}`}>
              <div className="route-head">
                <input type="checkbox" checked={selected.has(r.vehicleLabel)} onChange={() => onToggle(r.vehicleLabel)} aria-label={`Select ${r.vehicleLabel}`} />
                <span className="swatch" style={{ background: color }} />
                <button className="link" onClick={() => onFocus(focused === r.vehicleLabel ? null : r.vehicleLabel)}>
                  {r.vehicleLabel}
                </button>
                {r.isRoundTrip && <span className="badge">Round trip</span>}
                <button className="link small push" onClick={() => setExpanded(open ? null : r.vehicleLabel)}>
                  {open ? 'Hide stops' : `${r.visits.length} stops`}
                </button>
              </div>
              <div className="route-stats">
                <span>
                  {formatClock(r.vehicleStartTime, planDate)} → {formatClock(r.vehicleEndTime, planDate)}
                </span>
                <span>{formatKm(r.distanceMeters)}</span>
                <span>{formatDuration(r.durationSeconds)}</span>
                <span>
                  {r.loadAmount} {unit} delivered
                </span>
              </div>
              <div className="util" title={`Peak load ${r.peakLoad} of ${r.capacity} ${unit}`}>
                <div className="util-bar" style={{ width: `${Math.min(100, r.utilizationPercent)}%`, background: color }} />
                <span>{r.utilizationPercent}% peak utilization</span>
              </div>
              {open && (
                <table className="stops">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Type</th>
                      <th>DO</th>
                      <th>Location</th>
                      <th>Arrive</th>
                      <th>Depart</th>
                      <th>On board</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.visits.map((v) => (
                      <tr key={v.sequence}>
                        <td>{v.sequence}</td>
                        <td>
                          <span className={`pill ${v.isReturn ? 'return' : v.type}`}>{v.isReturn ? 'Return' : v.type === 'pickup' ? 'Pickup' : 'Delivery'}</span>
                        </td>
                        <td>{v.doNumber ?? '—'}</td>
                        <td>{v.locationName ?? '—'}</td>
                        <td>{formatClock(v.arrivalTime, planDate)}</td>
                        <td>{formatClock(v.departureTime, planDate)}</td>
                        <td>{v.loadAfter ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </li>
          )
        })}
      </ul>

      {result.unassignedVehicles.length > 0 && (
        <div className="muted small">Unused vehicles: {result.unassignedVehicles.join(', ')}</div>
      )}

      {result.skippedShipments.length > 0 && (
        <details className="skipped" open>
          <summary>Skipped shipments ({result.skippedShipments.length})</summary>
          <table className="stops">
            <thead>
              <tr>
                <th>DO</th>
                <th>Load</th>
                <th>Priority</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {result.skippedShipments.map((s) => (
                <tr key={s.draftId ?? s.doNumber}>
                  <td>{s.doNumber}</td>
                  <td>
                    {s.loadAmount} {unit}
                  </td>
                  <td>{s.priority ?? '—'}</td>
                  <td>{s.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  )
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: 'warn' }) {
  return (
    <div className={`metric ${tone ?? ''}`}>
      <div className="metric-value">{value}</div>
      <div className="metric-label">{label}</div>
    </div>
  )
}
