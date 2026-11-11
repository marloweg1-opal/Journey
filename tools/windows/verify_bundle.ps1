param(
    [Parameter(Mandatory = $true)][string]$Zip,
    [Parameter(Mandatory = $true)][string]$Destination
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Expand-Archive -LiteralPath $Zip -DestinationPath $Destination
$app = (Resolve-Path (Join-Path $Destination 'Journey')).Path
$env:JOURNEY_REQUIRE_DESKTOP = '1'
Push-Location $repo
try {
    & (Join-Path $app 'runtime\python.exe') -B -c "import sys,unittest; from journey_planner import __file__; print('Testing bundled app:', __file__); sys.exit(not unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('tests', 'test_folder_planner*.py')).wasSuccessful())"
    if ($LASTEXITCODE -ne 0) { throw 'Bundled planner tests failed.' }
}
finally {
    Pop-Location
}

$launcher = Start-Process -FilePath (Join-Path $app 'Journey.exe') -WorkingDirectory $env:TEMP -PassThru
$desktop = $null
try {
    $deadline = (Get-Date).AddSeconds(20)
    do {
        $desktop = Get-Process -Name pythonw -ErrorAction SilentlyContinue |
            Where-Object { $_.MainWindowTitle -eq 'Journey | Folder Planner' } |
            Select-Object -First 1
        if (!$desktop) { Start-Sleep -Milliseconds 200 }
        $launcher.Refresh()
    } until ($desktop -or $launcher.HasExited -or (Get-Date) -ge $deadline)

    if (!$desktop) { throw 'Journey.exe did not open the planner window.' }
    if (!$desktop.CloseMainWindow()) { throw 'Could not close the planner window.' }
    if (!$launcher.WaitForExit(10000) -or $launcher.ExitCode -ne 0) {
        throw 'Journey.exe did not exit cleanly.'
    }
    Write-Host 'Verified the bundled workflow, Journey.exe launch, and clean exit.'
}
finally {
    if ($desktop -and !$desktop.HasExited) { $desktop.Kill() }
    if (!$launcher.HasExited) { $launcher.Kill() }
}
