param(
  [switch]$Execute,
  [int]$Limit = 0,
  [string]$TargetRoot = "R:\RuneScript\_ProfileMigration_Staging_Clean",
  [int]$HierarchyDepth = 2
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Ark = Join-Path $Root "ark.cmd"

Write-Host "[STARTING] Mini ARK R: user-profile migration prep"
Write-Host "  Profile roots: R:\Users, R:\Junior, R:\Downloads"
Write-Host "  Target root: $TargetRoot"
Write-Host "  Policy: copy/verify only; no deletes; no profile root removal."

$MapArgs = @("profile-migration-map", "--target-root", $TargetRoot)
if ($Limit -gt 0) {
  $MapArgs += @("--limit", "$Limit")
}
if ($Execute) {
  $MapArgs += "--execute"
}

& $Ark @MapArgs
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

Write-Host ""
Write-Host "[STARTING] Mini ARK R: hierarchy scan"
& $Ark "r-hierarchy-scan" "--root" "R:\" "--max-depth" "$HierarchyDepth"
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

Write-Host ""
Write-Host "[DONE] R: user-profile migration prep complete"
Write-Host "  Review the generated Markdown reports in C:\mini_ark\docs."
Write-Host "  Deletion/removal remains a separate approval after review."
