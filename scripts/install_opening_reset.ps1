$ErrorActionPreference = 'Stop'
$openingModuleSource = Join-Path $PSScriptRoot '..\bridge\opening_reset\opening_reset.main.lua'
$openingModuleDirectory = Join-Path $env:APPDATA 'CONTROL\AoE2Control\modules\opening_reset'
$openingModuleTarget = Join-Path $openingModuleDirectory 'opening_reset.main.lua'
New-Item -ItemType Directory -Path $openingModuleDirectory -Force | Out-Null
if (Test-Path -LiteralPath $openingModuleTarget) {
    $openingBackup = $openingModuleTarget + '.' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.bak'
    Copy-Item -LiteralPath $openingModuleTarget -Destination $openingBackup
}
Copy-Item -LiteralPath $openingModuleSource -Destination $openingModuleTarget -Force
Write-Output "Installed reset helper: $openingModuleTarget"
Write-Output 'Select opening_reset in CONTROL > Modules > Player 1 > Module. No game commands have been run.'
