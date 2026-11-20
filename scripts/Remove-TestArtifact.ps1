[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory = $true)]
    [string]$Path
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$allowedRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot '.promo'))
$target = [IO.Path]::GetFullPath($Path)
$allowedPrefix = $allowedRoot.TrimEnd('\') + '\'

if (-not $target.StartsWith($allowedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to remove a path outside the playbook test root. target=$target allowed=$allowedRoot"
}
if ($target.TrimEnd('\') -eq $allowedRoot.TrimEnd('\')) {
    throw "Refusing to remove the allowed root itself: $target"
}
if (-not (Test-Path -LiteralPath $target)) {
    Write-Host "Nothing to remove: $target"
    return
}

$item = Get-Item -LiteralPath $target -Force
if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw "Refusing to remove a reparse point/symlink: $target"
}

if (-not $PSCmdlet.ShouldProcess($target, 'Remove test artifact recursively')) {
    return
}
Remove-Item -LiteralPath $target -Recurse -Force