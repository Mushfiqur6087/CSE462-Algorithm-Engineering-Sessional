# CSE-462 Algorithm Engineering (Sessional) — Team Orienteering Problem

This repository contains implementations and experiment tooling for the **Team Orienteering Problem (TOP)**: multiple routes (vehicles), customer rewards (scores), a distance budget per route, and a goal to maximize total collected score without visiting customers more than once across routes.

Two solver families are provided:

- **Iterated Local Search (ILS)** — heuristic search (`top_ils.py`, `top_ils_improved.py`).
- **Practical Branch-and-Price style** — column generation with an LP master and heuristic pricing (`top_branch_price.py`, `top_branch_price_improved.py`).

Batch experiments write **CSV/JSON summaries** and optional **plots**. Comparison scripts merge baseline vs improved runs for reporting.

---

## Requirements

- **Python** 3.10+ recommended (uses modern type hints).
- **Packages** (install into a virtual environment if you prefer):

```powershell
python -m pip install pulp pandas matplotlib
```

- **`pulp`** is required for Branch-and-Price (CBC backend).
- **`pandas`** and **`matplotlib`** are required for `compare_results.py` and `compare_bp_results.py` (and for runtime plots inside experiment runners).

**Windows:** Run PowerShell scripts from the project root so relative paths resolve correctly.

---

## Repository layout

```
/experiments
├── datasets/                 # Benchmark instances (see below)
├── doc/                      # Markdown reports and design notes
├── output_ils/               # Baseline ILS experiment outputs (generated)
├── output_ils_improved/      # Improved ILS outputs (generated)
├── output_ils_comparison/    # ILS baseline vs improved comparison (generated)
├── output_bp/                # Baseline B&P experiment outputs (generated)
├── output_bp_improved/       # Improved B&P outputs (generated)
├── output_bp_comparison/     # B&P baseline vs improved comparison (generated)
├── prepare_datasets.ps1      # Downloads/prepares dataset files
├── run_experiment.ps1        # Baseline ILS batch run
├── run_experiment_improved.ps1
├── run_experiment_bp.ps1     # Baseline B&P batch run
├── run_experiment_bp_improved.ps1
├── run_all_experiments.ps1   # All four experiments + both comparisons
├── top_ils.py
├── top_ils_improved.py
├── top_branch_price.py
├── top_branch_price_improved.py
├── compare_results.py        # ILS comparison
├── compare_bp_results.py     # B&P comparison
├── ils.md                    # ILS algorithm documentation
├── Team Orienteering Problem.pdf
├── run_ils.ps1 / run_ils.sh  # Optional thin wrappers around top_ils.py
└── README.md                 # This file
```

You may also see **`output/`**, **`output_comparison/`**, or **`output_bp_*_check`** folders from older runs; they are not required by the code. Safe to archive or delete if you do not need those artifacts.

---

## Datasets (`datasets/`)

| Path | Purpose |
|------|---------|
| `datasets/chao/` | Chao-style TOP instances (`*.txt`). |
| `datasets/dang/` | Large-instance subset used as the “Dang” view. |
| `datasets/vansteenwegen/` | Large-instance subset used as the “Vansteenwegen” view. |
| `datasets/raw/` | Downloaded archives / raw sources before filtering. |
| `datasets/tmp/` | Scratch or one-off test files. |

**Format:** Each instance is a text file with header lines `n`, `m`, `tmax`, followed by `n` rows of `x y score` (space- or semicolon-separated). The parsers infer depots from zero-score nodes when possible.

**Preparation:** `prepare_datasets.ps1` downloads and unpacks public benchmarks and fills the folders above. Most `run_*.ps1` scripts call it automatically.

---

## What each main Python file does

| File | Role |
|------|------|
| `top_ils.py` | Baseline ILS solver + `--experiment` batch mode. Default experiment output root: `output_ils`. |
| `top_ils_improved.py` | Improved ILS variant + batch mode. Default output: `output_ils_improved`. Supports `--skip-existing` to resume without redoing finished JSON runs. |
| `top_branch_price.py` | Practical B&P-style pipeline (column generation at root, heuristic pricing, integer master on generated columns). Default output: `output_bp`. |
| `top_branch_price_improved.py` | Wraps baseline B&P with multiple diversified attempts (`restarts`, `seed_jump`) and keeps the best solution. Default output: `output_bp_improved`. |
| `compare_results.py` | Reads `output_ils` and `output_ils_improved`, writes merged metrics and plots under **`output_ils_comparison/`**. |
| `compare_bp_results.py` | Reads `output_bp` and `output_bp_improved`, writes merged metrics and plots under **`output_bp_comparison/`**. |

---

## Experiment outputs (what each folder contains)

After a successful batch run, each output root (e.g. `output_ils`, `output_bp`) typically contains:

| Artifact | Meaning |
|----------|---------|
| `instances/<dataset>/...json` | One JSON per instance run with routes, scores, timings, and metadata. |
| `summary.csv` | One row per run (all instances and runs). |
| `instance_metrics.csv` | Aggregated statistics per benchmark instance. |
| `dataset_metrics.csv` | Aggregated statistics per dataset (`chao`, `dang`, `vansteenwegen`). |
| `quality_distribution.csv` | Run-level score and gap distribution. |
| `runtime_vs_instance_size.csv` | Mean CPU time vs number of nodes. |
| `runtime_vs_instance_size.png` | Scatter plot (if `matplotlib` is available). |
| `metrics_overview.json` | Run configuration and paths to generated files. |

**Comparison folders** (`output_ils_comparison`, `output_bp_comparison`) add:

- `dataset_comparison.csv`, `instance_comparison.csv`, `quick_delta_table.csv`
- `figures/` — bar charts and scatter plots for side-by-side metrics.

**Note on “gap” metrics:** Gaps are often computed against the **best score seen across repeated runs for that instance** in the same output set, not necessarily a published global optimum.

---

## Step-by-step: first-time setup

1. **Open a terminal** in the project directory:

   ```powershell
   cd "path\to\experiments"
   ```

2. **Create a virtual environment (optional but recommended):**

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. **Install dependencies:**

   ```powershell
   python -m pip install -U pip
   python -m pip install pulp pandas matplotlib
   ```

4. **Prepare datasets** (or rely on the next step to call it):

   ```powershell
   powershell -ExecutionPolicy Bypass -File ".\prepare_datasets.ps1"
   ```

---

## How to run experiments

All commands assume your **current directory** is the project root.

### Option A — Full pipeline (all four experiments + both comparisons)

This can take a **very long time** (full benchmark suites for ILS and B&P).

```powershell
powershell -ExecutionPolicy Bypass -File ".\run_all_experiments.ps1"
```

Order: prepare datasets once → baseline ILS → improved ILS (with `--skip-existing` where JSONs already exist) → baseline B&P → improved B&P → `compare_results.py` → `compare_bp_results.py`.

### Option B — Individual experiments

| Goal | Command |
|------|---------|
| Baseline ILS | `powershell -ExecutionPolicy Bypass -File ".\run_experiment.ps1"` |
| Improved ILS | `powershell -ExecutionPolicy Bypass -File ".\run_experiment_improved.ps1"` |
| Baseline B&P | `powershell -ExecutionPolicy Bypass -File ".\run_experiment_bp.ps1"` |
| Improved B&P | `powershell -ExecutionPolicy Bypass -File ".\run_experiment_bp_improved.ps1"` |

### Option C — Direct Python (full control)

Examples:

```powershell
python .\top_ils.py --experiment --datasets-root datasets --output-root output_ils --iterations 20 --seed 7
python .\top_branch_price.py --experiment --datasets-root datasets --output-root output_bp --seed 7 --max-cg-iterations 12 --pricing-trials 22 --max-insertions 18
```

Quick test on a **subset** of instances:

```powershell
python .\top_ils.py --experiment --datasets-root datasets --output-root output_ils_test --max-instances-per-dataset 3 --iterations 50
```

### Comparisons (after both sides exist)

```powershell
python .\compare_results.py
python .\compare_bp_results.py
```

---


---

## Troubleshooting

| Symptom | Likely cause | What to do |
|---------|----------------|------------|
| `ModuleNotFoundError: pulp` | B&P dependency missing | `python -m pip install pulp` |
| `PermissionError` writing CSV under `output_*` | File open in Excel or another program | Close the CSV, rerun; or write to a new `--output-root` |
| Experiment finishes “too fast” with no new solves | `--skip-existing` skips existing JSONs | Delete outputs or use a fresh folder name, or run without `--skip-existing` |
| Comparison CSVs almost empty | Missing or non-overlapping baseline/improved runs | Ensure both folders have `dataset_metrics.csv` from runs on the same datasets |
| Very long runtime | Full benchmarks + ILS + B&P | Use `--max-instances-per-dataset` for smoke tests |

---

## Reproducibility tips

- Fixed **seeds** appear in the `run_experiment*.ps1` scripts; change them only when you intend to compare randomness.
- For a clean A/B study, use **separate output directories** per configuration so old JSON files are not mixed into summary regeneration.
- **`metrics_overview.json`** in each output root records the effective settings for that run.

---

## License / course use

This project is structured for **coursework and experimentation**. Verify your institution’s policies before redistributing benchmark data or derived results.

If you extend the solvers, keep changes focused and document new CLI flags in this README.
