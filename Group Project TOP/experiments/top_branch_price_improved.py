from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Tuple

import top_branch_price as bp


def solve_top_branch_and_price_improved(
    instance: bp.TOPInstance,
    seed: int | None = None,
    max_cg_iterations: int = 12,
    pricing_trials: int = 22,
    max_insertions: int = 18,
    restarts: Optional[int] = None,
    seed_jump: Optional[int] = None,
) -> Tuple[bp.BPSolution, bp.BPStats]:
    """Improved practical B&P.

    Strategy:
    - Run baseline B&P several times with diversified seeds.
    - Keep the best-scoring solution.
    - Aggregate effort metrics across attempts.
    """

    tries = 3 if restarts is None else max(1, restarts)
    jump = 97 if seed_jump is None else max(1, seed_jump)

    best_sol: bp.BPSolution | None = None
    best_stats: bp.BPStats | None = None

    total_cpu = 0.0
    total_cg_iters = 0
    total_lp_solves = 0
    total_labels = 0
    total_columns_generated = 0

    for k in range(tries):
        run_seed = None if seed is None else seed + (k * jump)
        sol, stats = bp.solve_top_branch_and_price(
            instance=instance,
            seed=run_seed,
            max_cg_iterations=max_cg_iterations,
            pricing_trials=pricing_trials,
            max_insertions=max_insertions,
        )

        total_cpu += stats.cpu_time_seconds
        total_cg_iters += stats.cg_iterations
        total_lp_solves += stats.lp_solves
        total_labels += stats.labels_generated
        total_columns_generated += stats.columns_generated

        if best_sol is None:
            best_sol = sol
            best_stats = stats
            continue

        if sol.total_score > best_sol.total_score + 1e-12:
            best_sol = sol
            best_stats = stats
        elif abs(sol.total_score - best_sol.total_score) <= 1e-12 and stats.cpu_time_seconds < best_stats.cpu_time_seconds:
            best_sol = sol
            best_stats = stats

    assert best_sol is not None
    assert best_stats is not None

    merged_stats = bp.BPStats(
        cpu_time_seconds=total_cpu,
        cg_iterations=total_cg_iters,
        lp_solves=total_lp_solves,
        labels_generated=total_labels,
        columns_generated=total_columns_generated,
        columns_in_pool=best_stats.columns_in_pool,
        fractional_columns_at_root=best_stats.fractional_columns_at_root,
        restarts_performed=tries,
    )
    return best_sol, merged_stats


def _run_batch_experiment(
    datasets_root: Path,
    output_root: Path,
    seed: int,
    max_cg_iterations: int,
    pricing_trials: int,
    max_insertions: int,
    runs_per_instance: int,
    skip_existing: bool,
    max_instances_per_dataset: int | None,
    restarts: int,
    seed_jump: int,
) -> None:
    bp.run_dataset_experiments(
        datasets_root=datasets_root,
        output_root=output_root,
        seed=seed,
        max_cg_iterations=max_cg_iterations,
        pricing_trials=pricing_trials,
        max_insertions=max_insertions,
        runs_per_instance=runs_per_instance,
        skip_existing=skip_existing,
        max_instances_per_dataset=max_instances_per_dataset,
        solver_fn=solve_top_branch_and_price_improved,
        solver_kwargs={"restarts": restarts, "seed_jump": seed_jump},
    )

    # Add improved-specific config to overview for reproducibility.
    overview_path = output_root / "metrics_overview.json"
    if overview_path.exists():
        try:
            overview = json.loads(overview_path.read_text(encoding="utf-8"))
            overview.setdefault("config", {})
            overview["config"]["improved_restarts"] = restarts
            overview["config"]["improved_seed_jump"] = seed_jump
            overview_path.write_text(json.dumps(overview, indent=2), encoding="utf-8")
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Improved practical Branch-and-Price for TOP")
    parser.add_argument("--instance", type=str, default="", help="Path to one TOP instance")
    parser.add_argument("--experiment", action="store_true", help="Run batch experiments")
    parser.add_argument("--datasets-root", type=str, default="datasets", help="Datasets root path")
    parser.add_argument("--output-root", type=str, default="output_bp_improved", help="Output root path")
    parser.add_argument("--seed", type=int, default=7, help="Random seed")
    parser.add_argument("--max-cg-iterations", type=int, default=12, help="Max column generation iterations")
    parser.add_argument("--pricing-trials", type=int, default=22, help="Pricing trials per CG iteration")
    parser.add_argument("--max-insertions", type=int, default=18, help="Max insertions per pricing construction")
    parser.add_argument("--runs-per-instance", type=int, default=2, help="Independent runs per instance")
    parser.add_argument("--skip-existing", action="store_true", help="Skip already generated run JSON")
    parser.add_argument("--max-instances-per-dataset", type=int, default=None, help="Optional cap for quick tests")
    parser.add_argument("--restarts", type=int, default=3, help="Number of diversified B&P attempts per run")
    parser.add_argument("--seed-jump", type=int, default=97, help="Seed increment between diversified attempts")

    args = parser.parse_args()

    if args.experiment:
        _run_batch_experiment(
            datasets_root=Path(args.datasets_root),
            output_root=Path(args.output_root),
            seed=args.seed,
            max_cg_iterations=args.max_cg_iterations,
            pricing_trials=args.pricing_trials,
            max_insertions=args.max_insertions,
            runs_per_instance=args.runs_per_instance,
            skip_existing=args.skip_existing,
            max_instances_per_dataset=args.max_instances_per_dataset,
            restarts=args.restarts,
            seed_jump=args.seed_jump,
        )
        print(f"Improved B&P experiment complete. See output folder: {Path(args.output_root).resolve()}")
        return

    if args.instance:
        instance = bp._parse_top_instance_file(Path(args.instance))
        sol, stats = solve_top_branch_and_price_improved(
            instance=instance,
            seed=args.seed,
            max_cg_iterations=args.max_cg_iterations,
            pricing_trials=args.pricing_trials,
            max_insertions=args.max_insertions,
            restarts=args.restarts,
            seed_jump=args.seed_jump,
        )
        print(f"Total score: {sol.total_score:.2f}")
        for i, r in enumerate(sol.routes, start=1):
            print(f"Route {i}: {' -> '.join(map(str, r))}")
        print(f"Aggregated CPU time (s): {stats.cpu_time_seconds:.4f}")
        print(f"Aggregated LP solves: {stats.lp_solves}")
        print(f"Aggregated labels generated: {stats.labels_generated}")
        return

    bp._demo()


if __name__ == "__main__":
    main()
