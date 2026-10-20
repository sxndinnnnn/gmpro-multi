from datetime import date

import pytest

from app import polyline
from app.capacity import check_capacity
from app.models import OrderRow, PreviewRouteOptimizationRequest, VehicleSelection
from app.preview import PreviewValidationError, preview_route_optimization, priority_weight
from app.solvers.base import OptimizeResult, ReturnLeg, SolvedRoute, SolvedVisit, SolverError
from app.solvers.google import GoogleRouteOptimizationService, GoogleRouteOptimizationSettings
from app.solvers.local import LocalRouteOptimizationService

TYPES = {
    "van": {"id": "van", "name": "Van", "max_weight": 1.5, "max_volume": 8},
    "truck": {"id": "truck", "name": "Truck", "max_weight": 4, "max_volume": 0},
}


def lookup(ids):
    return {i: TYPES[i] for i in ids if i in TYPES}


def row(n, weight=1.0, volume=None, **kw):
    base = dict(
        draft_id=f"d{n}",
        do_number=f"DO-{n}",
        weight=weight,
        volume=volume,
        pickup_location_code=f"P{n}",
        pickup_latitude=6.90 + n * 0.01,
        pickup_longitude=79.85,
        delivery_location_code=f"D{n}",
        delivery_latitude=6.95 + n * 0.01,
        delivery_longitude=79.90,
    )
    base.update(kw)
    return OrderRow(**base)


def request(rows, vehicles=None, **kw):
    base = dict(
        plan_date=date(2026, 10, 21),
        unloading_time_per_unit=10,
        shift_start="08:00",
        shift_end="18:00",
        vehicles=vehicles or [VehicleSelection(vehicle_type_id="truck", count=2)],
        order_rows=rows,
    )
    base.update(kw)
    return PreviewRouteOptimizationRequest(**base)


class FakeService:
    name = "fake"

    def __init__(self, fail_traffic_leg=False):
        self.request = None
        self.legs = []
        self.fail_traffic_leg = fail_traffic_leg

    def optimize_tours(self, req):
        self.request = req
        visits = []
        t = 8 * 3600
        for i in range(len(req.shipments)):
            visits += [SolvedVisit(i, True, t), SolvedVisit(i, False, t + 600)]
            t += 1200
        enc = polyline.encode([(6.9, 79.8), (6.95, 79.9)])
        return OptimizeResult(routes=[SolvedRoute(0, visits, enc, 1000, 5000, 8 * 3600, t)], skipped=[], total_cost=5)

    def return_leg(self, plan_date, start, end, depart_at, traffic, avoid_tolls, avoid_highways):
        self.legs.append(traffic)
        if traffic and self.fail_traffic_leg:
            raise SolverError("traffic failed")
        return ReturnLeg(900, 7000, polyline.encode([start, end]))


def test_multi_pick_model_shape():
    svc = FakeService()
    preview_route_optimization(request([row(1, 2.0), row(2, 0.5)], truck_use="minimizeVehicleCount", load_cost_factor=1), svc, lookup)
    req = svc.request
    assert req.load_key == "weight"
    assert [s.demand for s in req.shipments] == [2000, 500]  # weight x 1000
    assert all(s.include_pickup_visit and s.pickup is not None for s in req.shipments)
    assert all(v.omit_start_location for v in req.vehicles)
    assert [v.label for v in req.vehicles] == ["Truck-1", "Truck-2"]
    assert req.vehicles[0].capacity == 4000
    assert req.vehicles[0].fixed_cost == 1_000_000
    assert req.shipments[0].delivery.duration_seconds == 10 * 2.0 * 60  # unloading min/unit * demand * 60
    assert req.shipments[0].delivery.cost_per_hour_after_soft_end == 2000  # demand * loadCostFactor
    assert req.shipments[0].delivery.soft_end == 8 * 3600


def test_no_fixed_cost_when_spreading_fleet():
    svc = FakeService()
    preview_route_optimization(request([row(1)], truck_use="useAllVehicles"), svc, lookup)
    assert all(v.fixed_cost == 0 for v in svc.request.vehicles)


def test_volume_scaling():
    svc = FakeService()
    preview_route_optimization(request([row(1, weight=None, volume=2.5)], vehicles=[VehicleSelection(vehicle_type_id="van", count=1)]), svc, lookup)
    assert svc.request.load_key == "volume"
    assert svc.request.shipments[0].demand == 250


def test_mixed_load_types_rejected():
    with pytest.raises(PreviewValidationError, match="same load type"):
        preview_route_optimization(request([row(1, 1.0), row(2, weight=None, volume=3)]), FakeService(), lookup)


def test_vehicle_without_dimension_capacity_rejected():
    with pytest.raises(PreviewValidationError, match="no volume capacity"):
        preview_route_optimization(request([row(1, weight=None, volume=3)]), FakeService(), lookup)


@pytest.mark.parametrize(
    "kw,msg",
    [
        (dict(multi_pickup=False), "Single Pick"),
        (dict(pickup_location_id="11111111-1111-1111-1111-111111111111"), "empty pickupLocationId"),
        (dict(unloading_time_per_unit=0), "Unloading time"),
        (dict(vehicles=[VehicleSelection(vehicle_type_id="truck", count=0)]), "at least one vehicle"),
        (dict(shift_end="07:00"), "Shift end"),
        (dict(break_start="12:00"), "both break"),
    ],
)
def test_request_validation(kw, msg):
    with pytest.raises(PreviewValidationError, match=msg):
        preview_route_optimization(request([row(1)], **kw), FakeService(), lookup)


def test_capacity_precheck_and_missing_coordinates_are_skipped():
    rows = [row(1, 5.0), row(2, 1.0, pickup_latitude=None), row(3, 1.0)]
    resp = preview_route_optimization(request(rows), FakeService(), lookup)
    reasons = {s.do_number: s.reason for s in resp.skipped_shipments}
    assert "largest selected vehicle" in reasons["DO-1"]
    assert "pickup coordinates" in reasons["DO-2"]
    assert [v.do_number for v in resp.routes[0].visits] == ["DO-3", "DO-3"]
    assert resp.unassigned_vehicles == ["Truck-2"]


def test_capacity_assigner_respects_fleet_total_and_priority():
    result = check_capacity([300, 300, 300], [1, 3, 1], [500, 500], str)
    assert result.accepted == [0, 1, 2] or len(result.accepted) == 3
    result = check_capacity([400, 400, 400], [1, 3, 2], [500, 500], str)
    assert result.accepted == [1, 2]
    assert result.rejected[0][0] == 0


def test_round_trip_appends_return_leg_and_retries_without_traffic():
    svc = FakeService(fail_traffic_leg=True)
    resp = preview_route_optimization(request([row(1)], enable_route_trip=True), svc, lookup)
    route = resp.routes[0]
    assert svc.legs == [True, False]
    assert route.is_round_trip
    last = route.visits[-1]
    assert last.is_return and last.type == "pickup"
    assert (last.latitude, last.longitude) == (route.visits[0].latitude, route.visits[0].longitude)
    assert route.distance_meters == 5000 + 7000
    assert len(polyline.decode(route.polyline)) == 4  # 2 route points + 2 return-leg points


def test_round_trip_off_leaves_route_open():
    resp = preview_route_optimization(request([row(1)]), FakeService(), lookup)
    assert not resp.routes[0].is_round_trip
    assert resp.routes[0].visits[-1].type == "delivery"


def test_priority_weight():
    assert priority_weight("High") == 3
    assert priority_weight("1") == 3
    assert priority_weight("low") == 1
    assert priority_weight(None) == 1


def test_polyline_roundtrip():
    pts = [(6.93751, 79.85212), (6.86491, 79.89971), (-33.5, 151.2)]
    assert polyline.decode(polyline.encode(pts)) == pts
    assert polyline.encode([(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]) == "_p~iF~ps|U_ulLnnqC_mqNvxq`@"


def test_local_solver_end_to_end():
    rows = [row(i, 1.0) for i in range(1, 6)]
    resp = preview_route_optimization(
        request(rows, enable_route_trip=True, break_start="12:00", break_end="12:30"),
        LocalRouteOptimizationService(time_limit_seconds=1),
        lookup,
    )
    assert not resp.skipped_shipments
    for r in resp.routes:
        seen = set()
        for v in r.visits:
            if v.is_return:
                continue
            if v.type == "pickup":
                seen.add(v.do_number)
            else:
                assert v.do_number in seen  # pickup precedes delivery on the same truck
        assert r.peak_load <= r.capacity


def test_google_body_and_parse():
    svc = GoogleRouteOptimizationService(GoogleRouteOptimizationSettings())
    fake = FakeService()
    preview_route_optimization(request([row(1, 2.0)], avoid_toll=True, shortest_distance=True, break_start="12:00", break_end="12:30"), fake, lookup)
    body = svc.build_body(fake.request)
    shipment = body["model"]["shipments"][0]
    vehicle = body["model"]["vehicles"][0]
    assert "pickups" in shipment and "deliveries" in shipment
    assert shipment["loadDemands"] == {"weight": {"amount": "2000"}}
    assert "startLocation" not in vehicle and "endLocation" not in vehicle
    assert vehicle["costPerKilometer"] == 1
    assert vehicle["routeModifiers"] == {"avoidTolls": True, "avoidHighways": True}
    assert vehicle["breakRule"]["breakRequests"][0]["minDuration"] == "1800s"
    assert body["populatePolylines"] and body["considerRoadTraffic"]

    parsed = svc.parse_response(
        date(2026, 10, 21),
        {
            "routes": [
                {
                    "vehicleLabel": "Truck-1",
                    "visits": [{"isPickup": True, "startTime": "2026-10-21T08:00:00Z"}, {"startTime": "2026-10-21T08:30:00Z"}],
                    "routePolyline": {"points": "abc"},
                    "metrics": {"travelDuration": "1200s", "travelDistanceMeters": 9000},
                    "vehicleStartTime": "2026-10-21T08:00:00Z",
                    "vehicleEndTime": "2026-10-21T08:50:00Z",
                },
                {"vehicleIndex": 1, "vehicleLabel": "Truck-2"},
            ],
            "skippedShipments": [{"index": 3, "label": "DO-4", "reasons": [{"code": "DEMAND_EXCEEDS_VEHICLE_CAPACITY"}]}],
            "metrics": {"totalCost": 9.5},
            "validationErrors": [{"code": 910, "displayName": "DEADLINE"}],
        },
    )
    assert parsed.routes[0].vehicle_index == 0 and parsed.routes[0].visits[1].is_pickup is False
    assert parsed.routes[0].visits[1].start_time == 8 * 3600 + 1800
    assert parsed.routes[0].travel_seconds == 1200 and parsed.routes[0].travel_meters == 9000
    assert parsed.skipped[0][0] == 3
    assert parsed.messages[0][0] == "warning"
