from __future__ import annotations

from dataclasses import dataclass, field
import heapq
import time
from itertools import combinations
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np
from scipy.optimize import linprog

from .core import (
    Route,
    TOPInstance,
    copy_routes,
    greedy_initial_routes,
    make_route,
    route_customers,
    route_duration,
    route_profit,
    route_signature,
    singleton_routes,
    unique_routes,
)


@dataclass(order=False)
class BPNode:
    depth: int
    lp_bound: float = float("inf")
    forced_in: List[Tuple[int, int]] = field(default_factory=list)
    forced_out: List[Tuple[int, int]] = field(default_factory=list)

    def __lt__(self, other: "BPNode") -> bool:
        return self.lp_bound > other.lp_bound


@dataclass
class BPSolution:
    routes: List[Route]
    profit: float
    stats: Dict[str, float]
    history: List[Dict[str, float]]


def route_respects_branch(route: Route, forced_in: Sequence[Tuple[int, int]], forced_out: Sequence[Tuple[int, int]]) -> bool:
    customers = set(route_customers(route))
    for i, j in forced_out:
        if i in customers and j in customers:
            return False
    for i, j in forced_in:
        has_i = i in customers
        has_j = j in customers
        if has_i != has_j:
            return False
    return True


def solve_rmp(inst: TOPInstance, routes: Sequence[Route]) -> Tuple[np.ndarray, np.ndarray, float, float]:
    routes = list(routes)
    if not routes:
        return np.zeros(0), np.zeros(inst.n), 0.0, 0.0

    interior = inst.customers
    n_r = len(routes)
    n_c = len(interior)

    A = np.zeros((n_c + 1, n_r))
    for r_idx, route in enumerate(routes):
        customer_set = set(route_customers(route))
        for c_idx, customer in enumerate(interior):
            if customer in customer_set:
                A[c_idx, r_idx] = 1.0
        A[-1, r_idx] = 1.0

    c = -np.array([route.profit for route in routes], dtype=float)
    bounds = [(0.0, 1.0)] * n_r
    b = np.ones(n_c + 1)
    b[-1] = inst.m

    res = linprog(c, A_ub=A, b_ub=b, bounds=bounds, method="highs")
    if not res.success:
        return np.zeros(n_r), np.zeros(inst.n), 0.0, 0.0

    x_vals = res.x
    duals = np.zeros(inst.n)
    customer_duals = np.zeros(inst.n)
    vehicle_dual = 0.0
    if getattr(res, "ineqlin", None) is not None:
        marginals = -np.asarray(res.ineqlin.marginals)
        for idx, customer in enumerate(interior):
            customer_duals[customer] = max(0.0, marginals[idx])
        vehicle_dual = max(0.0, float(marginals[-1]))
    duals[:] = customer_duals
    return x_vals, duals, vehicle_dual, float(-res.fun)


@dataclass
class Label:
    time_used: float
    reduced_profit: float
    mask: int
    path: Tuple[int, ...]


def _prune_labels(labels: List[Label]) -> List[Label]:
    labels = sorted(labels, key=lambda lbl: (lbl.time_used, -lbl.reduced_profit, lbl.mask))
    pareto: List[Label] = []
    for candidate in labels:
        dominated = False
        for existing in pareto:
            if (
                existing.time_used <= candidate.time_used + 1e-12
                and existing.reduced_profit >= candidate.reduced_profit - 1e-12
                and (existing.mask & candidate.mask) == existing.mask
            ):
                dominated = True
                break
        if not dominated:
            pareto.append(candidate)
    return pareto


def _route_satisfies_constraints(customer_tuple: Tuple[int, ...], forced_in: Sequence[Tuple[int, int]], forced_out: Sequence[Tuple[int, int]]) -> bool:
    customer_set = set(customer_tuple)
    for i, j in forced_out:
        if i in customer_set and j in customer_set:
            return False
    for i, j in forced_in:
        has_i = i in customer_set
        has_j = j in customer_set
        if has_i != has_j:
            return False
    return True


def pricing_dp(
    inst: TOPInstance,
    duals: np.ndarray,
    vehicle_dual: float,
    forced_in: Sequence[Tuple[int, int]] = (),
    forced_out: Sequence[Tuple[int, int]] = (),
    forbidden_paths: Optional[Set[Tuple[int, ...]]] = None,
) -> Optional[Route]:
    forbidden_paths = forbidden_paths or set()
    customers = inst.customers
    if not customers:
        return None

    reduced_profit = inst.profits - duals
    start = inst.depot_start
    end = inst.end()

    labels: Dict[int, List[Label]] = {start: [Label(0.0, 0.0, 0, (start,))]}
    best: Optional[Route] = None

    def consider(label: Label) -> None:
        nonlocal best
        customers_tuple = label.path[1:]
        full_path = (start, *customers_tuple, end)
        if full_path in forbidden_paths:
            return
        if not _route_satisfies_constraints(tuple(customers_tuple), forced_in, forced_out):
            return
        candidate_profit = float(sum(inst.profits[list(customers_tuple)])) if customers_tuple else 0.0
        candidate_rc = float(label.reduced_profit - vehicle_dual)
        candidate = Route(nodes=list(full_path), profit=candidate_profit, duration=label.time_used + inst.dist[label.path[-1], end], reduced_cost=candidate_rc)
        if candidate.reduced_cost > 1e-6 and (best is None or candidate.reduced_cost > best.reduced_cost + 1e-12):
            best = candidate

    consider(labels[start][0])

    for _ in range(len(customers)):
        next_labels: Dict[int, List[Label]] = {customer: [] for customer in customers}
        any_extension = False
        for last_node, bucket in labels.items():
            for label in bucket:
                consider(label)
                visited = set(label.path[1:])
                for customer in customers:
                    if customer in visited:
                        continue
                    new_time = label.time_used + inst.dist[last_node, customer]
                    if new_time + inst.dist[customer, end] > inst.T_max + 1e-9:
                        continue
                    any_extension = True
                    next_labels[customer].append(
                        Label(
                            time_used=float(new_time),
                            reduced_profit=float(label.reduced_profit + reduced_profit[customer]),
                            mask=label.mask | (1 << (customer - 1)),
                            path=label.path + (customer,),
                        )
                    )
        if not any_extension:
            break
        labels = {node: _prune_labels(bucket) for node, bucket in next_labels.items() if bucket}

    for bucket in labels.values():
        for label in bucket:
            consider(label)

    return best


def column_generation(
    inst: TOPInstance,
    routes: Sequence[Route],
    forced_in: Sequence[Tuple[int, int]] = (),
    forced_out: Sequence[Tuple[int, int]] = (),
    max_iter: int = 60,
    verbose: bool = False,
) -> Tuple[List[Route], np.ndarray, np.ndarray, float, float, List[Dict[str, float]]]:
    routes = unique_routes([route for route in routes if route_respects_branch(route, forced_in, forced_out)])
    history: List[Dict[str, float]] = []

    for iteration in range(max_iter):
        x_vals, duals, vehicle_dual, lp_obj = solve_rmp(inst, routes)
        history.append(
            {
                "iteration": float(iteration + 1),
                "lp_obj": float(lp_obj),
                "n_routes": float(len(routes)),
                "vehicle_dual": float(vehicle_dual),
            }
        )

        forbidden_paths = {route_signature(route) for route in routes}
        new_route = pricing_dp(inst, duals, vehicle_dual, forced_in=forced_in, forced_out=forced_out, forbidden_paths=forbidden_paths)
        if new_route is None:
            break
        routes.append(new_route)
        if verbose:
            print(f"  CG iter {iteration + 1:02d}: LP={lp_obj:.4f}  add={new_route.nodes}  rc={new_route.reduced_cost:.4f}")

    x_vals, duals, vehicle_dual, lp_obj = solve_rmp(inst, routes)
    return routes, x_vals, duals, vehicle_dual, lp_obj, history


def is_integer_solution(x_vals: np.ndarray, tol: float = 1e-5) -> bool:
    return bool(len(x_vals) == 0 or np.all((x_vals <= tol) | (x_vals >= 1.0 - tol)))


def extract_integer_solution(x_vals: np.ndarray, routes: Sequence[Route]) -> List[Route]:
    return [route for x, route in zip(x_vals, routes) if x > 0.5]


def choose_branch_pair(x_vals: np.ndarray, routes: Sequence[Route], rule: str = "best") -> Optional[Tuple[int, int]]:
    pair_sum: Dict[Tuple[int, int], float] = {}
    for x, route in zip(x_vals, routes):
        if x <= 1e-8:
            continue
        customers = sorted(route.nodes[1:-1])
        for i, j in combinations(customers, 2):
            pair_sum[(i, j)] = pair_sum.get((i, j), 0.0) + float(x)

    fractional = [(pair, total) for pair, total in pair_sum.items() if 1e-5 < total < 1.0 - 1e-5]
    if not fractional:
        return None

    if rule == "first":
        return fractional[0][0]

    fractional.sort(key=lambda item: (abs(item[1] - 0.5), -item[1]))
    return fractional[0][0]


def _branch_and_price(
    inst: TOPInstance,
    time_limit: float,
    verbose: bool,
    search: str,
    pair_rule: str,
    initial_pool: str,
) -> BPSolution:
    t_start = time.time()
    best_profit = 0.0
    best_routes: List[Route] = []
    nodes_explored = 0
    total_lp_solves = 0
    total_cg_iters = 0
    history: List[Dict[str, float]] = []

    base_pool = singleton_routes(inst)
    if initial_pool == "enhanced":
        base_pool = unique_routes(base_pool + greedy_initial_routes(inst))

    root = BPNode(depth=0, lp_bound=float("inf"))
    if search == "best_bound":
        queue: List[Tuple[float, int, BPNode]] = [(0.0, 0, root)]
    else:
        queue = [(0.0, 0, root)]
    tie = 0

    while queue and (time.time() - t_start) < time_limit:
        if search == "best_bound":
            _, _, node = heapq.heappop(queue)
        else:
            _, _, node = queue.pop()
        nodes_explored += 1

        node_pool = [route for route in base_pool if route_respects_branch(route, node.forced_in, node.forced_out)]
        routes, x_vals, duals, vehicle_dual, lp_obj, cg_history = column_generation(
            inst,
            node_pool,
            forced_in=node.forced_in,
            forced_out=node.forced_out,
            verbose=False,
        )
        total_cg_iters += len(cg_history)
        total_lp_solves += len(cg_history) + 1
        history.extend(cg_history)
        node.lp_bound = lp_obj

        if verbose:
            print(f"  Node {nodes_explored:03d} depth={node.depth} LP={lp_obj:.4f} routes={len(routes)}")

        if lp_obj <= best_profit + 1e-6:
            if verbose:
                print(f"    prune: LP {lp_obj:.4f} <= best {best_profit:.4f}")
            continue

        if is_integer_solution(x_vals):
            chosen = extract_integer_solution(x_vals, routes)
            profit = float(sum(route.profit for route in chosen))
            if profit > best_profit + 1e-6:
                best_profit = profit
                best_routes = copy_routes(chosen)
                if verbose:
                    print(f"    integer solution profit={profit:.4f} new-best")
            continue

        pair = choose_branch_pair(x_vals, routes, rule=pair_rule)
        if pair is None:
            continue

        if verbose:
            print(f"    branch on pair={pair}")

        left = BPNode(depth=node.depth + 1, lp_bound=lp_obj, forced_in=node.forced_in + [pair], forced_out=list(node.forced_out))
        right = BPNode(depth=node.depth + 1, lp_bound=lp_obj, forced_in=list(node.forced_in), forced_out=node.forced_out + [pair])
        tie += 1
        if search == "best_bound":
            heapq.heappush(queue, (-lp_obj, tie, left))
            tie += 1
            heapq.heappush(queue, (-lp_obj, tie, right))
        else:
            queue.append((lp_obj, tie, left))
            tie += 1
            queue.append((lp_obj, tie, right))

    elapsed = time.time() - t_start
    stats = {
        "nodes_explored": float(nodes_explored),
        "lp_solves": float(total_lp_solves),
        "cg_iterations": float(total_cg_iters),
        "cpu_time": float(round(elapsed, 4)),
        "status": 1.0 if len(queue) == 0 else 0.0,
    }
    return BPSolution(routes=best_routes, profit=best_profit, stats=stats, history=history)


def branch_and_price_basic(inst: TOPInstance, time_limit: float = 120.0, verbose: bool = False) -> BPSolution:
    return _branch_and_price(
        inst=inst,
        time_limit=time_limit,
        verbose=verbose,
        search="dfs",
        pair_rule="first",
        initial_pool="basic",
    )


def branch_and_price_modified(inst: TOPInstance, time_limit: float = 120.0, verbose: bool = False) -> BPSolution:
    return _branch_and_price(
        inst=inst,
        time_limit=time_limit,
        verbose=verbose,
        search="best_bound",
        pair_rule="best",
        initial_pool="enhanced",
    )
