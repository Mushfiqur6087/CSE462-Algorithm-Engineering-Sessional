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

& $pythonCmd 'top_ils_improved.py' --experiment --datasets-root 'datasets' --output-root 'output_ils_improved' --iterations 20 --seed 7 --alpha 0.25 --remove-fraction 0.30 --restart-interval 20 --runs-per-instance 2 --skip-existing
