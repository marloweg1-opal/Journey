param(
  [ValidateSet('navigator','find','launch','guide','manage','diagnostics','tests','github','folder')]
  [string]$Action = 'navigator'
)

$ErrorActionPreference = 'Stop'
$MiniArkHome = if ($env:JOURNEY_HOME) {
  $env:JOURNEY_HOME
} else {
  (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
}
$StartScript = Join-Path $MiniArkHome 'start_mini_ark.ps1'
$ArkCmd = Join-Path $MiniArkHome 'ark.cmd'
$Handbook = Join-Path $MiniArkHome 'docs\HANDBOOK.md'
$GitHubUrl = 'https://github.com/marloweg1-opal/Journey'

function Start-PowerShellTask {
  param([string[]]$Arguments)
  Start-Process -FilePath 'powershell.exe' -ArgumentList $Arguments -WorkingDirectory $MiniArkHome -WindowStyle Hidden
}

switch ($Action) {
  'navigator' {
    Start-PowerShellTask @('-NoProfile','-ExecutionPolicy','Bypass','-File',$StartScript,'-Open')
  }
  'find' {
    Start-PowerShellTask @('-NoProfile','-ExecutionPolicy','Bypass','-File',$StartScript,'-Open')
  }
  'launch' {
    Start-PowerShellTask @('-NoProfile','-ExecutionPolicy','Bypass','-File',$StartScript,'-Open')
  }
  'guide' {
    if (Test-Path -LiteralPath $Handbook) {
      Start-Process -FilePath 'notepad.exe' -ArgumentList @($Handbook)
    } else {
      Start-PowerShellTask @('-NoProfile','-ExecutionPolicy','Bypass','-File',$StartScript,'-Open')
    }
  }
  'manage' {
    Start-Process -FilePath $MiniArkHome
  }
  'diagnostics' {
    Start-Process -FilePath 'cmd.exe' -ArgumentList @('/k', "`"$ArkCmd`" doctor") -WorkingDirectory $MiniArkHome
  }
  'tests' {
    Start-Process -FilePath 'cmd.exe' -ArgumentList @('/k', 'python -m unittest discover -s tests -v') -WorkingDirectory $MiniArkHome
  }
  'github' {
    Start-Process -FilePath $GitHubUrl
  }
  'folder' {
    Start-Process -FilePath $MiniArkHome
  }
}
