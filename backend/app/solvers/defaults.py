"""Search mode and timeout chosen from shipment count (GoogleRouteOptimizationSolverDefaults)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SolverDefaults:
    search_mode: str
    timeout_seconds: int
    local_time_limit_seconds: int


def for_shipment_count(count: int) -> SolverDefaults:
    if count <= 25:
        return SolverDefaults("RETURN_FAST", 15, 2)
    if count <= 100:
        return SolverDefaults("RETURN_FAST", 30, 5)
    if count <= 300:
        return SolverDefaults("CONSUME_ALL_AVAILABLE_TIME", 60, 15)
    return SolverDefaults("CONSUME_ALL_AVAILABLE_TIME", 120, 30)


FIXED_COST_PER_VEHICLE_USED = 1_000_000
# Skipping must always cost more than opening a vehicle, otherwise the solver
# would drop orders to save the fixed cost.
SKIP_PENALTY_BASE = 10_000_000
