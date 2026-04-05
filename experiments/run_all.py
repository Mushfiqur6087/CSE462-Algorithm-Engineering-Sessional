from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.experiments import (
    build_presentation_summary,
    load_named_benchmark_cases,
    run_branch_and_price_benchmark,
    run_convergence_case,
    run_ils_benchmark,
)
from src.plotting import plot_grouped_bar, plot_line


def main() -> None:
    parser = argparse.ArgumentParser(description="Run TOP experiments and generate plots.")
    parser.add_argument("--output", type=Path, default=ROOT / "results", help="Output directory")
    parser.add_argument(
        "--dataset-source",
        choices=["synthetic", "named"],
        default="synthetic",
        help="Use synthetic generated instances or named benchmark instances from manifest",
    )
    parser.add_argument(
        "--benchmark-manifest",
        type=Path,
        default=ROOT / "data" / "instances.csv",
        help="CSV manifest for named benchmark instances",
    )
    args = parser.parse_args()

    output_dir = args.output
    figures_dir = output_dir / "figures"
    tables_dir = output_dir / "tables"
    figures_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    benchmark_cases = None
    if args.dataset_source == "named":
        benchmark_cases = load_named_benchmark_cases(args.benchmark_manifest)

    bp_df = run_branch_and_price_benchmark(tables_dir, benchmark_cases=benchmark_cases)
    ils_df = run_ils_benchmark(tables_dir, benchmark_cases=benchmark_cases)
    convergence = run_convergence_case(tables_dir)
    build_presentation_summary(bp_df, ils_df, tables_dir)

    plot_grouped_bar(bp_df, x="n", y="profit", hue="algorithm", title="Branch-and-Price Profit by Instance Size", output_path=figures_dir / "bp_profit_by_n.png")
    plot_grouped_bar(bp_df, x="n", y="cpu_time", hue="algorithm", title="Branch-and-Price Runtime by Instance Size", output_path=figures_dir / "bp_runtime_by_n.png")
    plot_grouped_bar(ils_df, x="n", y="profit", hue="algorithm", title="ILS Profit by Instance Size", output_path=figures_dir / "ils_profit_by_n.png")
    plot_grouped_bar(ils_df, x="n", y="cpu_time", hue="algorithm", title="ILS Runtime by Instance Size", output_path=figures_dir / "ils_runtime_by_n.png")

    plot_line(convergence["bp_basic"], x="iteration", y="lp_obj", hue="variant", title="B&P Convergence", output_path=figures_dir / "bp_convergence_basic.png")
    plot_line(convergence["bp_modified"], x="iteration", y="lp_obj", hue="variant", title="B&P Convergence", output_path=figures_dir / "bp_convergence_modified.png")
    plot_line(convergence["ils_basic"], x="iteration", y="best_profit", hue="variant", title="ILS Best-So-Far", output_path=figures_dir / "ils_best_basic.png")
    plot_line(convergence["ils_modified"], x="iteration", y="best_profit", hue="variant", title="ILS Best-So-Far", output_path=figures_dir / "ils_best_modified.png")

    print("Experiments completed.")
    print(f"Tables: {tables_dir}")
    print(f"Figures: {figures_dir}")


if __name__ == "__main__":
    main()
