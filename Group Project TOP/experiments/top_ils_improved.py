from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import math
import random
import statistics
import time
from pathlib import Path
from typing import List, Sequence, Tuple


@dataclass
class TOPInstance:
    """Team Orienteering Problem instance.

    Nodes are indexed from 0..n-1.
    The instance can use either one depot (start=end) or two depots.
    """

    coordinates: Sequence[Tuple[float, float]]
    scores: Sequence[float]
    team_size: int
    max_route_distance: float
    start_depot: int = 0
    end_depot: int | None = None

    def __post_init__(self) -> None:
        if len(self.coordinates) != len(self.scores):
            raise ValueError("coordinates and scores must have equal length")
        if len(self.coordinates) < 2:
            raise ValueError("instance needs at least two nodes")
        if self.team_size <= 0:
            raise ValueError("team_size must be positive")
        if self.max_route_distance <= 0:
            raise ValueError("max_route_distance must be positive")
        if self.end_depot is None:
            self.end_depot = self.start_depot
        n = len(self.coordinates)
        if not (0 <= self.start_depot < n and 0 <= self.end_depot < n):
            raise ValueError("depot index out of range")

    @property
    def customer_nodes(self) -> List[int]:
        depots = {self.start_depot, self.end_depot}
        return [i for i in range(len(self.coordinates)) if i not in depots]


@dataclass
class TOPSolution:
    routes: List[List[int]]
    total_score: float


@dataclass
class ILSStats:
    cpu_time_seconds: float
    iterations: int
    last_improvement_iteration: int
    iterations_to_convergence: int
    stagnation_iterations: int
    accepted_worse_moves: int
    restarts_performed: int


def _euclidean(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _distance_matrix(coords: Sequence[Tuple[float, float]]) -> List[List[float]]:
    n = len(coords)
    d = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            dij = _euclidean(coords[i], coords[j])
            d[i][j] = dij
            d[j][i] = dij
    return d


def _route_length(route: Sequence[int], dist: Sequence[Sequence[float]]) -> float:
    return sum(dist[route[i]][route[i + 1]] for i in range(len(route) - 1))


def _total_distance(routes: Sequence[Sequence[int]], dist: Sequence[Sequence[float]]) -> float:
    return sum(_route_length(route, dist) for route in routes)


def _visited_set(routes: Sequence[Sequence[int]], depots: set[int]) -> set[int]:
    visited: set[int] = set()
    for route in routes:
        for node in route:
            if node not in depots:
                visited.add(node)
    return visited


def _total_score(routes: Sequence[Sequence[int]], scores: Sequence[float], depots: set[int]) -> float:
    return sum(scores[node] for node in _visited_set(routes, depots))


def _best_insertion_for_node(
    node: int,
    routes: Sequence[Sequence[int]],
    dist: Sequence[Sequence[float]],
    max_route_distance: float,
) -> Tuple[float, int, int]:
    """Return (extra_distance, route_index, insert_position)."""
    best = (float("inf"), -1, -1)
    for r_idx, route in enumerate(routes):
        route_len = _route_length(route, dist)
        for pos in range(len(route) - 1):
            i = route[pos]
            j = route[pos + 1]
            extra = dist[i][node] + dist[node][j] - dist[i][j]
            if route_len + extra <= max_route_distance and extra < best[0]:
                best = (extra, r_idx, pos + 1)
    return best


def _construct_initial_solution(
    instance: TOPInstance,
    dist: Sequence[Sequence[float]],
    rng: random.Random,
    alpha: float,
) -> TOPSolution:
    depots = {instance.start_depot, instance.end_depot}
    routes = [[instance.start_depot, instance.end_depot] for _ in range(instance.team_size)]
    unvisited = set(instance.customer_nodes)

    while unvisited:
        candidates = []
        for node in unvisited:
            extra, r_idx, pos = _best_insertion_for_node(
                node, routes, dist, instance.max_route_distance
            )
            if r_idx >= 0:
                value = instance.scores[node] / (1.0 + extra)
                candidates.append((value, node, extra, r_idx, pos))

        if not candidates:
            break

        candidates.sort(reverse=True, key=lambda x: x[0])
        rcl_size = max(1, int(math.ceil(alpha * len(candidates))))
        _, node, _, r_idx, pos = rng.choice(candidates[:rcl_size])
        routes[r_idx].insert(pos, node)
        unvisited.remove(node)

    return TOPSolution(routes=routes, total_score=_total_score(routes, instance.scores, depots))


def _try_insert_unvisited(
    routes: List[List[int]],
    unvisited: set[int],
    instance: TOPInstance,
    dist: Sequence[Sequence[float]],
) -> bool:
    best_rank = 0.0
    best_move = None
    for node in unvisited:
        extra, r_idx, pos = _best_insertion_for_node(
            node, routes, dist, instance.max_route_distance
        )
        if r_idx >= 0:
            rank = instance.scores[node] / (1.0 + extra)
            if rank > best_rank:
                best_rank = rank
                best_move = (node, r_idx, pos)

    if best_move is None:
        return False

    node, r_idx, pos = best_move
    routes[r_idx].insert(pos, node)
    unvisited.remove(node)
    return True


def _try_swap_with_unvisited(
    routes: List[List[int]],
    unvisited: set[int],
    instance: TOPInstance,
    dist: Sequence[Sequence[float]],
) -> bool:
    best_delta_score = 0.0
    best_move = None

    for r_idx, route in enumerate(routes):
        route_len = _route_length(route, dist)
        for pos in range(1, len(route) - 1):
            old = route[pos]
            prev_node = route[pos - 1]
            next_node = route[pos + 1]

            remove_delta = (
                dist[prev_node][next_node]
                - dist[prev_node][old]
                - dist[old][next_node]
            )

            for new in unvisited:
                add_delta = (
                    dist[prev_node][new]
                    + dist[new][next_node]
                    - dist[prev_node][next_node]
                )
                new_route_len = route_len + remove_delta + add_delta
                if new_route_len > instance.max_route_distance:
                    continue

                delta_score = instance.scores[new] - instance.scores[old]
                if delta_score > best_delta_score:
                    best_delta_score = delta_score
                    best_move = (r_idx, pos, old, new)

    if best_move is None:
        return False

    r_idx, pos, old, new = best_move
    routes[r_idx][pos] = new
    unvisited.remove(new)
    unvisited.add(old)
    return True


def _try_inter_route_relocate(
    routes: List[List[int]],
    instance: TOPInstance,
    dist: Sequence[Sequence[float]],
) -> bool:
    """Move one customer from one route to another if it shortens total distance."""
    route_lens = [_route_length(route, dist) for route in routes]
    best_delta = 0.0
    best_move = None

    for src_idx, src_route in enumerate(routes):
        if len(src_route) <= 2:
            continue
        for src_pos in range(1, len(src_route) - 1):
            node = src_route[src_pos]
            prev_src = src_route[src_pos - 1]
            next_src = src_route[src_pos + 1]
            remove_delta = (
                dist[prev_src][next_src] - dist[prev_src][node] - dist[node][next_src]
            )
            new_src_len = route_lens[src_idx] + remove_delta
            if new_src_len > instance.max_route_distance:
                continue

            for dst_idx, dst_route in enumerate(routes):
                if dst_idx == src_idx:
                    continue
                for dst_pos in range(len(dst_route) - 1):
                    i = dst_route[dst_pos]
                    j = dst_route[dst_pos + 1]
                    add_delta = dist[i][node] + dist[node][j] - dist[i][j]
                    new_dst_len = route_lens[dst_idx] + add_delta
                    if new_dst_len > instance.max_route_distance:
                        continue

                    total_delta = remove_delta + add_delta
                    if total_delta < best_delta:
                        best_delta = total_delta
                        best_move = (src_idx, src_pos, dst_idx, dst_pos + 1, node)

    if best_move is None:
        return False

    src_idx, src_pos, dst_idx, dst_insert, node = best_move
    del routes[src_idx][src_pos]
    routes[dst_idx].insert(dst_insert, node)
    return True


def _try_inter_route_swap(
    routes: List[List[int]],
    instance: TOPInstance,
    dist: Sequence[Sequence[float]],
) -> bool:
    """Swap two customers from different routes if it shortens total distance."""
    route_lens = [_route_length(route, dist) for route in routes]
    best_delta = 0.0
    best_move = None

    for a_idx in range(len(routes)):
        ra = routes[a_idx]
        if len(ra) <= 2:
            continue
        for b_idx in range(a_idx + 1, len(routes)):
            rb = routes[b_idx]
            if len(rb) <= 2:
                continue

            for pa in range(1, len(ra) - 1):
                a = ra[pa]
                a_prev = ra[pa - 1]
                a_next = ra[pa + 1]
                for pb in range(1, len(rb) - 1):
                    b = rb[pb]
                    b_prev = rb[pb - 1]
                    b_next = rb[pb + 1]

                    delta_a = (
                        dist[a_prev][b] + dist[b][a_next] - dist[a_prev][a] - dist[a][a_next]
                    )
                    delta_b = (
                        dist[b_prev][a] + dist[a][b_next] - dist[b_prev][b] - dist[b][b_next]
                    )
                    new_a_len = route_lens[a_idx] + delta_a
                    new_b_len = route_lens[b_idx] + delta_b
                    if (
                        new_a_len > instance.max_route_distance
                        or new_b_len > instance.max_route_distance
                    ):
                        continue

                    total_delta = delta_a + delta_b
                    if total_delta < best_delta:
                        best_delta = total_delta
                        best_move = (a_idx, pa, b_idx, pb)

    if best_move is None:
        return False

    a_idx, pa, b_idx, pb = best_move
    routes[a_idx][pa], routes[b_idx][pb] = routes[b_idx][pb], routes[a_idx][pa]
    return True


def _two_opt_route(
    route: List[int],
    dist: Sequence[Sequence[float]],
    max_route_distance: float,
) -> bool:
    improved = False
    route_len = _route_length(route, dist)

    while True:
        best_delta = 0.0
        best_i = -1
        best_j = -1

        for i in range(1, len(route) - 2):
            a = route[i - 1]
            b = route[i]
            for j in range(i + 1, len(route) - 1):
                c = route[j]
                d = route[j + 1]
                delta = (dist[a][c] + dist[b][d]) - (dist[a][b] + dist[c][d])
                if delta < best_delta:
                    best_delta = delta
                    best_i = i
                    best_j = j

        if best_i < 0:
            break

        trial = route[:best_i] + list(reversed(route[best_i : best_j + 1])) + route[best_j + 1 :]
        new_len = route_len + best_delta
        if new_len <= max_route_distance:
            route[:] = trial
            route_len = new_len
            improved = True
        else:
            break

    return improved


def _local_search(
    solution: TOPSolution,
    instance: TOPInstance,
    dist: Sequence[Sequence[float]],
) -> TOPSolution:
    routes = [route[:] for route in solution.routes]
    depots = {instance.start_depot, instance.end_depot}
    unvisited = set(instance.customer_nodes) - _visited_set(routes, depots)
    enable_inter_route = len(instance.customer_nodes) <= 180

    changed = True
    rounds = 0
    max_rounds = 80
    while changed and rounds < max_rounds:
        rounds += 1
        changed = False

        for route in routes:
            if _two_opt_route(route, dist, instance.max_route_distance):
                changed = True

        if _try_insert_unvisited(routes, unvisited, instance, dist):
            changed = True
            continue

        if _try_swap_with_unvisited(routes, unvisited, instance, dist):
            changed = True
            continue

        if enable_inter_route:
            # These moves keep score but often reduce route costs and unlock future insertions.
            if _try_inter_route_relocate(routes, instance, dist):
                changed = True
                continue

            if _try_inter_route_swap(routes, instance, dist):
                changed = True

    return TOPSolution(routes=routes, total_score=_total_score(routes, instance.scores, depots))


def _perturb(
    solution: TOPSolution,
    instance: TOPInstance,
    dist: Sequence[Sequence[float]],
    rng: random.Random,
    remove_fraction: float,
) -> TOPSolution:
    routes = [route[:] for route in solution.routes]
    depots = {instance.start_depot, instance.end_depot}

    visited_nodes = [node for route in routes for node in route if node not in depots]
    if not visited_nodes:
        return solution

    k = max(1, int(math.ceil(remove_fraction * len(visited_nodes))))
    to_remove = set(rng.sample(visited_nodes, min(k, len(visited_nodes))))

    for route in routes:
        filtered = [node for node in route if node in depots or node not in to_remove]
        if not filtered:
            filtered = [instance.start_depot, instance.end_depot]
        if filtered[0] != instance.start_depot:
            filtered.insert(0, instance.start_depot)
        if filtered[-1] != instance.end_depot:
            filtered.append(instance.end_depot)
        if len(filtered) == 1:
            filtered.append(instance.end_depot)
        route[:] = filtered

    partial = TOPSolution(routes=routes, total_score=_total_score(routes, instance.scores, depots))
    return _local_search(partial, instance, dist)


def _solve_top_ils_internal(
    instance: TOPInstance,
    iterations: int,
    seed: int | None,
    alpha: float,
    remove_fraction: float,
    restart_interval: int,
) -> Tuple[TOPSolution, ILSStats]:
    if not (0 < alpha <= 1.0):
        raise ValueError("alpha must be in (0, 1]")
    if not (0 < remove_fraction <= 1.0):
        raise ValueError("remove_fraction must be in (0, 1]")
    if iterations <= 0:
        raise ValueError("iterations must be positive")

    start_t = time.perf_counter()
    rng = random.Random(seed)
    dist = _distance_matrix(instance.coordinates)

    current = _local_search(_construct_initial_solution(instance, dist, rng, alpha), instance, dist)
    best = current

    last_improvement_iter = 0
    accepted_worse = 0
    restarts = 0
    stagnation = 0

    min_remove_fraction = max(0.05, remove_fraction * 0.5)
    max_remove_fraction = min(0.60, remove_fraction * 2.0)
    adaptive_remove_fraction = remove_fraction

    temperature = max(1.0, current.total_score * 0.02)
    cooling_rate = 0.997

    progress_step = max(1, iterations // 10)
    for it in range(1, iterations + 1):
        candidate = _perturb(current, instance, dist, rng, adaptive_remove_fraction)
        candidate = _local_search(candidate, instance, dist)

        score_delta = candidate.total_score - current.total_score
        current_dist = _total_distance(current.routes, dist)
        candidate_dist = _total_distance(candidate.routes, dist)

        accepted = False
        if score_delta > 0:
            current = candidate
            accepted = True
        elif abs(score_delta) <= 1e-12 and candidate_dist + 1e-9 < current_dist:
            # Tie-break by total route length.
            current = candidate
            accepted = True
        else:
            prob = math.exp(score_delta / max(1e-9, temperature))
            if rng.random() < prob:
                current = candidate
                accepted = True
                accepted_worse += 1

        if current.total_score > best.total_score:
            best = current
            last_improvement_iter = it
            stagnation = 0
            adaptive_remove_fraction = max(min_remove_fraction, adaptive_remove_fraction * 0.90)
            temperature = max(1.0, temperature * 0.98)
        elif abs(current.total_score - best.total_score) <= 1e-12 and accepted:
            stagnation += 1
        else:
            stagnation += 1

        if stagnation > 0 and stagnation % 10 == 0:
            adaptive_remove_fraction = min(max_remove_fraction, adaptive_remove_fraction * 1.15)
            temperature = min(max(1.0, best.total_score * 0.10), temperature * 1.20)

        temperature = max(0.10, temperature * cooling_rate)

        if restart_interval > 0 and it % restart_interval == 0:
            restarts += 1
            restarted = _local_search(_construct_initial_solution(instance, dist, rng, alpha), instance, dist)
            if restarted.total_score > current.total_score:
                current = restarted
            if restarted.total_score > best.total_score:
                best = restarted
                last_improvement_iter = it
                stagnation = 0

        # Reactive restart after long stagnation.
        if restart_interval > 0 and stagnation >= max(20, restart_interval):
            restarts += 1
            current = _local_search(_construct_initial_solution(instance, dist, rng, alpha), instance, dist)
            adaptive_remove_fraction = remove_fraction
            temperature = max(1.0, current.total_score * 0.02)
            stagnation = 0

        if it == 1 or it == iterations or it % progress_step == 0:
            print(
                f"[ils-improved] iter {it}/{iterations} "
                f"best={best.total_score:.2f} current={current.total_score:.2f} "
                f"stagnation={stagnation} restarts={restarts} "
                f"remove_frac={adaptive_remove_fraction:.3f} temp={temperature:.3f}"
            )

    cpu_t = time.perf_counter() - start_t
    stats = ILSStats(
        cpu_time_seconds=cpu_t,
        iterations=iterations,
        last_improvement_iteration=last_improvement_iter,
        iterations_to_convergence=last_improvement_iter,
        stagnation_iterations=iterations - last_improvement_iter,
        accepted_worse_moves=accepted_worse,
        restarts_performed=restarts,
    )
    return best, stats


def solve_top_ils(
    instance: TOPInstance,
    iterations: int = 300,
    seed: int | None = None,
    alpha: float = 0.2,
    remove_fraction: float = 0.25,
    restart_interval: int = 80,
) -> TOPSolution:
    best, _ = _solve_top_ils_internal(
        instance=instance,
        iterations=iterations,
        seed=seed,
        alpha=alpha,
        remove_fraction=remove_fraction,
        restart_interval=restart_interval,
    )
    return best


def solve_top_ils_with_stats(
    instance: TOPInstance,
    iterations: int = 300,
    seed: int | None = None,
    alpha: float = 0.2,
    remove_fraction: float = 0.25,
    restart_interval: int = 80,
) -> Tuple[TOPSolution, ILSStats]:
    return _solve_top_ils_internal(
        instance=instance,
        iterations=iterations,
        seed=seed,
        alpha=alpha,
        remove_fraction=remove_fraction,
        restart_interval=restart_interval,
    )


def _parse_top_instance_file(path: Path) -> TOPInstance:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) < 4:
        raise ValueError(f"Invalid file format: {path}")

    sep = ";" if ";" in lines[0] else None

    def parse_header_value(line: str, expected_key: str) -> str:
        parts = line.split(sep) if sep else line.split()
        if len(parts) < 2:
            raise ValueError(f"Invalid header line: {line}")
        key = parts[0].strip().lower()
        if key != expected_key:
            raise ValueError(f"Expected '{expected_key}' in line: {line}")
        return parts[1].strip()

    n = int(parse_header_value(lines[0], "n"))
    m = int(parse_header_value(lines[1], "m"))
    tmax = float(parse_header_value(lines[2], "tmax"))

    coords: List[Tuple[float, float]] = []
    scores: List[float] = []

    for line in lines[3 : 3 + n]:
        parts = line.split(sep) if sep else line.split()
        if len(parts) < 3:
            raise ValueError(f"Invalid node row: {line}")
        x = float(parts[0])
        y = float(parts[1])
        s = float(parts[2])
        coords.append((x, y))
        scores.append(s)

    if len(coords) != n:
        raise ValueError(f"Header n={n}, but found {len(coords)} nodes in {path}")

    zero_score_nodes = [i for i, s in enumerate(scores) if abs(s) < 1e-12]
    if len(zero_score_nodes) >= 2:
        start_depot = zero_score_nodes[0]
        end_depot = zero_score_nodes[-1]
    else:
        start_depot = 0
        end_depot = 0

    return TOPInstance(
        coordinates=coords,
        scores=scores,
        team_size=m,
        max_route_distance=tmax,
        start_depot=start_depot,
        end_depot=end_depot,
    )


def _route_score(route: Sequence[int], scores: Sequence[float], depots: set[int]) -> float:
    return sum(scores[node] for node in route if node not in depots)


def _solution_to_dict(solution: TOPSolution, instance: TOPInstance, stats: ILSStats) -> dict:
    dist = _distance_matrix(instance.coordinates)
    depots = {instance.start_depot, instance.end_depot}
    routes = []
    for idx, route in enumerate(solution.routes, start=1):
        routes.append(
            {
                "route_index": idx,
                "nodes": route,
                "score": _route_score(route, instance.scores, depots),
                "length": _route_length(route, dist),
            }
        )

    return {
        "instance": {
            "num_nodes": len(instance.coordinates),
            "team_size": instance.team_size,
            "max_route_distance": instance.max_route_distance,
            "start_depot": instance.start_depot,
            "end_depot": instance.end_depot,
        },
        "objective": {
            "total_score": solution.total_score,
        },
        "performance": {
            "cpu_time_seconds": stats.cpu_time_seconds,
            "iterations": stats.iterations,
            "iterations_to_convergence": stats.iterations_to_convergence,
            "last_improvement_iteration": stats.last_improvement_iteration,
            "stagnation_iterations": stats.stagnation_iterations,
            "accepted_worse_moves": stats.accepted_worse_moves,
            "restarts_performed": stats.restarts_performed,
            "num_lp_solves": None,
            "num_labels_generated": None,
        },
        "routes": routes,
    }


def _safe_mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return statistics.fmean(values)


def _safe_std(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values)


def _safe_median(values: List[float]) -> float:
    if not values:
        return 0.0
    return statistics.median(values)


def _safe_quantile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    if q <= 0:
        return min(values)
    if q >= 1:
        return max(values)
    ordered = sorted(values)
    idx = int(round((len(ordered) - 1) * q))
    return ordered[idx]


def _write_runtime_vs_size_plot(rows: List[dict], plot_path: Path) -> str:
    try:
        import matplotlib.pyplot as plt  # type: ignore
    except Exception:
        return "matplotlib unavailable, plot not generated"

    sizes = [float(r["num_nodes"]) for r in rows]
    runtimes = [float(r["mean_cpu_time_seconds"]) for r in rows]

    plt.figure(figsize=(9, 6))
    plt.scatter(sizes, runtimes, alpha=0.65, s=22)
    plt.xlabel("Instance size (number of nodes)")
    plt.ylabel("Mean CPU time (seconds)")
    plt.title("ILS Runtime vs Instance Size")
    plt.grid(True, alpha=0.2)
    plt.tight_layout()
    plt.savefig(plot_path, dpi=150)
    plt.close()
    return "ok"


def run_dataset_experiments(
    datasets_root: Path,
    output_root: Path,
    iterations: int,
    seed: int,
    alpha: float,
    remove_fraction: float,
    restart_interval: int,
    runs_per_instance: int = 1,
    skip_existing: bool = True,
    max_instances_per_dataset: int | None = None,
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    per_instance_root = output_root / "instances"
    per_instance_root.mkdir(parents=True, exist_ok=True)

    dataset_names = ["chao", "dang", "vansteenwegen"]
    summary_rows: List[dict] = []
    by_instance_runs: dict[tuple[str, str], List[dict]] = {}

    for dataset in dataset_names:
        # Always create dedicated dataset output folders up front.
        (per_instance_root / dataset).mkdir(parents=True, exist_ok=True)

    error_rows: List[dict] = []

    for dataset in dataset_names:
        dataset_dir = datasets_root / dataset
        if not dataset_dir.exists():
            print(f"[skip] dataset folder missing: {dataset_dir}")
            continue

        files = sorted(dataset_dir.glob("*.txt"))
        if max_instances_per_dataset is not None:
            files = files[:max_instances_per_dataset]

        ds_output = per_instance_root / dataset
        print(f"[dataset] {dataset}: {len(files)} instances")

        for idx, file_path in enumerate(files):
            for run_idx in range(runs_per_instance):
                try:
                    json_path = ds_output / f"{file_path.stem}__run{run_idx:02d}.json"
                    if skip_existing and json_path.exists():
                        print(f"[skip] {dataset}/{file_path.name} run={run_idx} exists")
                        continue

                    instance = _parse_top_instance_file(file_path)
                    run_seed = seed + (idx * 1000) + run_idx
                    print(
                        f"[run] {dataset}/{file_path.name} run={run_idx} "
                        f"({idx + 1}/{len(files)})"
                    )
                    solution, stats = solve_top_ils_with_stats(
                        instance=instance,
                        iterations=iterations,
                        seed=run_seed,
                        alpha=alpha,
                        remove_fraction=remove_fraction,
                        restart_interval=restart_interval,
                    )

                    out_data = _solution_to_dict(solution, instance, stats)
                    out_data["dataset"] = dataset
                    out_data["instance_name"] = file_path.name
                    out_data["run_seed"] = run_seed
                    out_data["run_index"] = run_idx

                    json_path.write_text(json.dumps(out_data, indent=2), encoding="utf-8")
                    print(
                        f"[done] {dataset}/{file_path.name} run={run_idx} "
                        f"score={solution.total_score:.2f} cpu={stats.cpu_time_seconds:.3f}s "
                        f"iters_to_conv={stats.iterations_to_convergence}"
                    )
                except Exception as ex:
                    print(f"[error] {dataset}/{file_path.name} run={run_idx}: {ex}")
                    error_rows.append(
                        {
                            "dataset": dataset,
                            "instance": file_path.name,
                            "run_index": run_idx,
                            "run_seed": "",
                            "num_nodes": "",
                            "team_size": "",
                            "max_route_distance": "",
                            "total_score": "",
                            "cpu_time_seconds": "",
                            "iterations": iterations,
                            "iterations_to_convergence": "",
                            "last_improvement_iteration": "",
                            "stagnation_iterations": "",
                            "accepted_worse_moves": "",
                            "restarts_performed": "",
                            "num_lp_solves": "N/A (ILS)",
                            "num_labels_generated": "N/A (ILS)",
                            "status": f"error: {ex}",
                        }
                    )

    # Rebuild summary from all available run JSONs to make resume idempotent.
    for dataset in dataset_names:
        ds_output = per_instance_root / dataset
        if not ds_output.exists():
            continue
        for json_path in sorted(ds_output.glob("*.json")):
            try:
                out_data = json.loads(json_path.read_text(encoding="utf-8"))
                instance_obj = out_data.get("instance", {})
                perf = out_data.get("performance", {})
                objective = out_data.get("objective", {})
                row = {
                    "dataset": out_data.get("dataset", dataset),
                    "instance": out_data.get("instance_name", json_path.name),
                    "run_index": out_data.get("run_index", 0),
                    "run_seed": out_data.get("run_seed", ""),
                    "num_nodes": instance_obj.get("num_nodes", ""),
                    "team_size": instance_obj.get("team_size", ""),
                    "max_route_distance": instance_obj.get("max_route_distance", ""),
                    "total_score": objective.get("total_score", ""),
                    "cpu_time_seconds": perf.get("cpu_time_seconds", ""),
                    "iterations": perf.get("iterations", ""),
                    "iterations_to_convergence": perf.get("iterations_to_convergence", ""),
                    "last_improvement_iteration": perf.get("last_improvement_iteration", ""),
                    "stagnation_iterations": perf.get("stagnation_iterations", ""),
                    "accepted_worse_moves": perf.get("accepted_worse_moves", ""),
                    "restarts_performed": perf.get("restarts_performed", ""),
                    "num_lp_solves": "N/A (ILS)",
                    "num_labels_generated": "N/A (ILS)",
                    "status": "ok",
                }
                summary_rows.append(row)
                key = (str(row["dataset"]), str(row["instance"]))
                by_instance_runs.setdefault(key, []).append(row)
            except Exception as ex:
                error_rows.append(
                    {
                        "dataset": dataset,
                        "instance": json_path.name,
                        "run_index": "",
                        "run_seed": "",
                        "num_nodes": "",
                        "team_size": "",
                        "max_route_distance": "",
                        "total_score": "",
                        "cpu_time_seconds": "",
                        "iterations": iterations,
                        "iterations_to_convergence": "",
                        "last_improvement_iteration": "",
                        "stagnation_iterations": "",
                        "accepted_worse_moves": "",
                        "restarts_performed": "",
                        "num_lp_solves": "N/A (ILS)",
                        "num_labels_generated": "N/A (ILS)",
                        "status": f"error: invalid json output {ex}",
                    }
                )

    # Reference score is the best score found across runs per instance.
    reference_best: dict[tuple[str, str], float] = {}
    for key, rows in by_instance_runs.items():
        scores = [float(r["total_score"]) for r in rows]
        reference_best[key] = max(scores) if scores else 0.0

    for row in summary_rows:
        if row["status"] != "ok":
            row["reference_best_score"] = ""
            row["gap_to_reference_best_percent"] = ""
            row["success_reference_hit"] = ""
            continue
        key = (str(row["dataset"]), str(row["instance"]))
        ref = reference_best[key]
        score = float(row["total_score"])
        gap = 0.0 if ref <= 1e-12 else max(0.0, (ref - score) / ref * 100.0)
        hit = 1 if abs(score - ref) <= 1e-9 else 0
        row["reference_best_score"] = ref
        row["gap_to_reference_best_percent"] = gap
        row["success_reference_hit"] = hit

    summary_rows.extend(error_rows)

    instance_aggregate_rows: List[dict] = []
    quality_distribution_rows: List[dict] = []
    runtime_vs_size_rows: List[dict] = []

    for (dataset, instance_name), rows in sorted(by_instance_runs.items()):
        scores = [float(r["total_score"]) for r in rows]
        cpu = [float(r["cpu_time_seconds"]) for r in rows]
        gaps = [float(r["gap_to_reference_best_percent"]) for r in rows]
        it_conv = [float(r["iterations_to_convergence"]) for r in rows]
        success_hits = [int(r["success_reference_hit"]) for r in rows]

        num_nodes = int(rows[0]["num_nodes"])
        team_size = int(rows[0]["team_size"])

        agg = {
            "dataset": dataset,
            "instance": instance_name,
            "num_nodes": num_nodes,
            "team_size": team_size,
            "runs": len(rows),
            "reference_best_score": reference_best[(dataset, instance_name)],
            "best_score": max(scores),
            "mean_score": _safe_mean(scores),
            "std_score": _safe_std(scores),
            "mean_cpu_time_seconds": _safe_mean(cpu),
            "median_cpu_time_seconds": _safe_median(cpu),
            "mean_iterations_to_convergence": _safe_mean(it_conv),
            "success_rate_percent": 100.0 * _safe_mean([float(x) for x in success_hits]),
            "mean_gap_to_reference_best_percent": _safe_mean(gaps),
            "max_gap_to_reference_best_percent": max(gaps) if gaps else 0.0,
        }
        instance_aggregate_rows.append(agg)
        runtime_vs_size_rows.append(
            {
                "dataset": dataset,
                "instance": instance_name,
                "num_nodes": num_nodes,
                "mean_cpu_time_seconds": agg["mean_cpu_time_seconds"],
            }
        )

        for score, gap in zip(scores, gaps):
            quality_distribution_rows.append(
                {
                    "dataset": dataset,
                    "instance": instance_name,
                    "score": score,
                    "gap_to_reference_best_percent": gap,
                }
            )

    dataset_metrics_rows: List[dict] = []
    for dataset in dataset_names:
        ds_rows = [r for r in summary_rows if r["status"] == "ok" and r["dataset"] == dataset]
        if not ds_rows:
            continue

        gaps = [float(r["gap_to_reference_best_percent"]) for r in ds_rows]
        cpu = [float(r["cpu_time_seconds"]) for r in ds_rows]
        scores = [float(r["total_score"]) for r in ds_rows]
        it_conv = [float(r["iterations_to_convergence"]) for r in ds_rows]
        success = [float(r["success_reference_hit"]) for r in ds_rows]
        n_instances = len({(r["dataset"], r["instance"]) for r in ds_rows})

        dataset_metrics_rows.append(
            {
                "dataset": dataset,
                "num_instances": n_instances,
                "num_runs": len(ds_rows),
                "mean_cpu_time_seconds": _safe_mean(cpu),
                "median_cpu_time_seconds": _safe_median(cpu),
                "p90_cpu_time_seconds": _safe_quantile(cpu, 0.90),
                "mean_iterations_to_convergence": _safe_mean(it_conv),
                "mean_gap_to_reference_best_percent": _safe_mean(gaps),
                "median_gap_to_reference_best_percent": _safe_median(gaps),
                "p90_gap_to_reference_best_percent": _safe_quantile(gaps, 0.90),
                "success_rate_percent": 100.0 * _safe_mean(success),
                "score_mean": _safe_mean(scores),
                "score_std": _safe_std(scores),
                "score_p10": _safe_quantile(scores, 0.10),
                "score_p50": _safe_quantile(scores, 0.50),
                "score_p90": _safe_quantile(scores, 0.90),
            }
        )

    summary_path = output_root / "summary.csv"
    fieldnames = [
        "dataset",
        "instance",
        "run_index",
        "run_seed",
        "num_nodes",
        "team_size",
        "max_route_distance",
        "total_score",
        "reference_best_score",
        "gap_to_reference_best_percent",
        "success_reference_hit",
        "cpu_time_seconds",
        "iterations",
        "iterations_to_convergence",
        "last_improvement_iteration",
        "stagnation_iterations",
        "accepted_worse_moves",
        "restarts_performed",
        "num_lp_solves",
        "num_labels_generated",
        "status",
    ]
    with summary_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)

    instance_metrics_path = output_root / "instance_metrics.csv"
    with instance_metrics_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "dataset",
                "instance",
                "num_nodes",
                "team_size",
                "runs",
                "reference_best_score",
                "best_score",
                "mean_score",
                "std_score",
                "mean_cpu_time_seconds",
                "median_cpu_time_seconds",
                "mean_iterations_to_convergence",
                "success_rate_percent",
                "mean_gap_to_reference_best_percent",
                "max_gap_to_reference_best_percent",
            ],
        )
        writer.writeheader()
        writer.writerows(instance_aggregate_rows)

    dataset_metrics_path = output_root / "dataset_metrics.csv"
    with dataset_metrics_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "dataset",
                "num_instances",
                "num_runs",
                "mean_cpu_time_seconds",
                "median_cpu_time_seconds",
                "p90_cpu_time_seconds",
                "mean_iterations_to_convergence",
                "mean_gap_to_reference_best_percent",
                "median_gap_to_reference_best_percent",
                "p90_gap_to_reference_best_percent",
                "success_rate_percent",
                "score_mean",
                "score_std",
                "score_p10",
                "score_p50",
                "score_p90",
            ],
        )
        writer.writeheader()
        writer.writerows(dataset_metrics_rows)

    quality_distribution_path = output_root / "quality_distribution.csv"
    with quality_distribution_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["dataset", "instance", "score", "gap_to_reference_best_percent"],
        )
        writer.writeheader()
        writer.writerows(quality_distribution_rows)

    runtime_vs_size_path = output_root / "runtime_vs_instance_size.csv"
    with runtime_vs_size_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["dataset", "instance", "num_nodes", "mean_cpu_time_seconds"],
        )
        writer.writeheader()
        writer.writerows(runtime_vs_size_rows)

    plot_path = output_root / "runtime_vs_instance_size.png"
    plot_status = _write_runtime_vs_size_plot(runtime_vs_size_rows, plot_path)

    overview_path = output_root / "metrics_overview.json"
    overview = {
        "metric_notes": {
            "gap_to_optimum_note": (
                "Exact optimum values are not available for all TOP instances under ILS. "
                "Gap is reported against best score found across repeated runs per instance "
                "(reference_best_score)."
            ),
            "success_rate_note": (
                "success_reference_hit is 1 when a run matches reference_best_score for that instance. "
                "This is not a B&P optimality proof metric."
            ),
        },
        "config": {
            "iterations": iterations,
            "runs_per_instance": runs_per_instance,
            "seed": seed,
            "alpha": alpha,
            "remove_fraction": remove_fraction,
            "restart_interval": restart_interval,
        },
        "files": {
            "summary_csv": str(summary_path),
            "instance_metrics_csv": str(instance_metrics_path),
            "dataset_metrics_csv": str(dataset_metrics_path),
            "quality_distribution_csv": str(quality_distribution_path),
            "runtime_vs_instance_size_csv": str(runtime_vs_size_path),
            "runtime_vs_instance_size_plot": str(plot_path),
            "plot_status": plot_status,
        },
    }
    overview_path.write_text(json.dumps(overview, indent=2), encoding="utf-8")


def _pretty_print_solution(solution: TOPSolution, instance: TOPInstance) -> None:
    dist = _distance_matrix(instance.coordinates)
    depots = {instance.start_depot, instance.end_depot}
    print(f"Total score: {solution.total_score:.2f}")
    for idx, route in enumerate(solution.routes, start=1):
        route_score = _route_score(route, instance.scores, depots)
        length = _route_length(route, dist)
        print(
            f"Route {idx}: {' -> '.join(map(str, route))} | "
            f"score={route_score:.2f}, length={length:.2f}"
        )


def _demo() -> None:
    coords = [
        (0, 0),
        (2, 2),
        (4, 1),
        (6, 3),
        (1, 5),
        (3, 6),
        (7, 5),
        (8, 1),
        (5, 7),
    ]
    scores = [0, 8, 6, 9, 7, 10, 11, 5, 12]

    instance = TOPInstance(
        coordinates=coords,
        scores=scores,
        team_size=2,
        max_route_distance=18.0,
        start_depot=0,
        end_depot=0,
    )

    best, stats = solve_top_ils_with_stats(
        instance,
        iterations=400,
        seed=7,
        alpha=0.25,
        remove_fraction=0.30,
        restart_interval=100,
    )
    _pretty_print_solution(best, instance)
    print(f"CPU time (s): {stats.cpu_time_seconds:.4f}")
    print(f"Iterations to convergence: {stats.iterations_to_convergence}")


def main() -> None:
    parser = argparse.ArgumentParser(description="ILS for Team Orienteering Problem")
    parser.add_argument("--instance", type=str, default="", help="Path to one TOP instance file")
    parser.add_argument("--experiment", action="store_true", help="Run batch experiments from datasets folder")
    parser.add_argument("--datasets-root", type=str, default="datasets", help="Datasets root path")
    parser.add_argument("--output-root", type=str, default="output_ils_improved", help="Output root path")
    parser.add_argument("--iterations", type=int, default=300, help="ILS iterations")
    parser.add_argument("--seed", type=int, default=7, help="Random seed")
    parser.add_argument("--alpha", type=float, default=0.25, help="RCL ratio in construction")
    parser.add_argument("--remove-fraction", type=float, default=0.30, help="Perturbation destroy fraction")
    parser.add_argument("--restart-interval", type=int, default=100, help="Restart interval")
    parser.add_argument("--runs-per-instance", type=int, default=1, help="Independent runs per instance")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip already-generated run JSON files in output-root/instances",
    )
    parser.add_argument(
        "--max-instances-per-dataset",
        type=int,
        default=None,
        help="Optional cap for faster experiment runs",
    )

    args = parser.parse_args()

    if args.experiment:
        run_dataset_experiments(
            datasets_root=Path(args.datasets_root),
            output_root=Path(args.output_root),
            iterations=args.iterations,
            seed=args.seed,
            alpha=args.alpha,
            remove_fraction=args.remove_fraction,
            restart_interval=args.restart_interval,
            runs_per_instance=args.runs_per_instance,
            skip_existing=args.skip_existing,
            max_instances_per_dataset=args.max_instances_per_dataset,
        )
        print(f"Experiment complete. See output folder: {Path(args.output_root).resolve()}")
        return

    if args.instance:
        instance = _parse_top_instance_file(Path(args.instance))
        best, stats = solve_top_ils_with_stats(
            instance=instance,
            iterations=args.iterations,
            seed=args.seed,
            alpha=args.alpha,
            remove_fraction=args.remove_fraction,
            restart_interval=args.restart_interval,
        )
        _pretty_print_solution(best, instance)
        print(f"CPU time (s): {stats.cpu_time_seconds:.4f}")
        print(f"Iterations to convergence: {stats.iterations_to_convergence}")
        return

    _demo()


if __name__ == "__main__":
    main()
