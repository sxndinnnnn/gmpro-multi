import Papa from 'papaparse'
import type { DraftRowInput } from './types'

/** Normalised header -> field. Headers are matched case-insensitively, ignoring spaces and punctuation. */
const HEADER_MAP: Record<string, keyof DraftRowInput | 'pickupCoordinates' | 'deliveryCoordinates' | 'locationCode' | 'locationCoordinates'> = {
  donumber: 'doNumber',
  do: 'doNumber',
  dono: 'doNumber',
  ordernumber: 'doNumber',
  weight: 'weight',
  volume: 'volume',
  pickuplocationcode: 'pickupLocationCode',
  pickuplocationcoordinates: 'pickupCoordinates',
  pickupcoordinates: 'pickupCoordinates',
  pickuplatitude: 'pickupLatitude',
  pickuplongitude: 'pickupLongitude',
  deliverylocationcode: 'deliveryLocationCode',
  deliverylocationcoordinates: 'deliveryCoordinates',
  deliverycoordinates: 'deliveryCoordinates',
  deliverylatitude: 'deliveryLatitude',
  deliverylongitude: 'deliveryLongitude',
  locationcode: 'locationCode',
  locationcoordinates: 'locationCoordinates',
  priority: 'priority',
  pickupopentime: 'pickupOpenTime',
  pickupclosetime: 'pickupCloseTime',
  deliveryopentime: 'deliveryOpenTime',
  deliveryclosetime: 'deliveryCloseTime',
}

const normalise = (h: string) => h.toLowerCase().replace(/[^a-z0-9]/g, '')

function num(v: string | undefined): number | null {
  if (v === undefined || v.trim() === '') return null
  const n = Number(v.trim())
  return Number.isFinite(n) ? n : null
}

export function parseCoordinates(v: string | undefined): [number | null, number | null] {
  if (!v) return [null, null]
  const parts = v.split(/[,;\s]+/).filter(Boolean)
  if (parts.length !== 2) return [null, null]
  return [num(parts[0]), num(parts[1])]
}

export interface ParseResult {
  rows: DraftRowInput[]
  errors: string[]
  unknownHeaders: string[]
}

export function parseOrderImportFile(file: File): Promise<ParseResult> {
  return new Promise((resolve, reject) => {
    Papa.parse<Record<string, string>>(file, {
      header: true,
      skipEmptyLines: 'greedy',
      complete: ({ data, meta, errors: csvErrors }) => {
        const headers = meta.fields ?? []
        const mapping = new Map<string, (typeof HEADER_MAP)[string]>()
        const unknownHeaders: string[] = []
        for (const h of headers) {
          const field = HEADER_MAP[normalise(h)]
          if (field) mapping.set(h, field)
          else unknownHeaders.push(h)
        }
        const mapped = new Set(mapping.values())
        const hasDeliveryHeader = mapped.has('deliveryLocationCode') || mapped.has('deliveryCoordinates') || mapped.has('deliveryLatitude')
        const errors: string[] = csvErrors.slice(0, 5).map((e) => `Row ${(e.row ?? 0) + 2}: ${e.message}`)
        if (!mapped.has('doNumber')) errors.push('Missing "DO Number" column')

        const rows: DraftRowInput[] = []
        data.forEach((raw, i) => {
          const out: DraftRowInput & Record<string, unknown> = { doNumber: '' }
          let locationCode: string | undefined
          let locationCoords: string | undefined
          for (const [header, field] of mapping) {
            const value = raw[header]?.trim()
            switch (field) {
              case 'weight':
              case 'volume':
              case 'pickupLatitude':
              case 'pickupLongitude':
              case 'deliveryLatitude':
              case 'deliveryLongitude':
                out[field] = num(value)
                break
              case 'pickupCoordinates':
                ;[out.pickupLatitude, out.pickupLongitude] = parseCoordinates(value)
                break
              case 'deliveryCoordinates':
                ;[out.deliveryLatitude, out.deliveryLongitude] = parseCoordinates(value)
                break
              case 'locationCode':
                locationCode = value
                break
              case 'locationCoordinates':
                locationCoords = value
                break
              case 'doNumber':
                out.doNumber = value ?? ''
                break
              default:
                out[field] = value || null
            }
          }
          // Generic single-location file: copy the location onto both pickup and delivery so the API always has a via stop.
          if (!hasDeliveryHeader && (locationCode || locationCoords)) {
            const [lat, lng] = parseCoordinates(locationCoords)
            out.pickupLocationCode ??= locationCode ?? null
            out.deliveryLocationCode = locationCode ?? null
            if (out.pickupLatitude == null) [out.pickupLatitude, out.pickupLongitude] = [lat, lng]
            ;[out.deliveryLatitude, out.deliveryLongitude] = [lat, lng]
          }
          if (!out.doNumber) {
            errors.push(`Row ${i + 2}: DO Number is empty`)
            return
          }
          rows.push(out)
        })
        resolve({ rows, errors, unknownHeaders })
      },
      error: reject,
    })
  })
}
