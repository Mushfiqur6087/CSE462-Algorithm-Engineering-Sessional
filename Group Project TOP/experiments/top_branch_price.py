from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import math
import os
import random
import statistics
import time
from pathlib import Path
from typing import Callable, Dict, IO, List, Sequence, Tuple

import pulp


def _atomic_write_csv(path: Path, write_fn: Callable[[IO[str]], None]) -> None:
    """Write CSV via temp+replace; if locked, write a timestamped fallback file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("w", newline="", encoding="utf-8") as f:
            write_fn(f)
        os.replace(tmp, path)
    except PermissionError as e:
        # Windows often locks CSV files if opened in Excel/preview/editor.
        # Keep the run alive by writing to a fallback file instead of crashing.
        ts = int(time.time())
        fallback = path.with_name(f"{path.stem}__locked_write_{ts}{path.suffix}")
        try:
            with fallback.open("w", newline="", encoding="utf-8") as f:
                write_fn(f)
            print(
                f"[warn] could not overwrite locked file: {path.resolve()} "
                f"-> wrote fallback: {fallback.resolve()} ({e})"
            )
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
    except OSError:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


@dataclass
class TOPInstance:
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

    @property
    def customer_nodes(self) -> List[int]:
        depots = {self.start_depot, self.end_depot}
        return [i for i in range(len(self.coordinates)) if i not in depots]


@dataclass
class BPSolution:
    routes: List[List[int]]
    total_score: float


@dataclass
class BPStats:
    cpu_time_seconds: float
    cg_iterations: int
    lp_solves: int
    labels_generated: int
    columns_generated: int
    columns_in_pool: int
    fractional_columns_at_root: int
    restarts_performed: int = 0


@dataclass(frozen=True)
class RouteColumn:
    nodes: Tuple[int, ...]
    visited: Tuple[int, ...]
    score: float
    length: float


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


def _route_score(route: Sequence[int], instance: TOPInstance) -> float:
    depots = {instance.start_depot, instance.end_depot}
    return sum(instance.scores[n] for n in route if n not in depots)


def _safe_mean(values: List[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _safe_median(values: List[float]) -> float:
    return statistics.median(values) if values else 0.0


def _safe_std(values: List[float]) -> float:
    return statistics.stdev(values) if len(values) >= 2 else 0.0


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
        coords.append((float(parts[0]), float(parts[1])))
        scores.append(float(parts[2]))

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


def _make_column(route: List[int], instance: TOPInstance, dist: Sequence[Sequence[float]]) -> RouteColumn:
    depots = {instance.start_depot, instance.end_depot}
    visited = tuple(sorted([n for n in route if n not in depots]))
    return RouteColumn(
        nodes=tuple(route),
        visited=visited,
        score=_route_score(route, instance),
        length=_route_length(route, dist),
    )


def _initial_columns(instance: TOPInstance, dist: Sequence[Sequence[float]]) -> List[RouteColumn]:
    cols: List[RouteColumn] = []

    # Empty route column for slack in vehicle-count constraint.
    cols.append(_make_column([instance.start_depot, instance.end_depot], instance, dist))

    for i in instance.customer_nodes:
        route = [instance.start_depot, i, instance.end_depot]
        if _route_length(route, dist) <= instance.max_route_distance + 1e-9:
            cols.append(_make_column(route, instance, dist))

    # Add pair routes as richer initial basis where feasible.
    customers = instance.customer_nodes
    limit_pairs = min(len(customers), 40)
    for a_idx in range(limit_pairs):
        for b_idx in range(a_idx + 1, limit_pairs):
            a = customers[a_idx]
            b = customers[b_idx]
            for route in (
                [instance.start_depot, a, b, instance.end_depot],
                [instance.start_depot, b, a, instance.end_depot],
            ):
                if _route_length(route, dist) <= instance.max_route_distance + 1e-9:
                    cols.append(_make_column(route, instance, dist))

    # Remove duplicates by visited set and sequence.
    seen = set()
    uniq: List[RouteColumn] = []
    for c in cols:
        key = (c.visited, c.nodes)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    return uniq


def _solve_rmp(
    instance: TOPInstance,
    columns: List[RouteColumn],
    integer: bool,
) -> Tuple[float, List[float], Dict[int, float], float, int]:
    model = pulp.LpProblem("TOP_RMP", pulp.LpMaximize)
    cat = pulp.LpBinary if integer else pulp.LpContinuous

    x_vars = [pulp.LpVariable(f"x_{j}", lowBound=0, upBound=1, cat=cat) for j in range(len(columns))]

    model += pulp.lpSum(columns[j].score * x_vars[j] for j in range(len(columns)))

    customer_constraints: Dict[int, pulp.LpConstraint] = {}
    for i in instance.customer_nodes:
        c = pulp.lpSum((1 if i in columns[j].visited else 0) * x_vars[j] for j in range(len(columns))) <= 1
        cname = f"visit_{i}"
        model += c, cname
        customer_constraints[i] = model.constraints[cname]

    vehicle_cname = "vehicle_count"
    model += pulp.lpSum(x_vars) <= instance.team_size, vehicle_cname
    vehicle_con = model.constraints[vehicle_cname]

    solver = pulp.PULP_CBC_CMD(msg=False, mip=integer, threads=1)
    model.solve(solver)

    status = model.status
    if status not in (pulp.LpStatusOptimal,):
        return -1e18, [0.0] * len(columns), {i: 0.0 for i in instance.customer_nodes}, 0.0, status

    obj_val = pulp.value(model.objective)
    obj = float(obj_val) if obj_val is not None else 0.0
    x_vals = [float(v.value() if v.value() is not None else 0.0) for v in x_vars]

    duals = {i: 0.0 for i in instance.customer_nodes}
    sigma = 0.0
    if not integer:
        for i in instance.customer_nodes:
            try:
                duals[i] = float(customer_constraints[i].pi)
            except Exception:
                duals[i] = 0.0
        try:
            sigma = float(vehicle_con.pi)
        except Exception:
            sigma = 0.0

    return obj, x_vals, duals, sigma, status


def _pricing_heuristic(
    instance: TOPInstance,
    dist: Sequence[Sequence[float]],
    duals: Dict[int, float],
    sigma: float,
    existing: set[Tuple[int, ...]],
    rng: random.Random,
    trials: int,
    max_insertions: int,
) -> Tuple[List[RouteColumn], int]:
    labels_generated = 0
    candidates: List[Tuple[float, RouteColumn]] = []

    customers = instance.customer_nodes
    modified = {i: instance.scores[i] - duals.get(i, 0.0) for i in customers}

    for _ in range(trials):
        route = [instance.start_depot, instance.end_depot]
        in_route = set()

        for _step in range(max_insertions):
            best = None
            best_score = -1e18
            current_len = _route_length(route, dist)

            shuffled = customers[:]
            rng.shuffle(shuffled)
            for node in shuffled:
                if node in in_route:
                    continue
                if modified[node] <= 1e-9:
                    continue

                # Try every insertion edge.
                for pos in range(len(route) - 1):
                    labels_generated += 1
                    i = route[pos]
                    j = route[pos + 1]
                    extra = dist[i][node] + dist[node][j] - dist[i][j]
                    if current_len + extra > instance.max_route_distance + 1e-9:
                        continue
                    rank = modified[node] / (1.0 + extra)
                    if rank > best_score:
                        best_score = rank
                        best = (node, pos + 1)

            if best is None:
                break

            node, insert_pos = best
            route.insert(insert_pos, node)
            in_route.add(node)

        if len(route) <= 2:
            continue

        col = _make_column(route, instance, dist)
        if col.nodes in existing:
            continue

        reduced_profit = col.score - sum(duals.get(i, 0.0) for i in col.visited) - sigma
        if reduced_profit > 1e-6:
            candidates.append((reduced_profit, col))

    candidates.sort(key=lambda x: x[0], reverse=True)

    new_cols: List[RouteColumn] = []
    seen = set()
    for _rc, col in candidates:
        if col.nodes in seen:
            continue
        seen.add(col.nodes)
        new_cols.append(col)
        if len(new_cols) >= 8:
            break

    return new_cols, labels_generated


def solve_top_branch_and_price(
    instance: TOPInstance,
    seed: int | None = None,
    max_cg_iterations: int = 12,
    pricing_trials: int = 22,
    max_insertions: int = 18,
) -> Tuple[BPSolution, BPStats]:
    if max_cg_iterations <= 0:
        raise ValueError("max_cg_iterations must be positive")

    t0 = time.perf_counter()
    rng = random.Random(seed)
    dist = _distance_matrix(instance.coordinates)

    columns = _initial_columns(instance, dist)
    existing = {c.nodes for c in columns}

    lp_solves = 0
    labels_generated = 0
    columns_generated = len(columns)
    cg_iters_done = 0
    fractional_columns_at_root = 0

    # Column generation at root node.
    for cg_it in range(1, max_cg_iterations + 1):
        cg_iters_done = cg_it
        obj_lp, x_lp, duals, sigma, _status = _solve_rmp(instance, columns, integer=False)
        lp_solves += 1

        frac = sum(1 for x in x_lp if 1e-6 < x < 1 - 1e-6)
        fractional_columns_at_root = frac

        new_cols, n_labels = _pricing_heuristic(
            instance=instance,
            dist=dist,
            duals=duals,
            sigma=sigma,
            existing=existing,
            rng=rng,
            trials=pricing_trials,
            max_insertions=max_insertions,
        )
        labels_generated += n_labels

        if not new_cols:
            break

        for col in new_cols:
            columns.append(col)
            existing.add(col.nodes)
        columns_generated += len(new_cols)

    # Solve integer master over generated columns (branch-and-price style finalize).
    _obj_int, x_int, _duals, _sigma, _status_int = _solve_rmp(instance, columns, integer=True)

    selected_routes: List[List[int]] = []
    depots = {instance.start_depot, instance.end_depot}
    used_customers = set()
    for j, x in enumerate(x_int):
        if x < 0.5:
            continue
        route = list(columns[j].nodes)
        customers_in_route = [n for n in route if n not in depots]
        # Safety check to enforce set-packing interpretation in postprocessing.
        if any(c in used_customers for c in customers_in_route):
            continue
        selected_routes.append(route)
        for c in customers_in_route:
            used_customers.add(c)

    total_score = sum(instance.scores[i] for i in used_customers)

    # Fill unused vehicles with empty routes for consistent output shape.
    while len(selected_routes) < instance.team_size:
        selected_routes.append([instance.start_depot, instance.end_depot])

    cpu = time.perf_counter() - t0
    sol = BPSolution(routes=selected_routes, total_score=total_score)
    stats = BPStats(
        cpu_time_seconds=cpu,
        cg_iterations=cg_iters_done,
        lp_solves=lp_solves,
        labels_generated=labels_generated,
        columns_generated=columns_generated,
        columns_in_pool=len(columns),
        fractional_columns_at_root=fractional_columns_at_root,
    )
    return sol, stats


def _solution_to_dict(solution: BPSolution, instance: TOPInstance, stats: BPStats) -> dict:
    dist = _distance_matrix(instance.coordinates)
    depots = {instance.start_depot, instance.end_depot}
    routes = []
    for idx, route in enumerate(solution.routes, start=1):
        routes.append(
            {
                "route_index": idx,
                "nodes": route,
                "score": sum(instance.scores[n] for n in route if n not in depots),
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
        "objective": {"total_score": solution.total_score},
        "performance": {
            "cpu_time_seconds": stats.cpu_time_seconds,
            "iterations": stats.cg_iterations,
            "iterations_to_convergence": stats.cg_iterations,
            "last_improvement_iteration": stats.cg_iterations,
            "stagnation_iterations": 0,
            "accepted_worse_moves": 0,
            "restarts_performed": stats.restarts_performed,
            "num_lp_solves": stats.lp_solves,
            "num_labels_generated": stats.labels_generated,
            "columns_generated": stats.columns_generated,
            "columns_in_pool": stats.columns_in_pool,
            "fractional_columns_at_root": stats.fractional_columns_at_root,
        },
        "routes": routes,
    }


def run_dataset_experiments(
    datasets_root: Path,
    output_root: Path,
    seed: int,
    max_cg_iterations: int,
    pricing_trials: int,
    max_insertions: int,
    runs_per_instance: int = 1,
    skip_existing: bool = True,
    max_instances_per_dataset: int | None = None,
    solver_fn: Callable[..., Tuple[BPSolution, BPStats]] | None = None,
    solver_kwargs: dict | None = None,
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    per_instance_root = output_root / "instances"
    per_instance_root.mkdir(parents=True, exist_ok=True)

    dataset_names = ["chao", "dang", "vansteenwegen"]
    summary_rows: List[dict] = []
    by_instance_runs: dict[tuple[str, str], List[dict]] = {}
    error_rows: List[dict] = []

    for ds in dataset_names:
        (per_instance_root / ds).mkdir(parents=True, exist_ok=True)

    solver = solve_top_branch_and_price if solver_fn is None else solver_fn
    extra_solver_kwargs = {} if solver_kwargs is None else dict(solver_kwargs)

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
        skipped_existing = 0
        solved_runs = 0

        for idx, file_path in enumerate(files):
            for run_idx in range(runs_per_instance):
                json_path = ds_output / f"{file_path.stem}__run{run_idx:02d}.json"
                if skip_existing and json_path.exists():
                    skipped_existing += 1
                    continue

                try:
                    instance = _parse_top_instance_file(file_path)
                    run_seed = seed + (idx * 1000) + run_idx
                    print(f"[run] {dataset}/{file_path.name} run={run_idx} ({idx + 1}/{len(files)})")

                    solution, stats = solver(
                        instance=instance,
                        seed=run_seed,
                        max_cg_iterations=max_cg_iterations,
                        pricing_trials=pricing_trials,
                        max_insertions=max_insertions,
                        **extra_solver_kwargs,
                    )

                    out_data = _solution_to_dict(solution, instance, stats)
                    out_data["dataset"] = dataset
                    out_data["instance_name"] = file_path.name
                    out_data["run_seed"] = run_seed
                    out_data["run_index"] = run_idx
                    json_path.write_text(json.dumps(out_data, indent=2), encoding="utf-8")
                    solved_runs += 1
                except Exception as ex:
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
                            "iterations": "",
                            "iterations_to_convergence": "",
                            "last_improvement_iteration": "",
                            "stagnation_iterations": "",
                            "accepted_worse_moves": "",
                            "restarts_performed": "",
                            "num_lp_solves": "",
                            "num_labels_generated": "",
                            "status": f"error: {ex}",
                        }
                    )
        if skip_existing:
            print(
                f"[dataset-summary] {dataset}: solved_runs={solved_runs}, "
                f"skipped_existing={skipped_existing}"
            )

    # Rebuild summary from output JSONs for resume-idempotence.
    for dataset in dataset_names:
        ds_output = per_instance_root / dataset
        if not ds_output.exists():
            continue

        for json_path in sorted(ds_output.glob("*.json")):
            try:
                out_data = json.loads(json_path.read_text(encoding="utf-8"))
                inst = out_data.get("instance", {})
                perf = out_data.get("performance", {})
                obj = out_data.get("objective", {})

                row = {
                    "dataset": out_data.get("dataset", dataset),
                    "instance": out_data.get("instance_name", json_path.name),
                    "run_index": out_data.get("run_index", 0),
                    "run_seed": out_data.get("run_seed", ""),
                    "num_nodes": inst.get("num_nodes", ""),
                    "team_size": inst.get("team_size", ""),
                    "max_route_distance": inst.get("max_route_distance", ""),
                    "total_score": obj.get("total_score", ""),
                    "cpu_time_seconds": perf.get("cpu_time_seconds", ""),
                    "iterations": perf.get("iterations", ""),
                    "iterations_to_convergence": perf.get("iterations_to_convergence", ""),
                    "last_improvement_iteration": perf.get("last_improvement_iteration", ""),
                    "stagnation_iterations": perf.get("stagnation_iterations", ""),
                    "accepted_worse_moves": perf.get("accepted_worse_moves", ""),
                    "restarts_performed": perf.get("restarts_performed", ""),
                    "num_lp_solves": perf.get("num_lp_solves", ""),
                    "num_labels_generated": perf.get("num_labels_generated", ""),
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
                        "iterations": "",
                        "iterations_to_convergence": "",
                        "last_improvement_iteration": "",
                        "stagnation_iterations": "",
                        "accepted_worse_moves": "",
                        "restarts_performed": "",
                        "num_lp_solves": "",
                        "num_labels_generated": "",
                        "status": f"error: invalid json output {ex}",
                    }
                )

    reference_best: dict[tuple[str, str], float] = {}
    for key, rows in by_instance_runs.items():
        vals = [float(r["total_score"]) for r in rows]
        reference_best[key] = max(vals) if vals else 0.0

    for row in summary_rows:
        key = (str(row["dataset"]), str(row["instance"]))
        ref = reference_best.get(key, 0.0)
        score = float(row["total_score"])
        gap = 0.0 if ref <= 1e-12 else max(0.0, (ref - score) / ref * 100.0)
        hit = 1 if abs(score - ref) <= 1e-9 else 0
        row["reference_best_score"] = ref
        row["gap_to_reference_best_percent"] = gap
        row["success_reference_hit"] = hit

    summary_rows.extend(error_rows)

    summary_path = output_root / "summary.csv"
    summary_fields = [
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
    def _write_summary(f: IO[str]) -> None:
        w = csv.DictWriter(f, fieldnames=summary_fields)
        w.writeheader()
        w.writerows(summary_rows)

    _atomic_write_csv(summary_path, _write_summary)

    # Aggregate by instance.
    instance_rows: List[dict] = []
    quality_rows: List[dict] = []
    runtime_rows: List[dict] = []

    for (dataset, instance_name), rows in sorted(by_instance_runs.items()):
        scores = [float(r["total_score"]) for r in rows]
        cpu = [float(r["cpu_time_seconds"]) for r in rows]
        gaps = [float(r["gap_to_reference_best_percent"]) for r in rows]
        lp = [float(r["num_lp_solves"]) for r in rows]
        labels = [float(r["num_labels_generated"]) for r in rows]

        num_nodes = int(rows[0]["num_nodes"])
        team_size = int(rows[0]["team_size"])

        row = {
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
            "mean_lp_solves": _safe_mean(lp),
            "mean_labels_generated": _safe_mean(labels),
            "success_rate_percent": 100.0 * _safe_mean([float(r["success_reference_hit"]) for r in rows]),
            "mean_gap_to_reference_best_percent": _safe_mean(gaps),
            "max_gap_to_reference_best_percent": max(gaps) if gaps else 0.0,
        }
        instance_rows.append(row)
        runtime_rows.append(
            {
                "dataset": dataset,
                "instance": instance_name,
                "num_nodes": num_nodes,
                "mean_cpu_time_seconds": row["mean_cpu_time_seconds"],
            }
        )

        for score, gap in zip(scores, gaps):
            quality_rows.append(
                {
                    "dataset": dataset,
                    "instance": instance_name,
                    "score": score,
                    "gap_to_reference_best_percent": gap,
                }
            )

    def _write_instance_metrics(f: IO[str]) -> None:
        fields = [
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
            "mean_lp_solves",
            "mean_labels_generated",
            "success_rate_percent",
            "mean_gap_to_reference_best_percent",
            "max_gap_to_reference_best_percent",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(instance_rows)

    _atomic_write_csv(output_root / "instance_metrics.csv", _write_instance_metrics)

    dataset_rows: List[dict] = []
    for dataset in dataset_names:
        ds_rows = [r for r in summary_rows if r["status"] == "ok" and r["dataset"] == dataset]
        if not ds_rows:
            continue

        dataset_rows.append(
            {
                "dataset": dataset,
                "num_instances": len({(r["dataset"], r["instance"]) for r in ds_rows}),
                "num_runs": len(ds_rows),
                "mean_cpu_time_seconds": _safe_mean([float(r["cpu_time_seconds"]) for r in ds_rows]),
                "median_cpu_time_seconds": _safe_median([float(r["cpu_time_seconds"]) for r in ds_rows]),
                "p90_cpu_time_seconds": _safe_quantile([float(r["cpu_time_seconds"]) for r in ds_rows], 0.90),
                "mean_iterations_to_convergence": _safe_mean([float(r["iterations_to_convergence"]) for r in ds_rows]),
                "mean_gap_to_reference_best_percent": _safe_mean([float(r["gap_to_reference_best_percent"]) for r in ds_rows]),
                "median_gap_to_reference_best_percent": _safe_median([float(r["gap_to_reference_best_percent"]) for r in ds_rows]),
                "p90_gap_to_reference_best_percent": _safe_quantile([float(r["gap_to_reference_best_percent"]) for r in ds_rows], 0.90),
                "success_rate_percent": 100.0 * _safe_mean([float(r["success_reference_hit"]) for r in ds_rows]),
                "score_mean": _safe_mean([float(r["total_score"]) for r in ds_rows]),
                "score_std": _safe_std([float(r["total_score"]) for r in ds_rows]),
                "score_p10": _safe_quantile([float(r["total_score"]) for r in ds_rows], 0.10),
                "score_p50": _safe_quantile([float(r["total_score"]) for r in ds_rows], 0.50),
                "score_p90": _safe_quantile([float(r["total_score"]) for r in ds_rows], 0.90),
                "mean_lp_solves": _safe_mean([float(r["num_lp_solves"]) for r in ds_rows]),
                "mean_labels_generated": _safe_mean([float(r["num_labels_generated"]) for r in ds_rows]),
            }
        )

    def _write_dataset_metrics(f: IO[str]) -> None:
        fields = [
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
            "mean_lp_solves",
            "mean_labels_generated",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(dataset_rows)

    _atomic_write_csv(output_root / "dataset_metrics.csv", _write_dataset_metrics)

    def _write_quality_distribution(f: IO[str]) -> None:
        w = csv.DictWriter(f, fieldnames=["dataset", "instance", "score", "gap_to_reference_best_percent"])
        w.writeheader()
        w.writerows(quality_rows)

    _atomic_write_csv(output_root / "quality_distribution.csv", _write_quality_distribution)

    def _write_runtime_vs_size(f: IO[str]) -> None:
        w = csv.DictWriter(f, fieldnames=["dataset", "instance", "num_nodes", "mean_cpu_time_seconds"])
        w.writeheader()
        w.writerows(runtime_rows)

    _atomic_write_csv(output_root / "runtime_vs_instance_size.csv", _write_runtime_vs_size)

    try:
        import matplotlib.pyplot as plt  # type: ignore

        plt.figure(figsize=(9, 6))
        plt.scatter(
            [float(r["num_nodes"]) for r in runtime_rows],
            [float(r["mean_cpu_time_seconds"]) for r in runtime_rows],
            s=18,
            alpha=0.65,
        )
        plt.xlabel("Instance size (number of nodes)")
        plt.ylabel("Mean CPU time (seconds)")
        plt.title("Branch-and-Price Runtime vs Instance Size")
        plt.grid(True, alpha=0.2)
        plt.tight_layout()
        plt.savefig(output_root / "runtime_vs_instance_size.png", dpi=150)
        plt.close()
        plot_status = "ok"
    except Exception:
        plot_status = "matplotlib unavailable, plot not generated"

    overview = {
        "metric_notes": {
            "gap_to_optimum_note": (
                "Exact optimum values are not available for all instances in this practical B&P pipeline. "
                "Gap is reported against best score found across repeated runs per instance."
            ),
            "success_rate_note": (
                "success_reference_hit is 1 when a run matches reference_best_score for that instance."
            ),
            "bp_note": (
                "This is a practical branch-and-price style pipeline: LP column generation at root with heuristic pricing, "
                "then integer master over generated columns."
            ),
        },
        "config": {
            "seed": seed,
            "max_cg_iterations": max_cg_iterations,
            "pricing_trials": pricing_trials,
            "max_insertions": max_insertions,
            "runs_per_instance": runs_per_instance,
            "skip_existing": skip_existing,
        },
        "files": {
            "summary_csv": str(output_root / "summary.csv"),
            "instance_metrics_csv": str(output_root / "instance_metrics.csv"),
            "dataset_metrics_csv": str(output_root / "dataset_metrics.csv"),
            "quality_distribution_csv": str(output_root / "quality_distribution.csv"),
            "runtime_vs_instance_size_csv": str(output_root / "runtime_vs_instance_size.csv"),
            "runtime_vs_instance_size_plot": str(output_root / "runtime_vs_instance_size.png"),
            "plot_status": plot_status,
        },
    }
    (output_root / "metrics_overview.json").write_text(json.dumps(overview, indent=2), encoding="utf-8")


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
    )

    sol, stats = solve_top_branch_and_price(
        instance,
        seed=7,
        max_cg_iterations=8,
        pricing_trials=16,
        max_insertions=8,
    )

    print(f"Total score: {sol.total_score:.2f}")
    for i, r in enumerate(sol.routes, start=1):
        print(f"Route {i}: {' -> '.join(map(str, r))}")
    print(f"CPU time (s): {stats.cpu_time_seconds:.4f}")
    print(f"LP solves: {stats.lp_solves}")
    print(f"Labels generated: {stats.labels_generated}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Practical Branch-and-Price for TOP")
    parser.add_argument("--instance", type=str, default="", help="Path to one TOP instance")
    parser.add_argument("--experiment", action="store_true", help="Run batch experiments")
    parser.add_argument("--datasets-root", type=str, default="datasets", help="Datasets root path")
    parser.add_argument("--output-root", type=str, default="output_bp", help="Output root path")
    parser.add_argument("--seed", type=int, default=7, help="Random seed")
    parser.add_argument("--max-cg-iterations", type=int, default=12, help="Max column generation iterations")
    parser.add_argument("--pricing-trials", type=int, default=22, help="Pricing heuristic trials per CG iteration")
    parser.add_argument("--max-insertions", type=int, default=18, help="Max insertions in one pricing construction")
    parser.add_argument("--runs-per-instance", type=int, default=1, help="Independent runs per instance")
    parser.add_argument("--skip-existing", action="store_true", help="Skip already generated run JSON")
    parser.add_argument("--max-instances-per-dataset", type=int, default=None, help="Optional cap for quick tests")

    args = parser.parse_args()

    if args.experiment:
        run_dataset_experiments(
            datasets_root=Path(args.datasets_root),
            output_root=Path(args.output_root),
            seed=args.seed,
            max_cg_iterations=args.max_cg_iterations,
            pricing_trials=args.pricing_trials,
            max_insertions=args.max_insertions,
            runs_per_instance=args.runs_per_instance,
            skip_existing=args.skip_existing,
            max_instances_per_dataset=args.max_instances_per_dataset,
        )
        print(f"B&P experiment complete. See output folder: {Path(args.output_root).resolve()}")
        return

    if args.instance:
        instance = _parse_top_instance_file(Path(args.instance))
        sol, stats = solve_top_branch_and_price(
            instance,
            seed=args.seed,
            max_cg_iterations=args.max_cg_iterations,
            pricing_trials=args.pricing_trials,
            max_insertions=args.max_insertions,
        )
        print(f"Total score: {sol.total_score:.2f}")
        for i, r in enumerate(sol.routes, start=1):
            print(f"Route {i}: {' -> '.join(map(str, r))}")
        print(f"CPU time (s): {stats.cpu_time_seconds:.4f}")
        print(f"LP solves: {stats.lp_solves}")
        print(f"Labels generated: {stats.labels_generated}")
        return

    _demo()


if __name__ == "__main__":
    main()
