param(
    [ValidateSet('main', 'replays', 'both')][string]$Environment = 'main',
    [switch]$ReuseInstalled
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$projectTemp = Join-Path $projectRoot '.cache\package-install'
New-Item -ItemType Directory -Path $projectTemp -Force | Out-Null
$oldTemp = $env:TEMP
$oldTmp = $env:TMP
$env:TEMP = $projectTemp
$env:TMP = $projectTemp

function Invoke-CheckedPython {
    param([string]$PythonPath, [string[]]$Arguments)
    & $PythonPath @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python setup failed with exit code $LASTEXITCODE" }
}

Push-Location -LiteralPath $projectRoot
try {
    $targets = if ($Environment -eq 'both') { @('main', 'replays') } else { @($Environment) }
    foreach ($target in $targets) {
        $directory = if ($target -eq 'main') { '.venv' } else { '.venv-replays' }
        $environmentPath = Join-Path $projectRoot $directory
        $pythonPath = Join-Path $environmentPath 'Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $pythonPath)) {
            if ($ReuseInstalled) { throw "$directory does not exist; omit -ReuseInstalled for a fresh setup" }
            & py -3.12 -m venv $environmentPath
            if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 environment creation failed' }
        }
        if (-not $ReuseInstalled) {
            if ($target -eq 'main') {
                Invoke-CheckedPython -PythonPath $pythonPath -Arguments @('-m','pip','install','-r','requirements-lock.txt','--extra-index-url','https://download.pytorch.org/whl/cu128')
            } else {
                Invoke-CheckedPython -PythonPath $pythonPath -Arguments @('-m','pip','install','-r','requirements-replays.txt')
            }
        }
        # The replay environment intentionally has no training dependencies.
        Invoke-CheckedPython -PythonPath $pythonPath -Arguments @('-m','pip','install','--no-deps','-e','.')
        Invoke-CheckedPython -PythonPath $pythonPath -Arguments @('scripts/repair_environment.py')
        if ($target -eq 'replays' -and -not $ReuseInstalled) {
            Invoke-CheckedPython -PythonPath $pythonPath -Arguments @('scripts/patch_replay_parser.py')
        }
    }
} finally {
    Pop-Location
    $env:TEMP = $oldTemp
    $env:TMP = $oldTmp
}
Write-Output 'Setup complete. No tests, capture, training, or game commands were run.'
