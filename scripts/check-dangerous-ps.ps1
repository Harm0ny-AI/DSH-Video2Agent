# Fail the build if a repo script can delete the wrong directory.
#
# Created after 2026-10-26: an inline command did
#     $home = Join-Path $env:TEMP 'vp-anchor-e2e'
#     Remove-Item -Recurse -Force $home -ErrorAction SilentlyContinue
# The assignment failed ($HOME is a read-only automatic variable), so
# `Remove-Item` ran against the user profile and the user lost ~/.dsh sessions,
# ~/.video2agent and ~/.cache.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check-dangerous-ps.ps1
#
# Rules checked:
#   1. no assignment to $home/$HOME or other read-only automatic variables;
#   2. no `Remove-Item -Recurse` with -ErrorAction SilentlyContinue (keeps deleting);
#   3. no recursive delete of an unvalidated variable path.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$patterns = @(
  @{ name = 'automatic-variable assignment'; regex = '\$(home|HOME|host|args|input|matches|error|pwd|true|false)\s*=' },
  @{ name = 'silent recursive delete';      regex = 'Remove-Item[^\r\n]*-Recurse[^\r\n]*-ErrorAction\s+SilentlyContinue' },
  @{ name = 'recursive delete of a variable'; regex = 'Remove-Item[^\r\n]*-Recurse[^\r\n]*\$(?!env:)' }
)

$files = Get-ChildItem $root -Recurse -Include *.ps1, *.psm1 -File -ErrorAction SilentlyContinue |
  Where-Object { $_.FullName -notmatch '\\node_modules\\|\\\.testhome' }

$problems = 0
foreach ($file in $files) {
  $lines = Get-Content $file.FullName -Encoding utf8
  for ($i = 0; $i -lt $lines.Count; $i++) {
    foreach ($p in $patterns) {
      if ($lines[$i] -match $p.regex) {
        # this checker itself contains the sample text
        if ($file.Name -eq 'check-dangerous-ps.ps1') { continue }
        $problems++
        "{0}:{1}  [{2}]" -f ($file.FullName.Replace("$root\", '')), ($i + 1), $p.name
        "    " + $lines[$i].Trim()
      }
    }
  }
}

if ($problems -gt 0) {
  Write-Output "`n$problems dangerous line(s) found."
  exit 1
}
Write-Output "no dangerous delete patterns in $($files.Count) script(s)."
