param(
  [switch]$Execute,
  [int]$PreviewLimit = 25
)

$ErrorActionPreference = 'Stop'

$miniArkRoot = 'C:\mini_ark'
$ark = Join-Path $miniArkRoot 'ark.cmd'
$docs = Join-Path $miniArkRoot 'docs'
$stamp = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$report = Join-Path $docs "ARCHITECTURE_CORRECTION_PREP_$stamp.md"

if (-not (Test-Path -LiteralPath $ark)) {
  throw "Mini ARK launcher not found: $ark"
}

if (-not (Test-Path -LiteralPath $docs)) {
  New-Item -ItemType Directory -Path $docs | Out-Null
}

function Invoke-Ark {
  param([string[]]$ArkArgs)
  Push-Location $miniArkRoot
  try {
    & $ark @ArkArgs
    if ($LASTEXITCODE -ne 0) {
      throw "Mini ARK command failed: .\ark.cmd $($ArkArgs -join ' ')"
    }
  } finally {
    Pop-Location
  }
}

function Invoke-ArkCapture {
  param([string[]]$ArkArgs)
  Push-Location $miniArkRoot
  try {
    $output = & $ark @ArkArgs 2>&1
    $code = $LASTEXITCODE
    if ($code -ne 0) {
      throw "Mini ARK command failed: .\ark.cmd $($ArkArgs -join ' ')`n$($output -join "`n")"
    }
    return $output
  } finally {
    Pop-Location
  }
}

$reservations = @(
  @{ Path='R:\Windows'; Reason='System mirror / Windows-managed area; not Project ARK architecture' },
  @{ Path='R:\ProgramData\Microsoft'; Reason='Microsoft app/system data; not Project ARK architecture' },
  @{ Path='R:\Program Files'; Reason='Program install area; not Project ARK architecture' },
  @{ Path='R:\Program Files (x86)'; Reason='Program install area; not Project ARK architecture' },
  @{ Path='R:\RuneScript\_CareBloomArchive'; Reason='CareBloomOS historical archive / reference-only; do not reorganize as generic code' }
)

$mode = if ($Execute) { 'EXECUTE ledger cleanup for protected proposal items' } else { 'DRY RUN only' }
$generated = Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz'
$lines = @(
  '# Mini ARK Architecture Correction Prep',
  '',
  ('- Generated: ' + $generated),
  ('- Mode: ' + $mode),
  '- Mini ARK home: `C:\mini_ark`',
  '',
  '## Boundary Reservations',
  ''
)

foreach ($reservation in $reservations) {
  $reservationLine = '* `' + $reservation.Path + '` - ' + $reservation.Reason
  $lines += $reservationLine
  Invoke-Ark @('reserve', $reservation.Path, '--reason', $reservation.Reason)
}

$lines += ''
$lines += '## Protected Proposal Item Cleanup'
$lines += ''
$lines += 'These operations only affect Mini ARK ledger item status. They do not move, delete, quarantine, or shortcut files.'
$lines += ''

$skipArgs = @('skip-protected-items', '--limit', [string]$PreviewLimit)
if ($Execute) { $skipArgs += '--execute' }
$skipOutput = Invoke-ArkCapture $skipArgs
$lines += '```text'
$skipOutput | ForEach-Object { $lines += [string]$_ }
$lines += '```'
$lines += ''

$closeArgs = @('close-empty-proposals')
if ($Execute) { $closeArgs += '--execute' }
$closeOutput = Invoke-ArkCapture $closeArgs
$lines += '## Empty Proposal Header Cleanup'
$lines += ''
$lines += 'Proposal headers with no remaining pending items are closed so the brief reflects the real queue.'
$lines += ''
$lines += '```text'
$closeOutput | ForEach-Object { $lines += [string]$_ }
$lines += '```'
$lines += ''

$lines += '## Reservations After Prep'
$lines += ''
$reservationOutput = Invoke-ArkCapture @('list-reservations')
$lines += '```text'
$reservationOutput | ForEach-Object { $lines += [string]$_ }
$lines += '```'
$lines += ''

$lines += '## Current Brief After Prep'
$lines += ''
$briefOutput = Invoke-ArkCapture @('brief')
$lines += '```text'
$briefOutput | ForEach-Object { $lines += [string]$_ }
$lines += '```'
$lines += ''

$lines += '## Next Human-Safe Steps'
$lines += ''
$lines += '1. Review the remaining proposal list.'
$lines += '2. Use `.\ark.cmd list-items PROPOSAL_ID` for any remaining proposal that still looks relevant.'
$lines += '3. Use `.\ark.cmd apply PROPOSAL_ID --preview` only after explicit approval.'
$lines += '4. Do not run real apply until the preview is accepted.'

$lines | Set-Content -LiteralPath $report -Encoding UTF8

Write-Host "Mini ARK architecture correction prep complete."
Write-Host "Mode: $(if ($Execute) { 'EXECUTE' } else { 'DRY RUN' })"
Write-Host "Report: $report"
Write-Host ""
Write-Host "Next:"
Write-Host "  cd C:\mini_ark"
Write-Host "  .\ark.cmd brief"
