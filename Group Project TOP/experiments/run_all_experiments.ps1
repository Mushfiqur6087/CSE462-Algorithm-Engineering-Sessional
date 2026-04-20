$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host ""
Write-Host "=== Preparing datasets (once) ===" -ForegroundColor Cyan
& "$root/prepare_datasets.ps1"

$pythonCandidates = @(
    '.venv/Scripts/python.exe',
    '.venv/bin/python',
    'python',
    'python3'
)

$pythonCmd = $null
foreach ($candidate in $pythonCandidates) {
    if ($candidate -like '*/*' -or $candidate -like '*\\*') {
        if (Test-Path $candidate) {
            $pythonCmd = $candidate
            break
        }
    } else {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($null -ne $cmd) {
            $pythonCmd = $cmd.Source
            break
        }
    }
}

if ($null -eq $pythonCmd) {
    Write-Error 'Python not found. Activate/install Python first.'
}

function Invoke-Step {
    param([string]$Title, [scriptblock]$Block)
    Write-Host ""
    Write-Host "=== $Title ===" -ForegroundColor Cyan
    & $Block
}

# 1) Baseline ILS (same as run_experiment.ps1)
Invoke-Step "Experiment 1/4: Baseline ILS -> output_ils" {
    & $pythonCmd 'top_ils.py' --experiment --datasets-root 'datasets' --output-root 'output_ils' --iterations 20 --seed 7 --alpha 0.25 --remove-fraction 0.30 --restart-interval 20 --runs-per-instance 2
}

# 2) Improved ILS (same as run_experiment_improved.ps1)
Invoke-Step "Experiment 2/4: Improved ILS -> output_ils_improved" {
    & $pythonCmd 'top_ils_improved.py' --experiment --datasets-root 'datasets' --output-root 'output_ils_improved' --iterations 20 --seed 7 --alpha 0.25 --remove-fraction 0.30 --restart-interval 20 --runs-per-instance 2 --skip-existing
}

# 3) Baseline Branch-and-Price (same as run_experiment_bp.ps1)
Invoke-Step "Experiment 3/4: Baseline B&P -> output_bp" {
    & $pythonCmd 'top_branch_price.py' --experiment --datasets-root 'datasets' --output-root 'output_bp' --seed 7 --max-cg-iterations 12 --pricing-trials 22 --max-insertions 18 --runs-per-instance 1
}

# 4) Improved Branch-and-Price (same as run_experiment_bp_improved.ps1)
Invoke-Step "Experiment 4/4: Improved B&P -> output_bp_improved" {
    & $pythonCmd 'top_branch_price_improved.py' --experiment --datasets-root 'datasets' --output-root 'output_bp_improved' --seed 7 --max-cg-iterations 12 --pricing-trials 22 --max-insertions 18 --runs-per-instance 2
}

# Comparisons (paths must match compare_results.py / compare_bp_results.py)
Invoke-Step "Comparison: ILS baseline vs improved -> output_ils_comparison" {
    & $pythonCmd 'compare_results.py'
}

Invoke-Step "Comparison: B&P baseline vs improved -> output_bp_comparison" {
    & $pythonCmd 'compare_bp_results.py'
}

Write-Host ""
Write-Host "=== All experiments and comparisons finished ===" -ForegroundColor Green
Write-Host "  ILS:      output_ils, output_ils_improved, output_ils_comparison"
Write-Host "  B&P:      output_bp, output_bp_improved, output_bp_comparison"
Write-Host ""
