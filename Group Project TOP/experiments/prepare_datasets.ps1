$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$datasetsRoot = Join-Path $root 'datasets'
$rawRoot = Join-Path $datasetsRoot 'raw'
$chaoRaw = Join-Path $rawRoot 'chao'
$largeRaw = Join-Path $rawRoot 'large_instances'
$chaoOut = Join-Path $datasetsRoot 'chao'
$dangOut = Join-Path $datasetsRoot 'dang'
$vanOut = Join-Path $datasetsRoot 'vansteenwegen'

New-Item -ItemType Directory -Force -Path $chaoRaw,$largeRaw,$chaoOut,$dangOut,$vanOut | Out-Null

$chaoLinks = @(
    'https://www.mech.kuleuven.be/en/mim/op/instances/ChaoTOP4',
    'https://www.mech.kuleuven.be/en/mim/op/instances/ChaoTOP5',
    'https://www.mech.kuleuven.be/en/mim/op/instances/ChaoTOP6',
    'https://www.mech.kuleuven.be/en/mim/op/instances/ChaoTOP7'
)

Add-Type -AssemblyName System.IO.Compression.FileSystem

foreach ($url in $chaoLinks) {
    $name = ($url.Split('/')[-1] + '.zip')
    $zipPath = Join-Path $chaoRaw $name
    if (-not (Test-Path $zipPath)) {
        Invoke-WebRequest -UseBasicParsing $url -OutFile $zipPath
    }

    $extractDir = Join-Path $chaoRaw ($name -replace '\.zip$','')
    if (Test-Path $extractDir) {
        Remove-Item -Recurse -Force $extractDir
    }
    [IO.Compression.ZipFile]::ExtractToDirectory($zipPath, $extractDir)

    Get-ChildItem -Path $extractDir -File -Filter '*.txt' | ForEach-Object {
        Copy-Item $_.FullName -Destination (Join-Path $chaoOut $_.Name) -Force
    }
}

# Pull a broad set of TOP large instances from a public TOP repository.
$apiUrl = 'https://api.github.com/repos/drfaroukhammami/Team_Orienteering_Problem/contents/Large%20Instances'
$entries = Invoke-RestMethod $apiUrl
foreach ($entry in $entries) {
    if ($entry.type -ne 'file') { continue }
    if (-not $entry.name.EndsWith('.txt')) { continue }
    $dst = Join-Path $largeRaw $entry.name
    if (-not (Test-Path $dst)) {
        Invoke-WebRequest -UseBasicParsing $entry.download_url -OutFile $dst
    }
}

function Parse-Header($path) {
    $line1 = (Get-Content $path -TotalCount 1).Trim()
    $line2 = (Get-Content $path -TotalCount 2)[1].Trim()

    $splitter1 = if ($line1 -like '*;*') { ';' } else { ' ' }
    $splitter2 = if ($line2 -like '*;*') { ';' } else { ' ' }

    $n = [int](($line1 -split $splitter1)[1])
    $m = [int](($line2 -split $splitter2)[1])
    return @($n,$m)
}

# Build dataset views by the standard customer/vehicle ranges in the benchmark table.
Get-ChildItem -Path $largeRaw -File -Filter '*.txt' | ForEach-Object {
    $vals = Parse-Header $_.FullName
    $n = $vals[0]
    $m = $vals[1]

    if ($n -ge 102 -and $n -le 401 -and $m -ge 2 -and $m -le 4) {
        Copy-Item $_.FullName -Destination (Join-Path $dangOut $_.Name) -Force
    }

    if ($n -ge 50 -and $n -le 300 -and $m -ge 1 -and $m -le 4) {
        Copy-Item $_.FullName -Destination (Join-Path $vanOut $_.Name) -Force
    }
}

Write-Output 'Dataset preparation complete.'
Write-Output "Chao files: $((Get-ChildItem $chaoOut -File -Filter '*.txt').Count)"
Write-Output "Dang files: $((Get-ChildItem $dangOut -File -Filter '*.txt').Count)"
Write-Output "Vansteenwegen files: $((Get-ChildItem $vanOut -File -Filter '*.txt').Count)"
