param(
  [string]$StageResult = "R:\RuneScript\_ProfileMigration_Staging_Clean\00_MANIFESTS\R_PROFILE_MIGRATION_STAGE_RESULT_2026-09-03_100145.json",
  [string]$QuarantineRoot = "R:\_ark_quarantine",
  [switch]$Execute,
  [switch]$RemoveEmptyDirs
)

$ErrorActionPreference = "Stop"
$Stamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$KillSwitch = Join-Path $Root "ARK_EXECUTION_DISABLED.flag"
if ($Execute -and (Test-Path -LiteralPath $KillSwitch -PathType Leaf)) {
  Write-Host "[BLOCKED] Emergency stop is active. -Execute refused. Nothing was changed." -ForegroundColor Red
  Write-Host "RESULT: BLOCKED. No files were moved or removed."
  exit 2
}
if ($Execute) {
  Write-Host "[HELD] -Execute is disabled for this script. Nothing was changed." -ForegroundColor Yellow
  Write-Host "RESULT: HELD. No files were moved or removed."
  exit 3
}
$Docs = Join-Path $Root "docs"
$MoveRoot = Join-Path $QuarantineRoot "R_Profile_Source_Removals_$Stamp"
$ReportPath = Join-Path $Docs "R_PROFILE_CLEANUP_$Stamp.json"

$ProtectedRoots = @(
  "R:\Users",
  "R:\Junior",
  "R:\Downloads"
)

function Test-UnderProtectedRoot {
  param([string]$Path)
  foreach ($rootPath in $ProtectedRoots) {
    if ($Path.Equals($rootPath, [System.StringComparison]::OrdinalIgnoreCase)) {
      return $false
    }
    $prefix = $rootPath.TrimEnd("\") + "\"
    if ($Path.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
      return $true
    }
  }
  return $false
}

function Get-QuarantinePath {
  param([string]$Source)
  $relative = $Source
  if ($relative.StartsWith("R:\", [System.StringComparison]::OrdinalIgnoreCase)) {
    $relative = $relative.Substring(3)
  }
  $dest = Join-Path $MoveRoot $relative
  if (-not (Test-Path -LiteralPath $dest)) {
    return $dest
  }
  $hash = [System.BitConverter]::ToString(
    [System.Security.Cryptography.SHA1]::HashData([System.Text.Encoding]::UTF8.GetBytes($Source.ToLowerInvariant()))
  ).Replace("-", "").Substring(0, 12).ToLowerInvariant()
  $parent = Split-Path -Parent $dest
  $stem = [System.IO.Path]::GetFileNameWithoutExtension($dest)
  $ext = [System.IO.Path]::GetExtension($dest)
  return (Join-Path $parent "$stem`__$hash$ext")
}

if (-not (Test-Path -LiteralPath $StageResult -PathType Leaf)) {
  throw "Stage result not found: $StageResult"
}

$result = Get-Content -LiteralPath $StageResult -Raw | ConvertFrom-Json
$plan = Get-Content -LiteralPath $result.plan_path -Raw | ConvertFrom-Json
$stageFailed = @{}
foreach ($failure in $result.failed) {
  $stageFailed[[string]$failure.source] = $true
}
$planned = New-Object System.Collections.Generic.List[object]
$skipped = New-Object System.Collections.Generic.List[object]
$moved = New-Object System.Collections.Generic.List[object]
$failed = New-Object System.Collections.Generic.List[object]

foreach ($item in $plan.items) {
  $source = [string]$item.source_path
  $dest = [string]$item.destination_path
  if ($stageFailed.ContainsKey($source)) {
    $skipped.Add([pscustomobject]@{ source = $source; reason = "stage copy failed" })
    continue
  }
  $leaf = [System.IO.Path]::GetFileName($source)
  if ($leaf -match '^(ntuser|usrclass)\.dat' -or $leaf -match '^(ntuser|usrclass)\.dat\.log' -or $leaf -eq 'desktop.ini') {
    $skipped.Add([pscustomobject]@{ source = $source; reason = "Windows profile metadata" })
    continue
  }
  if (-not (Test-UnderProtectedRoot -Path $source)) {
    $skipped.Add([pscustomobject]@{ source = $source; reason = "outside approved profile roots" })
    continue
  }
  if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    $skipped.Add([pscustomobject]@{ source = $source; reason = "source already absent" })
    continue
  }
  if (-not (Test-Path -LiteralPath $dest -PathType Leaf)) {
    $skipped.Add([pscustomobject]@{ source = $source; reason = "staged copy missing" })
    continue
  }
  try {
    $sourceInfo = Get-Item -LiteralPath $source
    $destInfo = Get-Item -LiteralPath $dest
  } catch {
    $skipped.Add([pscustomobject]@{ source = $source; reason = "unreadable source or staged copy: $($_.Exception.Message)" })
    continue
  }
  if ($sourceInfo.Length -ne $destInfo.Length) {
    $skipped.Add([pscustomobject]@{ source = $source; reason = "staged copy size mismatch" })
    continue
  }
  $quarantine = Get-QuarantinePath -Source $source
  $planned.Add([pscustomobject]@{
    source = $source
    staged_copy = $dest
    quarantine = $quarantine
    bytes = $sourceInfo.Length
    bucket = $item.bucket
  })
}

if ($Execute) {
  New-Item -ItemType Directory -Force -Path $MoveRoot | Out-Null
  foreach ($item in $planned) {
    try {
      $parent = Split-Path -Parent $item.quarantine
      New-Item -ItemType Directory -Force -Path $parent | Out-Null
      Move-Item -LiteralPath $item.source -Destination $item.quarantine -Force
      $moved.Add($item)
    } catch {
      $failed.Add([pscustomobject]@{
        source = $item.source
        quarantine = $item.quarantine
        reason = "$($_.Exception.GetType().Name): $($_.Exception.Message)"
      })
    }
  }

  if ($RemoveEmptyDirs) {
    foreach ($rootPath in $ProtectedRoots) {
      if (-not (Test-Path -LiteralPath $rootPath -PathType Container)) {
        continue
      }
      Get-ChildItem -LiteralPath $rootPath -Directory -Recurse -Force -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending |
        ForEach-Object {
          try {
            if (-not (Get-ChildItem -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue | Select-Object -First 1)) {
              Remove-Item -LiteralPath $_.FullName -Force
            }
          } catch {
          }
        }
    }
  }
}

$report = [pscustomobject]@{
  created_at = (Get-Date).ToString("s")
  mode = $(if ($Execute) { "execute" } else { "preview" })
  stage_result = $StageResult
  migration_map = $result.plan_path
  move_root = $MoveRoot
  planned_count = $planned.Count
  moved_count = $moved.Count
  skipped_count = $skipped.Count
  failed_count = $failed.Count
  files_deleted = 0
  profile_roots_deleted = 0
  remove_empty_dirs_requested = [bool]$RemoveEmptyDirs
  planned = @($planned.ToArray() | Select-Object -First 250)
  skipped = @($skipped.ToArray() | Select-Object -First 250)
  moved = @($moved.ToArray() | Select-Object -First 250)
  failed = @($failed.ToArray())
}

$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ReportPath -Encoding UTF8

Write-Host "[DONE] R: profile source cleanup $($report.mode)"
Write-Host "  Report: $ReportPath"
Write-Host "  Move root: $MoveRoot"
Write-Host "  Planned: $($report.planned_count)"
Write-Host "  Moved: $($report.moved_count)"
Write-Host "  Skipped: $($report.skipped_count)"
Write-Host "  Failed: $($report.failed_count)"
Write-Host "  Files deleted: 0"
if (-not $Execute) {
  Write-Host ""
  Write-Host "Preview only. Execution is HELD for this legacy cleanup script."
}
Write-Host "RESULT: PREVIEW COMPLETE. No files were moved or removed."
