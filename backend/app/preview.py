"""PreviewRouteOptimization handler: turns order rows into a solver model and maps the result back.

This build implements Multi Pick RO only: every row has its own pickup and its
own delivery, both are sent as visits, and vehicles omit their start location.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Callable, Optional

from . import load_units, polyline
from .capacity import check_capacity
from .models import (
    EMPTY_GUID,
    Metrics,
    OrderRow,
    PreviewRouteOptimizationRequest,
    PreviewRouteOptimizationResponse,
    RouteResult,
    RouteVisit,
    SkippedShipment,
    ValidationMessage,
)
from .solvers.base import (
    OptimizeRequest,
    RouteOptimizationService,
    ShipmentInput,
    SolverError,
    VehicleInput,
    VisitInput,
)
from .solvers.defaults import FIXED_COST_PER_VEHICLE_USED, SKIP_PENALTY_BASE, for_shipment_count

logger = logging.getLogger(__name__)

MAX_VEHICLES = 200
_TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$")


class PreviewValidationError(Exception):
    def __init__(self, messages: list[str]) -> None:
        super().__init__("; ".join(messages))
        self.messages = messages


# ---------------------------------------------------------------- helpers


def parse_time(value: Optional[str], field: str) -> Optional[int]:
    """'HH:MM' or 'HH:MM:SS' -> seconds from midnight."""
    if value is None or str(value).strip() == "":
        return None
    m = _TIME_RE.match(str(value))
    if not m:
        raise ValueError(f"{field} '{value}' is not a valid HH:MM time")
    h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    if h > 23 or mi > 59 or s > 59:
        raise ValueError(f"{field} '{value}' is not a valid HH:MM time")
    return h * 3600 + mi * 60 + s


def priority_weight(priority: Optional[str]) -> int:
    """High/Medium/Low or 1 (highest) .. 3+. Higher weight = more important."""
    if priority is None or str(priority).strip() == "":
        return 1
    p = str(priority).strip().lower()
    named = {"high": 3, "h": 3, "urgent": 3, "critical": 3, "medium": 2, "m": 2, "normal": 2, "low": 1, "l": 1}
    if p in named:
        return named[p]
    try:
        n = int(float(p))
    except ValueError:
        return 1
    return max(1, min(3, 4 - n)) if n >= 1 else 1


def resolve_load_dimension(rows: list[OrderRow]) -> str:
    has_weight = [r for r in rows if (r.weight or 0) > 0]
    volume_only = [r for r in rows if (r.weight or 0) <= 0 and (r.volume or 0) > 0]
    neither = [r for r in rows if (r.weight or 0) <= 0 and (r.volume or 0) <= 0]
    if neither:
        raise PreviewValidationError([f"Rows without weight or volume: {', '.join(r.do_number for r in neither[:10])}"])
    if has_weight and volume_only:
        raise PreviewValidationError(["All route optimization rows must use the same load type"])
    return "weight" if has_weight else "volume"


def _valid_coord(lat: Optional[float], lng: Optional[float]) -> bool:
    return lat is not None and lng is not None and -90 <= lat <= 90 and -180 <= lng <= 180 and not (lat == 0 and lng == 0)


def _clock(plan_date: date, seconds: Optional[int]) -> Optional[str]:
    if seconds is None:
        return None
    return (datetime.combine(plan_date, time(0)) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


@dataclass
class _Prepared:
    row: OrderRow
    demand: int
    weight: int
    shipment: ShipmentInput


# ---------------------------------------------------------------- handler


def preview_route_optimization(
    req: PreviewRouteOptimizationRequest,
    service: RouteOptimizationService,
    get_vehicle_types: Callable[[list[str]], dict[str, dict]],
) -> PreviewRouteOptimizationResponse:
    # 1-2. request validation
    errors: list[str] = []
    if not req.multi_pickup:
        errors.append("Single Pick RO is not available in this build; send multiPickup: true")
    if req.pickup_location_id not in ("", EMPTY_GUID):
        errors.append("Multi Pick RO must send an empty pickupLocationId")
    if req.unloading_time_per_unit is None or req.unloading_time_per_unit <= 0:
        errors.append("Unloading time per unit must be greater than 0")
    selected = [v for v in req.vehicles if v.count > 0]
    if not selected:
        errors.append("Select at least one vehicle type with a count greater than 0")
    if sum(v.count for v in selected) > MAX_VEHICLES:
        errors.append(f"At most {MAX_VEHICLES} vehicles can be planned at once")
    if not req.order_rows:
        errors.append("Select at least one order row")
    if req.load_cost_factor not in (0, 1):
        errors.append("loadCostFactor must be 0 or 1")

    shift_start = shift_end = break_start = break_end = None
    try:
        shift_start = parse_time(req.shift_start, "Shift start")
        shift_end = parse_time(req.shift_end, "Shift end")
        break_start = parse_time(req.break_start, "Break start")
        break_end = parse_time(req.break_end, "Break end")
    except ValueError as e:
        errors.append(str(e))
    if shift_start is None or shift_end is None:
        errors.append("Shift start and shift end are required")
    elif shift_end <= shift_start:
        errors.append("Shift end must be after shift start")
    if (break_start is None) != (break_end is None):
        errors.append("Provide both break start and break end, or neither")
    elif break_start is not None and break_end is not None:
        if break_end <= break_start:
            errors.append("Break end must be after break start")
        elif shift_start is not None and shift_end is not None and not (shift_start <= break_start and break_end <= shift_end):
            errors.append("Break must fall inside the shift")
    if errors:
        raise PreviewValidationError(errors)

    # 3. load dimension
    dimension = resolve_load_dimension(req.order_rows)
    fmt = lambda units: f"{load_units.from_units(dimension, units)} {'t' if dimension == 'weight' else 'm³'}"

    # 5. vehicle types
    types = get_vehicle_types([v.vehicle_type_id for v in selected])
    cap_field = "max_weight" if dimension == "weight" else "max_volume"
    for v in selected:
        vt = types.get(v.vehicle_type_id)
        if vt is None:
            errors.append(f"Vehicle type {v.vehicle_type_id} was not found")
        elif (vt.get(cap_field) or 0) <= 0:
            errors.append(f"Vehicle type '{vt['name']}' has no {dimension} capacity")
    if errors:
        raise PreviewValidationError(errors)

    response = PreviewRouteOptimizationResponse(solver=service.name, load_dimension=dimension)
    skipped: list[SkippedShipment] = []

    def skip(row: OrderRow, reason: str) -> None:
        amount = row.weight if dimension == "weight" else row.volume
        skipped.append(SkippedShipment(draft_id=row.draft_id, do_number=row.do_number, reason=reason, priority=row.priority, load_amount=amount or 0))

    # 9. vehicles ("{VehicleTypeName}-{n}")
    vehicles: list[VehicleInput] = []
    vehicle_meta: list[tuple[str, dict]] = []
    minimize = req.truck_use == "minimizeVehicleCount"
    for sel in selected:
        vt = types[sel.vehicle_type_id]
        for n in range(1, sel.count + 1):
            label = f"{vt['name']}-{n}"
            vehicles.append(
                VehicleInput(
                    label=label,
                    capacity=load_units.to_units(dimension, vt[cap_field]),
                    start_time=shift_start,
                    end_time=shift_end,
                    omit_start_location=True,
                    fixed_cost=FIXED_COST_PER_VEHICLE_USED if minimize else 0,
                    avoid_tolls=req.avoid_toll,
                    avoid_highways=req.shortest_distance,
                    break_start=break_start,
                    break_duration=(break_end - break_start) if break_start is not None else 0,
                )
            )
            vehicle_meta.append((label, vt))

    # 6. capacity pre-check
    rows = req.order_rows
    demands = [load_units.to_units(dimension, r.weight if dimension == "weight" else r.volume) for r in rows]
    weights = [priority_weight(r.priority) for r in rows]
    check = check_capacity(demands, weights, [v.capacity for v in vehicles], fmt)
    for i, reason in check.rejected:
        skip(rows[i], reason)

    # 7-8. coordinates + shipments
    prepared: list[_Prepared] = []
    for i in check.accepted:
        row = rows[i]
        missing = []
        if not _valid_coord(row.pickup_latitude, row.pickup_longitude):
            missing.append("pickup")
        if not _valid_coord(row.delivery_latitude, row.delivery_longitude):
            missing.append("delivery")
        if missing:
            skip(row, f"Missing or invalid {' and '.join(missing)} coordinates")
            continue
        try:
            p_open = parse_time(row.pickup_open_time, "Pickup open time")
            p_close = parse_time(row.pickup_close_time, "Pickup close time")
            d_open = parse_time(row.delivery_open_time, "Delivery open time")
            d_close = parse_time(row.delivery_close_time, "Delivery close time")
        except ValueError as e:
            skip(row, str(e))
            continue
        if (p_open is not None and p_close is not None and p_close <= p_open) or (
            d_open is not None and d_close is not None and d_close <= d_open
        ):
            skip(row, "Time window close must be after open")
            continue

        demand = demands[i]
        amount = (row.weight if dimension == "weight" else row.volume) or 0
        soft_end = None
        cost_per_hour = 0.0
        if req.load_cost_factor > 0:
            soft_end = max(shift_start, d_open or 0)
            if d_close is not None:
                soft_end = min(soft_end, d_close)
            cost_per_hour = float(demand * req.load_cost_factor)
        prepared.append(
            _Prepared(
                row=row,
                demand=demand,
                weight=weights[i],
                shipment=ShipmentInput(
                    label=row.do_number,
                    demand=demand,
                    include_pickup_visit=True,
                    pickup=VisitInput(row.pickup_latitude, row.pickup_longitude, 0, p_open, p_close),
                    delivery=VisitInput(
                        row.delivery_latitude,
                        row.delivery_longitude,
                        int(round(req.unloading_time_per_unit * amount * 60)),
                        d_open,
                        d_close,
                        soft_end,
                        cost_per_hour,
                    ),
                    penalty_cost=SKIP_PENALTY_BASE * weights[i],
                ),
            )
        )

    if not prepared:
        response.skipped_shipments = skipped
        response.unassigned_vehicles = [label for label, _ in vehicle_meta]
        response.validation_errors.append(ValidationMessage(severity="error", message="No orders left to optimize after validation"))
        return response

    # 10. solve
    defaults = for_shipment_count(len(prepared))
    opt_req = OptimizeRequest(
        plan_date=req.plan_date,
        load_key=dimension,
        shipments=[p.shipment for p in prepared],
        vehicles=vehicles,
        global_start=shift_start,
        global_end=shift_end,
        consider_road_traffic=req.consider_road_traffic,
        search_mode=defaults.search_mode,
        timeout_seconds=defaults.timeout_seconds,
        local_time_limit_seconds=defaults.local_time_limit_seconds,
    )
    try:
        result = service.optimize_tours(opt_req)
    except SolverError as e:
        logger.warning("Route optimization failed: %s", e)
        response.skipped_shipments = skipped
        response.validation_errors.append(ValidationMessage(severity="error", message=str(e)))
        return response

    for severity, message in result.messages:
        response.validation_errors.append(ValidationMessage(severity=severity, message=message))
    for idx, reason in result.skipped:
        skip(prepared[idx].row, reason)

    # 12. map back
    routes: list[RouteResult] = []
    for solved in result.routes:
        label, vt = vehicle_meta[solved.vehicle_index]
        if not any(not v.is_pickup for v in solved.visits):
            continue
        capacity_units = vehicles[solved.vehicle_index].capacity
        onboard = peak = delivered = 0
        visits: list[RouteVisit] = []
        for seq, v in enumerate(solved.visits, start=1):
            p = prepared[v.shipment_index]
            visit_input = p.shipment.pickup if v.is_pickup else p.shipment.delivery
            if v.is_pickup:
                onboard += p.demand
            else:
                onboard -= p.demand
                delivered += p.demand
            peak = max(peak, onboard)
            visits.append(
                RouteVisit(
                    sequence=seq,
                    type="pickup" if v.is_pickup else "delivery",
                    do_number=p.row.do_number,
                    draft_id=p.row.draft_id,
                    location_name=p.row.pickup_location_code if v.is_pickup else p.row.delivery_location_code,
                    latitude=visit_input.latitude,
                    longitude=visit_input.longitude,
                    arrival_time=_clock(req.plan_date, v.start_time),
                    departure_time=_clock(req.plan_date, v.start_time + visit_input.duration_seconds),
                    load_after=load_units.from_units(dimension, onboard),
                )
            )
        start_t = solved.start_time if solved.start_time is not None else solved.visits[0].start_time
        end_t = solved.end_time if solved.end_time is not None else start_t + solved.travel_seconds
        route = RouteResult(
            vehicle_label=label,
            vehicle_type_id=vt["id"],
            vehicle_type_name=vt["name"],
            visits=visits,
            polyline=solved.polyline,
            duration_seconds=max(0, end_t - start_t),
            distance_meters=solved.travel_meters,
            load_amount=load_units.from_units(dimension, delivered),
            peak_load=load_units.from_units(dimension, peak),
            capacity=load_units.from_units(dimension, capacity_units),
            utilization_percent=round(100 * peak / capacity_units, 1) if capacity_units else 0,
            vehicle_start_time=_clock(req.plan_date, start_t),
            vehicle_end_time=_clock(req.plan_date, end_t),
        )
        # 11. round trip (Multi Pick only): a second solve per route
        if req.enable_route_trip:
            _append_round_trip(route, req, service, response, end_t, shift_end)
        routes.append(route)

    used = {r.vehicle_label for r in routes}
    response.routes = routes
    response.skipped_shipments = skipped
    response.unassigned_vehicles = [label for label, _ in vehicle_meta if label not in used]
    response.metrics = Metrics(
        total_duration_seconds=sum(r.duration_seconds for r in routes),
        total_distance_meters=sum(r.distance_meters for r in routes),
        total_cost=round(result.total_cost, 2),
        used_vehicle_count=len(routes),
    )
    logger.info("Preview solved %d routes, %d skipped shipments via %s", len(routes), len(skipped), service.name)
    return response


def _append_round_trip(route: RouteResult, req, service, response, end_t: int, shift_end: int) -> None:
    first_pickup = next((v for v in route.visits if v.type == "pickup"), None)
    last_delivery = next((v for v in reversed(route.visits) if v.type == "delivery"), None)
    if first_pickup is None or last_delivery is None:
        response.validation_errors.append(
            ValidationMessage(severity="warning", message=f"{route.vehicle_label}: round trip skipped, the truck ends at the last delivery")
        )
        return
    start = (last_delivery.latitude, last_delivery.longitude)
    end = (first_pickup.latitude, first_pickup.longitude)
    if start == end:
        route.is_round_trip = True
        return

    leg = None
    attempts = [req.consider_road_traffic, False] if req.consider_road_traffic else [False]
    last_error = None
    for traffic in attempts:
        try:
            leg = service.return_leg(req.plan_date, start, end, end_t, traffic, req.avoid_toll, req.shortest_distance)
            break
        except SolverError as e:
            last_error = e
    if leg is None:
        response.validation_errors.append(
            ValidationMessage(
                severity="warning",
                message=f"{route.vehicle_label}: return leg failed ({last_error}); the truck ends at the last delivery",
            )
        )
        return

    arrival = end_t + leg.travel_seconds
    route.visits.append(
        RouteVisit(
            sequence=len(route.visits) + 1,
            type="pickup",
            location_name=f"Return to {first_pickup.location_name or 'start'}",
            latitude=end[0],
            longitude=end[1],
            arrival_time=_clock(req.plan_date, arrival),
            departure_time=_clock(req.plan_date, arrival),
            load_after=0,
            is_return=True,
        )
    )
    route.polyline = polyline.merge(route.polyline, leg.polyline) if route.polyline else leg.polyline
    route.duration_seconds += leg.travel_seconds
    route.distance_meters += leg.travel_meters
    route.vehicle_end_time = _clock(req.plan_date, arrival)
    route.is_round_trip = True
    if arrival > shift_end:
        response.validation_errors.append(
            ValidationMessage(severity="warning", message=f"{route.vehicle_label}: return leg ends after the shift end")
        )
