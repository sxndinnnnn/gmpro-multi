"""Request / response contracts for the route optimization API.

Field names are camelCase on the wire to match the Orders page payloads.
"""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

EMPTY_GUID = "00000000-0000-0000-0000-000000000000"


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ---------------------------------------------------------------- drafts


class DraftRowInput(ApiModel):
    do_number: str
    weight: Optional[float] = None
    volume: Optional[float] = None
    pickup_location_code: Optional[str] = None
    pickup_latitude: Optional[float] = None
    pickup_longitude: Optional[float] = None
    delivery_location_code: Optional[str] = None
    delivery_latitude: Optional[float] = None
    delivery_longitude: Optional[float] = None
    priority: Optional[str] = None
    pickup_open_time: Optional[str] = None
    pickup_close_time: Optional[str] = None
    delivery_open_time: Optional[str] = None
    delivery_close_time: Optional[str] = None


class DraftRow(DraftRowInput):
    id: str
    import_batch_id: str
    is_multi_pickup: bool = False
    is_proceed: bool = False
    created_at: str


class SaveDraftsRequest(ApiModel):
    import_batch_id: Optional[str] = None
    is_multi_pickup: bool = False
    rows: list[DraftRowInput]


class SaveDraftsResponse(ApiModel):
    import_batch_id: str
    rows: list[DraftRow]


class SearchDraftsRequest(ApiModel):
    is_multi_pickup: bool = False
    include_proceeded: bool = False


class DeleteDraftsRequest(ApiModel):
    ids: list[str]


# ---------------------------------------------------------------- vehicles


class VehicleType(ApiModel):
    id: str
    name: str
    max_weight: float = 0
    max_volume: float = 0


class VehicleTypeInput(ApiModel):
    name: str
    max_weight: float = 0
    max_volume: float = 0


class VehicleSelection(ApiModel):
    vehicle_type_id: str
    count: int = 0


# ---------------------------------------------------------------- preview


class OrderRow(ApiModel):
    draft_id: Optional[str] = None
    import_batch_id: Optional[str] = None
    do_number: str
    weight: Optional[float] = None
    volume: Optional[float] = None
    pickup_location_code: Optional[str] = None
    pickup_latitude: Optional[float] = None
    pickup_longitude: Optional[float] = None
    delivery_location_code: Optional[str] = None
    delivery_latitude: Optional[float] = None
    delivery_longitude: Optional[float] = None
    priority: Optional[str] = None
    pickup_open_time: Optional[str] = None
    pickup_close_time: Optional[str] = None
    delivery_open_time: Optional[str] = None
    delivery_close_time: Optional[str] = None


TruckUse = Literal["minimizeVehicleCount", "useAllVehicles", "balanced"]


class PreviewRouteOptimizationRequest(ApiModel):
    pickup_location_id: str = EMPTY_GUID
    delivery_location_id: Optional[str] = None
    delivery_as_last_destination: bool = False
    multi_pickup: bool = True
    enable_route_trip: bool = False
    plan_date: date
    unloading_time_per_unit: float
    shift_start: str
    shift_end: str
    break_start: Optional[str] = None
    break_end: Optional[str] = None
    vehicles: list[VehicleSelection]
    truck_use: TruckUse = "minimizeVehicleCount"
    shortest_distance: bool = False
    avoid_toll: bool = False
    load_cost_factor: int = 0
    consider_road_traffic: bool = True
    allow_capacity_exceed: bool = False
    order_rows: list[OrderRow]


class ValidationMessage(ApiModel):
    severity: Literal["error", "warning"]
    message: str


class RouteVisit(ApiModel):
    sequence: int
    type: Literal["pickup", "delivery"]
    do_number: Optional[str] = None
    draft_id: Optional[str] = None
    location_name: Optional[str] = None
    latitude: float
    longitude: float
    arrival_time: Optional[str] = None
    departure_time: Optional[str] = None
    load_after: Optional[float] = None
    is_return: bool = False


class RouteResult(ApiModel):
    vehicle_label: str
    vehicle_type_id: str
    vehicle_type_name: str
    visits: list[RouteVisit]
    polyline: str = ""
    duration_seconds: int = 0
    distance_meters: int = 0
    load_amount: float = 0
    peak_load: float = 0
    capacity: float = 0
    utilization_percent: float = 0
    vehicle_start_time: Optional[str] = None
    vehicle_end_time: Optional[str] = None
    is_round_trip: bool = False


class SkippedShipment(ApiModel):
    draft_id: Optional[str] = None
    do_number: str
    reason: str
    priority: Optional[str] = None
    load_amount: float = 0


class Metrics(ApiModel):
    total_duration_seconds: int = 0
    total_distance_meters: int = 0
    total_cost: float = 0
    used_vehicle_count: int = 0


class PreviewRouteOptimizationResponse(ApiModel):
    solver: str
    load_dimension: Optional[Literal["weight", "volume"]] = None
    routes: list[RouteResult] = Field(default_factory=list)
    skipped_shipments: list[SkippedShipment] = Field(default_factory=list)
    unassigned_vehicles: list[str] = Field(default_factory=list)
    metrics: Metrics = Field(default_factory=Metrics)
    validation_errors: list[ValidationMessage] = Field(default_factory=list)


# ---------------------------------------------------------------- shipment planning


class SaveShipmentPlanningRequest(ApiModel):
    import_batch_ids: list[str] = Field(default_factory=list)
    plan_date: Optional[date] = None
    load_dimension: Optional[str] = None
    routes: list[RouteResult]
    metrics: Metrics = Field(default_factory=Metrics)
    skipped_shipments: list[SkippedShipment] = Field(default_factory=list)
    mark_drafts_proceeded: bool = True


class ShipmentPlanning(ApiModel):
    id: str
    created_at: str
    import_batch_ids: list[str]
    plan_date: Optional[str] = None
    route_count: int
    proceeded_draft_ids: list[str]
