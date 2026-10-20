"""Offline fallback solver built on OR-Tools.

Mirrors the Google model closely enough for development without a GCP project:
pickup/delivery pairs, load limits, time windows, soft end costs, fixed vehicle
cost, breaks and an omitted start location. Travel uses straight-line distance
with a road factor and a constant speed, so polylines are straight segments.
"""
from __future__ import annotations

import math
import os

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from .. import polyline
from .base import OptimizeRequest, OptimizeResult, ReturnLeg, SolvedRoute, SolvedVisit, SolverError

ROAD_FACTOR = float(os.environ.get("LOCAL_SOLVER_ROAD_FACTOR", "1.3"))
SPEED_KMH = float(os.environ.get("LOCAL_SOLVER_SPEED_KMH", "35"))
# Arc costs are in metres, so 1 Google cost unit (1 km at costPerKilometer=1) = 1000 local units.
COST_SCALE = 1000


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def road_metres(a, b) -> int:
    return int(round(haversine_m(a, b) * ROAD_FACTOR))


def travel_seconds(metres: int) -> int:
    return int(round(metres / (SPEED_KMH * 1000 / 3600)))


class LocalRouteOptimizationService:
    name = "local"

    def __init__(self, time_limit_seconds: int | None = None) -> None:
        self.time_limit_override = time_limit_seconds

    def optimize_tours(self, req: OptimizeRequest) -> OptimizeResult:
        if any(not s.include_pickup_visit or s.pickup is None for s in req.shipments):
            raise SolverError("Local solver supports pickup-and-delivery shipments only")
        if any(not v.omit_start_location for v in req.vehicles):
            raise SolverError("Local solver supports vehicles with an omitted start location only")
        if not req.vehicles:
            raise SolverError("No vehicles")

        # node 0: virtual depot (zero-cost arcs => route starts at first pickup and ends at last delivery)
        coords: list[tuple[float, float]] = [(0.0, 0.0)]
        service: list[int] = [0]
        demand: list[int] = [0]
        windows: list[tuple[int | None, int | None]] = [(None, None)]
        soft: list[tuple[int | None, float]] = [(None, 0)]
        for s in req.shipments:
            for visit, sign in ((s.pickup, 1), (s.delivery, -1)):
                coords.append((visit.latitude, visit.longitude))
                service.append(visit.duration_seconds)
                demand.append(sign * s.demand)
                windows.append((visit.window_start, visit.window_end))
                soft.append((visit.soft_end, visit.cost_per_hour_after_soft_end))

        n = len(coords)
        dist = [[0] * n for _ in range(n)]
        for i in range(1, n):
            for j in range(1, n):
                if i != j:
                    dist[i][j] = road_metres(coords[i], coords[j])

        manager = pywrapcp.RoutingIndexManager(n, len(req.vehicles), 0)
        routing = pywrapcp.RoutingModel(manager)

        def dist_cb(fi, ti):
            return dist[manager.IndexToNode(fi)][manager.IndexToNode(ti)]

        def time_cb(fi, ti):
            f, t = manager.IndexToNode(fi), manager.IndexToNode(ti)
            return travel_seconds(dist[f][t]) + service[f]

        def demand_cb(fi):
            return demand[manager.IndexToNode(fi)]

        dist_idx = routing.RegisterTransitCallback(dist_cb)
        time_idx = routing.RegisterTransitCallback(time_cb)
        demand_idx = routing.RegisterUnaryTransitCallback(demand_cb)
        routing.SetArcCostEvaluatorOfAllVehicles(dist_idx)

        horizon = max(req.global_end, max(v.end_time for v in req.vehicles)) + 3600
        routing.AddDimension(time_idx, horizon, horizon, False, "Time")
        time_dim = routing.GetDimensionOrDie("Time")
        routing.AddDimensionWithVehicleCapacity(demand_idx, 0, [max(v.capacity, 0) for v in req.vehicles], True, "Load")
        load_dim = routing.GetDimensionOrDie("Load")

        for node in range(1, n):
            index = manager.NodeToIndex(node)
            lo, hi = windows[node]
            time_dim.CumulVar(index).SetRange(lo if lo is not None else req.global_start, hi if hi is not None else horizon)
            soft_end, cost_per_hour = soft[node]
            if soft_end is not None and cost_per_hour > 0:
                coef = max(1, int(round(cost_per_hour * COST_SCALE / 3600)))
                time_dim.SetCumulVarSoftUpperBound(index, soft_end, coef)

        solver = routing.solver()
        for i, s in enumerate(req.shipments):
            p, d = manager.NodeToIndex(1 + 2 * i), manager.NodeToIndex(2 + 2 * i)
            routing.AddPickupAndDelivery(p, d)
            solver.Add(routing.VehicleVar(p) == routing.VehicleVar(d))
            solver.Add(time_dim.CumulVar(p) <= time_dim.CumulVar(d))
            routing.AddDisjunction([p, d], max(1, int(s.penalty_cost * COST_SCALE)), 2)

        node_visit_transit = [service[manager.IndexToNode(i)] if i < routing.Size() else 0 for i in range(routing.Size())]
        for vi, v in enumerate(req.vehicles):
            start, end = routing.Start(vi), routing.End(vi)
            time_dim.CumulVar(start).SetRange(max(v.start_time, req.global_start), min(v.end_time, req.global_end))
            time_dim.CumulVar(end).SetRange(max(v.start_time, req.global_start), min(v.end_time, req.global_end))
            routing.AddVariableMaximizedByFinalizer(time_dim.CumulVar(start))
            routing.AddVariableMinimizedByFinalizer(time_dim.CumulVar(end))
            if v.fixed_cost > 0:
                routing.SetFixedCostOfVehicle(int(v.fixed_cost * COST_SCALE), vi)
            if v.break_start is not None and v.break_duration > 0:
                brk = solver.FixedDurationIntervalVar(v.break_start, v.break_start, v.break_duration, False, f"break-{vi}")
                time_dim.SetBreakIntervalsOfVehicle([brk], vi, node_visit_transit)

        params = pywrapcp.DefaultRoutingSearchParameters()
        params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
        params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        params.time_limit.seconds = self.time_limit_override or req.local_time_limit_seconds

        solution = routing.SolveWithParameters(params)
        if solution is None:
            return OptimizeResult(
                routes=[],
                skipped=[(i, "No feasible solution found") for i in range(len(req.shipments))],
                messages=[("error", "The local solver could not find any feasible plan for these constraints.")],
            )

        routes: list[SolvedRoute] = []
        visited: set[int] = set()
        for vi in range(len(req.vehicles)):
            index = routing.Start(vi)
            visits: list[SolvedVisit] = []
            nodes: list[int] = []
            index = solution.Value(routing.NextVar(index))
            while not routing.IsEnd(index):
                node = manager.IndexToNode(index)
                nodes.append(node)
                visits.append(
                    SolvedVisit(
                        shipment_index=(node - 1) // 2,
                        is_pickup=(node - 1) % 2 == 0,
                        start_time=solution.Value(time_dim.CumulVar(index)),
                    )
                )
                index = solution.Value(routing.NextVar(index))
            if not visits:
                routes.append(SolvedRoute(vi, [], "", 0, 0, None, None))
                continue
            visited.update(v.shipment_index for v in visits)
            metres = sum(dist[a][b] for a, b in zip(nodes, nodes[1:]))
            secs = sum(travel_seconds(dist[a][b]) for a, b in zip(nodes, nodes[1:]))
            start_t = visits[0].start_time
            end_t = visits[-1].start_time + service[nodes[-1]]
            routes.append(
                SolvedRoute(
                    vehicle_index=vi,
                    visits=visits,
                    polyline=polyline.encode([coords[x] for x in nodes]),
                    travel_seconds=secs,
                    travel_meters=metres,
                    start_time=start_t,
                    end_time=end_t,
                )
            )
        skipped = [
            (i, "Not assigned: no vehicle could serve it within capacity, time windows and shift")
            for i in range(len(req.shipments))
            if i not in visited
        ]
        return OptimizeResult(routes=routes, skipped=skipped, total_cost=solution.ObjectiveValue() / COST_SCALE)

    def return_leg(self, plan_date, start, end, depart_at, consider_road_traffic, avoid_tolls, avoid_highways) -> ReturnLeg:
        metres = road_metres(start, end)
        return ReturnLeg(travel_seconds(metres), metres, polyline.encode([start, end]))
