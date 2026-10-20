import { useState } from 'react'
import { api } from '../api'
import { parseOrderImportFile, type ParseResult } from '../orderImportUtils'
import { planningModes } from '../orderPlanningModes'
import { Modal } from './Modal'

interface Props {
  onClose: () => void
  onImported: (count: number) => void
}

export function ImportModal({ onClose, onImported }: Props) {
  const mode = planningModes.multiPickRouteOptimization
  const [parsed, setParsed] = useState<ParseResult | null>(null)
  const [fileName, setFileName] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const onFile = async (file?: File) => {
    setError(null)
    setParsed(null)
    if (!file) return
    setFileName(file.name)
    try {
      setParsed(await parseOrderImportFile(file))
    } catch (e) {
      setError(`Could not read file: ${(e as Error).message}`)
    }
  }

  const save = async () => {
    if (!parsed?.rows.length) return
    setSaving(true)
    setError(null)
    try {
      const res = await api.saveDrafts(parsed.rows, mode.isMultiPickup)
      onImported(res.rows.length)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const missingCoords = parsed?.rows.filter(
    (r) => r.pickupLatitude == null || r.pickupLongitude == null || r.deliveryLatitude == null || r.deliveryLongitude == null,
  ).length

  return (
    <Modal
      title={`Import CSV — ${mode.label}`}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" disabled={!parsed?.rows.length || saving} onClick={save}>
            {saving ? 'Saving…' : `Save ${parsed?.rows.length ?? 0} drafts`}
          </button>
        </>
      }
    >
      <p className="muted">
        Columns: DO Number, Weight, Volume, Pickup Location Code, Pickup Location Coordinates, Delivery Location Code, Delivery Location
        Coordinates, Priority, Pickup/Delivery Open and Close Time. Coordinates are <code>"lat, lng"</code>, times are <code>HH:MM</code>.{' '}
        <a href={`/${mode.csvTemplate}`} download>
          Download template
        </a>
      </p>
      <label className="file-drop">
        <input type="file" accept=".csv,text/csv" onChange={(e) => onFile(e.target.files?.[0])} />
        <span>{fileName || 'Choose a CSV file…'}</span>
      </label>
      {parsed && (
        <div className="import-summary">
          <div>
            <strong>{parsed.rows.length}</strong> rows ready to import
          </div>
          {!!missingCoords && <div className="warn">{missingCoords} rows are missing pickup or delivery coordinates and will be skipped at planning.</div>}
          {parsed.unknownHeaders.length > 0 && <div className="muted">Ignored columns: {parsed.unknownHeaders.join(', ')}</div>}
          {parsed.errors.map((e) => (
            <div key={e} className="error">
              {e}
            </div>
          ))}
        </div>
      )}
      {error && <div className="error">{error}</div>}
    </Modal>
  )
}
