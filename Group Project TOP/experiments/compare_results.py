from __future__ import annotations

from pathlib import Path
import math

import matplotlib.pyplot as plt
import pandas as pd


def pct_change(new: float, old: float) -> float:
    if abs(old) < 1e-12:
        return math.nan
    return (new - old) / old * 100.0


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def main() -> None:
    root = Path(__file__).resolve().parent
    out_base = root / "output_ils"
    out_improved = root / "output_ils_improved"
    out_cmp = root / "output_ils_comparison"
    fig_dir = out_cmp / "figures"
    ensure_dir(fig_dir)

    base_dataset = pd.read_csv(out_base / "dataset_metrics.csv")
    imp_dataset = pd.read_csv(out_improved / "dataset_metrics.csv")
    base_inst = pd.read_csv(out_base / "instance_metrics.csv")
    imp_inst = pd.read_csv(out_improved / "instance_metrics.csv")
    base_summary = pd.read_csv(out_base / "summary.csv")
    imp_summary = pd.read_csv(out_improved / "summary.csv")

    merged_ds = base_dataset.merge(
        imp_dataset,
        on="dataset",
        how="inner",
        suffixes=("_base", "_improved"),
    )

    for metric in [
        "mean_cpu_time_seconds",
        "mean_gap_to_reference_best_percent",
        "success_rate_percent",
        "score_mean",
        "mean_iterations_to_convergence",
    ]:
        merged_ds[f"{metric}_pct_change"] = merged_ds.apply(
            lambda r: pct_change(r[f"{metric}_improved"], r[f"{metric}_base"]), axis=1
        )

    merged_ds.to_csv(out_cmp / "dataset_comparison.csv", index=False)

    merged_inst = base_inst.merge(
        imp_inst,
        on=["dataset", "instance"],
        how="inner",
        suffixes=("_base", "_improved"),
    )
    merged_inst["score_delta"] = merged_inst["mean_score_improved"] - merged_inst["mean_score_base"]
    merged_inst["cpu_delta"] = (
        merged_inst["mean_cpu_time_seconds_improved"]
        - merged_inst["mean_cpu_time_seconds_base"]
    )
    merged_inst["gap_delta"] = (
        merged_inst["mean_gap_to_reference_best_percent_improved"]
        - merged_inst["mean_gap_to_reference_best_percent_base"]
    )
    merged_inst.to_csv(out_cmp / "instance_comparison.csv", index=False)

    # 1) Dataset-wise grouped bars for key metrics
    datasets = merged_ds["dataset"].tolist()
    x = range(len(datasets))
    w = 0.36

    plt.figure(figsize=(10, 6))
    plt.bar([i - w / 2 for i in x], merged_ds["mean_cpu_time_seconds_base"], w, label="Baseline")
    plt.bar([i + w / 2 for i in x], merged_ds["mean_cpu_time_seconds_improved"], w, label="Improved")
    plt.xticks(list(x), datasets)
    plt.ylabel("Mean CPU time (s)")
    plt.title("Mean CPU Time by Dataset: Baseline vs Improved")
    plt.legend()
    plt.tight_layout()
    plt.savefig(fig_dir / "dataset_mean_cpu_comparison.png", dpi=180)
    plt.close()

    plt.figure(figsize=(10, 6))
    plt.bar([i - w / 2 for i in x], merged_ds["mean_gap_to_reference_best_percent_base"], w, label="Baseline")
    plt.bar([i + w / 2 for i in x], merged_ds["mean_gap_to_reference_best_percent_improved"], w, label="Improved")
    plt.xticks(list(x), datasets)
    plt.ylabel("Mean gap to reference best (%)")
    plt.title("Mean Gap by Dataset: Baseline vs Improved")
    plt.legend()
    plt.tight_layout()
    plt.savefig(fig_dir / "dataset_mean_gap_comparison.png", dpi=180)
    plt.close()

    plt.figure(figsize=(10, 6))
    plt.bar([i - w / 2 for i in x], merged_ds["success_rate_percent_base"], w, label="Baseline")
    plt.bar([i + w / 2 for i in x], merged_ds["success_rate_percent_improved"], w, label="Improved")
    plt.xticks(list(x), datasets)
    plt.ylabel("Success rate (%)")
    plt.title("Success Rate by Dataset: Baseline vs Improved")
    plt.legend()
    plt.tight_layout()
    plt.savefig(fig_dir / "dataset_success_rate_comparison.png", dpi=180)
    plt.close()

    # 2) Instance-level scatter comparisons
    plt.figure(figsize=(8, 8))
    plt.scatter(merged_inst["mean_score_base"], merged_inst["mean_score_improved"], alpha=0.35, s=12)
    lo = min(merged_inst["mean_score_base"].min(), merged_inst["mean_score_improved"].min())
    hi = max(merged_inst["mean_score_base"].max(), merged_inst["mean_score_improved"].max())
    plt.plot([lo, hi], [lo, hi], "r--", linewidth=1)
    plt.xlabel("Baseline mean score")
    plt.ylabel("Improved mean score")
    plt.title("Instance-level Score Comparison")
    plt.tight_layout()
    plt.savefig(fig_dir / "instance_score_scatter.png", dpi=180)
    plt.close()

    plt.figure(figsize=(8, 8))
    plt.scatter(
        merged_inst["mean_cpu_time_seconds_base"],
        merged_inst["mean_cpu_time_seconds_improved"],
        alpha=0.35,
        s=12,
    )
    lo = min(
        merged_inst["mean_cpu_time_seconds_base"].min(),
        merged_inst["mean_cpu_time_seconds_improved"].min(),
    )
    hi = max(
        merged_inst["mean_cpu_time_seconds_base"].max(),
        merged_inst["mean_cpu_time_seconds_improved"].max(),
    )
    plt.plot([lo, hi], [lo, hi], "r--", linewidth=1)
    plt.xlabel("Baseline mean CPU time (s)")
    plt.ylabel("Improved mean CPU time (s)")
    plt.title("Instance-level Runtime Comparison")
    plt.tight_layout()
    plt.savefig(fig_dir / "instance_runtime_scatter.png", dpi=180)
    plt.close()

    # 3) Distribution comparison of run-level gaps
    base_ok = base_summary[base_summary["status"] == "ok"].copy()
    imp_ok = imp_summary[imp_summary["status"] == "ok"].copy()

    plt.figure(figsize=(10, 6))
    for dataset in sorted(base_ok["dataset"].unique()):
        vals = base_ok[base_ok["dataset"] == dataset]["gap_to_reference_best_percent"].astype(float)
        plt.hist(vals, bins=35, alpha=0.35, label=f"Base {dataset}")
    plt.xlabel("Gap to reference best (%)")
    plt.ylabel("Frequency")
    plt.title("Baseline Gap Distribution (run-level)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(fig_dir / "baseline_gap_distribution.png", dpi=180)
    plt.close()

    plt.figure(figsize=(10, 6))
    for dataset in sorted(imp_ok["dataset"].unique()):
        vals = imp_ok[imp_ok["dataset"] == dataset]["gap_to_reference_best_percent"].astype(float)
        plt.hist(vals, bins=35, alpha=0.35, label=f"Improved {dataset}")
    plt.xlabel("Gap to reference best (%)")
    plt.ylabel("Frequency")
    plt.title("Improved Gap Distribution (run-level)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(fig_dir / "improved_gap_distribution.png", dpi=180)
    plt.close()

    # 4) Runtime vs size overlays from aggregated instance metrics
    plt.figure(figsize=(10, 6))
    plt.scatter(
        merged_inst["num_nodes_base"],
        merged_inst["mean_cpu_time_seconds_base"],
        alpha=0.35,
        s=14,
        label="Baseline",
    )
    plt.scatter(
        merged_inst["num_nodes_improved"],
        merged_inst["mean_cpu_time_seconds_improved"],
        alpha=0.35,
        s=14,
        label="Improved",
    )
    plt.xlabel("Instance size (nodes)")
    plt.ylabel("Mean CPU time (s)")
    plt.title("Runtime vs Instance Size: Baseline vs Improved")
    plt.legend()
    plt.tight_layout()
    plt.savefig(fig_dir / "runtime_vs_size_overlay.png", dpi=180)
    plt.close()

    # Small text summary
    summary_lines = []
    summary_lines.append("dataset,metric,baseline,improved,delta,delta_percent")
    for _, row in merged_ds.iterrows():
        ds = row["dataset"]
        for m in [
            "mean_cpu_time_seconds",
            "mean_gap_to_reference_best_percent",
            "success_rate_percent",
            "score_mean",
            "mean_iterations_to_convergence",
        ]:
            b = float(row[f"{m}_base"])
            i = float(row[f"{m}_improved"])
            d = i - b
            p = pct_change(i, b)
            summary_lines.append(f"{ds},{m},{b},{i},{d},{p}")
    (out_cmp / "quick_delta_table.csv").write_text("\n".join(summary_lines), encoding="utf-8")


if __name__ == "__main__":
    main()
