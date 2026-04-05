from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .branch_and_price import branch_and_price_basic, branch_and_price_modified
from .core import TOPInstance, make_instance
from .ils import ils_basic, ils_modified


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _default_configs() -> List[Tuple[int, int, float]]:
    return [
        (8, 2, 12.0),
        (10, 2, 14.0),
        (12, 2, 16.0),
        (15, 2, 18.0),
    ]


def load_named_benchmark_cases(manifest_path: Path) -> List[Dict[str, object]]:
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Benchmark manifest not found: {manifest_path}. "
            "Provide Chao/Dang/Vansteenwegen instances in experiments/data."
        )

    manifest = pd.read_csv(manifest_path)
    required_cols = {"dataset", "instance_id", "file"}
    missing_cols = required_cols.difference(manifest.columns)
    if missing_cols:
        raise ValueError(f"Benchmark manifest is missing columns: {sorted(missing_cols)}")

    cases: List[Dict[str, object]] = []
    base_dir = manifest_path.parent
    for row in manifest.itertuples(index=False):
        dataset = str(getattr(row, "dataset"))
        instance_id = str(getattr(row, "instance_id"))
        file_name = str(getattr(row, "file"))
        json_path = (base_dir / file_name).resolve()
        if not json_path.exists():
            raise FileNotFoundError(f"Benchmark instance file not found: {json_path}")

        raw = json.loads(json_path.read_text(encoding="utf-8"))
        profits = np.asarray(raw["profits"], dtype=float)
        dist = np.asarray(raw["dist"], dtype=float)
        n = int(raw["n"])
        m = int(raw["m"])
        t_max = float(raw["T_max"])

        if profits.shape[0] != n:
            raise ValueError(f"profits length mismatch in {json_path}: expected {n}, got {profits.shape[0]}")
        if dist.shape != (n, n):
            raise ValueError(f"dist shape mismatch in {json_path}: expected {(n, n)}, got {dist.shape}")

        inst = TOPInstance(n=n, m=m, T_max=t_max, profits=profits, dist=dist)
        cases.append({"dataset": dataset, "instance_id": instance_id, "instance": inst})

    if not cases:
        raise ValueError(f"Benchmark manifest is empty: {manifest_path}")
    return cases


def run_branch_and_price_benchmark(
    output_dir: Path,
    seeds: Sequence[int] = (0, 1, 2),
    benchmark_cases: Optional[Sequence[Dict[str, object]]] = None,
) -> pd.DataFrame:
    rows: List[Dict[str, float]] = []

    if benchmark_cases:
        for case in benchmark_cases:
            inst = case["instance"]
            assert isinstance(inst, TOPInstance)
            basic = branch_and_price_basic(inst, time_limit=45, verbose=False)
            modified = branch_and_price_modified(inst, time_limit=45, verbose=False)
            rows.append(
                {
                    "algorithm": "B&P Basic",
                    "dataset": str(case["dataset"]),
                    "instance_id": str(case["instance_id"]),
                    "n": inst.n,
                    "m": inst.m,
                    "T_max": inst.T_max,
                    "seed": np.nan,
                    "profit": basic.profit,
                    "cpu_time": basic.stats["cpu_time"],
                    "nodes_explored": basic.stats["nodes_explored"],
                    "lp_solves": basic.stats["lp_solves"],
                    "cg_iterations": basic.stats["cg_iterations"],
                }
            )
            rows.append(
                {
                    "algorithm": "B&P Modified",
                    "dataset": str(case["dataset"]),
                    "instance_id": str(case["instance_id"]),
                    "n": inst.n,
                    "m": inst.m,
                    "T_max": inst.T_max,
                    "seed": np.nan,
                    "profit": modified.profit,
                    "cpu_time": modified.stats["cpu_time"],
                    "nodes_explored": modified.stats["nodes_explored"],
                    "lp_solves": modified.stats["lp_solves"],
                    "cg_iterations": modified.stats["cg_iterations"],
                }
            )
    else:
        for n, m, t_max in _default_configs():
            for seed in seeds:
                inst = make_instance(n=n, m=m, T_max=t_max, seed=seed)
                basic = branch_and_price_basic(inst, time_limit=45, verbose=False)
                modified = branch_and_price_modified(inst, time_limit=45, verbose=False)
                rows.append(
                    {
                        "algorithm": "B&P Basic",
                        "dataset": "synthetic",
                        "instance_id": f"syn_n{n}_m{m}_t{int(t_max)}_s{seed}",
                        "n": n,
                        "m": m,
                        "T_max": t_max,
                        "seed": seed,
                        "profit": basic.profit,
                        "cpu_time": basic.stats["cpu_time"],
                        "nodes_explored": basic.stats["nodes_explored"],
                        "lp_solves": basic.stats["lp_solves"],
                        "cg_iterations": basic.stats["cg_iterations"],
                    }
                )
                rows.append(
                    {
                        "algorithm": "B&P Modified",
                        "dataset": "synthetic",
                        "instance_id": f"syn_n{n}_m{m}_t{int(t_max)}_s{seed}",
                        "n": n,
                        "m": m,
                        "T_max": t_max,
                        "seed": seed,
                        "profit": modified.profit,
                        "cpu_time": modified.stats["cpu_time"],
                        "nodes_explored": modified.stats["nodes_explored"],
                        "lp_solves": modified.stats["lp_solves"],
                        "cg_iterations": modified.stats["cg_iterations"],
                    }
                )
    df = pd.DataFrame(rows)
    _ensure_dir(output_dir)
    df.to_csv(output_dir / "branch_and_price_results.csv", index=False)
    return df


def run_ils_benchmark(
    output_dir: Path,
    seeds: Sequence[int] = (0, 1, 2, 3, 4),
    benchmark_cases: Optional[Sequence[Dict[str, object]]] = None,
) -> pd.DataFrame:
    rows: List[Dict[str, float]] = []

    if benchmark_cases:
        for case in benchmark_cases:
            inst = case["instance"]
            assert isinstance(inst, TOPInstance)
            basic = ils_basic(inst, iterations=80, seed=0, verbose=False)
            modified = ils_modified(inst, iterations=80, seed=0, verbose=False)
            rows.append(
                {
                    "algorithm": "ILS Basic",
                    "dataset": str(case["dataset"]),
                    "instance_id": str(case["instance_id"]),
                    "n": inst.n,
                    "m": inst.m,
                    "T_max": inst.T_max,
                    "seed": np.nan,
                    "profit": basic.profit,
                    "cpu_time": basic.stats["cpu_time"],
                    "iterations": basic.stats["iterations"],
                }
            )
            rows.append(
                {
                    "algorithm": "ILS Modified",
                    "dataset": str(case["dataset"]),
                    "instance_id": str(case["instance_id"]),
                    "n": inst.n,
                    "m": inst.m,
                    "T_max": inst.T_max,
                    "seed": np.nan,
                    "profit": modified.profit,
                    "cpu_time": modified.stats["cpu_time"],
                    "iterations": modified.stats["iterations"],
                }
            )
    else:
        for n, m, t_max in _default_configs():
            for seed in seeds:
                inst = make_instance(n=n, m=m, T_max=t_max, seed=seed)
                basic = ils_basic(inst, iterations=80, seed=seed, verbose=False)
                modified = ils_modified(inst, iterations=80, seed=seed, verbose=False)
                rows.append(
                    {
                        "algorithm": "ILS Basic",
                        "dataset": "synthetic",
                        "instance_id": f"syn_n{n}_m{m}_t{int(t_max)}_s{seed}",
                        "n": n,
                        "m": m,
                        "T_max": t_max,
                        "seed": seed,
                        "profit": basic.profit,
                        "cpu_time": basic.stats["cpu_time"],
                        "iterations": basic.stats["iterations"],
                    }
                )
                rows.append(
                    {
                        "algorithm": "ILS Modified",
                        "dataset": "synthetic",
                        "instance_id": f"syn_n{n}_m{m}_t{int(t_max)}_s{seed}",
                        "n": n,
                        "m": m,
                        "T_max": t_max,
                        "seed": seed,
                        "profit": modified.profit,
                        "cpu_time": modified.stats["cpu_time"],
                        "iterations": modified.stats["iterations"],
                    }
                )
    df = pd.DataFrame(rows)
    _ensure_dir(output_dir)
    df.to_csv(output_dir / "ils_results.csv", index=False)
    return df


def run_convergence_case(output_dir: Path, n: int = 12, m: int = 2, t_max: float = 16.0, seed: int = 7) -> Dict[str, pd.DataFrame]:
    inst = make_instance(n=n, m=m, T_max=t_max, seed=seed)
    basic_bp = branch_and_price_basic(inst, time_limit=45, verbose=False)
    mod_bp = branch_and_price_modified(inst, time_limit=45, verbose=False)
    basic_ils = ils_basic(inst, iterations=80, seed=seed, verbose=False)
    mod_ils = ils_modified(inst, iterations=80, seed=seed, verbose=False)

    bp_df = pd.DataFrame(basic_bp.history)
    bp_df["variant"] = "basic"
    bp_mod_df = pd.DataFrame(mod_bp.history)
    bp_mod_df["variant"] = "modified"

    ils_basic_df = pd.DataFrame(basic_ils.history)
    ils_basic_df["variant"] = "basic"
    ils_mod_df = pd.DataFrame(mod_ils.history)
    ils_mod_df["variant"] = "modified"

    _ensure_dir(output_dir)
    bp_df.to_csv(output_dir / "bp_convergence_basic.csv", index=False)
    bp_mod_df.to_csv(output_dir / "bp_convergence_modified.csv", index=False)
    ils_basic_df.to_csv(output_dir / "ils_convergence_basic.csv", index=False)
    ils_mod_df.to_csv(output_dir / "ils_convergence_modified.csv", index=False)

    return {
        "bp_basic": bp_df,
        "bp_modified": bp_mod_df,
        "ils_basic": ils_basic_df,
        "ils_modified": ils_mod_df,
    }


def build_presentation_summary(bp_df: pd.DataFrame, ils_df: pd.DataFrame, output_dir: Path) -> pd.DataFrame:
    bp_summary = (
        bp_df.groupby("algorithm", as_index=False)[["profit", "cpu_time", "nodes_explored", "lp_solves", "cg_iterations"]]
        .mean()
        .assign(section="Branch-and-Price")
    )
    ils_summary = (
        ils_df.groupby("algorithm", as_index=False)[["profit", "cpu_time", "iterations"]]
        .mean()
        .assign(section="ILS")
    )

    summary = pd.concat([bp_summary, ils_summary], ignore_index=True, sort=False)
    _ensure_dir(output_dir)
    summary.to_csv(output_dir / "presentation_summary.csv", index=False)
    return summary
