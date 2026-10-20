import { Fragment, useEffect, useMemo } from 'react'
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMap } from 'react-leaflet'
import type { LatLngBoundsExpression, LatLngTuple } from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { decodePolyline } from '../polyline'
import { formatClock } from '../orderPlanningModes'
import type { RouteResult } from '../types'

export const ROUTE_COLORS = ['#2563eb', '#dc2626', '#16a34a', '#9333ea', '#ea580c', '#0891b2', '#ca8a04', '#db2777', '#4f46e5', '#65a30d']

interface Props {
  routes: RouteResult[]
  focused: string | null
  planDate: string
}

function FitBounds({ bounds }: { bounds: LatLngBoundsExpression | null }) {
  const map = useMap()
  useEffect(() => {
    if (bounds) map.fitBounds(bounds, { padding: [30, 30] })
  }, [map, bounds])
  return null
}

export function RouteOptimizationMap({ routes, focused, planDate }: Props) {
  const lines = useMemo(() => routes.map((r) => (r.polyline ? decodePolyline(r.polyline) : r.visits.map((v) => [v.latitude, v.longitude] as LatLngTuple))), [routes])

  const bounds = useMemo<LatLngBoundsExpression | null>(() => {
    const target = focused ? routes.filter((r) => r.vehicleLabel === focused) : routes
    const pts = target.flatMap((r) => r.visits.map((v) => [v.latitude, v.longitude] as LatLngTuple))
    return pts.length ? pts : null
  }, [routes, focused])

  return (
    <MapContainer center={[0, 0]} zoom={2} className="map" scrollWheelZoom>
      <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      <FitBounds bounds={bounds} />
      {routes.map((r, i) => {
        const color = ROUTE_COLORS[i % ROUTE_COLORS.length]
        const dim = focused && focused !== r.vehicleLabel
        return (
          <Fragment key={r.vehicleLabel}>
            <Polyline positions={lines[i]} pathOptions={{ color, weight: dim ? 2 : 4, opacity: dim ? 0.25 : 0.85 }} />
            {r.visits.map((v) => (
              <CircleMarker
                key={`${v.sequence}`}
                center={[v.latitude, v.longitude]}
                radius={v.type === 'pickup' ? 7 : 6}
                pathOptions={{
                  color,
                  weight: 2,
                  fillColor: v.type === 'pickup' ? '#ffffff' : color,
                  fillOpacity: dim ? 0.2 : 1,
                  opacity: dim ? 0.3 : 1,
                }}
              >
                <Tooltip>
                  <strong>
                    {r.vehicleLabel} #{v.sequence}
                  </strong>{' '}
                  {v.isReturn ? 'Return' : v.type === 'pickup' ? 'Pickup' : 'Delivery'}
                  <br />
                  {v.doNumber && <>{v.doNumber} · </>}
                  {v.locationName}
                  <br />
                  Arrive {formatClock(v.arrivalTime, planDate)}
                </Tooltip>
              </CircleMarker>
            ))}
          </Fragment>
        )
      })}
    </MapContainer>
  )
}
