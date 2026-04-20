# CSE462 Algorithm Engineering Sessional

This repository contains coursework materials for CSE462 (Algorithm Engineering), including a full implementation project and presentation artifacts.

## Repository Overview

### 1) Group Project TOP

Main implementation project for the Team Orienteering Problem (TOP).

- Location: `Group Project TOP/`
- Includes:
  - Solvers (baseline and improved variants)
  - Experiment scripts
  - Benchmark datasets
  - Output reports (CSV/JSON/figures)

The detailed project documentation is available in:

- `Group Project TOP/README.md`

### 2) Group Presentation Khachiyan's Ellipsoid Algorithm

Presentation materials related to Khachiyan's Ellipsoid Algorithm.

- Location: `Group Presentation Khachiyan's Ellipsoid Algorithm/`

### 3) Presentation Feedback Vertex Set

Presentation files and supporting materials for Feedback Vertex Set.

- Location: `Presentation Feedback Vertex Set/`

## Quick Start (TOP Project)

If you want to run experiments immediately, start with the TOP project.

1. Move into the experiments folder:

   ```bash
   cd "Group Project TOP/experiments"
   ```

2. Install dependencies:

   ```bash
   python -m pip install -U pip
   python -m pip install pulp pandas matplotlib
   ```

3. Run experiments:

   - Full pipeline (PowerShell):

     ```bash
     pwsh ./run_all_experiments.ps1
     ```

   - Or run individual Python scripts for custom settings.

## Current TOP Experiments Layout

Inside `Group Project TOP/experiments/`, the key folders are:

- `datasets/` for benchmark instances
- `output_ils/` and `output_ils_improved/` for ILS results
- `output_bp/` and `output_bp_improved/` for branch-and-price results
- `output_ils_comparison/` and `output_bp_comparison/` for baseline vs improved comparisons

## Notes

- Some output folders are generated artifacts from previous runs.
- For reproducible experiments, use fixed seeds and separate output directories per configuration.