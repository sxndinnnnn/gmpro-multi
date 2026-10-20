"""Solver port: the preview handler builds these inputs, adapters solve them.

All times are integer seconds from midnight (UTC) of the plan date.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Protocol


@dataclass
class VisitInput:
    latitude: float
    longitude: float
    duration_seconds: int = 0
    window_start: Optional[int] = None
    window_end: Optional[int] = None
    soft_end: Optional[int] = None
    cost_per_hour_after_soft_end: float = 0


@dataclass
class ShipmentInput:
    label: str
    demand: int  # scaled integer (see load_units)
    delivery: VisitInput
    pickup: Optional[VisitInput] = None
    include_pickup_visit: bool = True
    penalty_cost: float = 0


@dataclass
class VehicleInput:
    label: str
    capacity: int  # scaled integer
    start_time: int
    end_time: int
    omit_start_location: bool = True
    start_latitude: float = 0
    start_longitude: float = 0
    end_latitude: Optional[float] = None
    end_longitude: Optional[float] = None
    fixed_cost: float = 0
    cost_per_kilometer: float = 1
    avoid_tolls: bool = False
    avoid_highways: bool = False
    break_start: Optional[int] = None
    break_duration: int = 0


@dataclass
class OptimizeRequest:
    plan_date: date
    load_key: str  # "weight" | "volume"
    shipments: list[ShipmentInput]
    vehicles: list[VehicleInput]
    global_start: int
    global_end: int
    consider_road_traffic: bool
    search_mode: str
    timeout_seconds: int
    local_time_limit_seconds: int = 3


@dataclass
class SolvedVisit:
    shipment_index: int
    is_pickup: bool
    start_time: int


@dataclass
class SolvedRoute:
    vehicle_index: int
    visits: list[SolvedVisit]
    polyline: str
    travel_seconds: int
    travel_meters: int
    start_time: Optional[int]
    end_time: Optional[int]


@dataclass
class OptimizeResult:
    routes: list[SolvedRoute]
    skipped: list[tuple[int, str]]  # (shipment index, reason)
    total_cost: float = 0
    messages: list[tuple[str, str]] = field(default_factory=list)  # (severity, message)


@dataclass
class ReturnLeg:
    travel_seconds: int
    travel_meters: int
    polyline: str


class RouteOptimizationService(Protocol):
    name: str

    def optimize_tours(self, request: OptimizeRequest) -> OptimizeResult: ...

    def return_leg(
        self,
        plan_date: date,
        start: tuple[float, float],
        end: tuple[float, float],
        depart_at: int,
        consider_road_traffic: bool,
        avoid_tolls: bool,
        avoid_highways: bool,
    ) -> ReturnLeg: ...


class SolverError(Exception):
    pass
