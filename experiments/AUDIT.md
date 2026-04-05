# Audit Report

Date: 2026-04-05
Project root: experiments/

## 1. What is done

This project implements and evaluates two solution approaches for the Team Orienteering Problem (TOP):

1. Branch-and-Price (exact/decomposition-oriented)
2. Iterated Local Search (heuristic/metaheuristic)

Each approach has two variants:

- Basic variant
- Modified variant

The pipeline is fully automated by one runner:

- experiments/run_all.py

The pipeline generates:

- CSV result tables in experiments/results/tables/
- PNG figures in experiments/results/figures/
- Aggregated summary table presentation_summary.csv

## 2. How it is done (execution flow)

### 2.1 Entry point orchestration

File: experiments/run_all.py

Execution sequence:

1. Parse CLI args:
   - --output
   - --dataset-source = synthetic | named
   - --benchmark-manifest (CSV)
2. Create output directories (tables/, figures/)
3. If named mode, load manifest + JSON instances through loader
4. Run Branch-and-Price benchmark
5. Run ILS benchmark
6. Run convergence case
7. Build summary table
8. Generate all plots

### 2.2 Dataset handling

Implemented in experiments/src/experiments.py.

Two modes are supported:

1. synthetic mode
   - Uses make_instance() from experiments/src/core.py
   - Config sizes: (8,2,12), (10,2,14), (12,2,16), (15,2,18)
   - Repeats over fixed seeds

2. named mode
   - Reads a manifest CSV with required columns: dataset, instance_id, file
   - Loads each JSON instance from experiments/data/
   - Validates shape consistency:
     - profits length == n
     - dist is n x n
   - Fails fast with clear errors if manifest/file/schema invalid

### 2.3 Branch-and-Price implementation

File: experiments/src/branch_and_price.py

Main technical pieces:

- Restricted master LP solved by scipy.optimize.linprog
- Column generation loop
- Pricing DP with labeling and dominance pruning
- Branching on customer-pair relations
- Node exploration and incumbent tracking

Outputs per run include:

- profit
- cpu_time
- nodes_explored
- lp_solves
- cg_iterations

### 2.4 ILS implementation

File: experiments/src/ils.py

Main technical pieces:

- Greedy construction of initial solution
- 2-opt/local search improvements
- Perturbation by customer removal/reinsertion
- Acceptance/restart logic
- Adaptive perturbation in modified variant

Outputs per run include:

- profit
- cpu_time
- iterations

### 2.5 Plot and summary generation

Plot generation: experiments/src/plotting.py
Summary generation: build_presentation_summary() in experiments/src/experiments.py

Produced figures include:

- bp_profit_by_n.png
- bp_runtime_by_n.png
- bp_convergence_basic.png
- bp_convergence_modified.png
- ils_profit_by_n.png
- ils_runtime_by_n.png
- ils_best_basic.png
- ils_best_modified.png

## 3. Why these choices were made

### 3.1 Why two algorithm families

TOP is NP-hard, so both exact and heuristic perspectives are required:

- Branch-and-Price provides stronger optimality-focused behavior on small/medium instances.
- ILS provides faster high-quality solutions and scalability behavior.

### 3.2 Why two variants per method

Basic vs Modified variants allow controlled ablation-style comparison:

- Branch-and-Price modified variant focuses on stronger search/branch behavior and warm-start policy.
- ILS modified variant focuses on adaptive diversification/intensification.

This supports presentation requirements for "what changed" and "why it helps".

### 3.3 Why synthetic + named modes

- synthetic mode guarantees reproducible baseline experiments even without external files.
- named mode enables direct use of benchmark datasets (Chao, Dang, Vansteenwegen OP/TOP) when files are supplied.

This gives both immediate runnability and benchmark realism.

## 4. Current dataset status (important)

Manifest file: experiments/data/instances.csv

Current entries:

1. Chao Benchmark -> chao_rep_32.json
2. Dang Benchmark -> dang_rep_102.json
3. Vansteenwegen OP/TOP -> van_rep_50.json

Important note:

- The current manifest has one representative JSON instance per dataset family.
- It does NOT yet include all family instance counts (e.g., all 157 Chao instances).
- The "instances" column in manifest is currently metadata about family size, not number of loaded files.

## 5. How to run

### 5.1 Synthetic mode

python experiments/run_all.py --dataset-source synthetic --output experiments/results

### 5.2 Named mode

python experiments/run_all.py --dataset-source named --benchmark-manifest experiments/data/instances.csv --output experiments/results

## 6. Evidence of generated outputs

Fresh generation confirmation:

- Latest run command: `python experiments/run_all.py --dataset-source synthetic --output experiments/results`
- Run status: completed successfully

Current tables directory includes:

- branch_and_price_results.csv
- ils_results.csv
- bp_convergence_basic.csv
- bp_convergence_modified.csv
- ils_convergence_basic.csv
- ils_convergence_modified.csv
- presentation_summary.csv

Current figures directory includes all expected B&P and ILS comparison/convergence plots.

## 7. Latest aggregate summary snapshot

From presentation_summary.csv:

- B&P Basic: profit 41.25, cpu_time 0.08115
- B&P Modified: profit 41.25, cpu_time 0.08049166666666667
- ILS Basic: profit 40.9, cpu_time 0.046115
- ILS Modified: profit 40.95, cpu_time 0.14788

## 8. Known limitations and next required step

1. Named dataset mode is functional, but full benchmark coverage requires adding many more JSON instance files and manifest rows.
2. If the goal is to claim complete family usage (e.g., all Chao 157), manifest must be expanded to include each instance explicitly.

## 9. Conclusion

The codebase is operational and reproducible with a clear algorithmic pipeline, documented benchmark loading pathway, and generated artifacts for reporting.

What is done:

- Full solver implementation (B&P + ILS, each basic/modified)
- End-to-end runner
- Results + plotting pipeline
- Named benchmark loading infrastructure

What remains for full benchmark claim:

- Populate manifest and JSON files to full official instance counts per family.
