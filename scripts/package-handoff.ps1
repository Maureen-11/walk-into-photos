param([string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
& (Join-Path $PSScriptRoot 'build-handoff-reader.ps1') | Out-Null
if (-not $OutputDirectory) { $OutputDirectory = Join-Path (Split-Path $repo -Parent) 'output/handoff' }
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$stage = Join-Path $OutputDirectory "walk-into-photos-handoff-$stamp"
New-Item -ItemType Directory -Path $stage | Out-Null
$roots = @('backend/app','backend/scripts','backend/tests','frontend/src','docs','scripts','.github')
$allowed = @('.py','.ts','.tsx','.css','.md','.ps1','.json','.yaml','.yml','.html','.txt')
$files = @()
foreach ($relative in $roots) {
    $folder = Join-Path $repo $relative
    if (Test-Path $folder) {
        $files += Get-ChildItem -LiteralPath $folder -Recurse -File | Where-Object {
            $_.Extension -in $allowed -and $_.FullName -notmatch '[\\/](__pycache__|node_modules|\.pytest_cache)[\\/]'
        }
    }
}
$explicit = @('README.md','HANDOFF.md','OPEN-HANDOFF.html','AGENTS.md','.gitignore','backend/.env.example','backend/.env.demo.example','backend/.env.real.example','backend/requirements.txt','backend/requirements-dev.txt','backend/requirements-models.txt','frontend/.env.example','frontend/package.json','frontend/pnpm-workspace.yaml','frontend/pnpm-lock.yaml','frontend/tsconfig.json','frontend/tsconfig.node.json','frontend/vite.config.ts','frontend/index.html')
foreach ($relative in $explicit) { $files += Get-Item -LiteralPath (Join-Path $repo $relative) }
$entries = @()
foreach ($file in ($files | Sort-Object FullName -Unique)) {
    $relative = [IO.Path]::GetRelativePath($repo, $file.FullName)
    $destination = Join-Path $stage $relative
    New-Item -ItemType Directory -Force -Path (Split-Path $destination -Parent) | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $destination
    $entries += @{path=$relative.Replace('\','/'); bytes=$file.Length; sha256=(Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash}
}
@{created=(Get-Date -Format o); description='Source-only handoff. Runtime assets and secrets excluded.'; files=$entries} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $stage 'PACKAGE_MANIFEST.json') -Encoding utf8
$zip = "$stage.zip"
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip
# Compress-Archive may skip dot files on some hosts. Assert every selected file survived.
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead($zip)
try {
    $names = @($archive.Entries | ForEach-Object { $_.FullName.Replace('\','/') })
    foreach ($entry in $entries) { if ($entry.path -notin $names) { throw "Archive missing $($entry.path)" } }
    if ($names | Where-Object { $_ -match '(^|/)(\.env|data|node_modules|model-cache|third_party|\.venv)(/|$)' }) { throw 'Unexpected runtime or private file in archive' }
} finally { $archive.Dispose() }
Write-Output "PACKAGE=$zip"
Write-Output "FILES=$($entries.Count)"
Write-Output "SHA256=$((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash)"
