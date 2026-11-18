[CmdletBinding()]
param(
    [string]$CandidateRoot = $PSScriptRoot,
    [string]$DataDir = ''
)
$ErrorActionPreference = 'Stop'
$report = [ordered]@{ Diagnostic = 'Journey conversation read-only verification'; Status = 'FAILED'; Checks = @(); Issues = @(); LocalAcceptance = 'LOCAL_RUNTIME_ACCEPTANCE_PENDING' }
$passed = $true
function Add-Check([string]$Name, $Value) {
    $report.Checks += [ordered]@{ Name = $Name; Value = $Value }
    Write-Host ('[CHECK] ' + $Name)
}
try {
    Write-Progress -Activity 'Journey read-only verification' -Status 'Checking candidate files' -PercentComplete 10
    $root = (Resolve-Path -LiteralPath $CandidateRoot).Path
    if (-not $DataDir) { $DataDir = Join-Path $root 'Conversation checkpoint' }
    $buildPath = Join-Path $root 'BUILD.txt'
    $manifestPath = Join-Path $root 'MANIFEST.json'
    if (-not (Test-Path -LiteralPath $buildPath -PathType Leaf)) { throw 'Select the extracted candidate package containing BUILD.txt.' }
    $buildText = [System.IO.File]::ReadAllText($buildPath)
    if ($buildText.Length -gt 4096) { throw 'BUILD.txt exceeds the expected metadata size.' }
    $expectedCommit = ($buildText -split "`r?`n")[0] -replace '^Journey source commit ', ''
    Add-Check 'Package commit' $expectedCommit
    $manifest = [System.IO.File]::ReadAllText($manifestPath) | ConvertFrom-Json
    foreach ($relative in @('app/journey_navigator/capabilities.py', 'app/journey_navigator/conversation.py', 'app/journey_navigator/__main__.py')) {
        $file = Join-Path $root $relative
        $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
        $expected = $manifest.PSObject.Properties[$relative].Value
        if (-not $expected -or $actual -ne $expected) { throw ('Selected candidate file integrity failed: ' + $relative) }
    }
    Add-Check 'Selected integration-file integrity' '3 declared SHA-256 hashes matched; this is not a complete package audit.'
    Write-Progress -Activity 'Journey read-only verification' -Status 'Checking authenticated running candidate' -PercentComplete 40
    $recordPath = Join-Path $DataDir 'navigator-session.dat'
    if (-not (Test-Path -LiteralPath $recordPath -PathType Leaf)) { throw 'No session record in the selected checkpoint. Open the isolated demonstration first.' }
    Add-Type -AssemblyName System.Security
    $encrypted = [System.IO.File]::ReadAllBytes($recordPath)
    if ($encrypted.Length -gt 65536) { throw 'The session record exceeds its diagnostic size limit.' }
    $bytes = [System.Security.Cryptography.ProtectedData]::Unprotect($encrypted, $null, [System.Security.Cryptography.DataProtectionScope]::CurrentUser)
    $record = [System.Text.Encoding]::UTF8.GetString($bytes) | ConvertFrom-Json
    $port = [int]$record.port
    if ($port -lt 1 -or $port -gt 65535) { throw 'Invalid local session port.' }
    $process = Get-Process -Id ([int]$record.process.pid)
    if ($process.Path -ne $record.process.executable -or $process.StartTime.ToFileTimeUtc() -ne [long]$record.process.created) { throw 'Session process identity did not match the current process.' }
    $origin = 'http://127.0.0.1:' + $port
    $controlHeaders = @{ Origin = $origin; 'X-Journey-Control' = [string]$record.control }
    $running = Invoke-RestMethod -Uri ($origin + '/api/session/status') -Method Post -ContentType 'application/json' -Headers $controlHeaders -Body '{}' -TimeoutSec 5
    if ($running.session -ne $record.session -or $running.commit -ne $expectedCommit) { throw 'The authenticated running session does not match this package.' }
    Add-Check 'Authenticated running build' ([ordered]@{ Commit = $running.commit; Build = $running.build; ProcessId = $process.Id })
    $fragment = ([uri]$running.url).Fragment.TrimStart('#')
    $sessionToken = ([regex]::Match($fragment, '(?:^|&)session=([^&]+)')).Groups[1].Value
    if (-not $sessionToken) { throw 'The authenticated local session returned no conversation token.' }
    $headers = @{ Origin = $origin; 'X-Journey-Session' = [uri]::UnescapeDataString($sessionToken) }
    foreach ($instruction in @('Who are you?', 'What can you do?', 'What permissions do you have?')) {
        $body = @{ instruction = $instruction; use_model = $false; share_evidence = $false } | ConvertTo-Json
        $result = Invoke-RestMethod -Uri ($origin + '/api/inspect/conversation') -Method Post -ContentType 'application/json' -Headers $headers -Body $body -TimeoutSec 5
        if ($result.state -ne 'COMPLETE' -or $result.metrics.calls -ne 0) { throw ('Conversation metadata check failed: ' + $instruction) }
        Add-Check $instruction ([ordered]@{ State = $result.state; Intent = $result.intent; Calls = $result.metrics.calls; Message = $result.message })
    }
    Write-Progress -Activity 'Journey read-only verification' -Status 'Checking local model inventory without inference' -PercentComplete 80
    try {
        $tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -Method Get -TimeoutSec 3
        $members = @($tags.models | Where-Object { $_.name -in @('qwen3:4b', 'phi4-mini', 'phi4-mini:latest', 'gemma3:4b') } | Select-Object name, digest, size)
        Add-Check 'Local model inventory only' $members
    } catch {
        Add-Check 'Local model inventory only' 'Unavailable. No model inference, download or configuration change was attempted.'
    }
    Add-Check 'Scope of this diagnostic' 'Read-only metadata checks. Collection inspection, real model inference and the full owner-account acceptance remain unverified.'
    $report.Status = 'SUCCESS'
} catch {
    $passed = $false
    $report.Issues += $_.Exception.Message
} finally {
    Write-Progress -Activity 'Journey read-only verification' -Completed
}
$text = $report | ConvertTo-Json -Depth 10
Write-Output $text
try {
    Set-Clipboard -Value $text
    Write-Host '[CLIPBOARD] Report copied. Session and control tokens excluded.'
} catch {
    $passed = $false
    Write-Host '[CLIPBOARD] Copy failed. The report is printed above.'
}
if ($passed) { Write-Host 'FINISHED SUCCESS' } else { Write-Host 'FINISHED FAILED'; exit 1 }
