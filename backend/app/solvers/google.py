"""Google Route Optimization adapter (optimizeTours REST endpoint)."""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from .base import (
    OptimizeRequest,
    OptimizeResult,
    ReturnLeg,
    ShipmentInput,
    SolvedRoute,
    SolvedVisit,
    SolverError,
    VehicleInput,
    VisitInput,
)

logger = logging.getLogger(__name__)

API_ROOT = "https://routeoptimization.googleapis.com/v1"
DEADLINE_CODE = 910


class GoogleRouteOptimizationSettings:
    def __init__(self) -> None:
        self.project_id = os.environ.get("GOOGLE_ROUTE_OPTIMIZATION_PROJECT_ID", "")
        self.credentials_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        self.request_timeout = int(os.environ.get("GOOGLE_ROUTE_OPTIMIZATION_HTTP_TIMEOUT", "180"))

    @property
    def configured(self) -> bool:
        return bool(self.project_id)


def _ts(plan_date: date, seconds: int) -> str:
    dt = datetime.combine(plan_date, time(0), tzinfo=timezone.utc) + timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(plan_date: date, value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    base = datetime.combine(plan_date, time(0), tzinfo=timezone.utc)
    return int((dt - base).total_seconds())


def _dur(value: Optional[str]) -> int:
    if not value:
        return 0
    return int(round(float(value.rstrip("s"))))


class GoogleRouteOptimizationService:
    name = "google"

    def __init__(self, settings: GoogleRouteOptimizationSettings) -> None:
        self.settings = settings
        self._session = None

    # -------------------------------------------------------------- transport

    def _http(self):
        if self._session is None:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession

            scopes = ["https://www.googleapis.com/auth/cloud-platform"]
            if self.settings.credentials_file:
                from google.oauth2 import service_account

                creds = service_account.Credentials.from_service_account_file(self.settings.credentials_file, scopes=scopes)
            else:
                creds, _ = google.auth.default(scopes=scopes)
            self._session = AuthorizedSession(creds)
        return self._session

    def _post(self, body: dict) -> dict:
        url = f"{API_ROOT}/projects/{self.settings.project_id}:optimizeTours"
        resp = self._http().post(url, json=body, timeout=self.settings.request_timeout)
        if resp.status_code >= 400:
            try:
                err = resp.json().get("error", {})
                message = err.get("message", resp.text)
            except ValueError:
                message = resp.text
            raise SolverError(f"Google Route Optimization returned {resp.status_code}: {message}")
        return resp.json()

    # -------------------------------------------------------------- model building

    @staticmethod
    def _visit(plan_date: date, v: VisitInput) -> dict:
        visit: dict[str, Any] = {
            "arrivalLocation": {"latitude": v.latitude, "longitude": v.longitude},
            "duration": f"{v.duration_seconds}s",
        }
        if v.window_start is not None or v.window_end is not None or v.soft_end is not None:
            tw: dict[str, Any] = {}
            if v.window_start is not None:
                tw["startTime"] = _ts(plan_date, v.window_start)
            if v.window_end is not None:
                tw["endTime"] = _ts(plan_date, v.window_end)
            if v.soft_end is not None and v.cost_per_hour_after_soft_end > 0:
                tw["softEndTime"] = _ts(plan_date, v.soft_end)
                tw["costPerHourAfterSoftEndTime"] = v.cost_per_hour_after_soft_end
            visit["timeWindows"] = [tw]
        return visit

    def _shipment(self, req: OptimizeRequest, s: ShipmentInput) -> dict:
        shipment: dict[str, Any] = {
            "label": s.label,
            "deliveries": [self._visit(req.plan_date, s.delivery)],
        }
        if s.include_pickup_visit and s.pickup is not None:
            shipment["pickups"] = [self._visit(req.plan_date, s.pickup)]
        if s.demand > 0:
            shipment["loadDemands"] = {req.load_key: {"amount": str(s.demand)}}
        if s.penalty_cost > 0:
            shipment["penaltyCost"] = s.penalty_cost
        return shipment

    def _vehicle(self, req: OptimizeRequest, v: VehicleInput) -> dict:
        vehicle: dict[str, Any] = {
            "label": v.label,
            "costPerKilometer": v.cost_per_kilometer,
            "startTimeWindows": [{"startTime": _ts(req.plan_date, v.start_time)}],
            "endTimeWindows": [{"endTime": _ts(req.plan_date, v.end_time)}],
            "routeModifiers": {"avoidTolls": v.avoid_tolls, "avoidHighways": v.avoid_highways},
        }
        if v.capacity > 0:
            vehicle["loadLimits"] = {req.load_key: {"maxLoad": str(v.capacity)}}
        if not v.omit_start_location:
            vehicle["startLocation"] = {"latitude": v.start_latitude, "longitude": v.start_longitude}
        if v.end_latitude is not None and v.end_longitude is not None:
            vehicle["endLocation"] = {"latitude": v.end_latitude, "longitude": v.end_longitude}
        if v.fixed_cost > 0:
            vehicle["fixedCost"] = v.fixed_cost
        if v.break_start is not None and v.break_duration > 0:
            vehicle["breakRule"] = {
                "breakRequests": [
                    {
                        "earliestStartTime": _ts(req.plan_date, v.break_start),
                        "latestStartTime": _ts(req.plan_date, v.break_start),
                        "minDuration": f"{v.break_duration}s",
                    }
                ]
            }
        return vehicle

    def build_body(self, req: OptimizeRequest) -> dict:
        return {
            "model": {
                "globalStartTime": _ts(req.plan_date, req.global_start),
                "globalEndTime": _ts(req.plan_date, req.global_end),
                "shipments": [self._shipment(req, s) for s in req.shipments],
                "vehicles": [self._vehicle(req, v) for v in req.vehicles],
            },
            "searchMode": req.search_mode,
            "timeout": f"{req.timeout_seconds}s",
            "considerRoadTraffic": req.consider_road_traffic,
            "populatePolylines": True,
            "populateTransitionPolylines": False,
        }

    # -------------------------------------------------------------- port

    def optimize_tours(self, request: OptimizeRequest) -> OptimizeResult:
        body = self.build_body(request)
        logger.info("Calling Google optimizeTours with %d shipments and %d vehicles", len(request.shipments), len(request.vehicles))
        return self.parse_response(request.plan_date, self._post(body))

    @staticmethod
    def parse_response(plan_date: date, data: dict) -> OptimizeResult:
        messages: list[tuple[str, str]] = []
        for v in data.get("validationErrors", []) or []:
            code = v.get("code", 0)
            severity = "warning" if code == DEADLINE_CODE else "error"
            messages.append((severity, f"Google validation {code}: {v.get('displayName') or v.get('errorMessage') or ''}".strip()))

        routes: list[SolvedRoute] = []
        for r in data.get("routes", []) or []:
            visits = [
                SolvedVisit(
                    shipment_index=int(v.get("shipmentIndex", 0)),
                    is_pickup=bool(v.get("isPickup", False)),
                    start_time=_parse_ts(plan_date, v.get("startTime")) or 0,
                )
                for v in r.get("visits", []) or []
            ]
            metrics = r.get("metrics", {}) or {}
            routes.append(
                SolvedRoute(
                    vehicle_index=int(r.get("vehicleIndex", 0)),
                    visits=visits,
                    polyline=(r.get("routePolyline") or {}).get("points", ""),
                    travel_seconds=_dur(metrics.get("travelDuration")),
                    travel_meters=int(float(metrics.get("travelDistanceMeters", 0) or 0)),
                    start_time=_parse_ts(plan_date, r.get("vehicleStartTime")),
                    end_time=_parse_ts(plan_date, r.get("vehicleEndTime")),
                )
            )

        skipped = []
        for s in data.get("skippedShipments", []) or []:
            reasons = [str(x.get("code", "UNSPECIFIED")) for x in s.get("reasons", []) or []]
            skipped.append((int(s.get("index", 0)), "Skipped by Google: " + (", ".join(reasons) or "no feasible route")))

        total_cost = float((data.get("metrics") or {}).get("totalCost", 0) or 0)
        return OptimizeResult(routes=routes, skipped=skipped, total_cost=total_cost, messages=messages)

    def return_leg(self, plan_date, start, end, depart_at, consider_road_traffic, avoid_tolls, avoid_highways) -> ReturnLeg:
        req = OptimizeRequest(
            plan_date=plan_date,
            load_key="weight",
            shipments=[
                ShipmentInput(
                    label="round-trip-return",
                    demand=0,
                    pickup=VisitInput(start[0], start[1]),
                    delivery=VisitInput(end[0], end[1]),
                )
            ],
            vehicles=[
                VehicleInput(
                    label="return",
                    capacity=0,
                    start_time=depart_at,
                    end_time=depart_at + 24 * 3600,
                    avoid_tolls=avoid_tolls,
                    avoid_highways=avoid_highways,
                )
            ],
            global_start=depart_at,
            global_end=depart_at + 24 * 3600,
            consider_road_traffic=consider_road_traffic,
            search_mode="RETURN_FAST",
            timeout_seconds=10,
        )
        result = self.optimize_tours(req)
        route = next((r for r in result.routes if r.visits), None)
        if route is None:
            raise SolverError("Google could not route the return leg")
        return ReturnLeg(route.travel_seconds, route.travel_meters, route.polyline)
