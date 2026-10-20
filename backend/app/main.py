"""FastAPI app: Multi Pick route optimization (drafts, preview, shipment planning)."""
from __future__ import annotations

import logging
import os
import uuid

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db
from .models import (
    DeleteDraftsRequest,
    DraftRow,
    PreviewRouteOptimizationRequest,
    PreviewRouteOptimizationResponse,
    SaveDraftsRequest,
    SaveDraftsResponse,
    SaveShipmentPlanningRequest,
    SearchDraftsRequest,
    ShipmentPlanning,
    ValidationMessage,
    VehicleType,
    VehicleTypeInput,
)
from .preview import PreviewValidationError, preview_route_optimization
from .solvers.base import RouteOptimizationService
from .solvers.google import GoogleRouteOptimizationService, GoogleRouteOptimizationSettings
from .solvers.local import LocalRouteOptimizationService

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("route_optimizer")


def build_service() -> RouteOptimizationService:
    mode = os.environ.get("RO_SOLVER", "auto").lower()
    settings = GoogleRouteOptimizationSettings()
    if mode == "google" or (mode == "auto" and settings.configured):
        if not settings.configured:
            raise RuntimeError("RO_SOLVER=google requires GOOGLE_ROUTE_OPTIMIZATION_PROJECT_ID")
        return GoogleRouteOptimizationService(settings)
    return LocalRouteOptimizationService()


app = FastAPI(title="Route Optimization (Multi Pick RO)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
db.init_db()
service = build_service()


def require_auth(authorization: str | None = Header(default=None)) -> None:
    token = os.environ.get("API_TOKEN")
    if token and authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "solver": service.name}


api = APIRouter(dependencies=[Depends(require_auth)], tags=["Orders"])


@api.get("/vehicle-types", response_model=list[VehicleType])
def list_vehicle_types():
    return db.list_vehicle_types()


@api.post("/vehicle-types", response_model=VehicleType)
def create_vehicle_type(body: VehicleTypeInput):
    if body.max_weight <= 0 and body.max_volume <= 0:
        raise HTTPException(status_code=400, detail="Vehicle type needs max weight or max volume greater than 0")
    vt = db.create_vehicle_type(body.name, body.max_weight, body.max_volume)
    logger.info("Created vehicle type %s", vt["id"])
    return vt


@api.post("/orders/route-optimization/drafts", response_model=SaveDraftsResponse)
def save_drafts(body: SaveDraftsRequest):
    if not body.rows:
        raise HTTPException(status_code=400, detail="No rows to save")
    missing = [i + 1 for i, r in enumerate(body.rows) if not r.do_number.strip()]
    if missing:
        raise HTTPException(status_code=400, detail=f"DO Number is required (rows {missing[:10]})")
    batch_id = body.import_batch_id or str(uuid.uuid4())
    rows = db.save_drafts([r.model_dump() for r in body.rows], batch_id, body.is_multi_pickup)
    logger.info("Saved %d route optimization drafts in batch %s", len(rows), batch_id)
    return {"import_batch_id": batch_id, "rows": rows}


@api.post("/orders/route-optimization/drafts/search", response_model=list[DraftRow])
def search_drafts(body: SearchDraftsRequest):
    return db.search_drafts(body.is_multi_pickup, body.include_proceeded)


@api.post("/orders/route-optimization/drafts/delete")
def delete_drafts(body: DeleteDraftsRequest):
    count = db.delete_drafts(body.ids)
    if count == 0 and body.ids:
        logger.warning("Delete drafts: none of %d ids were found", len(body.ids))
    else:
        logger.info("Soft-deleted %d drafts", count)
    return {"deleted": count}


@api.post("/orders/route-optimization/preview", response_model=PreviewRouteOptimizationResponse)
def preview(body: PreviewRouteOptimizationRequest):
    body.allow_capacity_exceed = False  # public API always applies capacity checks
    try:
        return preview_route_optimization(body, service, db.get_vehicle_types)
    except PreviewValidationError as e:
        logger.warning("Preview validation failed: %s", e)
        resp = PreviewRouteOptimizationResponse(
            solver=service.name,
            validation_errors=[ValidationMessage(severity="error", message=m) for m in e.messages],
        )
        return JSONResponse(status_code=400, content=resp.model_dump(by_alias=True, mode="json"))


@api.post("/orders/route-optimization/shipment-planning", response_model=ShipmentPlanning)
def save_shipment_planning(body: SaveShipmentPlanningRequest):
    if not body.routes:
        raise HTTPException(status_code=400, detail="Select at least one route to proceed")
    draft_ids = sorted({v.draft_id for r in body.routes for v in r.visits if v.draft_id})
    record = db.save_shipment_planning(
        body.import_batch_ids,
        body.plan_date.isoformat() if body.plan_date else None,
        body.model_dump(by_alias=True, mode="json"),
        draft_ids,
        body.mark_drafts_proceeded,
    )
    logger.info("Saved shipment planning %s with %d routes", record["id"], record["route_count"])
    return record


@api.get("/orders/route-optimization/shipment-planning", response_model=list[ShipmentPlanning])
def list_shipment_planning():
    return db.list_shipment_plannings()


app.include_router(api)
