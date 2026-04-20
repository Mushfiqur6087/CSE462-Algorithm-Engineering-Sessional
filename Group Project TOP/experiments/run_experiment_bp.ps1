$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

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

& $pythonCmd 'top_branch_price.py' --experiment --datasets-root 'datasets' --output-root 'output_bp' --seed 7 --max-cg-iterations 12 --pricing-trials 22 --max-insertions 18 --runs-per-instance 1
