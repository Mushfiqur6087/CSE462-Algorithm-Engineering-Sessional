from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

import numpy as np


@dataclass
class TOPInstance:
    n: int
    m: int
    T_max: float
    profits: np.ndarray
    dist: np.ndarray
    depot_start: int = 0
    depot_end: int = -1

    def end(self) -> int:
        return self.n - 1 if self.depot_end == -1 else self.depot_end

    @property
    def customers(self) -> List[int]:
        return list(range(1, self.n - 1))


@dataclass
class Route:
    nodes: List[int]
    profit: float
    duration: float
    reduced_cost: float = 0.0


def route_profit(inst: TOPInstance, nodes: Sequence[int]) -> float:
    return float(np.sum(inst.profits[list(nodes[1:-1])])) if len(nodes) > 2 else 0.0


def route_duration(inst: TOPInstance, nodes: Sequence[int]) -> float:
    return float(sum(inst.dist[a, b] for a, b in zip(nodes[:-1], nodes[1:])))


def make_route(inst: TOPInstance, customers: Sequence[int]) -> Route:
    nodes = [inst.depot_start, *customers, inst.end()]
    return Route(nodes=nodes, profit=route_profit(inst, nodes), duration=route_duration(inst, nodes))


def route_signature(route: Route) -> Tuple[int, ...]:
    return tuple(route.nodes)


def route_customers(route: Route) -> Tuple[int, ...]:
    return tuple(route.nodes[1:-1])


def route_is_feasible(inst: TOPInstance, nodes: Sequence[int]) -> bool:
    return route_duration(inst, nodes) <= inst.T_max + 1e-9


def make_instance(
    n: int = 10,
    m: int = 2,
    T_max: float = 15.0,
    seed: int = 42,
    coord_scale: float = 10.0,
    profit_low: int = 1,
    profit_high: int = 10,
) -> TOPInstance:
    rng = np.random.default_rng(seed)
    coords = rng.uniform(0, coord_scale, (n, 2))
    dist = np.linalg.norm(coords[:, None, :] - coords[None, :, :], axis=-1)
    profits = np.zeros(n)
    if n > 2:
        profits[1:-1] = rng.integers(profit_low, profit_high, n - 2).astype(float)
    return TOPInstance(n=n, m=m, T_max=T_max, profits=profits, dist=dist)


def singleton_routes(inst: TOPInstance) -> List[Route]:
    routes = []
    for customer in inst.customers:
        nodes = [inst.depot_start, customer, inst.end()]
        if route_is_feasible(inst, nodes):
            routes.append(Route(nodes=nodes, profit=route_profit(inst, nodes), duration=route_duration(inst, nodes)))
    return routes


def greedy_initial_routes(inst: TOPInstance) -> List[Route]:
    used = set()
    routes: List[Route] = []
    s, e = inst.depot_start, inst.end()
    for _ in range(inst.m):
        best_customer = None
        best_score = (-1.0, float("inf"))
        for customer in inst.customers:
            if customer in used:
                continue
            nodes = [s, customer, e]
            duration = route_duration(inst, nodes)
            if duration <= inst.T_max + 1e-9:
                score = (inst.profits[customer], duration)
                if score[0] > best_score[0] or (score[0] == best_score[0] and score[1] < best_score[1]):
                    best_customer = customer
                    best_score = score
        if best_customer is None:
            routes.append(Route(nodes=[s, e], profit=0.0, duration=route_duration(inst, [s, e])))
        else:
            used.add(best_customer)
            nodes = [s, best_customer, e]
            routes.append(Route(nodes=nodes, profit=route_profit(inst, nodes), duration=route_duration(inst, nodes)))
    return routes


def empty_routes(inst: TOPInstance) -> List[Route]:
    return [Route(nodes=[inst.depot_start, inst.end()], profit=0.0, duration=route_duration(inst, [inst.depot_start, inst.end()])) for _ in range(inst.m)]


def unique_routes(routes: Sequence[Route]) -> List[Route]:
    seen = set()
    result = []
    for route in routes:
        signature = route_signature(route)
        if signature not in seen:
            seen.add(signature)
            result.append(route)
    return result


def copy_routes(routes: Sequence[Route]) -> List[Route]:
    return [Route(nodes=list(route.nodes), profit=route.profit, duration=route.duration, reduced_cost=route.reduced_cost) for route in routes]


def solution_profit(routes: Sequence[Route]) -> float:
    return float(sum(route.profit for route in routes))


def solution_customers(routes: Sequence[Route]) -> List[int]:
    customers = []
    for route in routes:
        customers.extend(route.nodes[1:-1])
    return customers
