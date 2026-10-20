param(
  [switch]$Remove
)

$ErrorActionPreference = 'Stop'

$JourneyRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Launcher = Join-Path $JourneyRoot 'start_mini_ark.ps1'
$Icon = Join-Path $JourneyRoot 'assets\journey.ico'
$Desktop = [Environment]::GetFolderPath('Desktop')
$ShortcutPath = Join-Path $Desktop 'Journey.lnk'

if ($Remove) {
  if (Test-Path -LiteralPath $ShortcutPath -PathType Leaf) {
    Remove-Item -LiteralPath $ShortcutPath -Force
    Write-Host "Journey desktop shortcut removed: $ShortcutPath"
  } else {
    Write-Host 'Journey desktop shortcut is not installed.'
  }
  exit 0
}

if (-not (Test-Path -LiteralPath $Launcher -PathType Leaf)) {
  throw "Journey launcher was not found: $Launcher"
}

if (-not (Test-Path -LiteralPath $Icon -PathType Leaf)) {
  throw "Journey icon was not found: $Icon"
}

$PowerShell = Join-Path $PSHOME 'powershell.exe'
if (-not (Test-Path -LiteralPath $PowerShell -PathType Leaf)) {
  $PowerShell = 'powershell.exe'
}

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $PowerShell
$Shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$Launcher`" -Open"
$Shortcut.WorkingDirectory = $JourneyRoot
$Shortcut.IconLocation = "$Icon,0"
$Shortcut.Description = 'Open Journey, the human-governed local AI navigator'
$Shortcut.Save()

Write-Host ''
Write-Host 'Journey is ready.' -ForegroundColor Green
Write-Host "Desktop shortcut: $ShortcutPath"
Write-Host 'Double-click Journey whenever you want to open the Navigator.'
