"""Capacity pre-check (PreviewRouteOptimizationCapacityAssigner).

Does not assign trucks. It only drops rows the selected fleet can never carry:
rows larger than every vehicle, or rows that would push the running total past
the whole fleet's capacity. Google does the actual assignment.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CapacityCheck:
    accepted: list[int]
    rejected: list[tuple[int, str]]


def check_capacity(demands: list[int], priorities: list[int], vehicle_capacities: list[int], format_units) -> CapacityCheck:
    """demands/capacities are scaled ints; priorities: higher = more important.

    Rows are considered by priority (highest first), keeping input order for ties.
    """
    max_cap = max(vehicle_capacities, default=0)
    fleet_total = sum(vehicle_capacities)
    order = sorted(range(len(demands)), key=lambda i: -priorities[i])
    accepted: list[int] = []
    rejected: list[tuple[int, str]] = []
    running = 0
    for i in order:
        d = demands[i]
        if d > max_cap:
            rejected.append((i, f"Capacity validation: load {format_units(d)} exceeds the largest selected vehicle ({format_units(max_cap)})"))
        elif running + d > fleet_total:
            rejected.append((i, f"Capacity validation: accepting this order would exceed total fleet capacity ({format_units(fleet_total)})"))
        else:
            running += d
            accepted.append(i)
    accepted.sort()
    return CapacityCheck(accepted, rejected)
