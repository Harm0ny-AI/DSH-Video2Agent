<#
.SYNOPSIS
  Fails when the repository contains a command that could write to or delete the
  live DSH/Video2Agent homes, and reports the live-home invariants it can check.

.DESCRIPTION
  Two incidents came from the same class of mistake: a script deleted or rewrote
  something under %USERPROFILE%\.dsh (2026-10-25, 2026-10-28). The 10-28 one was
  `rmSync($HOME/.dsh/sessions)` inside a restore tool while DSH was running: the
  session being written disappeared and the turn died with
  `ENOENT ... session.v4.jsonl.zstd`.

  This check is deliberately blunt: any repo script that names the live homes
  together with a delete/overwrite primitive fails the build. Tests and helpers may
  copy FROM a home; nothing may copy INTO it or remove from it.
#>
[CmdletBinding()]
param(
  [string]$RepoRoot = '',
  # Text scanning cannot enumerate every way to delete a file. `-Snapshot` records the
  # live home before a test run and `-Verify` fails if anything was removed or
  # rewritten during it - that is the check that actually catches a regression.
  [switch]$Snapshot,
  [switch]$Verify
)

$ErrorActionPreference = 'Stop'
if (-not $RepoRoot) {
  # $PSScriptRoot is empty when the script is piped, so fall back to this file's path.
  $here = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
  $RepoRoot = Split-Path -Parent $here
}
$problems = New-Object System.Collections.Generic.List[string]

$scanRoots = @('scripts', 'tools', 'packages')
$extensions = @('.ps1', '.psm1', '.mjs', '.js', '.cmd', '.bat', '.py')

$liveHome = '(\.dsh|\.video2agent|USERPROFILE\s*\)\s*\+\s*["'']\.dsh|homedir\(\).*\.dsh)'
$danger = '(Remove-Item|rmdir|rd\s+/s|\bdel\b|rmSync|rmtree|unlinkSync|unlink\(|Remove-ItemProperty|robocopy[^\r\n]*/MIR|taskkill[^\r\n]*DSH)'

foreach ($root in $scanRoots) {
  $dir = Join-Path $RepoRoot $root
  if (-not (Test-Path -LiteralPath $dir)) { continue }
  foreach ($file in Get-ChildItem -LiteralPath $dir -Recurse -File -ErrorAction SilentlyContinue) {
    if ($file.Extension -notin $extensions) { continue }
    if ($file.FullName -match '\\node_modules\\') { continue }
    $text = Get-Content -LiteralPath $file.FullName -Raw -ErrorAction SilentlyContinue
    if (-not $text) { continue }
    if ($file.Name -eq 'check-live-home.ps1') { continue }  # this file contains the patterns
    foreach ($line in ($text -split "`r?`n")) {
      $trim = $line.Trim()
      # Comments and messages explain the rules; they are not commands.
      if ($trim -match '^(#|//|\*|<!--|<#)') { continue }
      if ($trim -match '^(Write-Host|Write-Output|Write-Warning|echo|console\.(log|warn|error|info)|print\(|throw )') { continue }
      if ($line -match $danger -and $line -match $liveHome) {
        $rel = $file.FullName.Substring($RepoRoot.Length).TrimStart('\')
        $problems.Add("${rel}: $($line.Trim())")
      }
      if ($line -match 'taskkill' -and $line -match 'DeepSeek Harness') {
        $rel = $file.FullName.Substring($RepoRoot.Length).TrimStart('\')
        $problems.Add("${rel}: $($line.Trim())")
      }
    }
  }
}

if ($problems.Count -gt 0) {
  Write-Host 'FAIL: a repository command could touch the live homes:' -ForegroundColor Red
  $problems | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
  Write-Host ''
  Write-Host 'Rules: never delete/overwrite under %USERPROFILE%\.dsh or .video2agent from a'
  Write-Host 'repo script; copy to a temp home instead. Pass --force only for a reviewed case.'
  exit 1
}

# Invariants: cheap read-only checks that would have caught both incidents early.
$dshHome = Join-Path $env:USERPROFILE '.dsh'
# A clean CI runner has no live home. Failing here would make the Windows leg red
# for the wrong reason; the text scan above already ran and there is nothing to
# protect, so say so and pass.
if (-not (Test-Path -LiteralPath $dshHome)) {
  Write-Host "live home: not present at $dshHome (clean runner); text scan clean, nothing to protect"
  exit 0
}
$sessions = 0
if (Test-Path -LiteralPath (Join-Path $dshHome 'sessions')) {
  $sessions = @(Get-ChildItem -LiteralPath (Join-Path $dshHome 'sessions') -Recurse -File -Filter 'session.v4.jsonl.zstd' -ErrorAction SilentlyContinue).Count
}
$workspace = Join-Path $dshHome 'storages\workspace.json'
$workspaceOk = $false
if (Test-Path -LiteralPath $workspace) {
  $bytes = [System.IO.File]::ReadAllBytes($workspace)
  $noBom = -not ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
  if ($noBom) {
    try {
      $null = [System.Text.Encoding]::UTF8.GetString($bytes) | ConvertFrom-Json
      $workspaceOk = $true
    } catch { $workspaceOk = $false }
  }
}

Write-Host "live home: sessions=$sessions | workspace.json valid=$workspaceOk"
if (-not $workspaceOk) {
  Write-Host 'FAIL: storages/workspace.json is missing, has a BOM, or is not JSON.' -ForegroundColor Red
  exit 1
}
# A home that has been provisioned (a profile exists) but holds zero sessions has been
# emptied: that is exactly the state the 2026-10-28 restore produced and it must fail.
$profiles = Join-Path $dshHome 'profiles\desktop'
if ($sessions -eq 0 -and (Test-Path -LiteralPath $profiles)) {
  Write-Host 'FAIL: a provisioned DSH home has zero session files (emptied or pointing at a scratch home).' -ForegroundColor Red
  exit 1
}

$manifestPath = Join-Path $env:TEMP 'vp-live-home-manifest.json'
function Get-Manifest {
  $attachments = 0
  $attachmentsDir = Join-Path $dshHome 'attachments'
  if (Test-Path -LiteralPath $attachmentsDir) {
    $attachments = @(Get-ChildItem -LiteralPath $attachmentsDir -Recurse -File -ErrorAction SilentlyContinue).Count
  }
  $workspaceHash = ''
  if (Test-Path -LiteralPath $workspace) { $workspaceHash = (Get-FileHash -LiteralPath $workspace -Algorithm SHA256).Hash }
  [ordered]@{ sessions = $sessions; attachments = $attachments; workspace_sha256 = $workspaceHash; at = (Get-Date).ToString('o') }
}

if ($Snapshot) {
  (Get-Manifest | ConvertTo-Json) | Set-Content -LiteralPath $manifestPath -Encoding UTF8
  Write-Host "snapshot written: $manifestPath (sessions=$sessions)"
  exit 0
}
if ($Verify) {
  if (-not (Test-Path -LiteralPath $manifestPath)) {
    Write-Host "FAIL: no snapshot at $manifestPath - run with -Snapshot before the test." -ForegroundColor Red
    exit 1
  }
  $before = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
  $after = Get-Manifest
  $lost = $false
  if ($after.sessions -lt $before.sessions) { Write-Host "FAIL: sessions dropped $($before.sessions) -> $($after.sessions)" -ForegroundColor Red; $lost = $true }
  if ($after.attachments -lt $before.attachments) { Write-Host "FAIL: attachments dropped $($before.attachments) -> $($after.attachments)" -ForegroundColor Red; $lost = $true }
  if ($before.workspace_sha256 -and $after.workspace_sha256 -ne $before.workspace_sha256) { Write-Host 'FAIL: workspace.json changed during the run' -ForegroundColor Red; $lost = $true }
  if ($lost) { exit 1 }
  Write-Host "live-home unchanged during the run: sessions=$($after.sessions) attachments=$($after.attachments)"
  exit 0
}

Write-Host 'live-home check passed: best-effort text scan clean, storage readable, sessions present.'
exit 0
