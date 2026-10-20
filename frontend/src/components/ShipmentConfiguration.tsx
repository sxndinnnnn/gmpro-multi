import type { TruckUse, VehicleType } from '../types'

export interface PlanFormValues {
  planDate: string
  unloadingTimePerUnit: string
  shiftStart: string
  shiftEnd: string
  breakStart: string
  breakEnd: string
  vehicleCounts: Record<string, number>
  truckUse: TruckUse
  shortestDistance: boolean
  avoidToll: boolean
  deliverHeavyOrdersFirst: boolean
  enableRouteTrip: boolean
  considerRoadTraffic: boolean
}

export const initialPlanValues = (): PlanFormValues => ({
  planDate: new Date().toISOString().slice(0, 10),
  unloadingTimePerUnit: '10',
  shiftStart: '08:00',
  shiftEnd: '18:00',
  breakStart: '',
  breakEnd: '',
  vehicleCounts: {},
  truckUse: 'minimizeVehicleCount',
  shortestDistance: false,
  avoidToll: false,
  deliverHeavyOrdersFirst: false,
  enableRouteTrip: false,
  considerRoadTraffic: true,
})

interface Props {
  values: PlanFormValues
  onChange: (v: PlanFormValues) => void
  vehicleTypes: VehicleType[]
  loadDimension: 'weight' | 'volume' | null
  totalLoad: number
}

export function ShipmentConfiguration({ values, onChange, vehicleTypes, loadDimension, totalLoad }: Props) {
  const set = <K extends keyof PlanFormValues>(key: K, value: PlanFormValues[K]) => onChange({ ...values, [key]: value })
  const unit = loadDimension === 'volume' ? 'm³' : 't'
  const capOf = (vt: VehicleType) => (loadDimension === 'volume' ? vt.maxVolume : vt.maxWeight)
  const fleetCapacity = vehicleTypes.reduce((sum, vt) => sum + capOf(vt) * (values.vehicleCounts[vt.id] ?? 0), 0)

  return (
    <div className="plan-form">
      <section>
        <h3>Schedule</h3>
        <div className="grid">
          <label>
            Plan date
            <input type="date" value={values.planDate} onChange={(e) => set('planDate', e.target.value)} />
          </label>
          <label>
            Unloading time per unit (min / {unit})
            <input type="number" min="0" step="0.1" value={values.unloadingTimePerUnit} onChange={(e) => set('unloadingTimePerUnit', e.target.value)} />
          </label>
          <label>
            Shift start
            <input type="time" value={values.shiftStart} onChange={(e) => set('shiftStart', e.target.value)} />
          </label>
          <label>
            Shift end
            <input type="time" value={values.shiftEnd} onChange={(e) => set('shiftEnd', e.target.value)} />
          </label>
          <label>
            Break start <span className="muted">(optional)</span>
            <input type="time" value={values.breakStart} onChange={(e) => set('breakStart', e.target.value)} />
          </label>
          <label>
            Break end <span className="muted">(optional)</span>
            <input type="time" value={values.breakEnd} onChange={(e) => set('breakEnd', e.target.value)} />
          </label>
        </div>
      </section>

      <section>
        <h3>Vehicles</h3>
        <table className="vehicle-table">
          <thead>
            <tr>
              <th>Vehicle type</th>
              <th>Capacity</th>
              <th>Count</th>
            </tr>
          </thead>
          <tbody>
            {vehicleTypes.map((vt) => {
              const cap = capOf(vt)
              return (
                <tr key={vt.id} className={cap <= 0 ? 'disabled' : ''}>
                  <td>{vt.name}</td>
                  <td>{cap > 0 ? `${cap} ${unit}` : `no ${loadDimension} capacity`}</td>
                  <td>
                    <input
                      type="number"
                      min="0"
                      max="50"
                      disabled={cap <= 0}
                      value={values.vehicleCounts[vt.id] ?? 0}
                      onChange={(e) => set('vehicleCounts', { ...values.vehicleCounts, [vt.id]: Math.max(0, Number(e.target.value) || 0) })}
                    />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        <div className={`capacity-hint ${fleetCapacity && fleetCapacity < totalLoad ? 'warn' : 'muted'}`}>
          Selected orders: {totalLoad.toFixed(2)} {unit} · Fleet capacity: {fleetCapacity.toFixed(2)} {unit}
          {fleetCapacity > 0 && fleetCapacity < totalLoad && ' — some orders will be skipped by the capacity check'}
        </div>
        <label>
          Truck use
          <select value={values.truckUse} onChange={(e) => set('truckUse', e.target.value as TruckUse)}>
            <option value="minimizeVehicleCount">Minimize vehicle count</option>
            <option value="useAllVehicles">Use all vehicles</option>
            <option value="balanced">Balanced</option>
          </select>
        </label>
      </section>

      <section>
        <h3>Options</h3>
        <div className="checks">
          <Check label="Shortest distance (avoid highways)" checked={values.shortestDistance} onChange={(v) => set('shortestDistance', v)} />
          <Check label="Avoid toll" checked={values.avoidToll} onChange={(v) => set('avoidToll', v)} />
          <Check label="Deliver heavy orders first" checked={values.deliverHeavyOrdersFirst} onChange={(v) => set('deliverHeavyOrdersFirst', v)} />
          <Check label="Consider road traffic" checked={values.considerRoadTraffic} onChange={(v) => set('considerRoadTraffic', v)} />
          <Check
            label="Enable round trip"
            hint="Truck returns from its last delivery to the pickup where its route started"
            checked={values.enableRouteTrip}
            onChange={(v) => set('enableRouteTrip', v)}
          />
        </div>
      </section>
    </div>
  )
}

function Check({ label, hint, checked, onChange }: { label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="check" title={hint}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span>
        {label}
        {hint && <small className="muted"> — {hint}</small>}
      </span>
    </label>
  )
}
