param(
  [switch]$Remove
)

$ErrorActionPreference = 'Stop'

$JourneyRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Launcher = Join-Path $JourneyRoot 'start_mini_ark.ps1'
$SourceSkin = Join-Path $JourneyRoot 'rainmeter\JourneyCloverstone\Cloverstone.ini'
$RainmeterKey = 'HKCU:\Software\Rainmeter'
$SkinPath = $null

if (Test-Path -LiteralPath $RainmeterKey) {
  $SkinPath = (Get-ItemProperty -LiteralPath $RainmeterKey -Name SkinPath -ErrorAction SilentlyContinue).SkinPath
}
if (-not $SkinPath) {
  $SkinPath = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Rainmeter\Skins'
}

$ConfigName = 'Journey\Cloverstone'
$InstallDir = Join-Path $SkinPath $ConfigName
$InstalledSkin = Join-Path $InstallDir 'Cloverstone.ini'
$RainmeterCandidates = @(
  (Join-Path $env:ProgramFiles 'Rainmeter\Rainmeter.exe'),
  (Join-Path ${env:ProgramFiles(x86)} 'Rainmeter\Rainmeter.exe')
) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }
$RainmeterExe = $RainmeterCandidates | Select-Object -First 1

if ($Remove) {
  if ($RainmeterExe) {
    & $RainmeterExe '!DeactivateConfig' $ConfigName | Out-Null
  }
  if (Test-Path -LiteralPath $InstallDir) {
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
    Write-Host 'Cloverstone launcher removed.' -ForegroundColor Green
  } else {
    Write-Host 'Cloverstone launcher is not installed.'
  }
  exit 0
}

if (-not (Test-Path -LiteralPath $Launcher -PathType Leaf)) {
  throw "Journey launcher was not found: $Launcher"
}
if (-not (Test-Path -LiteralPath $SourceSkin -PathType Leaf)) {
  throw "Cloverstone skin was not found: $SourceSkin"
}
if (-not $RainmeterExe) {
  throw 'Rainmeter was not found. Install or start Rainmeter, then run this installer again.'
}

New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
$SkinText = Get-Content -LiteralPath $SourceSkin -Raw
$EscapedRoot = $JourneyRoot -replace '\\', '\\'
$SkinText = $SkinText -replace '(?m)^JourneyRoot=.*$', "JourneyRoot=$EscapedRoot"
Set-Content -LiteralPath $InstalledSkin -Value $SkinText -Encoding Unicode

& $RainmeterExe '!RefreshApp' | Out-Null
Start-Sleep -Milliseconds 500
& $RainmeterExe '!ActivateConfig' $ConfigName 'Cloverstone.ini' | Out-Null

Write-Host ''
Write-Host 'Cloverstone is now the Journey button.' -ForegroundColor Green
Write-Host 'Click the green Cloverstone badge on your desktop to open Journey.'
Write-Host 'The placement matches your 1920 x 1080 CareBloom desktop.'
