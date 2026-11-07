# Sync project skills\ directories to the DSH skills directory.
# Source of truth: <project>\skills ; deployment: %USERPROFILE%\.dsh\skills
# Usage: powershell -ExecutionPolicy Bypass -File skills\sync_skills.ps1
# Note: do not use Copy-Item "dir\*" wildcard form (silently skips overwrite on some builds).
$ErrorActionPreference = 'Stop'
$src  = $PSScriptRoot
$dest = Join-Path $env:USERPROFILE '.dsh\skills'
$count = 0
foreach ($dir in (Get-ChildItem $src -Directory)) {
    $skill = Join-Path $dir.FullName 'SKILL.md'
    if (-not (Test-Path $skill)) { continue }
    $dstDir = Join-Path $dest $dir.Name
    New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
    Copy-Item $skill (Join-Path $dstDir 'SKILL.md') -Force
    # copy optional subdirectories (references/ scripts/ assets/) as well
    foreach ($sub in (Get-ChildItem $dir.FullName -Directory)) {
        Copy-Item $sub.FullName $dstDir -Recurse -Force
    }
    $count++
    "synced: $($dir.Name)"
}
"done: $count skills"
