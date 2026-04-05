# Team Orienteering Problem (TOP) Research Package

This folder contains a complete, reproducible implementation of two TOP solvers and their modified variants:

- Branch-and-Price (exact)
- Iterated Local Search (heuristic)

All plots and tables are generated from actual runs through one master script.

## 1) Problem Definition and Hardness

Given:
- A start depot and an end depot.
- A set of customer nodes, each with a nonnegative profit.
- A travel-time (distance) matrix.
- `m` vehicles and a per-route time budget `T_max`.

Find up to `m` routes to maximize total collected profit subject to:
- Each route starts at the start depot and ends at the end depot.
- Route duration is at most `T_max`.
- Each customer is visited at most once globally.

Complexity:
- TOP is NP-hard and generalizes Orienteering / Prize-Collecting routing variants.
- Exact methods require branch-and-bound / branch-and-price style decomposition for nontrivial sizes.
- Heuristics are necessary for fast high-quality solutions on larger instances.

## 2) Brief Overview of Existing Algorithms (with references)

1. Dynamic programming / labeling-based exact methods:
	 - Solve restricted route-generation subproblems exactly.
	 - Reference: Feillet et al. (2004) [R5], exact elementary shortest path with resource constraints.

2. Branch-and-Price (column generation + branching):
	 - Master LP over route columns; pricing finds new improving routes.
	 - Branching resolves LP fractionality to obtain integer-optimal solutions.
	 - References: Barnhart et al. (1998) [R3], Desaulniers et al. (2005) [R4], Vansteenwegen et al. (2011) [R2].

3. Metaheuristics (ILS, VNS, GRASP, evolutionary methods):
	 - Trade exactness for speed; strong practical performance on routing-like NP-hard problems.
	 - References: Lourenco et al. (2019 chapter on ILS) [R6], Vansteenwegen et al. (2011) [R2].

## 3) Chosen Algorithms and Step-by-Step Flow

### A. Branch-and-Price (original baseline)

Implementation: `src/branch_and_price.py`

Flow:
1. Build an initial route pool (singleton routes).
2. Solve Restricted Master Problem (RMP) LP (`solve_rmp`).
3. Extract dual prices.
4. Run pricing DP (`pricing_dp`) to find a route with positive reduced cost.
5. Add column and repeat until no improving column exists.
6. If LP solution is fractional, branch on customer-pair relation (`choose_branch_pair`).
7. Repeat recursively until integer solution and global bound close.

Suggested slide animation frames:
1. Show only initial columns and LP value.
2. Add one pricing column and update LP value.
3. Highlight fractional variables.
4. Show branch split (forced-in vs forced-out pair).
5. Show pruning and incumbent update.

### B. ILS (original baseline)

Implementation: `src/ils.py`

Flow:
1. Greedy initialization (`_greedy_construct`).
2. Local search improvement (`_local_search`, route 2-opt).
3. Perturb current solution (`_perturb`) by removing and reinserting customers.
4. Re-optimize locally.
5. Accept/reject candidate and update best-so-far.
6. Iterate for fixed budget (`iterations`).

Suggested slide animation frames:
1. Show initial greedy routes.
2. Show node removal perturbation.
3. Show reinsertion and 2-opt improvement.
4. Show best-so-far update chart.

## 4) Proposed Modifications and Rationale

### Branch-and-Price modified version

Function: `branch_and_price_modified`

Changes applied:
1. Explicit vehicle-count constraint in RMP (`sum x_r <= m`).
2. Vehicle dual included in pricing reduced cost.
3. Branch constraints enforced consistently in both route pool filtering and pricing feasibility checks.
4. Best-bound node selection and stronger branch-pair choice.
5. Enhanced initial pool (singleton + greedy warm-start columns).

Why these changes:
- Tightens LP consistency with original problem.
- Improves branching correctness and search efficiency.
- Stabilizes convergence quality across random seeds.

### ILS modified version

Function: `ils_modified`

Changes applied:
1. Adaptive perturbation strength based on stagnation.
2. Multi-trial candidate generation per iteration.
3. Elite restart strategy after repeated stagnation.
4. Fixed insertion scoring logic to choose shortest feasible insertion.

Why these changes:
- Increases diversification when stuck.
- Preserves intensification around good basins.
- Reduces premature stagnation with small runtime overhead.

## 5) Experiment Protocol and Genuine Outputs

Master runner: `run_all.py`

It produces:
- Original and modified Branch-and-Price results:
	- `results/tables/branch_and_price_results.csv`
- Original and modified ILS results:
	- `results/tables/ils_results.csv`
- Convergence tables:
	- `results/tables/bp_convergence_basic.csv`
	- `results/tables/bp_convergence_modified.csv`
	- `results/tables/ils_convergence_basic.csv`
	- `results/tables/ils_convergence_modified.csv`
- Plots for slides:
	- `results/figures/bp_profit_by_n.png`
	- `results/figures/bp_runtime_by_n.png`
	- `results/figures/bp_convergence_basic.png`
	- `results/figures/bp_convergence_modified.png`
	- `results/figures/ils_profit_by_n.png`
	- `results/figures/ils_runtime_by_n.png`
	- `results/figures/ils_best_basic.png`
	- `results/figures/ils_best_modified.png`

Dataset note:
- Current experiments use synthetic Euclidean instances generated from fixed seeds.
- Justification and reproducibility rationale are documented in `data/README.md`.

Academic integrity note:
- All numbers and charts are generated from executable code paths in this repository.
- No manual/fabricated plot editing is used.

## 6) Reproducibility (Single Master Script)

From repository root:

```bash
python experiments/run_all.py --dataset-source synthetic --output experiments/results
```

This command regenerates all tables and figures used in the final presentation.

Fresh run status (current workspace):
- Last full regeneration completed successfully using synthetic mode.
- Command used: `python experiments/run_all.py --dataset-source synthetic --output experiments/results`
- Generated outputs:
	- `experiments/results/tables/*.csv`
	- `experiments/results/figures/*.png`

To run with real named benchmark datasets (Chao / Dang / Vansteenwegen) from files:

```bash
python experiments/run_all.py --dataset-source named --benchmark-manifest experiments/data/instances.csv --output experiments/results
```

Note: named mode requires non-empty manifest entries and corresponding JSON instance files listed from `experiments/data/instances.csv`.

## Recommended 18-Minute Presentation Allocation (3 x 6)

1. Segment 1 (6 min): Problem, hardness, literature overview.
2. Segment 2 (6 min): Branch-and-Price + ILS step-by-step explanation.
3. Segment 3 (6 min): Modifications, experiments, results, reproducibility demo.

## References

[R1] Chao, I.-M., Golden, B. L., and Wasil, E. A. (1996). The Team Orienteering Problem. European Journal of Operational Research, 88(3), 464-474.
[R2] Vansteenwegen, P., Souffriau, W., and Van Oudheusden, D. (2011). The orienteering problem: A survey. European Journal of Operational Research, 209(1), 1-10.
[R3] Barnhart, C., Johnson, E. L., Nemhauser, G. L., Savelsbergh, M. W. P., and Vance, P. H. (1998). Branch-and-price: Column generation for solving huge integer programs. Operations Research, 46(3), 316-329.
[R4] Desaulniers, G., Desrosiers, J., and Solomon, M. M. (Eds.). (2005). Column Generation. Springer.
[R5] Feillet, D., Dejax, P., Gendreau, M., and Guéguen, C. (2004). An exact algorithm for the elementary shortest path problem with resource constraints: Application to some vehicle routing problems. Networks, 44(3), 216-229.
[R6] Lourenco, H. R., Martin, O. C., and Stützle, T. (2019). Iterated Local Search: Framework and Applications. In Handbook of Metaheuristics (3rd ed.). Springer.
