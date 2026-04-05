from __future__ import annotations

from dataclasses import dataclass
import math
import random
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from .core import (
    Route,
    TOPInstance,
    copy_routes,
    greedy_initial_routes,
    make_route,
    route_customers,
    route_duration,
    route_profit,
    solution_customers,
    solution_profit,
)


@dataclass
class ILSResult:
    routes: List[Route]
    profit: float
    history: List[Dict[str, float]]
    stats: Dict[str, float]


def _route_with_nodes(inst: TOPInstance, nodes: Sequence[int]) -> Route:
    return Route(nodes=list(nodes), profit=route_profit(inst, nodes), duration=route_duration(inst, nodes))


def _recompute_route(inst: TOPInstance, route: Route) -> Route:
    route.profit = route_profit(inst, route.nodes)
    route.duration = route_duration(inst, route.nodes)
    return route


def _route_2opt(inst: TOPInstance, route: Route) -> Route:
    nodes = list(route.nodes)
    if len(nodes) <= 4:
        return _recompute_route(inst, route)

    improved = True
    best_nodes = nodes
    best_duration = route_duration(inst, nodes)
    while improved:
        improved = False
        for i in range(1, len(best_nodes) - 2):
            for j in range(i + 1, len(best_nodes) - 1):
                if j - i < 1:
                    continue
                candidate = best_nodes[:i] + list(reversed(best_nodes[i:j + 1])) + best_nodes[j + 1 :]
                candidate_duration = route_duration(inst, candidate)
                if candidate_duration + 1e-9 < best_duration and candidate_duration <= inst.T_max + 1e-9:
                    best_nodes = candidate
                    best_duration = candidate_duration
                    improved = True
                    break
            if improved:
                break
    return _route_with_nodes(inst, best_nodes)


def _optimize_solution(inst: TOPInstance, routes: List[Route]) -> List[Route]:
    return [_route_2opt(inst, route) for route in routes]


def _visited_set(routes: Sequence[Route]) -> set[int]:
    visited = set()
    for route in routes:
        visited.update(route_customers(route))
    return visited


def _best_insertion(inst: TOPInstance, routes: Sequence[Route], customer: int) -> Optional[Tuple[int, int, List[int], float]]:
    best = None
    for route_idx, route in enumerate(routes):
        nodes = route.nodes
        for pos in range(1, len(nodes)):
            prev_node = nodes[pos - 1]
            next_node = nodes[pos]
            new_duration = route.duration + inst.dist[prev_node, customer] + inst.dist[customer, next_node] - inst.dist[prev_node, next_node]
            if new_duration <= inst.T_max + 1e-9:
                new_nodes = nodes[:pos] + [customer] + nodes[pos:]
                if best is None or new_duration < best[3] - 1e-12:
                    best = (route_idx, pos, new_nodes, float(new_duration))
    return best


def _insert_customer(inst: TOPInstance, routes: List[Route], customer: int) -> bool:
    candidate = _best_insertion(inst, routes, customer)
    if candidate is None:
        return False
    route_idx, _, new_nodes, new_duration = candidate
    routes[route_idx] = _route_with_nodes(inst, new_nodes)
    return True


def _greedy_construct(inst: TOPInstance, rng: random.Random) -> List[Route]:
    routes = [Route(nodes=[inst.depot_start, inst.end()], profit=0.0, duration=route_duration(inst, [inst.depot_start, inst.end()])) for _ in range(inst.m)]
    customers = sorted(inst.customers, key=lambda c: (-inst.profits[c], rng.random()))
    for customer in customers:
        _insert_customer(inst, routes, customer)
    return _optimize_solution(inst, routes)


def _remove_customers(inst: TOPInstance, routes: List[Route], customers: Sequence[int]) -> List[Route]:
    to_remove = set(customers)
    new_routes: List[Route] = []
    for route in routes:
        kept = [node for node in route.nodes if node not in to_remove]
        if kept[0] != inst.depot_start:
            kept.insert(0, inst.depot_start)
        if kept[-1] != inst.end():
            kept.append(inst.end())
        if len(kept) < 2:
            kept = [inst.depot_start, inst.end()]
        new_routes.append(_route_with_nodes(inst, kept))
    return _optimize_solution(inst, new_routes)


def _perturb(inst: TOPInstance, routes: List[Route], strength: float, rng: random.Random, mode: str) -> List[Route]:
    active_customers = list(_visited_set(routes))
    if not active_customers:
        return copy_routes(routes)

    k = max(1, int(math.ceil(len(active_customers) * strength)))
    if mode == "adaptive" and len(active_customers) >= 2:
        ranked = sorted(active_customers, key=lambda c: (inst.profits[c], rng.random()))
        removed = ranked[: max(1, k // 2)]
        remaining = [c for c in active_customers if c not in removed]
        removed.extend(rng.sample(remaining, min(len(remaining), k - len(removed))))
    else:
        removed = rng.sample(active_customers, min(len(active_customers), k))

    perturbed = _remove_customers(inst, copy_routes(routes), removed)
    rng.shuffle(removed)
    for customer in removed:
        _insert_customer(inst, perturbed, customer)
    return _optimize_solution(inst, perturbed)


def _local_search(inst: TOPInstance, routes: List[Route], max_rounds: int = 20) -> List[Route]:
    current = _optimize_solution(inst, copy_routes(routes))
    improved = True
    rounds = 0
    while improved and rounds < max_rounds:
        rounds += 1
        improved = False
        visited = _visited_set(current)
        unvisited = sorted(set(inst.customers) - visited, key=lambda c: (-inst.profits[c], c))
        for customer in unvisited:
            if _insert_customer(inst, current, customer):
                current = _optimize_solution(inst, current)
                improved = True
                break
    return _optimize_solution(inst, current)


def _ils(
    inst: TOPInstance,
    iterations: int,
    seed: int,
    adaptive: bool,
    verbose: bool,
) -> ILSResult:
    rng = random.Random(seed)
    start = time.time()

    current = _greedy_construct(inst, rng)
    current = _local_search(inst, current)
    best = copy_routes(current)
    best_profit = solution_profit(best)
    history: List[Dict[str, float]] = [{"iteration": 0.0, "current_profit": float(solution_profit(current)), "best_profit": float(best_profit)}]

    stagnation = 0
    for iteration in range(1, iterations + 1):
        strength = 0.15 if not adaptive else min(0.60, 0.16 + 0.05 * stagnation)
        mode = "adaptive" if adaptive else "fixed"

        trials = 1 if not adaptive else 3
        candidate = None
        candidate_profit = -1.0
        base_solution = best if adaptive and stagnation >= 6 else current
        for _ in range(trials):
            perturbed = _perturb(inst, base_solution, strength=strength, rng=rng, mode=mode)
            perturbed = _local_search(inst, perturbed)
            perturbed_profit = solution_profit(perturbed)
            if perturbed_profit > candidate_profit + 1e-9:
                candidate = perturbed
                candidate_profit = perturbed_profit

        assert candidate is not None
        current_profit = solution_profit(current)

        if candidate_profit >= current_profit - 1e-9:
            current = candidate
            stagnation = 0
        else:
            stagnation += 1

        if candidate_profit > best_profit + 1e-9:
            best = copy_routes(candidate)
            best_profit = candidate_profit

        if adaptive and stagnation >= 8:
            current = _greedy_construct(inst, rng)
            current = _local_search(inst, current)
            stagnation = 0

        history.append(
            {
                "iteration": float(iteration),
                "current_profit": float(solution_profit(current)),
                "best_profit": float(best_profit),
                "strength": float(strength),
            }
        )

        if verbose and (iteration % 10 == 0 or iteration == 1):
            print(f"  ILS iter {iteration:03d} current={solution_profit(current):.2f} best={best_profit:.2f} strength={strength:.2f}")

    elapsed = time.time() - start
    stats = {
        "iterations": float(iterations),
        "cpu_time": float(round(elapsed, 4)),
        "best_profit": float(best_profit),
    }
    return ILSResult(routes=best, profit=best_profit, history=history, stats=stats)


def ils_basic(inst: TOPInstance, iterations: int = 100, seed: int = 0, verbose: bool = False) -> ILSResult:
    return _ils(inst=inst, iterations=iterations, seed=seed, adaptive=False, verbose=verbose)


def ils_modified(inst: TOPInstance, iterations: int = 100, seed: int = 0, verbose: bool = False) -> ILSResult:
    return _ils(inst=inst, iterations=iterations, seed=seed, adaptive=True, verbose=verbose)
