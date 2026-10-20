import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { ImportModal } from './components/ImportModal'
import { ShipmentPlanModal } from './components/ShipmentPlanModal'
import { planningModes } from './orderPlanningModes'
import type { DraftRow, VehicleType } from './types'

const mode = planningModes.multiPickRouteOptimization

export default function App() {
  const [rows, setRows] = useState<DraftRow[]>([])
  const [vehicleTypes, setVehicleTypes] = useState<VehicleType[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [solver, setSolver] = useState<string>('')
  const [dialog, setDialog] = useState<'import' | 'plan' | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const drafts = await api.searchDrafts(mode.isMultiPickup)
      setRows(drafts)
      setSelected((prev) => new Set([...prev].filter((id) => drafts.some((d) => d.id === id))))
    } catch (e) {
      setError(`Could not load orders: ${(e as Error).message}`)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    api.vehicleTypes().then(setVehicleTypes).catch((e) => setError(`Could not load vehicle types: ${e.message}`))
    api.health().then((h) => setSolver(h.solver)).catch(() => undefined)
  }, [load])

  useEffect(() => {
    if (!notice) return
    const t = setTimeout(() => setNotice(null), 4000)
    return () => clearTimeout(t)
  }, [notice])

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  const allSelected = rows.length > 0 && rows.every((r) => selected.has(r.id))
  const selectedRows = rows.filter((r) => selected.has(r.id))

  const deleteSelected = async () => {
    if (!selected.size || !confirm(`Delete ${selected.size} draft order(s)?`)) return
    try {
      const { deleted } = await api.deleteDrafts([...selected])
      setNotice(`Deleted ${deleted} drafts`)
      setSelected(new Set())
      load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <h1>Orders</h1>
        {solver && (
          <span className="badge" title="Configure GOOGLE_ROUTE_OPTIMIZATION_PROJECT_ID on the backend to use Google">
            Solver: {solver === 'google' ? 'Google Route Optimization' : 'Local (OR-Tools)'}
          </span>
        )}
      </header>

      <nav className="tabs">
        <button className="tab active">{mode.label}</button>
      </nav>

      <div className="toolbar">
        <button className="btn" onClick={() => setDialog('import')}>
          Import CSV
        </button>
        <a className="btn" href={`/${mode.csvTemplate}`} download>
          Template
        </a>
        <button className="btn danger" disabled={!selected.size} onClick={deleteSelected}>
          Delete
        </button>
        <span className="muted small push">
          {selected.size} of {rows.length} selected
        </span>
        <button className="btn primary" disabled={!selected.size || !vehicleTypes.length} onClick={() => setDialog('plan')}>
          Plan Route
        </button>
      </div>

      {error && <div className="error">{error}</div>}
      {notice && <div className="notice">{notice}</div>}

      <div className="table-wrap">
        <table className="orders">
          <thead>
            <tr>
              <th>
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={(e) => setSelected(e.target.checked ? new Set(rows.map((r) => r.id)) : new Set())}
                  aria-label="Select all"
                />
              </th>
              {mode.tableColumns.map((c) => (
                <th key={c.key}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className={selected.has(r.id) ? 'selected' : ''} onClick={() => toggle(r.id)}>
                <td>
                  <input type="checkbox" checked={selected.has(r.id)} onChange={() => toggle(r.id)} onClick={(e) => e.stopPropagation()} />
                </td>
                {mode.tableColumns.map((c) => (
                  <td key={c.key}>{c.render(r)}</td>
                ))}
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={mode.tableColumns.length + 1} className="empty">
                  {loading ? 'Loading…' : 'No open orders. Import a CSV to get started.'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {dialog === 'import' && (
        <ImportModal
          onClose={() => setDialog(null)}
          onImported={(n) => {
            setDialog(null)
            setNotice(`Imported ${n} orders`)
            load()
          }}
        />
      )}
      {dialog === 'plan' && (
        <ShipmentPlanModal
          rows={selectedRows}
          vehicleTypes={vehicleTypes}
          onClose={() => setDialog(null)}
          onProceeded={(n) => {
            setDialog(null)
            setSelected(new Set())
            setNotice(`Saved shipment planning with ${n} route${n === 1 ? '' : 's'}`)
            load()
          }}
        />
      )}
    </div>
  )
}
